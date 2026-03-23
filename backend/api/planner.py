import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.services import planner_service

logger = logging.getLogger(__name__)
router = APIRouter()

# ===================== Pydantic Models =====================

class PlanCreate(BaseModel):
    date: str  # YYYY-MM-DD
    template: str = "study"
    notes: Optional[str] = None

class ActivityLogCreate(BaseModel):
    date: str  # YYYY-MM-DD
    category: str  # workout, food, study, mind
    data: dict

class AddTaskIn(BaseModel):
    title: str
    category: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    notes: Optional[str] = None

class ReminderCreate(BaseModel):
    date: str
    time: str
    message: str

# ===================== TEMPLATE ENDPOINTS =====================

@router.get("/templates")
async def get_templates():
    return planner_service.TEMPLATE_SCHEDULES

# ===================== PLAN ENDPOINTS =====================

@router.post("/plans")
async def create_plan(data: PlanCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    day = await planner_service.get_or_create_planner_day(
        db, user_id, data.date, data.template, data.notes, auto_fill=True
    )
    return {"status": "created", "plan_id": day["id"]}

@router.get("/plans/{date}")
async def get_plan(date: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    day = await planner_service.get_day_with_tasks(db, user_id, date)
    if not day:
        raise HTTPException(404, "No plan found for this date")
    return day

@router.post("/plans/{day_id}/tasks")
async def add_task_to_plan(day_id: str, data: AddTaskIn, current_user=Depends(get_current_user), db=Depends(get_db)):
    task = await planner_service.add_task(
        db, day_id, data.title, data.category, data.start_time, data.end_time, notes=data.notes
    )
    return task

@router.patch("/tasks/{task_id}/complete")
async def mark_task_complete(task_id: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    try:
        task = await planner_service.toggle_task_complete(db, task_id)
        return {"status": "success", "is_completed": task["is_completed"]}
    except ValueError as e:
        raise HTTPException(404, str(e))

# ===================== ACTIVITY TRACKING =====================

@router.post("/activities")
async def log_activity(data: ActivityLogCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    log = await planner_service.log_activity(db, user_id, data.category, data.data, data.date)
    return {"status": "logged", "activity_id": log["id"]}

@router.get("/activities")
async def list_activities(
    date: Optional[str] = None, 
    category: Optional[str] = None, 
    current_user=Depends(get_current_user), 
    db=Depends(get_db)
):
    user_id = str(current_user["_id"])
    activities = await planner_service.get_activity_logs(db, user_id, start_date=date, end_date=date, category=category)
    return activities

@router.get("/activities/summary/{date}")
async def activity_summary(date: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    summary = await planner_service.get_daily_summary(db, user_id, date)
    return summary

# ===================== REMINDERS =====================

@router.post("/reminders")
async def add_reminder(data: ReminderCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    reminder = await planner_service.add_reminder(db, user_id, data.date, data.time, data.message)
    return reminder

@router.get("/reminders")
async def list_reminders(date: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    return await planner_service.get_reminders(db, user_id, date)

@router.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    success = await planner_service.delete_reminder(db, reminder_id)
    return {"success": success}
