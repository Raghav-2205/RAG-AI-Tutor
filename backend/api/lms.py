from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from bson import ObjectId

from backend.utils.db import get_db
from backend.utils.security import get_current_user, normalize_role, require_role
import backend.services.lms_service as lms_service
from backend.services.analytics_service import get_teacher_analytics

router = APIRouter()


def maybe_envelope(request: Request | None, data):
    if request and (request.headers.get("x-lms-envelope") == "1" or request.query_params.get("envelope") == "1"):
        return {"success": True, "data": data, "error": None}
    return data


def _serialize_assignment(assignment: dict) -> dict:
    max_points = float(assignment.get("max_points") or 0)
    return {
        "id": assignment["id"],
        "assignment_id": assignment["id"],
        "class_id": assignment.get("class_id"),
        "title": assignment.get("title"),
        "description": assignment.get("description"),
        "type": assignment.get("type"),
        "due_date": assignment.get("due_date"),
        "max_points": max_points,
        "max_marks": max_points,
        "allow_late": assignment.get("allow_late", False),
        "unit_id": assignment.get("unit_id"),
    }


def _serialize_submission(submission: dict) -> dict:
    return {
        "id": submission["id"],
        "submission_id": submission["id"],
        "assignment_id": submission.get("assignment_id"),
        "class_id": submission.get("class_id"),
        "student_id": submission.get("student_id"),
        "status": submission.get("status"),
        "points_earned": submission.get("points_earned"),
        "feedback": submission.get("feedback"),
        "submitted_at": submission.get("submitted_at"),
        "student_name": submission.get("student_name"),
        "student_email": submission.get("student_email", ""),
        "graded": submission.get("status") == "graded",
        "file_url": submission.get("file_url"),
        "content": submission.get("content"),
    }


def _serialize_quiz_summary(quiz: dict, attempt_map: Optional[dict] = None) -> dict:
    attempt = (attempt_map or {}).get(quiz["id"])
    return {
        "id": quiz["id"],
        "quiz_id": quiz["id"],
        "title": quiz.get("title"),
        "description": quiz.get("description"),
        "class_id": quiz.get("class_id"),
        "due_date": quiz.get("end_time"),
        "start_time": quiz.get("start_time"),
        "end_time": quiz.get("end_time"),
        "time_limit": quiz.get("time_limit"),
        "is_published": quiz.get("is_published", False),
        "submitted": bool(attempt),
        "score": attempt.get("percentage") if attempt else None,
    }

# ─── Dependency: require role ──────────────────────────────────────────────────

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
    points_earned: Optional[float] = None
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


def _serialize_quiz_option(option, include_answers: bool = False):
    if not isinstance(option, dict):
        return option

    payload = {
        "label": option.get("label"),
        "text": option.get("text"),
    }
    if include_answers and "is_correct" in option:
        payload["is_correct"] = bool(option.get("is_correct"))
    return payload


def _serialize_quiz_question(question: dict, include_answers: bool = False) -> dict:
    payload = {
        "id": question["id"],
        "question": question["question"],
        "options": [
            _serialize_quiz_option(option, include_answers=include_answers)
            for option in (question.get("options") or [])
        ],
        "type": question.get("type", "mcq"),
        "points": question.get("points", 1),
    }
    if include_answers and question.get("explanation"):
        payload["explanation"] = question.get("explanation")
    return payload


async def _get_class_or_404(db, class_id: str) -> dict:
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    return cls


async def _authorize_class_access(db, class_id: str, current_user) -> dict:
    cls = await _get_class_or_404(db, class_id)
    user_id = str(current_user["_id"])
    role = normalize_role(current_user.get("role"))

    if role == "admin":
        return cls
    if role == "teacher" and cls.get("teacher_id") == user_id:
        return cls
    if user_id in (cls.get("students") or []):
        return cls

    raise HTTPException(status_code=403, detail="You do not have access to this class")


async def _authorize_quiz_access(db, quiz: dict, current_user) -> tuple[dict, bool]:
    cls = await _authorize_class_access(db, quiz["class_id"], current_user)
    role = normalize_role(current_user.get("role"))
    user_id = str(current_user["_id"])
    include_answers = role == "admin" or (role == "teacher" and cls.get("teacher_id") == user_id)
    return cls, include_answers


async def _authorize_class_staff_access(db, class_id: str, current_user) -> dict:
    cls = await _get_class_or_404(db, class_id)
    user_id = str(current_user["_id"])
    role = normalize_role(current_user.get("role"))

    if role == "admin":
        return cls
    if role == "teacher" and cls.get("teacher_id") == user_id:
        return cls

    raise HTTPException(status_code=403, detail="Only the assigned teacher or an admin can manage this class")


async def _build_latest_attempt_map(db, quiz_ids: list[str], student_id: str) -> dict:
    if not quiz_ids:
        return {}

    attempts = await db.quiz_attempts.find(
        {
            "quiz_id": {"$in": quiz_ids},
            "student_id": student_id,
            "is_complete": True,
        }
    ).sort("submitted_at", -1).to_list(None)

    latest_attempts = {}
    for attempt in attempts:
        quiz_id = attempt.get("quiz_id")
        if quiz_id and quiz_id not in latest_attempts:
            latest_attempts[quiz_id] = attempt
    return latest_attempts


# ─── Class Routes ─────────────────────────────────────────────────────────────

@router.post("/classes", summary="Teacher: create a class")
async def create_class(
    request: Request,
    body: CreateClassIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    cls = await lms_service.create_class(
        db, str(current_user["_id"]), body.name, body.section, body.description, body.subject
    )
    return maybe_envelope(
        request,
        {
            "id": cls["id"],
            "class_id": cls["id"],
            "name": cls.get("name"),
            "join_code": cls.get("join_code"),
            "section": cls.get("section"),
            "subject": cls.get("subject"),
        },
    )

@router.get("/classes", summary="Get classes (teacher: own | student: enrolled)")
async def list_classes(
    request: Request,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = normalize_role(current_user.get("role"))
    user_id = str(current_user["_id"])
    if role in ("teacher", "admin"):
        classes = await lms_service.get_classes_for_teacher(db, user_id)
    else:
        classes = await lms_service.get_classes_for_student(db, user_id)
    
    # ensure "class_id" compatibility so old code works transparently
    payload = [
        {
            "id": c.get("id"), "class_id": c.get("id"), "name": c.get("name"), "section": c.get("section"),
            "subject": c.get("subject"), "join_code": c.get("join_code"),
            "description": c.get("description"), "students": c.get("students")
        }
        for c in classes
    ]
    return maybe_envelope(request, payload)

@router.post("/classes/enroll", summary="Student: join a class via join code")
async def enroll(
    request: Request,
    body: EnrollIn,
    db = Depends(get_db),
    current_user=Depends(require_role("student")),
):
    try:
        enrollment = await lms_service.enroll_student(db, body.join_code, str(current_user["_id"]))
        return maybe_envelope(
            request,
            {"message": "Enrolled successfully", "class_id": enrollment["class_id"]},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

class EnrollByEmailIn(BaseModel):
    student_email: str

@router.post("/classes/{class_id}/enroll-by-email", summary="Teacher: enroll student by email")
async def enroll_by_email(
    request: Request,
    class_id: str,
    body: EnrollByEmailIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    from bson import ObjectId
    student = await db.users.find_one({"email": body.student_email.lower()})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found with that email.")
    student_id = str(student["_id"])
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found.")
    if student_id in cls.get("students", []):
        return maybe_envelope(request, {"message": "Student already enrolled.", "student_id": student_id})
    await db.classes.update_one({"id": class_id}, {"$push": {"students": student_id}})
    return maybe_envelope(
        request,
        {"message": "Student enrolled successfully.", "student_id": student_id, "student_name": student.get("name", "")},
    )

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

    cls = await _authorize_class_staff_access(db, class_id, current_user)

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

    await _authorize_class_staff_access(db, class_id, current_user)
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
    cls = await _authorize_class_staff_access(db, class_id, current_user)
    
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
    request: Request,
    class_id: str,
    body: RemoveStudentIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    removed = await lms_service.remove_student(db, class_id, body.student_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Enrollment not found.")
    return maybe_envelope(request, {"message": "Student removed from class."})

class UpdateClassIn(BaseModel):
    name: Optional[str] = None
    section: Optional[str] = None
    subject: Optional[str] = None
    description: Optional[str] = None

@router.put("/classes/{class_id}", summary="Teacher: update class details")
async def update_class(
    request: Request,
    class_id: str,
    body: UpdateClassIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    await db.classes.update_one({"id": class_id}, {"$set": updates})
    return maybe_envelope(request, {"message": "Class updated.", "class_id": class_id, **updates})

@router.delete("/classes/{class_id}", summary="Teacher: delete (archive) a class")
async def delete_class(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    await db.classes.update_one({"id": class_id}, {"$set": {"is_active": False}})
    return maybe_envelope(request, {"message": "Class archived successfully."})

@router.get("/classes/{class_id}/students", summary="Teacher: list enrolled students with details")
async def get_students(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    student_ids = await lms_service.get_enrolled_students(db, class_id)
    if not student_ids:
        return maybe_envelope(request, {"class_id": class_id, "students": [], "count": 0})

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
    return maybe_envelope(request, {"class_id": class_id, "students": students, "count": len(students)})

@router.get("/classes/{class_id}/analytics", summary="Teacher: per-class stats")
async def class_analytics(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found.")

    teacher_stats = await get_teacher_analytics(db, class_id)
    student_ids = cls.get("students", [])
    att_cursor = db.attendance_records.find({"class_id": class_id})
    att_records = await att_cursor.to_list(None)
    total_att = len(att_records)
    present_count = sum(1 for r in att_records if r.get("status") == "present")
    att_pct = round(present_count / total_att * 100, 1) if total_att > 0 else 0

    payload = {
        "class_id": class_id,
        "class_name": cls.get("name"),
        "total_students": len(student_ids),
        "active_students": teacher_stats.get("active_students_count", 0),
        "avg_quiz_score": teacher_stats.get("avg_score", 0),
        "avg_score": teacher_stats.get("avg_score", 0),
        "attendance_pct": att_pct,
        "engagement_rate": teacher_stats.get("engagement_rate", 0),
        "quiz_stats": teacher_stats.get("quiz_stats", []),
    }
    return maybe_envelope(request, payload)

# ─── Curriculum & Materials ───────────────────────────────────────────────────

@router.get("/classes/{class_id}/units", summary="List curriculum units for a class")
async def list_units(
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await _authorize_class_access(db, class_id, current_user)
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
    await _authorize_class_staff_access(db, class_id, current_user)
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
    await _authorize_class_staff_access(db, class_id, current_user)
    mat = await lms_service.add_material(
        db, class_id, str(current_user["_id"]), title, file_url, file_type,
        None, unit_id, description,
    )
    return {"id": mat["id"], "title": mat["title"], "file_url": mat["file_url"]}

@router.get("/classes/{class_id}/attendance/stats", summary="Student: get own attendance % in a class")
async def get_attendance_stats(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("student")),
):
    """Returns overall and per-date attendance for the current student in a class."""
    await _authorize_class_access(db, class_id, current_user)
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
    return maybe_envelope(request, {
        "class_id": class_id,
        "total_sessions": total,
        "present": present,
        "absent": total - present,
        "overall_percentage": percentage,  # student portal reads this field
        "attendance_percentage": percentage, # fallback alias
    })



@router.get("/classes/{class_id}/materials", summary="List class materials")
async def list_materials(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await _authorize_class_access(db, class_id, current_user)
    materials = await lms_service.get_materials(db, class_id)
    payload = [
        {
            "id": m["id"], "title": m.get("title"), "description": m.get("description"),
            "file_url": m.get("file_url"), "file_type": m.get("file_type"),
            "unit_id": m.get("unit_id"), "created_at": m.get("created_at"), "class_id": m.get("class_id"),
        }
        for m in materials
    ]
    return maybe_envelope(request, payload)

# ─── Assignments ──────────────────────────────────────────────────────────────

@router.post("/assignments", summary="Teacher: create assignment")
async def create_assignment(
    request: Request,
    body: CreateAssignmentIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, body.class_id, current_user)
    assignment = await lms_service.create_assignment(
        db, body.class_id, str(current_user["_id"]),
        body.title, body.description, body.due_date,
        body.max_points, body.allow_late, None, body.unit_id, body.type,
    )
    return maybe_envelope(request, _serialize_assignment(assignment))

@router.get("/classes/{class_id}/assignments", summary="List class assignments")
async def list_assignments(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await _authorize_class_access(db, class_id, current_user)
    assignments = await lms_service.get_assignments(db, class_id)
    return maybe_envelope(request, [_serialize_assignment(a) for a in assignments])

@router.get("/assignments", summary="List assignments across user's classes")
async def list_assignments_all(
    request: Request,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # This matches the legacy endpoint expected by frontend portals
    role = normalize_role(current_user.get("role"))
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

    return maybe_envelope(request, [_serialize_assignment(a) for a in assignments])

# Legacy /submissions POST removed — use /assignments/{assignment_id}/submit instead

@router.post("/assignments/{assignment_id}/submit", summary="Student: submit assignment")
async def submit_assignment(
    request: Request,
    assignment_id: str,
    body: SubmitAssignmentIn,
    db = Depends(get_db),
    current_user=Depends(require_role("student")),
):
    sub = await lms_service.submit_assignment(
        db, assignment_id, str(current_user["_id"]), body.content, body.file_url
    )
    return maybe_envelope(request, _serialize_submission(sub))

@router.get("/submissions", summary="Teacher: view all submissions across classes")
async def global_submissions(
    request: Request,
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

    assignment_map = {a["id"]: a for a in assignments}
    payload = []
    for s in subs:
        assignment = assignment_map.get(s.get("assignment_id"), {})
        payload.append(
            _serialize_submission(
                {
                    **s,
                    "class_id": assignment.get("class_id"),
                    "student_name": user_map.get(s["student_id"], {}).get("name") or user_map.get(s["student_id"], {}).get("email") or "Unknown",
                    "student_email": user_map.get(s["student_id"], {}).get("email", ""),
                }
            )
        )
    return maybe_envelope(request, payload)

@router.post("/submissions/grade", summary="Teacher: grade a submission")
async def grade_submission(
    request: Request,
    body: GradeSubmissionIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    try:
        points = body.get_points()
        sub = await lms_service.grade_submission(
            db, body.submission_id, str(current_user["_id"]), points, body.feedback
        )
        return maybe_envelope(request, _serialize_submission(sub))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/students/me/submissions", summary="Student: view own submissions")
async def my_submissions(
    request: Request,
    class_id: Optional[str] = None,
    db = Depends(get_db),
    current_user=Depends(require_role("student")),
):
    subs = await lms_service.get_student_submissions(db, str(current_user["_id"]), class_id)
    assignment_ids = list({s.get("assignment_id") for s in subs if s.get("assignment_id")})
    assignments = await db.assignments.find({"id": {"$in": assignment_ids}}).to_list(None) if assignment_ids else []
    assignment_map = {a["id"]: a for a in assignments}
    payload = []
    for s in subs:
        payload.append(
            _serialize_submission(
                {
                    **s,
                    "class_id": assignment_map.get(s.get("assignment_id"), {}).get("class_id"),
                }
            )
        )
    return maybe_envelope(request, payload)

# ─── Quizzes ──────────────────────────────────────────────────────────────────

@router.post("/classes/{class_id}/quizzes", summary="Teacher: create quiz/test")
async def create_quiz(
    request: Request,
    class_id: str,
    body: CreateQuizIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    questions = [q.model_dump() for q in body.questions] if body.questions else None
    quiz = await lms_service.create_quiz(
        db, class_id, str(current_user["_id"]),
        body.title, body.description, body.type,
        body.time_limit, body.max_attempts,
        body.start_time, body.end_time, questions,
    )
    return maybe_envelope(request, _serialize_quiz_summary(quiz))

@router.get("/classes/{class_id}/quizzes", summary="List class quizzes")
async def list_quizzes(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await _authorize_class_access(db, class_id, current_user)
    cursor = db.lms_quizzes.find({"class_id": class_id})
    quizzes = await cursor.to_list(None)
    role = normalize_role(current_user.get("role"))
    attempt_map = {}
    if role not in ("teacher", "admin"):
        attempt_map = await _build_latest_attempt_map(
            db,
            [q["id"] for q in quizzes],
            str(current_user["_id"]),
        )
    return maybe_envelope(request, [_serialize_quiz_summary(q, attempt_map) for q in quizzes])

@router.get("/quizzes", summary="List all quizzes across classes")
async def global_quizzes(
    request: Request,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = normalize_role(current_user.get("role"))
    user_id = str(current_user["_id"])
    if role == "admin":
        c_cursor = db.classes.find({})
    elif role == "teacher":
        c_cursor = db.classes.find({"teacher_id": user_id})
    else:
        c_cursor = db.classes.find({"students": user_id})
    
    classes = await c_cursor.to_list(None)
    class_ids = [c["id"] for c in classes]
    q_cursor = db.lms_quizzes.find({"class_id": {"$in": class_ids}})
    quizzes = await q_cursor.to_list(None)
    attempt_map = {}
    if role not in ("teacher", "admin"):
        attempt_map = await _build_latest_attempt_map(db, [q["id"] for q in quizzes], user_id)
    return maybe_envelope(request, [_serialize_quiz_summary(q, attempt_map) for q in quizzes])

@router.get("/quizzes/{quiz_id}", summary="Get quiz details and questions")
async def get_quiz(
    request: Request,
    quiz_id: str,
    db = Depends(get_db),
    current_user=Depends(get_current_user),
):
    quiz = await db.lms_quizzes.find_one({"id": quiz_id})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    _, include_answers = await _authorize_quiz_access(db, quiz, current_user)

    q_cursor = db.quiz_questions.find({"quiz_id": quiz_id}).sort("order_index", 1)
    questions = await q_cursor.to_list(None)
    
    return maybe_envelope(request, {
        "id": quiz["id"],
        "quiz_id": quiz["id"],
        "class_id": quiz.get("class_id"),
        "title": quiz.get("title"),
        "description": quiz.get("description"),
        "time_limit": quiz.get("time_limit"),
        "type": quiz.get("type", "quiz"),
        "max_attempts": quiz.get("max_attempts", 1),
        "start_time": quiz.get("start_time"),
        "end_time": quiz.get("end_time"),
        "questions": [
            _serialize_quiz_question(q, include_answers=include_answers)
            for q in questions
        ]
    })

@router.post("/quizzes/{quiz_id}/attempt", summary="Student: submit quiz attempt")
async def attempt_quiz(
    request: Request,
    quiz_id: str,
    body: SubmitQuizIn,
    db = Depends(get_db),
    current_user=Depends(require_role("student")),
):
    try:
        quiz = await db.lms_quizzes.find_one({"id": quiz_id})
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        await _authorize_quiz_access(db, quiz, current_user)
        attempt = await lms_service.submit_quiz_attempt(
            db, quiz_id, str(current_user["_id"]), body.answers
        )
        return maybe_envelope(request, {
            "id": attempt.get("id"),
            "quiz_id": quiz_id,
            "class_id": attempt.get("class_id"),
            "submitted": True,
            "score": attempt.get("score"),
            "max_score": attempt.get("max_score"),
            "percentage": attempt.get("percentage"),
            "correct_count": attempt.get("correct_count"),
            "question_results": attempt.get("question_results", []),
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ─── Quiz Analytics ───────────────────────────────────────────────────────────

@router.get("/quizzes/{quiz_id}/analytics", summary="Teacher: quiz attempt analytics")
async def quiz_analytics(
    request: Request,
    quiz_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    quiz = await db.lms_quizzes.find_one({"id": quiz_id})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    await _authorize_class_staff_access(db, quiz["class_id"], current_user)

    # Get all complete attempts
    attempts_cursor = db.quiz_attempts.find({"quiz_id": quiz_id, "is_complete": True})
    attempts = await attempts_cursor.to_list(None)

    if not attempts:
        return maybe_envelope(request, {"quiz_id": quiz_id, "title": quiz.get("title"), "attempt_count": 0, "avg_score": 0, "results": []})

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

    return maybe_envelope(request, {
        "quiz_id": quiz_id,
        "title": quiz.get("title"),
        "attempt_count": len(attempts),
        "avg_score": avg_score,
        "results": results,
    })


# ─── Per-Student Engagement in a Class ────────────────────────────────────────

@router.get("/classes/{class_id}/students/engagement", summary="Teacher: per-student engagement scores")
async def class_student_engagement(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
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

    quiz_ids = [q["id"] for q in await db.lms_quizzes.find({"class_id": class_id}).to_list(None)]
    attempts = await db.quiz_attempts.find({"quiz_id": {"$in": quiz_ids}, "is_complete": True}).to_list(None) if quiz_ids else []
    attempt_by_student = {}
    for attempt in attempts:
        sid = attempt.get("student_id")
        if not sid:
            continue
        attempt_by_student.setdefault(sid, []).append(float(attempt.get("percentage") or 0))

    attendance_rows = await db.attendance_records.find({"class_id": class_id}).to_list(None)
    attendance_by_student = {}
    for row in attendance_rows:
        sid = row.get("student_id")
        if not sid:
            continue
        attendance_by_student.setdefault(sid, {"present": 0, "total": 0})
        attendance_by_student[sid]["total"] += 1
        if row.get("status") == "present":
            attendance_by_student[sid]["present"] += 1

    payload = {
        "class_id": class_id,
        "engagement_rate": stats.get("engagement_rate", 0),
        "students": [
            {
                "student_id": sid,
                "name": user_map.get(sid, {}).get("name") or user_map.get(sid, {}).get("email") or "Unknown",
                "email": user_map.get(sid, {}).get("email", ""),
                "avg_score": round(sum(attempt_by_student.get(sid, [])) / len(attempt_by_student[sid]), 1) if attempt_by_student.get(sid) else None,
                "avg_quiz_score": round(sum(attempt_by_student.get(sid, [])) / len(attempt_by_student[sid]), 1) if attempt_by_student.get(sid) else None,
                "quizzes_taken": len(attempt_by_student.get(sid, [])),
                "attendance_pct": round((attendance_by_student[sid]["present"] / attendance_by_student[sid]["total"]) * 100, 1) if attendance_by_student.get(sid, {}).get("total") else None,
            }
            for sid in student_ids
        ],
    }
    return maybe_envelope(request, payload)


# ─── Attendance ──────────────────────────────────────────────────────────────

@router.post("/classes/{class_id}/attendance", summary="Teacher: mark bulk attendance")
async def take_attendance(
    request: Request,
    class_id: str,
    body: MarkAttendanceIn,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    records = [r.dict() for r in body.records]
    await lms_service.mark_attendance(db, class_id, body.date, records)
    return maybe_envelope(request, {"message": "Attendance marked successfully."})

@router.get("/students/me/attendance", summary="Student: view own attendance")
async def my_attendance(
    request: Request,
    class_id: Optional[str] = None,
    db = Depends(get_db),
    current_user=Depends(require_role("student")),
):
    results = await lms_service.get_student_attendance(db, str(current_user["_id"]), class_id)
    return maybe_envelope(request, results)

@router.get("/classes/{class_id}/attendance/summary", summary="Teacher: view class stats")
async def class_attendance_stats(
    request: Request,
    class_id: str,
    db = Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    await _authorize_class_staff_access(db, class_id, current_user)
    stats = await lms_service.get_class_attendance_stats(db, class_id)
    return maybe_envelope(request, stats)

