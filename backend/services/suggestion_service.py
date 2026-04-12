import logging
import uuid
import asyncio
import json
from datetime import date, timedelta, datetime
from typing import Optional, List, Dict, Any

from bson import ObjectId

from backend.core.search_engine import search_engine
from backend.services.analytics_service import get_student_analytics

logger = logging.getLogger(__name__)

def _make_id():
    return str(uuid.uuid4())


def _serialize_suggestion_doc(doc: dict) -> dict:
    payload = {
        "id": doc.get("id") or (str(doc.get("_id")) if doc.get("_id") else ""),
        "category": doc.get("category", "general"),
        "suggestion": doc.get("suggestion", ""),
        "is_read": bool(doc.get("is_read", False)),
        "generated_at": doc.get("generated_at"),
    }
    generated_at = payload.get("generated_at")
    if isinstance(generated_at, datetime):
        payload["generated_at"] = generated_at.isoformat()
    return payload

# ─── Context Builder ──────────────────────────────────────────────────────────

async def _collect_user_context(db, user_id: str) -> dict:
    """Gather last 7 days of activity + recent quiz performance."""
    today = date.today()
    seven_days_ago = today - timedelta(days=7)
    
    start_date_str = str(seven_days_ago)

    # Activity logs
    cursor = db.activity_logs.find({
        "user_id": user_id,
        "date": {"$gte": start_date_str}
    }).sort("date", -1)
    logs = await cursor.to_list(None)

    # Recent quiz attempts
    cursor = db.quiz_attempts.find({
        "student_id": user_id,
        "is_complete": True
    }).sort("submitted_at", -1).limit(10)
    attempts = await cursor.to_list(None)

    # Aggregate by category
    totals: dict = {
        "workout": {"days": 0, "total_duration_min": 0, "total_calories": 0},
        "food":    {"total_calories": 0, "meals_logged": 0},
        "study":   {"total_duration_min": 0, "topics": []},
        "mind":    {"total_duration_min": 0, "activities": []},
    }

    for log in logs:
        d = log.get("data", {})
        cat = log.get("category")
        if cat == "workout":
            totals["workout"]["days"] += 1
            totals["workout"]["total_duration_min"] += int(d.get("duration_min", 0))
            totals["workout"]["total_calories"] += int(d.get("calories_burned", 0))
        elif cat == "food":
            totals["food"]["total_calories"] += int(d.get("total_calories", 0))
            totals["food"]["meals_logged"] += 1
        elif cat == "study":
            totals["study"]["total_duration_min"] += int(d.get("duration_min", 0))
            totals["study"]["topics"].extend(d.get("topics", []))
        elif cat == "mind":
            totals["mind"]["total_duration_min"] += int(d.get("duration_min", 0))
            totals["mind"]["activities"].append(d.get("activity", ""))

    quiz_summary = [
        {
            "quiz_id": a["quiz_id"],
            "percentage": float(a.get("percentage") or 0),
            "score": float(a.get("score") or 0),
            "max": float(a.get("max_score") or 0),
        }
        for a in attempts
    ]

    return {"totals": totals, "quiz_summary": quiz_summary, "days_tracked": 7}


# ─── LLM Prompt Builder ───────────────────────────────────────────────────────

def _build_suggestion_prompt(ctx: dict) -> str:
    t = ctx["totals"]
    avg_quiz = None
    if ctx["quiz_summary"]:
        total_pct = sum(float(q["percentage"]) for q in ctx["quiz_summary"])
        avg_quiz = float(f"{total_pct / len(ctx['quiz_summary']):.1f}")

    prompt_parts = [
        "You are a personal AI coach. Based on the following 7-day summary, give 3-5 concise, actionable suggestions across health, study, and productivity. Be specific and encouraging.\n",
        f"WORKOUT: {t['workout']['days']}/7 days active, "
        f"{t['workout']['total_duration_min']} min total, "
        f"{t['workout']['total_calories']} kcal burned.",

        f"NUTRITION: {t['food']['meals_logged']} meals logged, "
        f"{t['food']['total_calories']} total kcal.",

        f"STUDY: {t['study']['total_duration_min']} min studied, "
        f"topics: {', '.join(set(t['study']['topics'][:10])) or 'none tracked'}.",

        f"MINDFULNESS: {t['mind']['total_duration_min']} min, "
        f"activities: {', '.join(set(t['mind']['activities'][:5])) or 'none'}.",
    ]

    if avg_quiz is not None:
        prompt_parts.append(f"QUIZ PERFORMANCE: avg score {avg_quiz}% across {len(ctx['quiz_summary'])} recent attempts.")

    prompt_parts.append(
        "\nRespond ONLY with a JSON array of objects, each with keys "
        '"category" (study|health|productivity) and "suggestion" (string). '
        "No preamble, no markdown fences."
    )

    return "\n".join(prompt_parts)


# ─── Suggestion Generator ─────────────────────────────────────────────────────

async def generate_suggestions(
    db,
    user_id: str,
    llm_client=None,
    save: bool = True,
) -> Dict[str, Any]:
    """
    Generate AI suggestions and material recommendations.
    """
    ctx = await _collect_user_context(db, user_id)
    analytics = await get_student_analytics(db, user_id)
    
    suggestions: List[Dict] = []

    if llm_client:
        try:
            prompt = _build_suggestion_prompt(ctx)
            raw = await llm_client.async_generate(prompt, temperature=0.8)
            
            if "```json" in raw:
                raw = raw.split("```json")[-1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[-1].split("```")[0].strip()
            
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                suggestions = parsed
        except Exception as e:
            logger.warning(f"LLM suggestion generation failed: {e}. Using rule-based fallback.")

    if not suggestions:
        suggestions = _rule_based_suggestions(ctx)

    # --- NEW: RAG-BASED RECOMMENDATIONS ---
    recommendations = []
    if analytics.get("weak_subjects"):
        loop = asyncio.get_event_loop()
        for ws in analytics["weak_subjects"]:
            subject_name = ws["subject"]
            query = f"Study materials and key concepts for {subject_name}"
            # Search knowledge base for this subject
            chunks = await loop.run_in_executor(None, search_engine.search, user_id, subject_name, query, 3, None)
            
            for c in chunks:
                recommendations.append({
                    "subject": subject_name,
                    "title": c.get("metadata", {}).get("source", "Reference Material"),
                    "text": c.get("text", "")[:200] + "...",
                    "score": c.get("score")
                })
    
    if save:
        docs = []
        for s in suggestions:
            doc = {
                "id": _make_id(),
                "user_id": user_id,
                "category": s.get("category", "general"),
                "suggestion": s["suggestion"],
                "is_read": False,
                "generated_at": datetime.utcnow()
            }
            docs.append(doc)
        if docs:
            await db.ai_suggestions.insert_many(docs)

    return {
        "suggestions": list(suggestions),
        "recommendations": recommendations[0:5], # Use explicit slice
        "analytics": dict(analytics)
    }


def _rule_based_suggestions(ctx: dict) -> list[dict]:
    """Lightweight rule-based suggestions when LLM is unavailable."""
    suggestions = []
    t = ctx["totals"]

    # Workout
    if t["workout"]["days"] < 3:
        suggestions.append({
            "category": "health",
            "suggestion": "You worked out fewer than 3 days this week. Try adding a 20-minute walk on rest days to stay active.",
        })
    if t["workout"]["total_calories"] < 1000 and t["workout"]["days"] > 0:
        suggestions.append({
            "category": "health",
            "suggestion": "Your workout intensity seems low. Consider adding 1 high-intensity session per week (HIIT, cycling) to boost calorie burn.",
        })

    # Study
    if t["study"]["total_duration_min"] < 300:
        suggestions.append({
            "category": "study",
            "suggestion": "Aim for at least 60 minutes of focused study daily. Use the Pomodoro technique (25 min work + 5 min break) to improve consistency.",
        })

    # Food
    if t["food"]["meals_logged"] < 7:
        suggestions.append({
            "category": "health",
            "suggestion": "Tracking your meals helps spot nutritional gaps. Try logging every meal for 7 days to build awareness.",
        })

    # Mindfulness
    if t["mind"]["total_duration_min"] < 60:
        suggestions.append({
            "category": "productivity",
            "suggestion": "Just 10 minutes of meditation or reading per day can significantly reduce stress and improve focus. Start small!",
        })

    # Quiz
    quiz_summary = ctx.get("quiz_summary", [])
    if quiz_summary:
        avg = sum(q["percentage"] for q in quiz_summary) / len(quiz_summary)
        if avg < 60:
            suggestions.append({
                "category": "study",
                "suggestion": f"Your average quiz score is {avg:.1f}%. Revisit the topics from recent quizzes and do practice problems before your next test.",
            })

    if not suggestions:
        suggestions.append({
            "category": "productivity",
            "suggestion": "Great week! Keep maintaining your current study and wellness routines for long-term success.",
        })

    return suggestions


async def get_user_suggestions(
    db,
    user_id: str,
    unread_only: bool = False,
    limit: int = 20,
) -> list:
    query = {"user_id": user_id}
    if unread_only:
        query["is_read"] = False
        
    cursor = db.ai_suggestions.find(query).sort("generated_at", -1).limit(limit)
    docs = await cursor.to_list(None)
    return [_serialize_suggestion_doc(doc) for doc in docs]


async def mark_suggestion_read(db, suggestion_id: str, user_id: str) -> bool:
    criteria = [{"id": suggestion_id}]
    if ObjectId.is_valid(suggestion_id):
        criteria.append({"_id": ObjectId(suggestion_id)})
    res = await db.ai_suggestions.update_one(
        {"user_id": user_id, "$or": criteria},
        {"$set": {"is_read": True}}
    )
    return res.modified_count > 0
