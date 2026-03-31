"""Announcements API — CRUD for class announcements."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from backend.utils.db import get_db
from backend.api.auth import get_current_user, require_role

router = APIRouter()


class CreateAnnouncementIn(BaseModel):
    title: str
    body: str
    class_ids: Optional[List[str]] = None  # None = global
    priority: Optional[str] = "normal"     # normal | important | urgent


class UpdateAnnouncementIn(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    priority: Optional[str] = None


def _clean(doc):
    """Strip MongoDB _id for JSON serialization."""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


@router.post("/", summary="Create announcement")
async def create_announcement(
    body: CreateAnnouncementIn,
    db=Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    ann = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "body": body.body,
        "class_ids": body.class_ids or [],
        "priority": body.priority or "normal",
        "author_id": str(current_user["_id"]),
        "author_name": current_user.get("name", "Unknown"),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    await db.announcements.insert_one(ann)
    return _clean(ann)


@router.get("/", summary="List announcements for current user")
async def list_announcements(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    role = (current_user.get("role") or "student").lower()

    # Get the user's class IDs
    if role in ("teacher", "admin"):
        cursor = db.classes.find({"teacher_id": user_id})
    else:
        cursor = db.classes.find({"students": user_id})
    classes = await cursor.to_list(None)
    class_ids = [c["id"] for c in classes if "id" in c]

    # Fetch announcements: global (no class_ids) OR matching user's classes
    ann_cursor = db.announcements.find({
        "$or": [
            {"class_ids": {"$size": 0}},       # global
            {"class_ids": {"$in": class_ids}},  # for user's classes
            {"author_id": user_id},             # own announcements
        ]
    }).sort("created_at", -1).limit(50)

    results = await ann_cursor.to_list(None)
    return [_clean(a) for a in results]


@router.put("/{ann_id}", summary="Update announcement")
async def update_announcement(
    ann_id: str,
    body: UpdateAnnouncementIn,
    db=Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    updates["updated_at"] = datetime.utcnow().isoformat()

    result = await db.announcements.update_one(
        {"id": ann_id, "author_id": str(current_user["_id"])},
        {"$set": updates}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found or not yours.")
    return {"message": "Updated."}


@router.delete("/{ann_id}", summary="Delete announcement")
async def delete_announcement(
    ann_id: str,
    db=Depends(get_db),
    current_user=Depends(require_role("teacher", "admin")),
):
    result = await db.announcements.delete_one(
        {"id": ann_id, "author_id": str(current_user["_id"])}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found or not yours.")
    return {"message": "Deleted."}
