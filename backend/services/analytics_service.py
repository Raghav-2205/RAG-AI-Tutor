import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

def _make_id():
    return str(uuid.uuid4())

async def get_student_analytics(db, user_id: str, days: int = 7) -> Dict[str, Any]:
    """
    Aggregate student performance and engagement data.
    """
    now = datetime.utcnow()
    start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

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
        d = log.get("date")
        duration = int(log.get("data", {}).get("duration_min", 0))
        study_time_by_day[d] = study_time_by_day.get(d, 0) + duration
        total_study_min += duration

    # 2. Performance Trends (from quiz attempts)
    quiz_attempts_cursor = db.quiz_attempts.find({
        "student_id": user_id,
        "is_complete": True,
        "submitted_at": {"$gte": now - timedelta(days=days)}
    }).sort("submitted_at", 1)
    attempts = await quiz_attempts_cursor.to_list(None)

    performance_trend = []
    subject_performance = {} # {subject: [scores]}
    
    for attempt in attempts:
        score_pct = float(attempt.get("percentage") or 0)
        performance_trend.append({
            "date": attempt["submitted_at"].strftime("%Y-%m-%d"),
            "score": score_pct,
            "quiz_id": attempt.get("quiz_id")
        })
        
        # Track by subject
        subject = attempt.get("subject") or "General"
        if subject not in subject_performance:
            subject_performance[subject] = []
        subject_performance[subject].append(score_pct)

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

    # 4. Engagement Rate
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    engagement_cursor = db.activity_logs.find({
        "user_id": {"$in": student_ids},
        "date": {"$gte": week_ago}
    })
    logs = await engagement_cursor.to_list(None)
    
    active_students = len(set(log["user_id"] for log in logs))
    # Return as 0-100 percentage
    engagement_rate = round((active_students / len(student_ids)) * 100, 1) if student_ids else 0.0

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
