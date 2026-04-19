import logging

from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Dict

from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.services.analytics_service import get_student_analytics, get_teacher_analytics
from backend.services.suggestion_service import generate_suggestions
from backend.core.llm_interface import llm_client

router = APIRouter()
logger = logging.getLogger(__name__)


def _empty_student_analytics(user_id: str) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "period_days": 7,
        "total_study_minutes": 0,
        "study_time_series": {},
        "performance_trend": [],
        "weak_subjects": [],
        "avg_score": 0.0,
    }

@router.get("/student", summary="Get personalized student analytics and recommendations")
async def student_analytics(
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user_id = str(current_user["_id"])

    analytics: Dict[str, Any] = _empty_student_analytics(user_id)
    suggestions: list = []
    recommendations: list = []

    try:
        analytics = await get_student_analytics(db, user_id)
    except Exception:
        logger.exception("Student analytics generation failed for user %s", user_id)

    try:
        suggestions_data = await generate_suggestions(db, user_id, llm_client=llm_client)
        if isinstance(suggestions_data, dict):
            generated_analytics = suggestions_data.get("analytics")
            if isinstance(generated_analytics, dict) and generated_analytics:
                analytics = generated_analytics
            suggestions = suggestions_data.get("suggestions") or []
            recommendations = suggestions_data.get("recommendations") or []
    except Exception:
        logger.exception("Student suggestion generation failed for user %s", user_id)

    return {
        "analytics": analytics,
        "suggestions": suggestions,
        "recommendations": recommendations,
    }

@router.get("/teacher/{class_id}", summary="Get class analytics for teachers")
async def teacher_analytics(
    class_id: str,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Ensure user is teacher/admin (role check)
    role = current_user.get("role", "student").lower()
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers can view class analytics")
    
    try:
        stats = await get_teacher_analytics(db, class_id)
        return stats
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


from bson import ObjectId

@router.get("/class/{class_id}/students", summary="Per-student engagement breakdown for teacher")
async def class_student_analytics(
    class_id: str,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Returns attendance %, quiz participation, and activity score per student."""
    role = current_user.get("role", "student").lower()
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")

    student_ids = cls.get("students", [])
    if not student_ids:
        return []

    # Resolve student names
    users = await db.users.find(
        {"_id": {"$in": [ObjectId(sid) for sid in student_ids]}}
    ).to_list(None)
    user_map = {str(u["_id"]): {"name": u.get("name", "Unknown"), "email": u.get("email", "")} for u in users}

    # Attendance per student
    att_cursor = db.attendance_records.find({"class_id": class_id, "student_id": {"$in": student_ids}})
    att_records = await att_cursor.to_list(None)
    att_data: Dict[str, Dict] = {sid: {"present": 0, "total": 0} for sid in student_ids}
    for r in att_records:
        sid = r.get("student_id")
        if sid in att_data:
            att_data[sid]["total"] += 1
            if r.get("status") == "present":
                att_data[sid]["present"] += 1

    # Quiz attempts per student
    quizzes = await db.lms_quizzes.find({"class_id": class_id}).to_list(None)
    quiz_ids = [q["id"] for q in quizzes]
    quiz_count_map: Dict[str, int] = {sid: 0 for sid in student_ids}
    quiz_score_map: Dict[str, list] = {sid: [] for sid in student_ids}
    if quiz_ids:
        attempts = await db.quiz_attempts.find({"quiz_id": {"$in": quiz_ids}}).to_list(None)
        for a in attempts:
            sid = a.get("student_id")
            if sid and sid in quiz_count_map:
                quiz_count_map[sid] += 1
                if a.get("percentage") is not None:
                    quiz_score_map[sid].append(float(a["percentage"]))

    result = []
    for sid in student_ids:
        att = att_data[sid]
        att_pct = round(att["present"] / att["total"] * 100, 1) if att["total"] > 0 else None
        scores = quiz_score_map[sid]
        avg_score = round(sum(scores) / len(scores), 1) if scores else None
        quizzes_taken = quiz_count_map[sid]

        result.append({
            "student_id": sid,
            "name": user_map.get(sid, {}).get("name", "Unknown"),
            "email": user_map.get(sid, {}).get("email", ""),
            "attendance_pct": att_pct,
            "quizzes_taken": quizzes_taken,
            "total_quizzes": len(quiz_ids),
            "avg_quiz_score": avg_score,
        })

    result.sort(key=lambda x: (x["avg_quiz_score"] or 0), reverse=True)
    return result


@router.get("/class/{class_id}/weak-topics", summary="Weak topics from quiz mistakes")
async def class_weak_topics(
    class_id: str,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Surfaces questions most-often answered incorrectly by the class."""
    role = current_user.get("role", "student").lower()
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teachers only")

    quizzes = await db.lms_quizzes.find({"class_id": class_id}).to_list(None)
    quiz_ids = [q["id"] for q in quizzes]
    if not quiz_ids:
        return []

    # Gather all question-level wrong answers from attempts
    from collections import defaultdict
    wrong_counts = defaultdict(int)
    total_counts = defaultdict(int)
    question_text_map = {}

    questions = await db.quiz_questions.find({"quiz_id": {"$in": quiz_ids}}).to_list(None)
    for q in questions:
        question_text_map[q["id"]] = q.get("question", "")

    attempts = await db.quiz_attempts.find({"quiz_id": {"$in": quiz_ids}, "is_complete": True}).to_list(None)
    for attempt in attempts:
        answers = attempt.get("answers", {})
        results = attempt.get("question_results", {})
        for qid, is_correct in results.items():
            total_counts[qid] += 1
            if not is_correct:
                wrong_counts[qid] += 1

    weak_topics = []
    for qid, wrong in wrong_counts.items():
        total = total_counts[qid]
        wrong_pct = round(wrong / total * 100, 1) if total > 0 else 0
        if wrong_pct >= 40:  # flag if ≥40% get it wrong
            weak_topics.append({
                "question_id": qid,
                "question": question_text_map.get(qid, "Unknown"),
                "wrong_pct": wrong_pct,
                "total_attempts": total
            })

    weak_topics.sort(key=lambda x: x["wrong_pct"], reverse=True)
    return weak_topics[:10]  # Top 10 weakest
