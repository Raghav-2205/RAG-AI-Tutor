import uuid
from datetime import date, datetime, timezone
from typing import Optional, Any, List, Dict

def _make_id():
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _clean(doc: dict) -> dict:
    """Remove MongoDB _id and serialize ObjectIds."""
    if doc is None:
        return doc
    out = {}
    for k, v in doc.items():
        if k == "_id":
            continue
        out[k] = str(v) if hasattr(v, "__class__") and type(v).__name__ == "ObjectId" else v
    return out

# ─── Day Templates ────────────────────────────────────────────────────────────

TEMPLATE_SCHEDULES: dict[str, list[dict]] = {
    "wellness": [
        {"title": "Morning Meditation","category": "mind",   "start": "06:30", "end": "07:00"},
        {"title": "Yoga / Stretching","category": "workout", "start": "07:00", "end": "08:00"},
        {"title": "Healthy Breakfast","category": "food",    "start": "08:00", "end": "08:30"},
        {"title": "Nature Walk",      "category": "workout", "start": "09:00", "end": "10:00"},
        {"title": "Journaling",       "category": "mind",    "start": "10:30", "end": "11:00"},
        {"title": "Nutritious Lunch", "category": "food",    "start": "13:00", "end": "14:00"},
        {"title": "Nap / Rest",       "category": "mind",    "start": "14:30", "end": "15:30"},
        {"title": "Evening Workout",  "category": "workout", "start": "17:00", "end": "18:00"},
        {"title": "Light Dinner",     "category": "food",    "start": "19:00", "end": "19:30"},
        {"title": "Reading",          "category": "mind",    "start": "20:00", "end": "21:00"},
    ],
    # User Requested Templates
    "study_day": [
        {"title": "Review Goals",      "category": "mind",    "start": "08:00", "end": "08:30"},
        {"title": "Intensive Study 1", "category": "study",   "start": "09:00", "end": "12:00"},
        {"title": "Nutritious Lunch",  "category": "food",    "start": "12:00", "end": "13:00"},
        {"title": "Intensive Study 2", "category": "study",   "start": "13:30", "end": "16:30"},
        {"title": "Active Break",      "category": "workout", "start": "17:00", "end": "18:00"},
        {"title": "Evening Review",    "category": "study",   "start": "20:00", "end": "21:30"},
    ],
    "productive_day": [
        {"title": "High Priority Work","category": "study",   "start": "08:30", "end": "11:30"},
        {"title": "Quick Workout",     "category": "workout", "start": "12:00", "end": "12:45"},
        {"title": "Power Lunch",       "category": "food",    "start": "13:00", "end": "13:45"},
        {"title": "Secondary Tasks",   "category": "study",   "start": "14:00", "end": "16:30"},
        {"title": "Admin & Planning",  "category": "study",   "start": "17:00", "end": "18:00"},
        {"title": "Mindful Reading",   "category": "mind",    "start": "20:00", "end": "21:00"},
    ],
    "casual_wellness_day": [
        {"title": "Leisurely Morning", "category": "mind",    "start": "09:00", "end": "10:30"},
        {"title": "Healthy Brunch",    "category": "food",    "start": "11:00", "end": "12:00"},
        {"title": "Yoga or Walk",      "category": "workout", "start": "13:00", "end": "14:30"},
        {"title": "Creative Hobby",    "category": "mind",    "start": "15:00", "end": "17:00"},
        {"title": "Light Reflection",  "category": "mind",    "start": "19:00", "end": "20:00"},
        {"title": "Sleep Prep",        "category": "mind",    "start": "21:30", "end": "22:00"},
    ],
}

# ─── Planner Day ──────────────────────────────────────────────────────────────

async def get_or_create_planner_day(
    db,
    user_id: str,
    target_date: str,
    template: str = "study",
    notes: Optional[str] = None,
    auto_fill: bool = True,
) -> dict:
    """
    Fetch an existing planner day or create one from the template.
    Uses ISO strings (YYYY-MM-DD) for target_date.
    """
    day = await db.planner_days.find_one({
        "user_id": user_id,
        "date": target_date,
    })

    if day:
        return _clean(day)

    day_id = _make_id()
    day = {
        "id": day_id,
        "user_id": user_id,
        "date": target_date,
        "template": template,
        "notes": notes,
        "created_at": _utcnow()
    }
    await db.planner_days.insert_one(day)

    if auto_fill:
        slots = TEMPLATE_SCHEDULES.get(template, [])
        tasks = []
        for i, slot in enumerate(slots):
            tasks.append({
                "id": _make_id(),
                "planner_day_id": day_id,
                "title": slot["title"],
                "category": slot["category"],
                "start_time": slot["start"],
                "end_time": slot["end"],
                "is_completed": False,
                "order_index": i,
                "created_at": _utcnow()
            })
        if tasks:
            await db.planner_tasks.insert_many(tasks)

    return _clean(day)

async def add_task(
    db,
    planner_day_id: str,
    title: str,
    category: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    reminder_at=None,
    notes: Optional[str] = None,
) -> dict:
    task_id = _make_id()
    doc = {
        "id": task_id,
        "planner_day_id": planner_day_id,
        "title": title,
        "category": category,
        "start_time": start_time,
        "end_time": end_time,
        "reminder_at": reminder_at,
        "is_completed": False,
        "order_index": 999,
        "notes": notes,
        "created_at": _utcnow()
    }
    await db.planner_tasks.insert_one(doc)
    return _clean(doc)

async def toggle_task_complete(
    db, task_id: str
) -> dict:
    task = await db.planner_tasks.find_one({"id": task_id})
    if not task:
        raise ValueError("Task not found.")
    
    new_status = not task.get("is_completed", False)
    await db.planner_tasks.update_one(
        {"id": task_id},
        {"$set": {"is_completed": new_status}}
    )
    task["is_completed"] = new_status
    return task

async def get_day_with_tasks(
    db, user_id: str, target_date: str
) -> Optional[dict]:
    day = await db.planner_days.find_one({
        "user_id": user_id,
        "date": target_date,
    })
    
    if day:
        cursor = db.planner_tasks.find({"planner_day_id": day["id"]}).sort("order_index", 1)
        tasks = await cursor.to_list(None)
        day["tasks"] = [_clean(t) for t in tasks]
    
    return _clean(day)

async def get_range_with_tasks(
    db, user_id: str, start_date: str, end_date: str
) -> List[dict]:
    cursor = db.planner_days.find({
        "user_id": user_id,
        "date": {"$gte": start_date, "$lte": end_date}
    }).sort("date", 1)
    
    days = await cursor.to_list(None)
    day_ids = [d["id"] for d in days]
    
    tasks_cursor = db.planner_tasks.find({"planner_day_id": {"$in": day_ids}}).sort([("planner_day_id", 1), ("start_time", 1), ("order_index", 1)])
    tasks = await tasks_cursor.to_list(None)
    
    tasks_by_day = {}
    for t in tasks:
        tasks_by_day.setdefault(t["planner_day_id"], []).append(_clean(t))
        
    cleaned_days = []
    for d in days:
        cd = _clean(d)
        cd["tasks"] = tasks_by_day.get(d["id"], [])
        cleaned_days.append(cd)
        
    return cleaned_days

# ─── Activity Logging ─────────────────────────────────────────────────────────

async def log_activity(
    db,
    user_id: str,
    category: str,
    data: dict,
    log_date: Optional[str] = None,
) -> dict:
    log_id = _make_id()
    doc = {
        "id": log_id,
        "user_id": user_id,
        "date": log_date or str(date.today()),
        "category": category,
        "data": data,
        "logged_at": _utcnow()
    }
    await db.activity_logs.insert_one(doc)
    return doc

async def get_activity_logs(
    db,
    user_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
) -> list:
    query: dict[str, Any] = {"user_id": user_id}
    if start_date or end_date:
        query["date"] = {}
        if start_date: query["date"]["$gte"] = start_date
        if end_date: query["date"]["$lte"] = end_date
    if category:
        query["category"] = category

    cursor = db.activity_logs.find(query).sort([("date", -1), ("logged_at", -1)])
    return await cursor.to_list(None)

async def get_daily_summary(db, user_id: str, target_date: str) -> dict:
    """Aggregate activity data for a single day."""
    cursor = db.activity_logs.find({
        "user_id": user_id,
        "date": target_date,
    })
    logs = await cursor.to_list(None)

    summary: dict[str, Any] = {
        "date": target_date,
        "workout": {"sessions": [], "total_duration_min": 0, "total_calories_burned": 0},
        "food":    {"meals": [], "total_calories": 0},
        "study":   {"topics": [], "total_duration_min": 0},
        "mind":    {"activities": [], "total_duration_min": 0},
    }

    for log in logs:
        d = log.get("data") or {}
        cat = log.get("category")

        if cat == "workout":
            summary["workout"]["sessions"].append(d)
            summary["workout"]["total_duration_min"] += int(d.get("duration_min", 0))
            summary["workout"]["total_calories_burned"] += int(d.get("calories_burned", 0))

        elif cat == "food":
            summary["food"]["meals"].append(d)
            summary["food"]["total_calories"] += int(d.get("total_calories", 0))

        elif cat == "study":
            summary["study"]["topics"].extend(d.get("topics", []))
            summary["study"]["total_duration_min"] += int(d.get("duration_min", 0))

        elif cat == "mind":
            summary["mind"]["activities"].append(d.get("activity", ""))
            summary["mind"]["total_duration_min"] += int(d.get("duration_min", 0))

    return summary

# ─── Reminders ───────────────────────────────────────────────────────────────

async def add_reminder(db, user_id: str, log_date: str, time_str: str, message: str) -> dict:
    reminder_id = _make_id()
    doc = {
        "id": reminder_id,
        "reminder_id": reminder_id, # for frontend compat
        "user_id": user_id,
        "date": log_date,
        "time": time_str,
        "message": message,
        "is_active": True,
        "created_at": _utcnow()
    }
    await db.planner_reminders.insert_one(doc)
    return doc

async def get_reminders(db, user_id: str, log_date: str) -> list:
    cursor = db.planner_reminders.find({"user_id": user_id, "date": log_date, "is_active": True})
    return await cursor.to_list(None)

async def delete_reminder(db, reminder_id: str) -> bool:
    res = await db.planner_reminders.update_one(
        {"id": reminder_id},
        {"$set": {"is_active": False}}
    )
    return res.modified_count > 0

# ─── Unified Calendar ─────────────────────────────────────────────────────────

async def get_unified_calendar(
    db,
    user_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> list:
    """
    Merge tasks, assignments, quizzes, and class events into a single timeline.
    """
    events = []

    # 1. Planner Tasks
    day_query: Dict[str, Any] = {"user_id": str(user_id)}
    if start_date or end_date:
        day_query["date"] = {}
        if start_date: day_query["date"]["$gte"] = start_date
        if end_date: day_query["date"]["$lte"] = end_date
    
    days = await db.planner_days.find(day_query).to_list(None)
    day_ids = [d["id"] for d in days]
    day_map = {d["id"]: d["date"] for d in days}
    
    if day_ids:
        tasks = await db.planner_tasks.find({"planner_day_id": {"$in": day_ids}}).to_list(None)
        for t in tasks:
            events.append({
                "id": t["id"],
                "title": t["title"],
                "start": f"{day_map[t['planner_day_id']]}T{t.get('start_time', '00:00')}",
                "end": f"{day_map[t['planner_day_id']]}T{t.get('end_time', '23:59')}",
                "type": "task",
                "category": t.get("category", "general"),
                "completed": t.get("is_completed", False)
            })

    # 2. LMS Assignments and Quizzes for classes where the user is a student or teacher
    classes = await db.classes.find({
        "$or": [
            {"students": user_id},
            {"teacher_id": user_id},
        ]
    }).to_list(None)
    class_ids = [c["id"] for c in classes if c.get("id")]

    if class_ids:
        assignments = await db.assignments.find({"class_id": {"$in": class_ids}}).to_list(None)
        for a in assignments:
            due_date = a.get("due_date")
            if hasattr(due_date, "isoformat"):
                due_date = due_date.isoformat()
            if not due_date:
                continue

            due_day = str(due_date)[:10]
            if start_date and due_day < start_date:
                continue
            if end_date and due_day > end_date:
                continue

            events.append({
                "id": a.get("id") or a.get("assignment_id"),
                "title": f"Assignment: {a['title']}",
                "start": due_date,
                "type": "assignment",
                "color": "#ff4444"
            })

        # 3. LMS Quizzes
        quizzes = await db.lms_quizzes.find({"class_id": {"$in": class_ids}}).to_list(None)
        for q in quizzes:
            start_value = q.get("end_time") or q.get("start_time") or q.get("created_at")
            if hasattr(start_value, "isoformat"):
                start_value = start_value.isoformat()
            if not start_value:
                continue

            start_day = str(start_value)[:10]
            if start_date and start_day < start_date:
                continue
            if end_date and start_day > end_date:
                continue

            events.append({
                "id": q.get("id") or q.get("quiz_id"),
                "title": f"Quiz: {q['title']}",
                "start": start_value,
                "type": "quiz",
                "color": "#00ffcc"
            })

    # 4. Global Calendar Events (Classes, Exams)
    cal_query: Dict[str, Any] = {"$or": [
        {"user_id": str(user_id)},
        {"class_id": {"$in": class_ids}}
    ]}
    if start_date or end_date:
        cal_query["start"] = {}
        if start_date:
            cal_query["start"]["$gte"] = start_date
        if end_date:
            cal_query["start"]["$lte"] = end_date
    
    cal_events = await db.calendar_events.find(cal_query).to_list(None)
    for ce in cal_events:
        events.append({
            "id": ce.get("id"),
            "title": ce["title"],
            "start": ce["start"],
            "end": ce.get("end"),
            "type": ce.get("type", "event"),
            "color": ce.get("color")
        })

    return sorted(events, key=lambda x: x["start"])
