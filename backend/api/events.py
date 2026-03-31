"""Events API — CRUD for class/school events."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from backend.utils.db import get_db
from backend.api.auth import get_current_user, require_role

router = APIRouter()


class CreateEventIn(BaseModel):
    title: str
    description: Optional[str] = None
    date: str                                # ISO date string e.g. "2026-03-28"
    time: Optional[str] = None               # e.g. "14:00"
    class_ids: Optional[List[str]] = None    # None = school-wide
    event_type: Optional[str] = "general"    # general | exam | meeting | holiday


class UpdateEventIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    event_type: Optional[str] = None


def _clean(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


@router.post("/", summary="Create event")
async def create_event(
    body: CreateEventIn,
    db=Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    event = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "description": body.description or "",
        "date": body.date,
        "time": body.time or "",
        "class_ids": body.class_ids or [],
        "event_type": body.event_type or "general",
        "author_id": str(current_user["_id"]),
        "author_name": current_user.get("name", "Unknown"),
        "created_at": datetime.utcnow().isoformat(),
    }
    await db.events.insert_one(event)
    return _clean(event)


@router.get("/", summary="List events for current user")
async def list_events(
    month: Optional[int] = None,
    year: Optional[int] = None,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    role = (current_user.get("role") or "student").lower()

    # Get user's class IDs
    if role in ("teacher", "admin"):
        cursor = db.classes.find({"teacher_id": user_id})
    else:
        cursor = db.classes.find({"students": user_id})
    classes = await cursor.to_list(None)
    class_ids = [c["id"] for c in classes if "id" in c]

    query = {
        "$or": [
            {"class_ids": {"$size": 0}},
            {"class_ids": {"$in": class_ids}},
            {"author_id": user_id},
        ]
    }

    # Optional month/year filter
    if month and year:
        prefix = f"{year}-{str(month).zfill(2)}"
        query["date"] = {"$regex": f"^{prefix}"}

    ev_cursor = db.events.find(query).sort("date", 1).limit(100)
    results = await ev_cursor.to_list(None)
    return [_clean(e) for e in results]


@router.delete("/{event_id}", summary="Delete event")
async def delete_event(
    event_id: str,
    db=Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    result = await db.events.delete_one(
        {"id": event_id, "author_id": str(current_user["_id"])}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Event not found or not yours.")
    return {"message": "Deleted."}
