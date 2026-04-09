from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from backend.utils.db import get_db
from backend.api.auth import get_current_user
import backend.services.notification_service as notification_service

router = APIRouter()

@router.get("/", summary="Get user notifications")
async def list_notifications(
    unread: Optional[bool] = None,
    current_user=Depends(get_current_user),
    db = Depends(get_db)
):
    notifications = await notification_service.get_user_notifications(db, str(current_user["_id"]))
    if unread:
        notifications = [n for n in notifications if not n.get("is_read")]
    return notifications

@router.post("/{notification_id}/read", summary="Mark notification as read")
async def mark_read(
    notification_id: str,
    current_user=Depends(get_current_user),
    db = Depends(get_db)
):
    success = await notification_service.mark_as_read(db, notification_id, str(current_user["_id"]))
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"message": "Marked as read"}

@router.post("/read-all", summary="Mark all as read")
async def mark_all_read(
    current_user=Depends(get_current_user),
    db = Depends(get_db)
):
    await notification_service.mark_all_as_read(db, str(current_user["_id"]))
    return {"message": "All marked as read"}
