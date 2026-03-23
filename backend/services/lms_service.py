import random
import string
import uuid
from datetime import datetime
from typing import Optional, List

def _generate_join_code(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

def _make_id():
    return str(uuid.uuid4())

# ─── Class Management ─────────────────────────────────────────────────────────

async def create_class(
    db,
    teacher_id: str,
    name: str,
    section: Optional[str] = None,
    description: Optional[str] = None,
    subject: Optional[str] = None,
) -> dict:
    join_code = _generate_join_code()
    class_id = _make_id()
    doc = {
        "id": class_id,
        "name": name,
        "section": section,
        "description": description,
        "subject": subject,
        "teacher_id": teacher_id,
        "join_code": join_code,
        "is_active": True,
        "students": [], # Stores student_ids
        "created_at": datetime.utcnow(),
    }
    await db.classes.insert_one(doc)
    return doc

async def get_classes_for_teacher(db, teacher_id: str) -> list:
    cursor = db.classes.find({"teacher_id": teacher_id, "is_active": True})
    return await cursor.to_list(None)

async def get_classes_for_student(db, student_id: str) -> list:
    cursor = db.classes.find({"students": student_id, "is_active": True})
    return await cursor.to_list(None)

async def enroll_student(db, join_code: str, student_id: str) -> dict:
    cls = await db.classes.find_one({"join_code": join_code, "is_active": True})
    if not cls:
        raise ValueError("Invalid join code or class is inactive.")

    if student_id in cls.get("students", []):
        raise ValueError("Student is already enrolled in this class.")

    await db.classes.update_one(
        {"id": cls["id"]},
        {"$push": {"students": student_id}}
    )
    return {"class_id": cls["id"], "student_id": student_id}

async def remove_student(db, class_id: str, student_id: str) -> bool:
    res = await db.classes.update_one(
        {"id": class_id},
        {"$pull": {"students": student_id}}
    )
    return res.modified_count > 0

async def get_enrolled_students(db, class_id: str) -> list:
    cls = await db.classes.find_one({"id": class_id})
    if cls:
        return cls.get("students", [])
    return []

# ─── Curriculum & Materials ───────────────────────────────────────────────────

async def create_unit(
    db,
    class_id: str,
    title: str,
    description: Optional[str] = None,
    order_index: int = 0,
) -> dict:
    unit_id = _make_id()
    doc = {
        "id": unit_id,
        "class_id": class_id,
        "title": title,
        "description": description,
        "order_index": order_index,
        "created_at": datetime.utcnow()
    }
    await db.curriculum_units.insert_one(doc)
    return doc

async def add_material(
    db,
    class_id: str,
    uploaded_by: str,
    title: str,
    file_url: str,
    file_type: Optional[str] = None,
    file_size: Optional[int] = None,
    unit_id: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    mat_id = _make_id()
    doc = {
        "id": mat_id,
        "class_id": class_id,
        "unit_id": unit_id,
        "title": title,
        "description": description,
        "file_url": file_url,
        "file_type": file_type,
        "file_size": file_size,
        "uploaded_by": uploaded_by,
        "created_at": datetime.utcnow()
    }
    await db.materials.insert_one(doc)
    return doc

async def get_materials(db, class_id: str) -> list:
    cursor = db.materials.find({"class_id": class_id}).sort("created_at", -1)
    return await cursor.to_list(None)

# ─── Assignments ──────────────────────────────────────────────────────────────

async def create_assignment(
    db,
    class_id: str,
    created_by: str,
    title: str,
    description: Optional[str] = None,
    due_date: Optional[datetime] = None,
    max_points: float = 100,
    allow_late: bool = False,
    attachment_url: Optional[str] = None,
    unit_id: Optional[str] = None,
    a_type: str = "homework",
) -> dict:
    assign_id = _make_id()
    doc = {
        "id": assign_id,
        "class_id": class_id,
        "unit_id": unit_id,
        "title": title,
        "description": description,
        "type": a_type,
        "due_date": due_date,
        "max_points": max_points,
        "allow_late": allow_late,
        "attachment_url": attachment_url,
        "created_by": created_by,
        "created_at": datetime.utcnow()
    }
    await db.assignments.insert_one(doc)
    return doc

async def get_assignments(db, class_id: str) -> list:
    cursor = db.assignments.find({"class_id": class_id}).sort("due_date", 1)
    return await cursor.to_list(None)

async def submit_assignment(
    db,
    assignment_id: str,
    student_id: str,
    content: Optional[str] = None,
    file_url: Optional[str] = None,
) -> dict:
    existing = await db.submissions.find_one({
        "assignment_id": assignment_id,
        "student_id": student_id
    })
    
    if existing:
        await db.submissions.update_one(
            {"id": existing["id"]},
            {"$set": {
                "content": content,
                "file_url": file_url,
                "status": "submitted",
                "submitted_at": datetime.utcnow()
            }}
        )
        existing["status"] = "submitted"
        existing["submitted_at"] = datetime.utcnow()
        return existing
    else:
        sub_id = _make_id()
        doc = {
            "id": sub_id,
            "assignment_id": assignment_id,
            "student_id": student_id,
            "content": content,
            "file_url": file_url,
            "status": "submitted",
            "submitted_at": datetime.utcnow(),
            "points_earned": None,
            "feedback": None
        }
        await db.submissions.insert_one(doc)
        return doc

async def grade_submission(
    db,
    submission_id: str,
    graded_by: str,
    points_earned: float,
    feedback: Optional[str] = None,
) -> dict:
    res = await db.submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "points_earned": points_earned,
            "feedback": feedback,
            "status": "graded",
            "graded_by": graded_by,
            "graded_at": datetime.utcnow()
        }}
    )
    if res.modified_count == 0:
        raise ValueError("Submission not found.")
    
    return await db.submissions.find_one({"id": submission_id})

async def get_submissions_for_assignment(db, assignment_id: str) -> list:
    cursor = db.submissions.find({"assignment_id": assignment_id})
    return await cursor.to_list(None)

async def get_student_submissions(db, student_id: str, class_id: Optional[str] = None) -> list:
    query = {"student_id": student_id}
    if class_id:
        # Resolve all assignments for this class_id
        assign_cursor = db.assignments.find({"class_id": class_id})
        assignments = await assign_cursor.to_list(None)
        a_ids = [a["id"] for a in assignments]
        query["assignment_id"] = {"$in": a_ids}

    cursor = db.submissions.find(query)
    return await cursor.to_list(None)

# ─── Quizzes ──────────────────────────────────────────────────────────────────

async def create_quiz(
    db,
    class_id: str,
    created_by: str,
    title: str,
    description: Optional[str] = None,
    q_type: str = "quiz",
    time_limit: Optional[int] = None,
    max_attempts: int = 1,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    questions: Optional[list] = None,
) -> dict:
    quiz_id = _make_id()
    doc = {
        "id": quiz_id,
        "class_id": class_id,
        "created_by": created_by,
        "title": title,
        "description": description,
        "type": q_type,
        "time_limit": time_limit,
        "max_attempts": max_attempts,
        "start_time": start_time,
        "end_time": end_time,
        "is_published": False,
        "created_at": datetime.utcnow()
    }
    await db.lms_quizzes.insert_one(doc)

    if questions:
        q_docs = []
        for i, q in enumerate(questions):
            q_docs.append({
                "id": _make_id(),
                "quiz_id": quiz_id,
                "question": q["question"],
                "type": q.get("type", "mcq"),
                "options": q.get("options", []),
                "answer_key": q.get("answer_key"),
                "points": q.get("points", 1),
                "order_index": i,
                "explanation": q.get("explanation")
            })
        if q_docs:
            await db.quiz_questions.insert_many(q_docs)
            
    return doc

async def submit_quiz_attempt(
    db,
    quiz_id: str,
    student_id: str,
    answers: dict,
) -> dict:
    quiz = await db.lms_quizzes.find_one({"id": quiz_id})
    if not quiz:
        raise ValueError("Quiz not found.")

    attempt_count = await db.quiz_attempts.count_documents({
        "quiz_id": quiz_id,
        "student_id": student_id,
        "is_complete": True
    })

    if attempt_count >= quiz.get("max_attempts", 1):
        raise ValueError("Maximum attempts reached for this quiz.")

    q_cursor = db.quiz_questions.find({"quiz_id": quiz_id})
    questions = await q_cursor.to_list(None)

    score = 0.0
    max_score = sum(float(q.get("points", 1)) for q in questions)

    for q in questions:
        user_answer = answers.get(str(q["id"]))
        if q.get("type") in ("mcq", "true_false"):
            correct_labels = {
                opt["label"] for opt in (q.get("options") or []) if opt.get("is_correct")
            }
            if user_answer in correct_labels:
                score += float(q.get("points", 1))

    percentage = round((score / max_score * 100), 2) if max_score else 0.0

    attempt_id = _make_id()
    doc = {
        "id": attempt_id,
        "quiz_id": quiz_id,
        "student_id": student_id,
        "answers": answers,
        "score": score,
        "max_score": max_score,
        "percentage": percentage,
        "submitted_at": datetime.utcnow(),
        "is_complete": True
    }
    await db.quiz_attempts.insert_one(doc)
    return doc

# ─── Attendance Tracking ──────────────────────────────────────────────────────

async def mark_attendance(
    db,
    class_id: str,
    date_str: str,
    records: List[dict], # [{student_id, status: 'present'|'absent'}]
) -> dict:
    attendance_id = _make_id()
    doc = {
        "id": attendance_id,
        "class_id": class_id,
        "date": date_str,
        "records": records,
        "created_at": datetime.utcnow()
    }
    # Upsert: one record per class per day
    await db.attendance.update_one(
        {"class_id": class_id, "date": date_str},
        {"$set": doc},
        upsert=True
    )
    return doc

async def get_student_attendance(db, student_id: str, class_id: Optional[str] = None) -> list:
    query = {"records.student_id": student_id}
    if class_id:
        query["class_id"] = class_id
    
    cursor = db.attendance.find(query).sort("date", -1)
    results = await cursor.to_list(None)
    
    output = []
    for r in results:
        status = next((record["status"] for record in r["records"] if record["student_id"] == student_id), "unknown")
        output.append({
            "date": r["date"],
            "class_id": r["class_id"],
            "status": status
        })
    return output

async def get_class_attendance_stats(db, class_id: str) -> dict:
    cursor = db.attendance.find({"class_id": class_id})
    records = await cursor.to_list(None)
    
    stats = {} # {student_id: {present: X, total: Y}}
    for r in records:
        for rec in r["records"]:
            sid = rec["student_id"]
            if sid not in stats:
                stats[sid] = {"present": 0, "total": 0}
            stats[sid]["total"] += 1
            if rec["status"] == "present":
                stats[sid]["present"] += 1
                
    # Format for UI
    return {
        "class_id": class_id,
        "days_tracked": len(records),
        "student_stats": [
            {
                "student_id": sid,
                "present": s["present"],
                "total": s["total"],
                "percentage": round((s["present"] / s["total"] * 100), 2) if s["total"] > 0 else 0
            }
            for sid, s in stats.items()
        ]
    }
