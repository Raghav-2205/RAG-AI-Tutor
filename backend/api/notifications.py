from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.utils.db import get_db
from backend.api.auth import get_current_user, require_role
import backend.services.notification_service as notification_service

router = APIRouter()


class SendNotificationIn(BaseModel):
    title: str
    message: str
    notification_type: str = "info"  # info | warning | success


@router.get("/", summary="Get user notifications")
async def list_notifications(
    unread: Optional[bool] = None,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    notifications = await notification_service.get_user_notifications(db, str(current_user["_id"]))
    if unread:
        notifications = [n for n in notifications if not n.get("is_read")]
    return notifications


@router.post("/send", summary="Admin/Teacher: broadcast notification to all users")
async def send_notification_to_all(
    body: SendNotificationIn,
    current_user=Depends(require_role("admin", "teacher")),
    db=Depends(get_db),
):
    """
    Fan-out: creates one notification document per user in the system.
    All existing users (any role) receive the notification.
    """
    sender_name = current_user.get("name") or current_user.get("email") or "System"
    # Fetch ALL users
    all_users = await db.users.find({}, {"_id": 1}).to_list(None)
    if not all_users:
        return {"sent": 0, "message": "No users found"}

    count = 0
    for u in all_users:
        uid = str(u["_id"])
        await notification_service.create_notification(
            db,
            user_id=uid,
            title=body.title,
            message=f"{body.message}",
            notification_type=body.notification_type,
            sender=sender_name,
        )
        count += 1

    return {"sent": count, "message": f"Notification sent to {count} users."}


@router.post("/read-all", summary="Mark all as read")
async def mark_all_read(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    await notification_service.mark_all_as_read(db, str(current_user["_id"]))
    return {"message": "All marked as read"}


@router.post("/{notification_id}/read", summary="Mark notification as read")
async def mark_read(
    notification_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    success = await notification_service.mark_as_read(db, notification_id, str(current_user["_id"]))
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Marked as read"}
