from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Any
from datetime import datetime, timedelta
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.services.planner_service import get_unified_calendar
import uuid

router = APIRouter(prefix="/calendar", tags=["Calendar"])

def _make_id():
    return str(uuid.uuid4())

@router.get("/events")
async def get_calendar_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get all events (tasks, assignments, quizzes, class schedules) for the user.
    """
    try:
        # Default to a 30-day range if not specified
        if not start_date:
            start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        events = await get_unified_calendar(db, str(current_user["_id"]), start_date, end_date)
        return events
    except Exception as e:
        print(f"Calendar Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/events")
async def create_calendar_event(
    event_data: dict,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Create a custom calendar event (Admin/Teacher only for class-wide, Student for personal).
    """
    user_role = current_user.get("role", "Student")
    user_id = str(current_user["_id"])

    if user_role not in ["Admin", "Teacher"] and event_data.get("class_id"):
        raise HTTPException(status_code=403, detail="Students cannot create class-wide events")

    event_id = _make_id()
    doc = {
        "id": event_id,
        "user_id": user_id if not event_data.get("class_id") else None,
        "class_id": event_data.get("class_id"),
        "title": event_data["title"],
        "start": event_data["start"],
        "end": event_data.get("end"),
        "type": event_data.get("type", "event"),
        "color": event_data.get("color", "#4444ff"),
        "created_at": datetime.utcnow()
    }
    
    await db.calendar_events.insert_one(doc)
    doc["_id"] = str(doc["_id"])
    return doc
