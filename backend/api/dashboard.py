# backend/api/dashboard.py
"""
Student Dashboard API
Aggregates data from all collections to power the LMS dashboard:
- Summary stats (streak, questions asked, quiz avg, documents)
- Topic mastery map (from quiz + validation data)
- Recent activity feed
- AI answer quality metrics
- Study recommendations
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from fastapi import APIRouter, Depends
from backend.utils.db import get_db
from backend.api.auth import get_current_user
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def _safe_avg(values: List[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


# ─────────────────────────────────────────────
# GET /api/dashboard/summary
# ─────────────────────────────────────────────
@router.get("/summary")
async def get_summary(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Hero stats: streak, total questions, quiz average, documents indexed, weekly trend.
    """
    from bson import ObjectId
    user_id = str(current_user["_id"])
    user_oid = current_user["_id"]
    now = datetime.utcnow()

    # ── 1. Total chat messages (questions asked) ──
    sessions = await db.chat_sessions.find(
        {"user_id": user_id}
    ).to_list(length=None)

    total_questions = sum(
        len([m for m in s.get("messages", []) if m.get("role") == "user"])
        for s in sessions
    )

    # ── 2. Study streak (days with at least 1 chat activity) ──
    active_days = set()
    for s in sessions:
        for m in s.get("messages", []):
            ts = m.get("timestamp")
            if ts:
                active_days.add(ts.date())

    streak = 0
    check = now.date()
    while check in active_days:
        streak += 1
        check -= timedelta(days=1)

    # ── 3. Questions this week ──
    week_ago = now - timedelta(days=7)
    questions_this_week = sum(
        len([
            m for m in s.get("messages", [])
            if m.get("role") == "user" and m.get("timestamp", datetime.min) >= week_ago
        ])
        for s in sessions
    )

    # ── 4. Documents uploaded ──
    doc_count = await db.documents.count_documents({"user_id": user_oid})

    # ── 5. Quiz average score ──
    quiz_results = await db.quiz_submissions.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(20).to_list(length=20)

    scores = [r.get("percentage", 0) for r in quiz_results if "percentage" in r]
    quiz_avg = round(_safe_avg(scores), 1)
    quizzes_taken = await db.quiz_submissions.count_documents({"user_id": user_id})

    # ── 6. Weekly activity (last 7 days) ──
    weekly_activity = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = sum(
            len([
                m for m in s.get("messages", [])
                if m.get("role") == "user"
                and day_start <= m.get("timestamp", datetime.min) < day_end
            ])
            for s in sessions
        )
        weekly_activity.append({
            "day": day.strftime("%a"),
            "date": day.strftime("%Y-%m-%d"),
            "questions": count
        })

    return {
        "streak": streak,
        "total_questions": total_questions,
        "questions_this_week": questions_this_week,
        "doc_count": doc_count,
        "quiz_avg": quiz_avg,
        "quizzes_taken": quizzes_taken,
        "weekly_activity": weekly_activity
    }


# ─────────────────────────────────────────────
# GET /api/dashboard/mastery
# ─────────────────────────────────────────────
@router.get("/mastery")
async def get_mastery(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Knowledge mastery per topic, derived from quiz results and validation scores.
    """
    user_id = str(current_user["_id"])

    quiz_submissions = await db.quiz_submissions.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(50).to_list(length=50)

    # Build a quiz_id → subject lookup from db.quizzes
    quiz_ids = list({s.get("quiz_id") for s in quiz_submissions if s.get("quiz_id")})
    subject_lookup: Dict[str, str] = {}
    if quiz_ids:
        quizzes_cursor = await db.quizzes.find(
            {"quiz_id": {"$in": quiz_ids}}, {"quiz_id": 1, "subject": 1}
        ).to_list(length=len(quiz_ids))
        for q in quizzes_cursor:
            subject_lookup[q["quiz_id"]] = q.get("subject", "General")

    # Aggregate per subject from quiz scores
    subject_scores: Dict[str, List[float]] = {}
    weak_topics_all: Dict[str, int] = {}

    for r in quiz_submissions:
        subject = subject_lookup.get(r.get("quiz_id", ""), "General")
        score = r.get("percentage")
        if score is not None:
            subject_scores.setdefault(subject, []).append(score)

        # Tally weak topic mentions
        for wt in r.get("weak_topics", []):
            topic = wt.strip()
            if topic:
                weak_topics_all[topic] = weak_topics_all.get(topic, 0) + 1

    # Build mastery map
    mastery = []
    for subject, scores in subject_scores.items():
        avg = _safe_avg(scores)
        last_score = scores[0] if scores else 0
        mastery.append({
            "subject": subject,
            "mastery_pct": round(avg, 1),
            "last_score": round(last_score, 1),
            "attempts": len(scores),
            "trend": "up" if len(scores) >= 2 and scores[0] > scores[1] else
                     "down" if len(scores) >= 2 and scores[0] < scores[1] else "stable"
        })

    mastery.sort(key=lambda x: x["mastery_pct"])  # weakest first

    # Top weak topics
    weak_topics = sorted(weak_topics_all.items(), key=lambda x: -x[1])
    weak_topics = [{"topic": t, "count": c} for t, c in weak_topics[:8]]

    return {
        "mastery": mastery,
        "weak_topics": weak_topics
    }


# ─────────────────────────────────────────────
# GET /api/dashboard/activity
# ─────────────────────────────────────────────
@router.get("/activity")
async def get_activity(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Recent activity: last chats, quiz attempts, uploaded documents.
    """
    from bson import ObjectId
    user_id = str(current_user["_id"])
    user_oid = current_user["_id"]

    # Recent chats
    recent_sessions = await db.chat_sessions.find(
        {"user_id": user_id, "messages": {"$not": {"$size": 0}}}
    ).sort("updated_at", -1).limit(5).to_list(length=5)

    chats = []
    for s in recent_sessions:
        msg_count = len([m for m in s.get("messages", []) if m.get("role") == "user"])
        chats.append({
            "chat_id": s.get("chat_id"),
            "title": s.get("title", "Untitled Chat"),
            "subject": s.get("subject", "General"),
            "message_count": msg_count,
            "updated_at": s.get("updated_at", datetime.utcnow()).isoformat()
        })

    # Recent quizzes — from quiz_submissions, join subject from quizzes
    recent_submissions = await db.quiz_submissions.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(5).to_list(length=5)

    # Build subject lookup for these quiz IDs
    sub_quiz_ids = [s.get("quiz_id") for s in recent_submissions if s.get("quiz_id")]
    sub_lookup: Dict[str, str] = {}
    if sub_quiz_ids:
        sub_docs = await db.quizzes.find(
            {"quiz_id": {"$in": sub_quiz_ids}}, {"quiz_id": 1, "subject": 1}
        ).to_list(length=len(sub_quiz_ids))
        for qd in sub_docs:
            sub_lookup[qd["quiz_id"]] = qd.get("subject", "General")

    quizzes = []
    for q in recent_submissions:
        ts = q.get("timestamp", datetime.utcnow())
        quizzes.append({
            "quiz_id": q.get("quiz_id"),
            "subject": sub_lookup.get(q.get("quiz_id", ""), "General"),
            "score_percentage": round(q.get("percentage", 0), 1),
            "correct": q.get("score", 0),
            "total": q.get("total", 0),
            "completed_at": ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        })

    # Recent documents
    recent_docs = await db.documents.find(
        {"user_id": user_oid}
    ).sort("created_at", -1).limit(5).to_list(length=5)

    documents = []
    for d in recent_docs:
        documents.append({
            "doc_id": d.get("doc_id"),
            "filename": d.get("filename"),
            "subject": d.get("subject", "General"),
            "chunks_count": d.get("chunks_count", 0),
            "created_at": d.get("created_at", datetime.utcnow()).isoformat()
        })

    return {
        "recent_chats": chats,
        "recent_quizzes": quizzes,
        "recent_documents": documents
    }


# ─────────────────────────────────────────────
# GET /api/dashboard/quality
# ─────────────────────────────────────────────
@router.get("/quality")
async def get_quality(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    AI answer quality metrics from validation engine results.
    """
    user_id = str(current_user["_id"])

    validations = await db.rag_answer_validations.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(50).to_list(length=50)

    if not validations:
        return {
            "total_validated": 0,
            "avg_faithfulness": 0,
            "avg_rag_score": 0,
            "avg_relevance": 0,
            "avg_hallucination_rate": 0,
            "status_breakdown": {},
            "has_data": False
        }

    faithfulness = [v.get("faithfulness_score", 0) for v in validations if v.get("faithfulness_score") is not None]
    rag_scores = [v.get("final_rag_score", 0) for v in validations if v.get("final_rag_score") is not None]
    relevance = [v.get("answer_relevance", 0) for v in validations if v.get("answer_relevance") is not None]
    hallucination = [v.get("hallucination_rate", 0) for v in validations if v.get("hallucination_rate") is not None]

    status_breakdown: Dict[str, int] = {}
    for v in validations:
        status = v.get("validation_status", "UNKNOWN")
        status_breakdown[status] = status_breakdown.get(status, 0) + 1

    return {
        "total_validated": len(validations),
        "avg_faithfulness": _safe_avg(faithfulness),
        "avg_rag_score": _safe_avg(rag_scores),
        "avg_relevance": _safe_avg(relevance),
        "avg_hallucination_rate": _safe_avg(hallucination),
        "status_breakdown": status_breakdown,
        "has_data": True
    }


# ─────────────────────────────────────────────
# GET /api/dashboard/recommendations
# ─────────────────────────────────────────────
@router.get("/recommendations")
async def get_recommendations(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Personalized study recommendations based on quiz + feedback + validation data.
    """
    user_id = str(current_user["_id"])
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    recommendations = []

    # 1. Topics with consistently low quiz scores
    recent_subs = await db.quiz_submissions.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(20).to_list(length=20)

    weak_topics: Dict[str, int] = {}
    for r in recent_subs:
        for wt in r.get("weak_topics", []):
            topic = wt.strip()
            if topic:
                weak_topics[topic] = weak_topics.get(topic, 0) + 1

    for topic, count in sorted(weak_topics.items(), key=lambda x: -x[1])[:3]:
        recommendations.append({
            "type": "weak_topic",
            "priority": "high",
            "icon": "📚",
            "title": f"Review: {topic}",
            "detail": f"Appeared as a weak topic in {count} quiz(zes). Upload a resource or ask the AI tutor directly.",
            "action": f"Ask about {topic}",
            "action_url": "/views/subjects.html"
        })

    # 2. No quiz taken recently
    recent_quiz = await db.quiz_submissions.find_one(
        {"user_id": user_id, "timestamp": {"$gte": week_ago}}
    )
    if not recent_quiz:
        recommendations.append({
            "type": "quiz_reminder",
            "priority": "medium",
            "icon": "🧠",
            "title": "Take a Quiz",
            "detail": "You haven't taken a quiz in 7 days. Test your knowledge to track your progress.",
            "action": "Start a Quiz",
            "action_url": "/views/quiz.html"
        })

    # 3. Negative feedback pattern
    recent_feedback = await db.feedback.find(
        {"user_id": user_id, "timestamp": {"$gte": week_ago}}
    ).to_list(length=50)

    if recent_feedback:
        negative = [f for f in recent_feedback if f.get("rating") in ["negative", "1", "2"]]
        if len(negative) >= 2:
            recommendations.append({
                "type": "feedback_pattern",
                "priority": "medium",
                "icon": "💡",
                "title": "Improve Answer Quality",
                "detail": f"You gave negative feedback {len(negative)} time(s) recently. Try uploading a more focused textbook or PDF.",
                "action": "Upload Document",
                "action_url": "/views/subjects.html"
            })

    # 4. No documents uploaded
    user_oid = current_user["_id"]
    doc_count = await db.documents.count_documents({"user_id": user_oid})
    if doc_count == 0:
        recommendations.append({
            "type": "upload_prompt",
            "priority": "high",
            "icon": "📄",
            "title": "Upload Your Study Material",
            "detail": "Upload a PDF, DOCX, or PPTX file to unlock document-scoped RAG and get more accurate answers.",
            "action": "Upload Now",
            "action_url": "/views/subjects.html"
        })

    # 5. Low validation scores
    poor_validations = await db.rag_answer_validations.count_documents({
        "user_id": user_id,
        "validation_status": {"$in": ["REJECTED", "WARNING"]},
        "timestamp": {"$gte": week_ago}
    })
    if poor_validations >= 3:
        recommendations.append({
            "type": "quality_alert",
            "priority": "high",
            "icon": "⚠️",
            "title": "Answer Quality Concerns",
            "detail": f"{poor_validations} recent answers had low faithfulness. The AI may be hallucinating. Try enabling strict mode or uploading better source material.",
            "action": "View Quality Report",
            "action_url": "/views/evaluation.html"
        })

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda x: priority_order.get(x["priority"], 3))

    return {"recommendations": recommendations[:5]}
