import uuid
import logging
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger(__name__)

def _make_id():
    return str(uuid.uuid4())

async def create_notification(
    db,
    user_id: str,
    n_type: str, # assignment, quiz, notice, system
    title: str,
    message: str,
    link: Optional[str] = None,
) -> dict:
    notif_id = _make_id()
    doc = {
        "id": notif_id,
        "user_id": user_id,
        "type": n_type,
        "title": title,
        "message": message,
        "link": link,
        "is_read": False,
        "created_at": datetime.utcnow()
    }
    await db.notifications.insert_one(doc)
    return doc

async def get_user_notifications(db, user_id: str, limit: int = 20) -> list:
    cursor = db.notifications.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(None)

async def mark_as_read(db, notification_id: str) -> bool:
    res = await db.notifications.update_one(
        {"id": notification_id},
        {"$set": {"is_read": True}}
    )
    return res.modified_count > 0

async def mark_all_as_read(db, user_id: str) -> bool:
    res = await db.notifications.update_many(
        {"user_id": user_id, "is_read": False},
        {"$set": {"is_read": True}}
    )
    return res.modified_count > 0
