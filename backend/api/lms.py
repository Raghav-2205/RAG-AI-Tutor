from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from bson import ObjectId

from backend.utils.db import get_db
from backend.api.auth import get_current_user
import backend.services.lms_service as lms_service

router = APIRouter()

# ─── Dependency: require role ──────────────────────────────────────────────────

def require_role(*roles: str):
    def _dep(current_user=Depends(get_current_user)):
        user_role = current_user.get("role", "student").lower()
        if user_role not in [r.lower() for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to: {roles}",
            )
        return current_user
    return _dep


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CreateClassIn(BaseModel):
    name: str
    section: Optional[str] = None
    description: Optional[str] = None
    subject: Optional[str] = None

class EnrollIn(BaseModel):
    join_code: str

class RemoveStudentIn(BaseModel):
    student_id: str

class CreateUnitIn(BaseModel):
    title: str
    description: Optional[str] = None
    order_index: int = 0

class CreateAssignmentIn(BaseModel):
    class_id: str
    title: str
    description: Optional[str] = None
    type: str = "homework"
    due_date: Optional[datetime] = None
    max_points: float = 100
    allow_late: bool = False
    unit_id: Optional[str] = None

class SubmitAssignmentIn(BaseModel):
    assignment_id: Optional[str] = None
    content: Optional[str] = None
    file_url: Optional[str] = None

class GradeSubmissionIn(BaseModel):
    submission_id: str
    points_earned: float
    feedback: Optional[str] = None

    # Also accept alternative field names for legacy compat
    marks: Optional[float] = None

    def get_points(self) -> float:
        return self.points_earned if self.points_earned is not None else (self.marks or 0.0)

class QuizQuestionIn(BaseModel):
    question: str
    type: str
    options: Optional[list] = None
    answer_key: Optional[str] = None
    points: float = 1
    explanation: Optional[str] = None

class CreateQuizIn(BaseModel):
    title: str
    description: Optional[str] = None
    type: str = "quiz"
    time_limit: Optional[int] = None
    max_attempts: int = 1
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    questions: Optional[list[QuizQuestionIn]] = None

class SubmitQuizIn(BaseModel):
    answers: dict  # {question_id: answer}

class AttendanceRecordIn(BaseModel):
    student_id: str
    status: str # 'present' or 'absent'

class MarkAttendanceIn(BaseModel):
    date: str # YYYY-MM-DD
    records: list[AttendanceRecordIn]


# ─── Class Routes ─────────────────────────────────────────────────────────────

@router.post("/classes", summary="Teacher: create a class")
async def create_class(
    body: CreateClassIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    cls = await lms_service.create_class(
        db, str(current_user["_id"]), body.name, body.section, body.description, body.subject
    )
    return {"id": cls["id"], "name": cls.get("name"), "join_code": cls.get("join_code")}

@router.get("/classes", summary="Get classes (teacher: own | student: enrolled)")
async def list_classes(
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = current_user.get("role", "student").lower()
    user_id = str(current_user["_id"])
    if role in ("teacher", "admin"):
        classes = await lms_service.get_classes_for_teacher(db, user_id)
    else:
        classes = await lms_service.get_classes_for_student(db, user_id)
    
    # ensure "class_id" compatibility so old code works transparently
    return [
        {
            "id": c.get("id"), "class_id": c.get("id"), "name": c.get("name"), "section": c.get("section"),
            "subject": c.get("subject"), "join_code": c.get("join_code"),
            "description": c.get("description"), "students": c.get("students")
        }
        for c in classes
    ]

@router.post("/classes/enroll", summary="Student: join a class via join code")
async def enroll(
    body: EnrollIn,
    db = Depends(get_db),
    current_user=Depends(require_role("student", "teacher", "admin")),
):
    try:
        enrollment = await lms_service.enroll_student(db, body.join_code, str(current_user["_id"]))
        return {"message": "Enrolled successfully", "class_id": enrollment["class_id"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

class EnrollByEmailIn(BaseModel):
    student_email: str

@router.post("/classes/{class_id}/enroll-by-email", summary="Teacher: enroll student by email")
async def enroll_by_email(
    class_id: str,
    body: EnrollByEmailIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    from bson import ObjectId
    student = await db.users.find_one({"email": body.student_email.lower()})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found with that email.")
    student_id = str(student["_id"])
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found.")
    if student_id in cls.get("students", []):
        return {"message": "Student already enrolled.", "student_id": student_id}
    await db.classes.update_one({"id": class_id}, {"$push": {"students": student_id}})
    return {"message": "Student enrolled successfully.", "student_id": student_id, "student_name": student.get("name", "")}

from fastapi import UploadFile, File
from fastapi.responses import StreamingResponse
import io
try:
    import pandas as pd
except ImportError:
    pd = None

@router.post("/classes/{class_id}/upload-excel", summary="Teacher: Bulk enroll via Excel")
async def upload_excel(
    class_id: str,
    file: UploadFile = File(...),
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    if not pd:
        raise HTTPException(status_code=500, detail="Pandas is missing. Run: pip install pandas openpyxl")
        
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found.")

    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content)) if file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(content))
        current_students = set(cls.get("students", []))
        added_count = 0
        from backend.auth import get_password_hash
        
        for index, row in df.iterrows():
            email = str(row.get("email", "")).strip().lower()
            if not email or email == "nan": continue
            
            student = await db.users.find_one({"email": email})
            if not student:
                name = str(row.get("name", email.split("@")[0]))
                new_user = {
                    "name": name,
                    "email": email,
                    "hashed_password": get_password_hash("default123"),
                    "role": "student",
                    "created_at": datetime.utcnow()
                }
                res = await db.users.insert_one(new_user)
                student_id = str(res.inserted_id)
            else:
                student_id = str(student["_id"])
                
            if student_id not in current_students:
                current_students.add(student_id)
                added_count += 1

        await db.classes.update_one({"id": class_id}, {"$set": {"students": list(current_students)}})
        return {"message": f"Successfully enrolled {added_count} students.", "added_count": added_count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")

@router.get("/classes/{class_id}/export-excel", summary="Teacher: Export Class Data (Attendance & Tests)")
async def export_class_excel(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    if not pd:
        raise HTTPException(status_code=500, detail="Pandas is missing.")
        
    from backend.services.analytics_service import get_teacher_analytics
    stats = await get_teacher_analytics(db, class_id)
    
    cls = await db.classes.find_one({"id": class_id})
    student_ids = cls.get("students", [])
    users = await db.users.find({"_id": {"$in": [ObjectId(sid) for sid in student_ids] if student_ids else []}}).to_list(None)
    user_map = {str(u["_id"]): u.get("name", u.get("email")) for u in users}

    # Gather rows using the analytics data which calculates scores properly
    rows = []
    for sid in student_ids:
        rows.append({
            "Student Name": user_map.get(sid, "Unknown"),
            "Engagement Score (%)": next((s["score"] for s in stats.get("top_performing_students", []) + stats.get("low_performing_students", []) if s["student_id"] == sid), "N/A"),
        })

    df = pd.DataFrame(rows)
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Class Analytics")
    
    stream.seek(0)
    headers = {'Content-Disposition': f'attachment; filename="class_{class_id}_analytics.xlsx"'}
    return StreamingResponse(stream, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

from datetime import timedelta
@router.get("/classes/{class_id}/live-activity", summary="Teacher: Live student interactions (Polling)")
async def get_live_activity(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    cls = await db.classes.find_one({"id": class_id})
    if not cls: raise HTTPException(status_code=404, detail="Class not found.")
    
    student_ids = cls.get("students", [])
    if not student_ids: return {"online": 0, "recent_logs": []}
    
    # 5 minutes ago = "online"
    five_mins_ago = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
    cursor = db.activity_logs.find({
        "user_id": {"$in": student_ids},
        "date": {"$gte": five_mins_ago}
    }).sort("date", -1).limit(10)
    
    logs = await cursor.to_list(None)
    online_count = len(set(log["user_id"] for log in logs))
    
    # Optional: fetch names
    users = await db.users.find({"_id": {"$in": [ObjectId(sid) for sid in set(log["user_id"] for log in logs)]}}).to_list(None)
    user_map = {str(u["_id"]): u.get("name", "Student") for u in users}
    
    formatted_logs = []
    for log in logs:
        formatted_logs.append({
            "student_name": user_map.get(log.get("user_id"), "Unknown"),
            "action": log.get("category", "activity"),
            "time": log.get("date")
        })
        
    return {"online": online_count, "recent_logs": formatted_logs}

@router.delete("/classes/{class_id}/students", summary="Teacher: remove a student")
async def remove_student(
    class_id: str,
    body: RemoveStudentIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    removed = await lms_service.remove_student(db, class_id, body.student_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Enrollment not found.")
    return {"message": "Student removed from class."}

class UpdateClassIn(BaseModel):
    name: Optional[str] = None
    section: Optional[str] = None
    subject: Optional[str] = None
    description: Optional[str] = None

@router.put("/classes/{class_id}", summary="Teacher: update class details")
async def update_class(
    class_id: str,
    body: UpdateClassIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    cls = await db.classes.find_one({"id": class_id, "teacher_id": str(current_user["_id"])})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found or not yours.")
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    await db.classes.update_one({"id": class_id}, {"$set": updates})
    return {"message": "Class updated.", "class_id": class_id, **updates}

@router.delete("/classes/{class_id}", summary="Teacher: delete (archive) a class")
async def delete_class(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    cls = await db.classes.find_one({"id": class_id, "teacher_id": str(current_user["_id"])})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found or not yours.")
    await db.classes.update_one({"id": class_id}, {"$set": {"is_active": False}})
    return {"message": "Class archived successfully."}

@router.get("/classes/{class_id}/students", summary="Teacher: list enrolled students with details")
async def get_students(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    student_ids = await lms_service.get_enrolled_students(db, class_id)
    if not student_ids:
        return {"class_id": class_id, "students": [], "count": 0}

    users = await db.users.find(
        {"_id": {"$in": [ObjectId(sid) for sid in student_ids]}}
    ).to_list(None)

    students = [
        {
            "id": str(u["_id"]),
            "name": u.get("name", "Unknown"),
            "email": u.get("email", ""),
            "roll_number": u.get("roll_number", ""),
        }
        for u in users
    ]
    return {"class_id": class_id, "students": students, "count": len(students)}

@router.get("/classes/{class_id}/analytics", summary="Teacher: per-class stats")
async def class_analytics(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found.")

    student_ids = cls.get("students", [])
    total_students = len(student_ids)

    # Avg quiz score
    attempts_cursor = db.quiz_attempts.find({
        "class_id": class_id,
        "student_id": {"$in": student_ids}
    })
    attempts = await attempts_cursor.to_list(None)
    avg_score = round(sum(a.get("percentage", 0) for a in attempts) / len(attempts), 1) if attempts else 0

    # Attendance %
    att_cursor = db.attendance_records.find({"class_id": class_id})
    att_records = await att_cursor.to_list(None)
    total_att = len(att_records)
    present_count = sum(1 for r in att_records if r.get("status") == "present")
    att_pct = round(present_count / total_att * 100, 1) if total_att > 0 else 0

    # Active students (asked at least one chat message in last 7 days)
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    active_set = set()
    if student_ids:
        activity_cursor = db.activity_logs.find({
            "user_id": {"$in": student_ids},
            "date": {"$gte": cutoff}
        })
        active_logs = await activity_cursor.to_list(None)
        active_set = {log["user_id"] for log in active_logs}

    return {
        "class_id": class_id,
        "class_name": cls.get("name"),
        "total_students": total_students,
        "active_students": len(active_set),
        "avg_quiz_score": avg_score,
        "attendance_pct": att_pct,
        "total_quizzes_taken": len(attempts),
    }

# ─── Curriculum & Materials ───────────────────────────────────────────────────

@router.get("/classes/{class_id}/units", summary="List curriculum units for a class")
async def list_units(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cursor = db.curriculum_units.find({"class_id": class_id}).sort("order_index", 1)
    units = await cursor.to_list(None)
    return [
        {"id": u["id"], "title": u["title"], "description": u.get("description"), "order_index": u.get("order_index", 0)}
        for u in units
    ]

@router.post("/classes/{class_id}/units", summary="Teacher: add curriculum unit")
async def create_unit(
    class_id: str,
    body: CreateUnitIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    unit = await lms_service.create_unit(db, class_id, body.title, body.description, body.order_index)
    return {"id": unit["id"], "title": unit["title"]}

@router.post("/classes/{class_id}/materials", summary="Teacher: upload material")
async def upload_material(
    class_id: str,
    title: str,
    file_url: str,
    file_type: Optional[str] = None,
    unit_id: Optional[str] = None,
    description: Optional[str] = None,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    mat = await lms_service.add_material(
        db, class_id, str(current_user["_id"]), title, file_url, file_type,
        None, unit_id, description,
    )
    return {"id": mat["id"], "title": mat["title"], "file_url": mat["file_url"]}

@router.get("/classes/{class_id}/attendance/stats", summary="Student: get own attendance % in a class")
async def get_attendance_stats(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns overall and per-date attendance for the current student in a class."""
    user_id = str(current_user["_id"])

    # Fetch all attendance records for this student in this class
    cursor = db.attendance_records.find({
        "class_id": class_id,
        "student_id": user_id
    })
    records = await cursor.to_list(None)

    if not records:
        # Try the old nested format (attendance marked as embedded in a date document)
        cursor2 = db.attendance.find({"class_id": class_id})
        docs = await cursor2.to_list(None)
        total, present = 0, 0
        for doc in docs:
            for r in doc.get("records", []):
                if r.get("student_id") == user_id:
                    total += 1
                    if r.get("status") == "present":
                        present += 1
    else:
        total = len(records)
        present = sum(1 for r in records if r.get("status") == "present")

    percentage = round(present / total * 100, 1) if total > 0 else None
    return {
        "class_id": class_id,
        "total_sessions": total,
        "present": present,
        "absent": total - present,
        "overall_percentage": percentage,  # student portal reads this field
        "attendance_percentage": percentage, # fallback alias
    }



@router.get("/classes/{class_id}/materials", summary="List class materials")
async def list_materials(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    materials = await lms_service.get_materials(db, class_id)
    return [
        {
            "id": m["id"], "title": m.get("title"), "description": m.get("description"),
            "file_url": m.get("file_url"), "file_type": m.get("file_type"),
            "unit_id": m.get("unit_id"), "created_at": m.get("created_at"),
        }
        for m in materials
    ]

# ─── Assignments ──────────────────────────────────────────────────────────────

@router.post("/assignments", summary="Teacher: create assignment")
async def create_assignment(
    body: CreateAssignmentIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    assignment = await lms_service.create_assignment(
        db, body.class_id, str(current_user["_id"]),
        body.title, body.description, body.due_date,
        body.max_points, body.allow_late, None, body.unit_id, body.type,
    )
    return {"id": assignment["id"], "assignment_id": assignment["id"], "title": assignment["title"], "due_date": assignment["due_date"]}

@router.get("/classes/{class_id}/assignments", summary="List class assignments")
async def list_assignments(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    assignments = await lms_service.get_assignments(db, class_id)
    return [
        {
            "id": a["id"], "assignment_id": a["id"], "title": a["title"], "type": a.get("type"),
            "due_date": a.get("due_date"), "max_points": float(a.get("max_points") or 0),
        }
        for a in assignments
    ]

@router.get("/assignments", summary="List assignments across user's classes")
async def list_assignments_all(
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # This matches the legacy endpoint expected by frontend portals
    role = current_user.get("role", "student").lower()
    user_id = str(current_user["_id"])

    if role in ("teacher", "admin"):
        # assignments across all this teacher's classes
        c_cursor = db.classes.find({"teacher_id": user_id})
        classes = await c_cursor.to_list(None)
    else:
        # assignments across this student's classes
        c_cursor = db.classes.find({"students": user_id})
        classes = await c_cursor.to_list(None)

    class_ids = [c["id"] for c in classes]
    cursor = db.assignments.find({"class_id": {"$in": class_ids}})
    assignments = await cursor.to_list(None)

    return [
        {
            "id": a["id"], "assignment_id": a["id"], "title": a.get("title"), "type": a.get("type"),
            "due_date": a.get("due_date"), "max_marks": float(a.get("max_points") or 0),
        }
        for a in assignments
    ]

# Legacy /submissions POST removed — use /assignments/{assignment_id}/submit instead

@router.post("/assignments/{assignment_id}/submit", summary="Student: submit assignment")
async def submit_assignment(
    assignment_id: str,
    body: SubmitAssignmentIn,
    db = Depends(get_db),
    current_user=Depends(require_role("student", "teacher")), # teacher for testing
):
    sub = await lms_service.submit_assignment(
        db, assignment_id, str(current_user["_id"]), body.content, body.file_url
    )
    return {"id": sub["id"], "submission_id": sub["id"], "status": sub["status"], "submitted_at": sub["submitted_at"]}

@router.get("/submissions", summary="Teacher: view all submissions across classes")
async def global_submissions(
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    user_id = str(current_user["_id"])
    c_cursor = db.classes.find({"teacher_id": user_id})
    classes = await c_cursor.to_list(None)
    class_ids = [c["id"] for c in classes]
    a_cursor = db.assignments.find({"class_id": {"$in": class_ids}})
    assignments = await a_cursor.to_list(None)
    assignment_ids = [a["id"] for a in assignments]
    s_cursor = db.submissions.find({"assignment_id": {"$in": assignment_ids}})
    subs = await s_cursor.to_list(None)

    # Resolve real student names from users collection
    student_ids_in_subs = list({s["student_id"] for s in subs if s.get("student_id")})
    users = []
    if student_ids_in_subs:
        users = await db.users.find(
            {"_id": {"$in": [ObjectId(sid) for sid in student_ids_in_subs]}}
        ).to_list(None)
    user_map = {str(u["_id"]): u for u in users}

    return [
        {
            "id": s["id"],
            "submission_id": s["id"],
            "assignment_id": s.get("assignment_id"),
            "student_id": s["student_id"],
            "status": s.get("status"),
            "points_earned": s.get("points_earned"),
            "feedback": s.get("feedback"),
            "submitted_at": s.get("submitted_at"),
            "student_name": user_map.get(s["student_id"], {}).get("name") or user_map.get(s["student_id"], {}).get("email") or "Unknown",
            "student_email": user_map.get(s["student_id"], {}).get("email", ""),
            "graded": s.get("status") == "graded",
            "file_url": s.get("file_url"),
            "content": s.get("content"),
        }
        for s in subs
    ]

@router.post("/submissions/grade", summary="Teacher: grade a submission")
async def grade_submission(
    body: GradeSubmissionIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    try:
        points = body.get_points()
        sub = await lms_service.grade_submission(
            db, body.submission_id, str(current_user["_id"]), points, body.feedback
        )
        return {"id": sub["id"], "submission_id": sub["id"], "status": sub["status"], "points_earned": sub["points_earned"]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/students/me/submissions", summary="Student: view own submissions")
async def my_submissions(
    class_id: Optional[str] = None,
    db = Depends(get_db),
    current_user=Depends(require_role("student", "teacher")),
):
    subs = await lms_service.get_student_submissions(db, str(current_user["_id"]), class_id)
    return [
        {
            "id": s["id"], "submission_id": s["id"], "assignment_id": s["assignment_id"],
            "status": s.get("status"), "points_earned": s.get("points_earned"),
            "feedback": s.get("feedback"), "submitted_at": s.get("submitted_at"),
        }
        for s in subs
    ]

# ─── Quizzes ──────────────────────────────────────────────────────────────────

@router.post("/classes/{class_id}/quizzes", summary="Teacher: create quiz/test")
async def create_quiz(
    class_id: str,
    body: CreateQuizIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    questions = [q.dict() for q in body.questions] if body.questions else None
    quiz = await lms_service.create_quiz(
        db, class_id, str(current_user["_id"]),
        body.title, body.description, body.type,
        body.time_limit, body.max_attempts,
        body.start_time, body.end_time, questions,
    )
    return {"id": quiz["id"], "title": quiz["title"], "is_published": quiz.get("is_published", False)}

@router.get("/classes/{class_id}/quizzes", summary="List class quizzes")
async def list_quizzes(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cursor = db.lms_quizzes.find({"class_id": class_id})
    quizzes = await cursor.to_list(None)
    return [
        {"id": q["id"], "title": q.get("title"), "description": q.get("description"), "time_limit": q.get("time_limit")}
        for q in quizzes
    ]

@router.get("/quizzes", summary="List all quizzes across classes")
async def global_quizzes(
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = current_user.get("role", "student").lower()
    user_id = str(current_user["_id"])
    if role in ("teacher", "admin"):
        c_cursor = db.classes.find({"teacher_id": user_id})
    else:
        c_cursor = db.classes.find({"students": user_id})
    
    classes = await c_cursor.to_list(None)
    class_ids = [c["id"] for c in classes]
    q_cursor = db.lms_quizzes.find({"class_id": {"$in": class_ids}})
    quizzes = await q_cursor.to_list(None)
    return [
        {"id": q["id"], "title": q.get("title"), "class_id": q["class_id"], "due_date": q.get("end_time")}
        for q in quizzes
    ]

@router.get("/quizzes/{quiz_id}", summary="Get quiz details and questions")
async def get_quiz(
    quiz_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    quiz = await db.lms_quizzes.find_one({"id": quiz_id})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    q_cursor = db.quiz_questions.find({"quiz_id": quiz_id}).sort("order_index", 1)
    questions = await q_cursor.to_list(None)
    
    return {
        "quiz_id": quiz["id"],
        "title": quiz.get("title"),
        "description": quiz.get("description"),
        "time_limit": quiz.get("time_limit"),
        "type": quiz.get("type", "quiz"),
        "max_attempts": quiz.get("max_attempts", 1),
        "start_time": quiz.get("start_time"),
        "end_time": quiz.get("end_time"),
        "questions": [
            {
                "id": q["id"],
                "question": q["question"],
                "options": q.get("options", []),
                "type": q.get("type", "mcq"),
                "points": q.get("points", 1)
            }
            for q in questions
        ]
    }

@router.post("/quizzes/{quiz_id}/attempt", summary="Student: submit quiz attempt")
async def attempt_quiz(
    quiz_id: str,
    body: SubmitQuizIn,
    db = Depends(get_db),
    current_user=Depends(require_role("student", "teacher")),
):
    try:
        attempt = await lms_service.submit_quiz_attempt(
            db, quiz_id, str(current_user["_id"]), body.answers
        )
        return {
            "id": attempt.get("id"),
            "score": attempt.get("score"),
            "max_score": attempt.get("max_score"),
            "percentage": attempt.get("percentage"),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ─── Quiz Analytics ───────────────────────────────────────────────────────────

@router.get("/quizzes/{quiz_id}/analytics", summary="Teacher: quiz attempt analytics")
async def quiz_analytics(
    quiz_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    quiz = await db.lms_quizzes.find_one({"id": quiz_id})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    # Get all complete attempts
    attempts_cursor = db.quiz_attempts.find({"quiz_id": quiz_id, "is_complete": True})
    attempts = await attempts_cursor.to_list(None)

    if not attempts:
        return {"quiz_id": quiz_id, "title": quiz.get("title"), "attempt_count": 0, "avg_score": 0, "results": []}

    # Resolve student names
    student_ids = list({a["student_id"] for a in attempts if a.get("student_id")})
    users = await db.users.find(
        {"_id": {"$in": [ObjectId(sid) for sid in student_ids]}}
    ).to_list(None)
    user_map = {str(u["_id"]): u.get("name") or u.get("email") or "Student" for u in users}

    scores = [float(a.get("percentage") or 0) for a in attempts]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    results = sorted(
        [
            {
                "student_id": a["student_id"],
                "student_name": user_map.get(a["student_id"], "Unknown"),
                "score": a.get("score", 0),
                "max_score": a.get("max_score", 0),
                "percentage": float(a.get("percentage") or 0),
                "submitted_at": a.get("submitted_at"),
            }
            for a in attempts
        ],
        key=lambda x: x["percentage"],
        reverse=True,
    )

    return {
        "quiz_id": quiz_id,
        "title": quiz.get("title"),
        "attempt_count": len(attempts),
        "avg_score": avg_score,
        "results": results,
    }


# ─── Per-Student Engagement in a Class ────────────────────────────────────────

@router.get("/classes/{class_id}/students/engagement", summary="Teacher: per-student engagement scores")
async def class_student_engagement(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    from backend.services.analytics_service import get_teacher_analytics
    stats = await get_teacher_analytics(db, class_id)
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    student_ids = cls.get("students", [])

    # Resolve names
    users = []
    if student_ids:
        users = await db.users.find(
            {"_id": {"$in": [ObjectId(sid) for sid in student_ids]}}
        ).to_list(None)
    user_map = {str(u["_id"]): {"name": u.get("name", ""), "email": u.get("email", "")} for u in users}

    # Build engagement table from analytics stats
    top = {s["student_id"]: s["score"] for s in stats.get("top_performing_students", [])}
    low = {s["student_id"]: s["score"] for s in stats.get("low_performing_students", [])}
    score_map = {**low, **top}

    return {
        "class_id": class_id,
        "engagement_rate": stats.get("engagement_rate", 0),
        "students": [
            {
                "student_id": sid,
                "name": user_map.get(sid, {}).get("name") or user_map.get(sid, {}).get("email") or "Unknown",
                "email": user_map.get(sid, {}).get("email", ""),
                "avg_score": score_map.get(sid, None),
            }
            for sid in student_ids
        ],
    }


# ─── Attendance ──────────────────────────────────────────────────────────────

@router.post("/classes/{class_id}/attendance", summary="Teacher: mark bulk attendance")
async def take_attendance(
    class_id: str,
    body: MarkAttendanceIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    records = [r.dict() for r in body.records]
    await lms_service.mark_attendance(db, class_id, body.date, records)
    return {"message": "Attendance marked successfully."}

@router.get("/students/me/attendance", summary="Student: view own attendance")
async def my_attendance(
    class_id: Optional[str] = None,
    db = Depends(get_db),
    current_user=Depends(require_role("student", "teacher")),
):
    results = await lms_service.get_student_attendance(db, str(current_user["_id"]), class_id)
    return results

@router.get("/classes/{class_id}/attendance/stats", summary="Teacher: view class stats")
async def class_attendance_stats(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    stats = await lms_service.get_class_attendance_stats(db, class_id)
    return stats

