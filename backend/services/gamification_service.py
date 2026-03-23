"""
Gamification Service — Points, Badges, Leaderboard
===================================================
Points:  Awarded for activities (submissions, quiz scores, logins, streaks)
Badges:  Milestone achievements
Leaderboard: Class & global ranking
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

# ─── Point Rules ─────────────────────────────────────────────────────────────
POINT_RULES = {
    "submit_assignment": 10,
    "assignment_graded_above_80": 20,
    "quiz_attempt": 5,
    "quiz_above_80": 15,
    "quiz_above_90": 25,
    "perfect_quiz": 50,
    "daily_login": 2,
    "streak_3_days": 10,
    "streak_7_days": 30,
    "streak_30_days": 100,
    "upload_material": 15,
    "forum_post": 5,
    "forum_reply": 3,
    "attend_class": 5,
}

# ─── Badge Definitions ────────────────────────────────────────────────────────
BADGE_DEFINITIONS = [
    {"id": "first_submission",    "name": "First Steps",      "emoji": "🎯", "desc": "Submit your first assignment",          "condition": lambda s: s.get("submissions", 0) >= 1},
    {"id": "quiz_master",         "name": "Quiz Master",       "emoji": "🧠", "desc": "Score 100% on any quiz",               "condition": lambda s: s.get("perfect_quizzes", 0) >= 1},
    {"id": "streak_7",            "name": "Week Warrior",      "emoji": "🔥", "desc": "Maintain a 7-day streak",              "condition": lambda s: s.get("max_streak", 0) >= 7},
    {"id": "streak_30",           "name": "Month Master",      "emoji": "⚡", "desc": "Maintain a 30-day streak",             "condition": lambda s: s.get("max_streak", 0) >= 30},
    {"id": "century",             "name": "Century Club",      "emoji": "💯", "desc": "Earn 100 total points",                "condition": lambda s: s.get("total_points", 0) >= 100},
    {"id": "top_performer",       "name": "Top Performer",     "emoji": "🏆", "desc": "Rank in the top 3 of your class",      "condition": lambda s: s.get("class_rank", 999) <= 3},
    {"id": "consistent_learner",  "name": "Consistent",        "emoji": "📅", "desc": "Complete 10 assignments on time",      "condition": lambda s: s.get("on_time_submissions", 0) >= 10},
    {"id": "knowledge_seeker",    "name": "Knowledge Seeker",  "emoji": "📚", "desc": "Ask 50 questions in AI Tutor",         "condition": lambda s: s.get("questions_asked", 0) >= 50},
    {"id": "perfect_attendee",    "name": "Perfect Attendee",  "emoji": "✅", "desc": "100% attendance in any class",          "condition": lambda s: s.get("perfect_attendance_classes", 0) >= 1},
    {"id": "social_butterfly",    "name": "Social Butterfly",  "emoji": "🦋", "desc": "Post 20 forum messages",               "condition": lambda s: s.get("forum_posts", 0) >= 20},
]


def _make_id():
    return str(uuid.uuid4())


async def award_points(db, user_id: str, action: str, meta: Optional[Dict] = None) -> int:
    """Award points for a specific action. Returns points awarded."""
    points = POINT_RULES.get(action, 0)
    if points == 0:
        return 0

    record = {
        "id": _make_id(),
        "user_id": user_id,
        "action": action,
        "points": points,
        "meta": meta or {},
        "created_at": datetime.utcnow()
    }
    await db.point_transactions.insert_one(record)

    # Update user total
    await db.user_stats.update_one(
        {"user_id": user_id},
        {"$inc": {"total_points": points}, "$set": {"last_updated": datetime.utcnow()}},
        upsert=True
    )
    return points


async def get_user_points(db, user_id: str) -> int:
    """Get total points for a user."""
    stats = await db.user_stats.find_one({"user_id": user_id})
    return int(stats.get("total_points", 0)) if stats else 0


async def get_user_stats(db, user_id: str) -> Dict[str, Any]:
    """Aggregate all stats needed for badge evaluation."""
    stats = await db.user_stats.find_one({"user_id": user_id}) or {}

    # Count submissions
    submissions = await db.submissions.count_documents({"student_id": user_id})

    # Count perfect quizzes
    perfect = await db.quiz_attempts.count_documents({
        "student_id": user_id,
        "percentage": 100.0,
        "is_complete": True
    })

    # Count questions asked
    questions = await db.chat_history.count_documents({"user_id": user_id})

    # Forum posts
    forum_posts = await db.forum_posts.count_documents({"author_id": user_id})
    forum_replies_cursor = db.forum_posts.find({"replies.author_id": user_id})
    all_posts = await forum_replies_cursor.to_list(None)
    reply_count = sum(
        sum(1 for r in p.get("replies", []) if r.get("author_id") == user_id)
        for p in all_posts
    )

    return {
        "total_points": int(stats.get("total_points", 0)),
        "max_streak": int(stats.get("max_streak", 0)),
        "submissions": submissions,
        "perfect_quizzes": perfect,
        "questions_asked": questions,
        "forum_posts": forum_posts + reply_count,
        "on_time_submissions": int(stats.get("on_time_submissions", 0)),
        "perfect_attendance_classes": int(stats.get("perfect_attendance_classes", 0)),
        "class_rank": int(stats.get("class_rank", 999)),
    }


async def check_and_award_badges(db, user_id: str) -> List[Dict]:
    """Check badge eligibility and award new badges. Returns newly awarded badges."""
    user_stats = await get_user_stats(db, user_id)

    # Get existing badges
    existing = await db.user_badges.find({"user_id": user_id}).to_list(None)
    existing_ids = {b["badge_id"] for b in existing}

    newly_awarded = []
    for badge_def in BADGE_DEFINITIONS:
        if badge_def["id"] in existing_ids:
            continue
        if badge_def["condition"](user_stats):
            badge_record = {
                "id": _make_id(),
                "user_id": user_id,
                "badge_id": badge_def["id"],
                "name": badge_def["name"],
                "emoji": badge_def["emoji"],
                "desc": badge_def["desc"],
                "awarded_at": datetime.utcnow()
            }
            await db.user_badges.insert_one(badge_record)
            newly_awarded.append(badge_record)

    return newly_awarded


async def get_user_badges(db, user_id: str) -> List[Dict]:
    """Get all badges earned by a user."""
    badges = await db.user_badges.find({"user_id": user_id}).sort("awarded_at", -1).to_list(None)
    for b in badges:
        b["_id"] = str(b["_id"])
    return badges


async def get_leaderboard(db, class_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """Get global or class-specific leaderboard."""
    if class_id:
        cls = await db.classes.find_one({"id": class_id})
        if not cls:
            return []
        student_ids = cls.get("students", [])
        if not student_ids:
            return []
        cursor = db.user_stats.find({"user_id": {"$in": student_ids}}).sort("total_points", -1).limit(limit)
    else:
        cursor = db.user_stats.find({}).sort("total_points", -1).limit(limit)

    entries = await cursor.to_list(None)
    result = []
    for rank, entry in enumerate(entries, 1):
        uid = entry["user_id"]
        user = await db.users.find_one({"_id": __import__("bson").ObjectId(uid)}) if len(uid) == 24 else None
        result.append({
            "rank": rank,
            "user_id": uid,
            "name": user.get("name", f"User {uid[:6]}") if user else f"User {uid[:6]}",
            "total_points": int(entry.get("total_points", 0)),
            "badge_count": await db.user_badges.count_documents({"user_id": uid}),
        })
    return result


async def get_point_history(db, user_id: str, limit: int = 30) -> List[Dict]:
    """Get recent point transaction history."""
    cursor = db.point_transactions.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    txns = await cursor.to_list(None)
    for t in txns:
        t["_id"] = str(t["_id"])
    return txns
