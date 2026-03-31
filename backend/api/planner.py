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

# ===================== SMART PLAN GENERATION =====================

class SmartPlanRequest(BaseModel):
    start_date: str # YYYY-MM-DD
    days: int = 7

@router.post("/plans/generate")
async def generate_smart_plan(
    data: SmartPlanRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    from backend.core.llm_interface import llm_client
    from backend.services import lms_service
    from datetime import datetime, timedelta
    import json
    import re

    user_id = str(current_user["_id"])
    
    # 1. Fetch Classes
    classes = await lms_service.get_classes_for_student(db, user_id)
    class_ids = [c["id"] for c in classes]
    class_names = [c["name"] for c in classes]
    
    # 2. Fetch Assignments & Quizzes
    assignments_text = []
    if class_ids:
        # Assignments
        a_cursor = db.assignments.find({"class_id": {"$in": class_ids}})
        assignments = await a_cursor.to_list(None)
        
        # Filter upcoming assignments
        today_dt = datetime.fromisoformat(data.start_date) if "T" not in data.start_date else datetime.fromisoformat(data.start_date.split("T")[0])
        future_assignments = [
            a for a in assignments 
            if a.get("due_date") and (isinstance(a["due_date"], datetime) and a["due_date"] >= today_dt or isinstance(a["due_date"], str) and a["due_date"][:10] >= data.start_date)
        ]
        
        for a in future_assignments:
            due = a["due_date"].isoformat()[:10] if isinstance(a["due_date"], datetime) else a["due_date"][:10]
            assignments_text.append(f"- Assignment: '{a.get('title')}' due on {due}")
            
        # Quizzes
        q_cursor = db.lms_quizzes.find({"class_id": {"$in": class_ids}})
        quizzes = await q_cursor.to_list(None)
        future_quizzes = [
            q for q in quizzes
            if q.get("start_time") and (isinstance(q["start_time"], datetime) and q["start_time"] >= today_dt or isinstance(q["start_time"], str) and q["start_time"][:10] >= data.start_date)
        ]
        for q in future_quizzes:
            start = q["start_time"].isoformat()[:10] if isinstance(q["start_time"], datetime) else q["start_time"][:10]
            assignments_text.append(f"- Quiz: '{q.get('title')}' scheduled for {start}")

        # Poor Quiz Scores (to emphasize study topics)
        attempts_cursor = db.quiz_attempts.find({"student_id": user_id})
        attempts = await attempts_cursor.to_list(None)
        for att in attempts:
            if att.get("percentage", 100) < 70:
                # Find matching quiz title
                quiz_title = next((q.get("title") for q in quizzes if q.get("id") == att.get("quiz_id")), "Unknown Quiz")
                assignments_text.append(f"- Needs Review: Scored strictly below 70% on '{quiz_title}'. Allocate study time for this.")

    # 3. Formulate Prompt
    prompt = f"""You are an expert AI Academic Planner.
Generate a highly optimized, realistic {data.days}-day study schedule for a student.

STUDENT CONTEXT:
Classes: {', '.join(class_names) if class_names else 'No current classes'}
Upcoming Deadlines & Priorities:
{chr(10).join(assignments_text) if assignments_text else 'None'}

Start Date of Plan: {data.start_date}

INSTRUCTIONS:
1. Break down the {data.days} days starting from {data.start_date}.
2. For each day, provide 3 to 6 logical time-blocked tasks.
3. Balance heavy study sessions with "food", "workout", or "mind" (rest/breaks).
4. Category MUST BE exactly one of: "study", "workout", "food", "mind", "general".
5. Output ONLY raw JSON containing the schedule. Do not include markdown codeblocks (no ```json text).

EXPECTED JSON SCHEMA:
{{
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "tasks": [
        {{
          "title": "Short string describing the task",
          "category": "study|workout|food|mind|general",
          "start_time": "HH:MM",
          "end_time": "HH:MM",
          "notes": "Optional short note"
        }}
      ]
    }}
  ]
}}
"""

    # 4. Request from LLM
    try:
        response_text = await llm_client.async_generate(prompt=prompt, temperature=0.5)
        # Clean potential markdown
        response_text = re.sub(r"```json\s*", "", response_text)
        response_text = re.sub(r"```\s*", "", response_text).strip()
        
        schedule_data = json.loads(response_text)
    except Exception as e:
        logger.error(f"Failed to generate or parse Smart Plan: {str(e)}")
        raise HTTPException(500, "Failed to generate AI study plan.")

    # 5. Populate DB
    generated_days = schedule_data.get("days", [])
    total_tasks = 0
    
    for d in generated_days:
        date_str = d.get("date")
        if not date_str:
            continue
            
        # Ensure the day exists
        planner_day = await planner_service.get_or_create_planner_day(
            db, user_id, date_str, template="empty", auto_fill=False
        )
        day_id = planner_day["id"]
        
        # Clear existing non-completed tasks for this auto-generated day? Optional. 
        # We will just append them.
        
        day_tasks = d.get("tasks", [])
        for task in day_tasks:
            await planner_service.add_task(
                db=db,
                planner_day_id=day_id,
                title=task.get("title", "Study Session"),
                category=task.get("category", "study"),
                start_time=task.get("start_time", "09:00"),
                end_time=task.get("end_time", "10:00"),
                notes=task.get("notes", "")
            )
            total_tasks += 1

    return {
        "status": "success", 
        "message": f"Generated {total_tasks} tasks across {len(generated_days)} days.",
        "days_processed": len(generated_days)
    }


@router.post("/plans")
async def create_plan(data: PlanCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    day = await planner_service.get_or_create_planner_day(
        db, user_id, data.date, data.template, data.notes, auto_fill=True
    )
    return {"status": "created", "plan_id": day["id"]}

@router.get("/plans/range")
async def get_plans_in_range(start: str, end: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    days = await planner_service.get_range_with_tasks(db, user_id, start, end)
    return days

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
