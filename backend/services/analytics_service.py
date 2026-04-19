import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

def _make_id():
    return str(uuid.uuid4())


UTC_MIN = datetime.min.replace(tzinfo=timezone.utc)


def _coerce_utc_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _coerce_utc_dt_or_min(value: Any) -> datetime:
    return _coerce_utc_dt(value) or UTC_MIN


def _coerce_date_key(value: Any) -> str:
    dt = _coerce_utc_dt(value)
    if dt:
        return dt.strftime("%Y-%m-%d")

    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:10]
    return text or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _build_lms_quiz_subject_lookup(db, quiz_ids: List[str]) -> Dict[str, Dict[str, str]]:
    if not quiz_ids:
        return {}

    quizzes = await db.lms_quizzes.find({"id": {"$in": quiz_ids}}).to_list(None)
    class_ids = list({q.get("class_id") for q in quizzes if q.get("class_id")})
    classes = await db.classes.find({"id": {"$in": class_ids}}).to_list(None) if class_ids else []
    class_lookup = {cls["id"]: cls for cls in classes if cls.get("id")}

    lookup: Dict[str, Dict[str, str]] = {}
    for quiz in quizzes:
        cls = class_lookup.get(quiz.get("class_id"))
        subject = "General"
        if cls:
            subject = cls.get("subject") or cls.get("name") or "General"
        lookup[quiz["id"]] = {
            "subject": subject,
            "title": quiz.get("title", "Quiz"),
        }
    return lookup


async def get_student_analytics(db, user_id: str, days: int = 7) -> Dict[str, Any]:
    """
    Aggregate student performance and engagement data.
    """
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=days)
    start_date = start_dt.strftime("%Y-%m-%d")

    # 1. Study Time (from activity logs)
    study_logs_cursor = db.activity_logs.find({
        "user_id": user_id,
        "category": "study",
        "date": {"$gte": start_date}
    })
    study_logs = await study_logs_cursor.to_list(None)
    
    study_time_by_day = {}
    total_study_min = 0
    for log in study_logs:
        d = _coerce_date_key(log.get("date") or log.get("logged_at"))
        duration = int(log.get("data", {}).get("duration_min", 0) or 0)
        study_time_by_day[d] = study_time_by_day.get(d, 0) + duration
        total_study_min += duration

    # 2. Performance Trends (from quiz attempts)
    quiz_attempts_cursor = db.quiz_attempts.find({
        "student_id": user_id,
        "is_complete": True,
    })
    attempts = await quiz_attempts_cursor.to_list(None)
    quiz_lookup = await _build_lms_quiz_subject_lookup(
        db,
        list({attempt.get("quiz_id") for attempt in attempts if attempt.get("quiz_id")}),
    )

    performance_trend = []
    subject_performance = {} # {subject: [scores]}
    
    for attempt in attempts:
        try:
            submitted_at = _coerce_utc_dt(attempt.get("submitted_at"))
            if not submitted_at or submitted_at < start_dt:
                continue

            score_pct = _safe_float(attempt.get("percentage"), 0.0)
            quiz_meta = quiz_lookup.get(attempt.get("quiz_id"), {})
            subject = quiz_meta.get("subject") or attempt.get("subject") or "General"

            performance_trend.append({
                "date": submitted_at.strftime("%Y-%m-%d"),
                "score": score_pct,
                "quiz_id": attempt.get("quiz_id")
            })

            if subject not in subject_performance:
                subject_performance[subject] = []
            subject_performance[subject].append(score_pct)
        except Exception:
            continue

    performance_trend.sort(key=lambda item: (item.get("date") or "", item.get("quiz_id") or ""))

    # 3. Identify Weak Subjects
    weak_subjects = []
    for subject, scores in subject_performance.items():
        avg = sum(scores) / len(scores)
        if avg < 70: # Arbitrary threshold for "weak"
            weak_subjects.append({
                "subject": subject,
                "average": float(round(avg, 1)),
                "count": len(scores)
            })
    
    weak_subjects.sort(key=lambda x: x["average"])

    return {
        "user_id": user_id,
        "period_days": int(days),
        "total_study_minutes": int(total_study_min),
        "study_time_series": dict(study_time_by_day),
        "performance_trend": list(performance_trend),
        "weak_subjects": list(weak_subjects[:3]), # Top 3 weak areas
        "avg_score": float(round(sum(q["score"] for q in performance_trend)/len(performance_trend), 1)) if performance_trend else 0.0
    }

async def get_teacher_analytics(db, class_id: str) -> Dict[str, Any]:
    """
    Aggregate class-wide performance for teachers.
    """
    # 1. Get Class Info
    cls = await db.classes.find_one({"id": class_id})
    if not cls:
        raise ValueError("Class not found")
    
    student_ids = cls.get("students", [])
    if not student_ids:
        return {
            "class_id": class_id,
            "message": "No students enrolled",
            "avg_score": 0,
            "engagement_rate": 0,
            "top_performing_students": [],
            "low_performing_students": [],
            "quiz_stats": [],
            "total_students": 0,
            "active_students_count": 0
        }

    # 2. Average Scores per Quiz
    quizzes_cursor = db.lms_quizzes.find({"class_id": class_id})
    quizzes = await quizzes_cursor.to_list(None)
    quiz_ids = [q["id"] for q in quizzes]

    quiz_stats = []
    all_scores_by_student: Dict[str, list] = {}
    
    for qid in quiz_ids:
        attempts_cursor = db.quiz_attempts.find({"quiz_id": qid, "is_complete": True})
        attempts = await attempts_cursor.to_list(None)
        if attempts:
            avg = sum(float(a.get("percentage") or 0) for a in attempts) / len(attempts)
            quiz_stats.append({
                "quiz_id": str(qid),
                "title": str(next((q["title"] for q in quizzes if q["id"] == qid), "Unknown")),
                "avg_score": float(round(avg, 1)),
                "submission_count": int(len(attempts))
            })
            # Track per-student scores
            for a in attempts:
                sid = a.get("student_id", "")
                if sid not in all_scores_by_student:
                    all_scores_by_student[sid] = []
                all_scores_by_student[sid].append(float(a.get("percentage") or 0))

    # 3. Class average score
    all_avg_scores = []
    student_avg_map = []
    for sid, scores in all_scores_by_student.items():
        avg = round(sum(scores) / len(scores), 1)
        student_avg_map.append({"student_id": sid, "score": avg})
        all_avg_scores.append(avg)
    
    class_avg_score = round(sum(all_avg_scores) / len(all_avg_scores), 1) if all_avg_scores else 0.0
    student_avg_map.sort(key=lambda x: x["score"], reverse=True)
    top_performers = student_avg_map[:3]
    low_performers = student_avg_map[-3:] if len(student_avg_map) > 3 else []

    # 4. Engagement Score Calculation (Attendance + Tests + Chat)
    
    # A. Attendance (40 pts)
    att_cursor = db.attendance.find({"class_id": class_id})
    att_records = await att_cursor.to_list(None)
    
    student_att_totals = {sid: {"present": 0, "total": 0} for sid in student_ids}
    for r in att_records:
        for rec in r.get("records", []):
            sid = rec.get("student_id")
            if sid in student_att_totals:
                student_att_totals[sid]["total"] += 1
                if rec.get("status") == "present":
                    student_att_totals[sid]["present"] += 1
                    
    # B. Test Participation (40 pts)
    student_quiz_counts = {sid: 0 for sid in student_ids}
    for qid in quiz_ids:
        attempts_cursor = db.quiz_attempts.find({"quiz_id": qid, "is_complete": True})
        q_attempts = await attempts_cursor.to_list(None)
        q_sids = set(a.get("student_id") for a in q_attempts if a.get("student_id"))
        for sid in q_sids:
            if sid in student_quiz_counts:
                student_quiz_counts[sid] += 1
                
    # C. Chat/Activity Interactions (20 pts)
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    engagement_cursor = db.activity_logs.find({
        "user_id": {"$in": student_ids},
        "date": {"$gte": week_ago}
    })
    logs = await engagement_cursor.to_list(None)
    
    student_interactions = {sid: 0 for sid in student_ids}
    for log in logs:
        sid = log.get("user_id")
        if sid in student_interactions:
            student_interactions[sid] += 1
            
    # Calculate Engagement Score per student
    total_quizzes = len(quiz_ids)
    all_engagement_scores = []
    active_count = 0
    
    for sid in student_ids:
        # Attendance 40%
        att_pts = 0.0
        if student_att_totals[sid]["total"] > 0:
            att_pts = (student_att_totals[sid]["present"] / student_att_totals[sid]["total"]) * 40.0
            
        # Test Participation 40%
        test_pts = 0.0
        if total_quizzes > 0:
            test_pts = (student_quiz_counts[sid] / total_quizzes) * 40.0
            
        # Chat 20% (Max 20 pts, 1 log = 4 pts)
        chat_pts = min(20.0, student_interactions[sid] * 4.0)
        
        score = att_pts + test_pts + chat_pts
        all_engagement_scores.append(score)
        
        # Track active
        if student_interactions[sid] > 0 or student_quiz_counts[sid] > 0:
            active_count += 1
            
    # Class Average Engagement
    engagement_rate = round(sum(all_engagement_scores) / len(all_engagement_scores), 1) if all_engagement_scores else 0.0
    active_students = active_count

    return {
        "class_id": class_id,
        "total_students": len(student_ids),
        "quiz_stats": quiz_stats,
        "engagement_rate": engagement_rate,       # 0-100 percentage
        "active_students_count": active_students,
        "avg_score": class_avg_score,             # 0-100 percentage
        "top_performing_students": top_performers,
        "low_performing_students": low_performers,
    }
