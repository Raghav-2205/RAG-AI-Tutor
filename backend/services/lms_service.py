import random
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List

def _generate_join_code(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

def _make_id():
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


VALID_ATTENDANCE_STATUSES = {"present", "absent", "late", "excused", "medical", "holiday"}
PRESENT_ATTENDANCE_STATUSES = {"present", "late"}
COUNTED_ATTENDANCE_STATUSES = {"present", "absent", "late", "excused", "medical"}


async def _log_activity(
    db,
    user_id: str,
    category: str,
    *,
    class_id: Optional[str] = None,
    data: Optional[dict] = None,
) -> None:
    """Write LMS activity in the same collection shape used by analytics/live activity."""
    await db.activity_logs.insert_one(
        {
            "id": _make_id(),
            "user_id": user_id,
            "class_id": class_id,
            "category": category,
            "data": data or {},
            "date": _utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "logged_at": _utcnow(),
        }
    )


def _normalize_attendance_status(status: Optional[str]) -> str:
    normalized = str(status or "absent").strip().lower()
    return normalized if normalized in VALID_ATTENDANCE_STATUSES else "absent"


def _build_attendance_summary_rows(rows: List[dict]) -> dict:
    stats = {}
    for row in rows:
        student_id = row.get("student_id")
        if not student_id:
            continue

        status = _normalize_attendance_status(row.get("status"))
        student_stats = stats.setdefault(
            student_id,
            {
                "present": 0,
                "total": 0,
                "status_breakdown": {key: 0 for key in sorted(VALID_ATTENDANCE_STATUSES)},
            },
        )
        student_stats["status_breakdown"][status] = student_stats["status_breakdown"].get(status, 0) + 1

        if status in COUNTED_ATTENDANCE_STATUSES:
            student_stats["total"] += 1
        if status in PRESENT_ATTENDANCE_STATUSES:
            student_stats["present"] += 1

    return stats

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
        "created_at": _utcnow(),
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


async def create_student_invitation(
    db,
    class_id: str,
    invited_by: str,
    student_email: str,
    student_name: Optional[str] = None,
    student_roll_number: Optional[str] = None,
    expires_in_days: int = 7,
) -> dict:
    token = secrets.token_urlsafe(24)
    invitation = {
        "id": _make_id(),
        "class_id": class_id,
        "student_email": student_email.lower().strip(),
        "student_name": (student_name or "").strip() or None,
        "student_roll_number": (student_roll_number or "").strip() or None,
        "invited_by": invited_by,
        "invite_token": token,
        "status": "pending",
        "created_at": _utcnow(),
    }
    invitation["expires_at"] = invitation["created_at"] + timedelta(days=expires_in_days)

    await db.class_invitations.update_one(
        {"class_id": class_id, "student_email": invitation["student_email"], "status": "pending"},
        {"$set": invitation},
        upsert=True,
    )
    return invitation

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
        "created_at": _utcnow()
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
        "created_at": _utcnow()
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
        "created_at": _utcnow()
    }
    await db.assignments.insert_one(doc)
    await _log_activity(
        db,
        created_by,
        "assignment_created",
        class_id=class_id,
        data={"assignment_id": assign_id, "title": title},
    )
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
    assignment = await db.assignments.find_one({"id": assignment_id})
    class_id = assignment.get("class_id") if assignment else None
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
                "submitted_at": _utcnow()
            }}
        )
        existing["status"] = "submitted"
        existing["submitted_at"] = _utcnow()
        await _log_activity(
            db,
            student_id,
            "assignment_submission",
            class_id=class_id,
            data={"assignment_id": assignment_id, "submission_id": existing["id"]},
        )
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
            "submitted_at": _utcnow(),
            "points_earned": None,
            "feedback": None
        }
        await db.submissions.insert_one(doc)
        await _log_activity(
            db,
            student_id,
            "assignment_submission",
            class_id=class_id,
            data={"assignment_id": assignment_id, "submission_id": sub_id},
        )
        return doc

async def grade_submission(
    db,
    submission_id: str,
    graded_by: str,
    points_earned: float,
    feedback: Optional[str] = None,
) -> dict:
    submission = await db.submissions.find_one({"id": submission_id})
    assignment = await db.assignments.find_one({"id": submission.get("assignment_id")}) if submission else None
    res = await db.submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "points_earned": points_earned,
            "feedback": feedback,
            "status": "graded",
            "graded_by": graded_by,
            "graded_at": _utcnow()
        }}
    )
    if res.modified_count == 0:
        raise ValueError("Submission not found.")

    await _log_activity(
        db,
        graded_by,
        "submission_graded",
        class_id=assignment.get("class_id") if assignment else None,
        data={"submission_id": submission_id, "assignment_id": assignment.get("id") if assignment else None},
    )
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
        "created_at": _utcnow()
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
    await _log_activity(
        db,
        created_by,
        "quiz_created",
        class_id=class_id,
        data={"quiz_id": quiz_id, "title": title},
    )
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
    correct_count = 0
    question_results = []

    for q in questions:
        question_id = str(q["id"])
        user_answer = answers.get(question_id)
        if q.get("type") in ("mcq", "true_false"):
            correct_labels = {
                opt["label"] for opt in (q.get("options") or []) if opt.get("is_correct")
            }
            is_correct = user_answer in correct_labels
            if is_correct:
                score += float(q.get("points", 1))
                correct_count += 1
            question_results.append({
                "question_id": question_id,
                "question": q.get("question"),
                "user_answer": user_answer,
                "correct_answers": sorted(correct_labels),
                "is_correct": is_correct,
                "points": q.get("points", 1),
                "options": [
                    {
                        "label": opt.get("label"),
                        "text": opt.get("text"),
                        "is_correct": bool(opt.get("is_correct")),
                    }
                    for opt in (q.get("options") or [])
                    if isinstance(opt, dict)
                ],
                "explanation": q.get("explanation"),
            })

    percentage = round((score / max_score * 100), 2) if max_score else 0.0

    attempt_id = _make_id()
    doc = {
        "id": attempt_id,
        "quiz_id": quiz_id,
        "class_id": quiz.get("class_id"),
        "student_id": student_id,
        "answers": answers,
        "score": score,
        "max_score": max_score,
        "percentage": percentage,
        "correct_count": correct_count,
        "question_results": question_results,
        "submitted_at": _utcnow(),
        "is_complete": True
    }
    await db.quiz_attempts.insert_one(doc)
    await _log_activity(
        db,
        student_id,
        "quiz_attempt",
        class_id=quiz.get("class_id"),
        data={"quiz_id": quiz_id, "attempt_id": attempt_id, "percentage": percentage},
    )
    return doc

# ─── Attendance Tracking ──────────────────────────────────────────────────────

async def mark_attendance(
    db,
    class_id: str,
    date_str: str,
    records: List[dict], # [{student_id, status}]
) -> dict:
    attendance_id = _make_id()
    normalized_records = []
    for rec in records:
        student_id = rec.get("student_id")
        if not student_id:
            continue
        normalized_records.append({
            "student_id": student_id,
            "status": _normalize_attendance_status(rec.get("status")),
        })
    doc = {
        "id": attendance_id,
        "class_id": class_id,
        "date": date_str,
        "records": normalized_records,
        "created_at": _utcnow()
    }
    # Upsert: one nested doc per class per day (for bulk queries)
    await db.attendance.update_one(
        {"class_id": class_id, "date": date_str},
        {"$set": doc},
        upsert=True
    )
    # CRITICAL FIX: Also sync flat per-student records into attendance_records
    # This collection is what the student stats endpoint reads from.
    for rec in normalized_records:
        student_id = rec.get("student_id")
        status = _normalize_attendance_status(rec.get("status"))
        if not student_id:
            continue
        await db.attendance_records.update_one(
            {"class_id": class_id, "student_id": student_id, "date": date_str},
            {"$set": {
                "class_id": class_id,
                "student_id": student_id,
                "date": date_str,
                "status": status,
                "updated_at": _utcnow()
            }},
            upsert=True
        )
    cls = await db.classes.find_one({"id": class_id})
    teacher_id = cls.get("teacher_id") if cls else None
    if teacher_id:
        await _log_activity(
            db,
            teacher_id,
            "attendance_marked",
            class_id=class_id,
            data={"date": date_str, "records": len(normalized_records)},
        )
    return doc

async def get_student_attendance(db, student_id: str, class_id: Optional[str] = None) -> list:
    flat_query = {"student_id": student_id}
    if class_id:
        flat_query["class_id"] = class_id

    flat_records = await db.attendance_records.find(flat_query).sort("date", -1).to_list(None)
    if flat_records:
        return [
            {
                "date": row.get("date"),
                "class_id": row.get("class_id"),
                "status": _normalize_attendance_status(row.get("status")),
            }
            for row in flat_records
        ]

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
            "status": _normalize_attendance_status(status),
        })
    return output

async def get_class_attendance_stats(db, class_id: str) -> dict:
    flat_rows = await db.attendance_records.find({"class_id": class_id}).to_list(None)
    if flat_rows:
        stats = _build_attendance_summary_rows(flat_rows)
        days_tracked = len({row.get("date") for row in flat_rows if row.get("date")})
    else:
        cursor = db.attendance.find({"class_id": class_id})
        records = await cursor.to_list(None)
        flattened = []
        for record in records:
            for rec in record.get("records", []):
                flattened.append({
                    "student_id": rec.get("student_id"),
                    "status": rec.get("status"),
                    "date": record.get("date"),
                })
        stats = _build_attendance_summary_rows(flattened)
        days_tracked = len(records)

    return {
        "class_id": class_id,
        "days_tracked": days_tracked,
        "student_stats": [
            {
                "student_id": sid,
                "present": s["present"],
                "total": s["total"],
                "percentage": round((s["present"] / s["total"] * 100), 2) if s["total"] > 0 else 0,
                "status_breakdown": s["status_breakdown"],
            }
            for sid, s in stats.items()
        ]
    }


async def get_class_attendance_dates(db, class_id: str) -> list:
    sessions = await db.attendance.find({"class_id": class_id}).sort("date", -1).to_list(None)
    output = []
    for session in sessions:
        counts = {key: 0 for key in sorted(VALID_ATTENDANCE_STATUSES)}
        for rec in session.get("records", []):
            status = _normalize_attendance_status(rec.get("status"))
            counts[status] = counts.get(status, 0) + 1
        output.append({
            "date": session.get("date"),
            "record_count": len(session.get("records", [])),
            "status_breakdown": counts,
        })
    return output


async def get_class_gradebook(db, class_id: str) -> dict:
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise ValueError("Class not found.")

    student_ids = cls.get("students", []) or []
    users = []
    if student_ids:
        from bson import ObjectId
        users = await db.users.find({"_id": {"$in": [ObjectId(student_id) for student_id in student_ids]}}).to_list(None)
    user_map = {str(user["_id"]): user for user in users}

    assignments = await db.assignments.find({"class_id": class_id}).sort("due_date", 1).to_list(None)
    assignment_ids = [assignment["id"] for assignment in assignments]
    submissions = await db.submissions.find({"assignment_id": {"$in": assignment_ids}}).to_list(None) if assignment_ids else []
    submission_map = {(submission.get("student_id"), submission.get("assignment_id")): submission for submission in submissions}

    quizzes = await db.lms_quizzes.find({"class_id": class_id}).sort("created_at", 1).to_list(None)
    quiz_ids = [quiz["id"] for quiz in quizzes]
    question_docs = await db.quiz_questions.find({"quiz_id": {"$in": quiz_ids}}).to_list(None) if quiz_ids else []
    quiz_max_scores = {}
    for question in question_docs:
        quiz_id = question.get("quiz_id")
        quiz_max_scores[quiz_id] = quiz_max_scores.get(quiz_id, 0.0) + float(question.get("points", 1) or 0)

    attempts = await db.quiz_attempts.find(
        {"class_id": class_id, "quiz_id": {"$in": quiz_ids}, "is_complete": True}
    ).sort("submitted_at", -1).to_list(None) if quiz_ids else []
    latest_attempt_map = {}
    for attempt in attempts:
        key = (attempt.get("student_id"), attempt.get("quiz_id"))
        if key not in latest_attempt_map:
            latest_attempt_map[key] = attempt

    attendance_rows = await db.attendance_records.find({"class_id": class_id}).to_list(None)
    attendance_stats = _build_attendance_summary_rows(attendance_rows)

    students = []
    for student_id in student_ids:
        assignment_points_earned = 0.0
        assignment_points_possible = 0.0
        quiz_points_earned = 0.0
        quiz_points_possible = 0.0

        assignment_scores = {}
        for assignment in assignments:
            submission = submission_map.get((student_id, assignment["id"]))
            points_earned = submission.get("points_earned") if submission else None
            assignment_scores[assignment["id"]] = {
                "title": assignment.get("title"),
                "points_earned": points_earned,
                "max_points": float(assignment.get("max_points") or 0),
                "status": submission.get("status") if submission else None,
                "submitted_at": submission.get("submitted_at") if submission else None,
            }
            if points_earned is not None:
                assignment_points_earned += float(points_earned)
                assignment_points_possible += float(assignment.get("max_points") or 0)

        quiz_scores = {}
        for quiz in quizzes:
            attempt = latest_attempt_map.get((student_id, quiz["id"]))
            max_score = float(quiz_max_scores.get(quiz["id"], 0) or 0)
            quiz_scores[quiz["id"]] = {
                "title": quiz.get("title"),
                "score": attempt.get("score") if attempt else None,
                "percentage": attempt.get("percentage") if attempt else None,
                "max_score": max_score,
                "submitted_at": attempt.get("submitted_at") if attempt else None,
            }
            if attempt:
                quiz_points_earned += float(attempt.get("score") or 0)
                quiz_points_possible += float(attempt.get("max_score") or max_score or 0)

        attendance = attendance_stats.get(student_id, {"present": 0, "total": 0, "status_breakdown": {}})
        overall_possible = assignment_points_possible + quiz_points_possible
        overall_earned = assignment_points_earned + quiz_points_earned

        user = user_map.get(student_id, {})
        students.append(
            {
                "student_id": student_id,
                "name": user.get("name") or user.get("email") or "Unknown",
                "email": user.get("email", ""),
                "roll_number": user.get("roll_number", ""),
                "assignment_scores": assignment_scores,
                "quiz_scores": quiz_scores,
                "assignment_average": round((assignment_points_earned / assignment_points_possible) * 100, 1) if assignment_points_possible else None,
                "quiz_average": round((quiz_points_earned / quiz_points_possible) * 100, 1) if quiz_points_possible else None,
                "overall_percentage": round((overall_earned / overall_possible) * 100, 1) if overall_possible else None,
                "attendance_percentage": round((attendance["present"] / attendance["total"]) * 100, 1) if attendance["total"] else None,
                "attendance_status_breakdown": attendance.get("status_breakdown", {}),
                "graded_assignments": sum(1 for score in assignment_scores.values() if score["points_earned"] is not None),
                "completed_quizzes": sum(1 for score in quiz_scores.values() if score["percentage"] is not None),
            }
        )

    return {
        "class_id": class_id,
        "class_name": cls.get("name"),
        "subject": cls.get("subject"),
        "assignments": [
            {
                "id": assignment["id"],
                "title": assignment.get("title"),
                "max_points": float(assignment.get("max_points") or 0),
                "due_date": assignment.get("due_date"),
            }
            for assignment in assignments
        ],
        "quizzes": [
            {
                "id": quiz["id"],
                "title": quiz.get("title"),
                "max_score": float(quiz_max_scores.get(quiz["id"], 0) or 0),
                "end_time": quiz.get("end_time"),
            }
            for quiz in quizzes
        ],
        "students": students,
    }
