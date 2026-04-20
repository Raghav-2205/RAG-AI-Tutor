import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.auth import get_current_user
from backend.services import lms_service, planner_service
from backend.utils.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_PLANNER_CATEGORIES = {"study", "workout", "food", "mind", "general"}
PLANNER_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
PLANNER_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_TASKS_PER_DAY = 3
MAX_TASKS_PER_DAY = 6
PLANNER_SYSTEM_PROMPT = (
    "You are a structured academic planning engine. "
    "Return exactly one valid JSON object and nothing else."
)


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


class SmartPlanRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    days: int = 7


def _normalize_start_date(raw_date: str) -> datetime:
    date_part = str(raw_date or "").split("T")[0].strip()
    if not PLANNER_DATE_RE.match(date_part):
        raise HTTPException(status_code=400, detail="Invalid start_date. Use YYYY-MM-DD.")
    try:
        return datetime.fromisoformat(date_part)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid start_date. Use YYYY-MM-DD.") from exc


def _build_planner_prompt(start_date: str, days: int, class_names: list[str], priorities: list[str]) -> str:
    priority_text = "\n".join(priorities) if priorities else "None"
    classes_text = ", ".join(class_names) if class_names else "No current classes"
    return f"""Generate a realistic {days}-day academic study schedule as strict JSON.

STUDENT CONTEXT:
Classes: {classes_text}
Upcoming Deadlines & Priorities:
{priority_text}

Plan start date: {start_date}

RULES:
- Return exactly one JSON object.
- Do not include markdown, prose, comments, explanations, or code fences.
- Use double quotes for all keys and strings.
- Do not use trailing commas.
- Category must be one of: "study", "workout", "food", "mind", "general".
- Each day should contain 3 to 6 time-blocked tasks when possible.
- Balance study sessions with breaks, food, workouts, or mind/rest blocks.

JSON SCHEMA:
{{
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "tasks": [
        {{
          "title": "Short task title",
          "category": "study",
          "start_time": "09:00",
          "end_time": "10:00",
          "notes": "Optional short note"
        }}
      ]
    }}
  ]
}}
"""


def _strip_markdown_fences(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _extract_first_json_object(raw_text: str) -> Optional[str]:
    text = str(raw_text or "")
    start_index = None
    depth = 0
    in_string = False
    escape = False

    for index, char in enumerate(text):
        if start_index is None:
            if char == "{":
                start_index = index
                depth = 1
            continue

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1].strip()

    return None


def _load_json_candidate(raw_text: str) -> dict:
    cleaned = _strip_markdown_fences(raw_text)
    candidates = [cleaned]
    extracted = _extract_first_json_object(cleaned)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    last_error = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    raise last_error or json.JSONDecodeError("No JSON object found.", cleaned, 0)


async def _repair_smart_plan_json(llm_client, broken_text: str) -> str:
    repair_prompt = f"""Fix the malformed planner JSON below.

Return exactly one valid JSON object matching this schema and nothing else:
{{
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "tasks": [
        {{
          "title": "Short task title",
          "category": "study|workout|food|mind|general",
          "start_time": "HH:MM",
          "end_time": "HH:MM",
          "notes": "Optional short note"
        }}
      ]
    }}
  ]
}}

Repair quoting, remove markdown/prose/comments, remove trailing commas, and preserve the original schedule meaning when possible.

MALFORMED INPUT:
{broken_text}
"""
    return await llm_client.async_generate(
        prompt=repair_prompt,
        system_prompt=PLANNER_SYSTEM_PROMPT,
        temperature=0.0,
    )


async def _parse_smart_plan_payload(llm_client, response_text: str) -> dict:
    try:
        return _load_json_candidate(response_text)
    except json.JSONDecodeError as exc:
        logger.warning("Planner JSON parse failed on first pass: %s", exc)
        repaired_text = await _repair_smart_plan_json(llm_client, response_text)
        try:
            return _load_json_candidate(repaired_text)
        except json.JSONDecodeError as repair_exc:
            logger.error("Planner JSON repair failed: %s", repair_exc)
            raise ValueError("AI planner returned malformed JSON that could not be repaired.") from repair_exc


def _minutes_from_time(value: str) -> int:
    hours, minutes = value.split(":")
    return (int(hours) * 60) + int(minutes)


def _minutes_to_time(total_minutes: int) -> str:
    capped = max(0, min(total_minutes, (23 * 60) + 59))
    hours = capped // 60
    minutes = capped % 60
    return f"{hours:02d}:{minutes:02d}"


def _normalize_time(value: Optional[str], fallback: str) -> str:
    raw = str(value or "").strip()
    return raw if PLANNER_TIME_RE.match(raw) else fallback


def _normalize_task_payload(task: dict) -> Optional[dict]:
    if not isinstance(task, dict):
        return None

    title = str(task.get("title") or "").strip() or "Study Session"
    category = str(task.get("category") or "").strip().lower() or "general"
    if category not in VALID_PLANNER_CATEGORIES:
        category = "general"

    start_time = _normalize_time(task.get("start_time"), "09:00")
    end_fallback = _minutes_to_time(_minutes_from_time(start_time) + 60)
    end_time = _normalize_time(task.get("end_time"), end_fallback)
    if _minutes_from_time(end_time) <= _minutes_from_time(start_time):
        end_time = end_fallback

    notes = str(task.get("notes") or "").strip()
    return {
        "title": title,
        "category": category,
        "start_time": start_time,
        "end_time": end_time,
        "notes": notes,
    }


def _normalize_generated_schedule(schedule_data: dict) -> list[dict]:
    if not isinstance(schedule_data, dict):
        raise ValueError("AI planner returned an invalid schedule payload.")

    raw_days = schedule_data.get("days")
    if not isinstance(raw_days, list):
        raise ValueError("AI planner response is missing a valid days list.")

    grouped_days: dict[str, list[dict]] = {}
    for day in raw_days:
        if not isinstance(day, dict):
            continue

        date_str = str(day.get("date") or "").strip()
        if not PLANNER_DATE_RE.match(date_str):
            continue

        normalized_tasks = []
        for task in day.get("tasks") or []:
            normalized_task = _normalize_task_payload(task)
            if normalized_task:
                normalized_tasks.append(normalized_task)

        if normalized_tasks:
            grouped_days.setdefault(date_str, []).extend(normalized_tasks)

    normalized_days = [
        {"date": date_str, "tasks": grouped_days[date_str]}
        for date_str in sorted(grouped_days.keys())
    ]

    if not normalized_days:
        raise ValueError("AI planner returned no valid schedule entries.")

    return normalized_days


def _build_expected_dates(start_date: str, days: int) -> list[str]:
    base = _normalize_start_date(start_date)
    return [(base + timedelta(days=index)).date().isoformat() for index in range(max(1, days))]


def _count_raw_schedule_items(schedule_data: dict) -> tuple[int, int]:
    raw_days = schedule_data.get("days") if isinstance(schedule_data, dict) else []
    if not isinstance(raw_days, list):
        return 0, 0
    raw_task_count = 0
    for day in raw_days:
        if isinstance(day, dict) and isinstance(day.get("tasks"), list):
            raw_task_count += len(day["tasks"])
    return len(raw_days), raw_task_count


def _task_sort_key(task: dict) -> tuple[int, str]:
    return (_minutes_from_time(task["start_time"]), task["title"])


def _tasks_overlap(task_a: dict, task_b: dict) -> bool:
    start_a = _minutes_from_time(task_a["start_time"])
    end_a = _minutes_from_time(task_a["end_time"])
    start_b = _minutes_from_time(task_b["start_time"])
    end_b = _minutes_from_time(task_b["end_time"])
    return start_a < end_b and start_b < end_a


def _build_fallback_task_templates(priority_heavy: bool) -> list[dict]:
    if priority_heavy:
        return [
            {"title": "Priority review block", "category": "study", "start_time": "08:30", "end_time": "09:30", "notes": "Focus on the nearest deadline first."},
            {"title": "Focused assignment work", "category": "study", "start_time": "10:00", "end_time": "11:00", "notes": "Break large coursework into one concrete deliverable."},
            {"title": "Quiz revision session", "category": "study", "start_time": "11:30", "end_time": "12:30", "notes": "Review weak topics and mistakes from earlier attempts."},
            {"title": "Lunch reset", "category": "food", "start_time": "12:45", "end_time": "13:30", "notes": "Eat and step away from work briefly."},
            {"title": "Recovery break", "category": "mind", "start_time": "15:00", "end_time": "15:30", "notes": "Short reset to maintain focus later in the day."},
            {"title": "Movement session", "category": "workout", "start_time": "17:00", "end_time": "18:00", "notes": "Walk, stretch, or do a quick workout."},
            {"title": "Evening recap", "category": "study", "start_time": "19:30", "end_time": "20:30", "notes": "Summarize what was completed and what still needs attention."},
            {"title": "Wind-down routine", "category": "mind", "start_time": "21:00", "end_time": "21:30", "notes": "Close the day with a light reset."},
        ]

    return [
        {"title": "Morning study block", "category": "study", "start_time": "09:00", "end_time": "10:00", "notes": "Make progress on your main learning goal."},
        {"title": "Lunch break", "category": "food", "start_time": "12:30", "end_time": "13:15", "notes": "Refuel and take a real break away from the desk."},
        {"title": "Reflection break", "category": "mind", "start_time": "15:00", "end_time": "15:30", "notes": "Pause, breathe, and reset for the afternoon."},
        {"title": "Light movement", "category": "workout", "start_time": "17:00", "end_time": "17:45", "notes": "Keep your energy up with a walk or short workout."},
        {"title": "Evening study recap", "category": "study", "start_time": "19:00", "end_time": "20:00", "notes": "Review key ideas and capture next steps."},
        {"title": "General catch-up", "category": "general", "start_time": "20:30", "end_time": "21:00", "notes": "Use this time for unfinished admin or planning tasks."},
        {"title": "Quiet reset", "category": "mind", "start_time": "21:15", "end_time": "21:45", "notes": "End the day with something calming."},
    ]


def _fill_day_tasks(existing_tasks: list[dict], *, priority_heavy: bool) -> tuple[list[dict], int]:
    tasks = sorted(list(existing_tasks), key=_task_sort_key)[:MAX_TASKS_PER_DAY]
    fallback_added = 0

    if len(tasks) >= MIN_TASKS_PER_DAY:
        return tasks, fallback_added

    for candidate in _build_fallback_task_templates(priority_heavy):
        normalized_candidate = _normalize_task_payload(candidate)
        if not normalized_candidate:
            continue
        if any(_tasks_overlap(normalized_candidate, existing_task) for existing_task in tasks):
            continue
        tasks.append(normalized_candidate)
        tasks.sort(key=_task_sort_key)
        fallback_added += 1
        if len(tasks) >= MIN_TASKS_PER_DAY:
            break

    if len(tasks) < MIN_TASKS_PER_DAY:
        raise ValueError("AI planner could not construct a complete daily schedule.")

    return tasks[:MAX_TASKS_PER_DAY], fallback_added


def _complete_generated_schedule(start_date: str, requested_days: int, generated_days: list[dict], priorities: list[str]) -> tuple[list[dict], dict]:
    expected_dates = _build_expected_dates(start_date, requested_days)
    generated_by_date = {day["date"]: list(day["tasks"]) for day in generated_days if day["date"] in expected_dates}
    completed_days = []
    missing_days = 0
    fallback_tasks_added = 0
    priority_heavy = bool(priorities)

    for date_str in expected_dates:
        existing_tasks = generated_by_date.get(date_str, [])
        if not existing_tasks:
            missing_days += 1

        completed_tasks, added_count = _fill_day_tasks(existing_tasks, priority_heavy=priority_heavy)
        fallback_tasks_added += added_count
        completed_days.append({"date": date_str, "tasks": completed_tasks})

    if len(completed_days) != len(expected_dates):
        raise ValueError("AI planner could not cover the requested date range.")

    if any(len(day["tasks"]) < MIN_TASKS_PER_DAY or len(day["tasks"]) > MAX_TASKS_PER_DAY for day in completed_days):
        raise ValueError("AI planner could not build a complete multi-task schedule.")

    return completed_days, {
        "missing_days": missing_days,
        "fallback_tasks_added": fallback_tasks_added,
        "expected_days": len(expected_dates),
    }


async def _collect_planner_context(db, user_id: str, start_date: str) -> tuple[list[str], list[str]]:
    classes = await lms_service.get_classes_for_student(db, user_id)
    class_ids = [c["id"] for c in classes]
    class_names = [c["name"] for c in classes]

    priorities: list[str] = []
    if not class_ids:
        return class_names, priorities

    today_dt = _normalize_start_date(start_date)

    assignments = await db.assignments.find({"class_id": {"$in": class_ids}}).to_list(None)
    future_assignments = [
        assignment for assignment in assignments
        if assignment.get("due_date")
        and (
            (isinstance(assignment["due_date"], datetime) and assignment["due_date"] >= today_dt)
            or (isinstance(assignment["due_date"], str) and assignment["due_date"][:10] >= start_date)
        )
    ]
    for assignment in future_assignments:
        due = assignment["due_date"].isoformat()[:10] if isinstance(assignment["due_date"], datetime) else assignment["due_date"][:10]
        priorities.append(f'- Assignment: "{assignment.get("title")}" due on {due}')

    quizzes = await db.lms_quizzes.find({"class_id": {"$in": class_ids}}).to_list(None)
    future_quizzes = [
        quiz for quiz in quizzes
        if quiz.get("start_time")
        and (
            (isinstance(quiz["start_time"], datetime) and quiz["start_time"] >= today_dt)
            or (isinstance(quiz["start_time"], str) and quiz["start_time"][:10] >= start_date)
        )
    ]
    for quiz in future_quizzes:
        start = quiz["start_time"].isoformat()[:10] if isinstance(quiz["start_time"], datetime) else quiz["start_time"][:10]
        priorities.append(f'- Quiz: "{quiz.get("title")}" scheduled for {start}')

    attempts = await db.quiz_attempts.find({"student_id": user_id}).to_list(None)
    for attempt in attempts:
        if attempt.get("percentage", 100) < 70:
            quiz_title = next((quiz.get("title") for quiz in quizzes if quiz.get("id") == attempt.get("quiz_id")), "Unknown Quiz")
            priorities.append(f'- Needs Review: Scored below 70% on "{quiz_title}". Allocate study time for this.')

    return class_names, priorities


# ===================== TEMPLATE ENDPOINTS =====================

@router.get("/templates")
async def get_templates():
    return planner_service.TEMPLATE_SCHEDULES


# ===================== PLAN ENDPOINTS =====================

@router.post("/plans/generate")
async def generate_smart_plan(
    data: SmartPlanRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    from backend.core.llm_interface import llm_client

    user_id = str(current_user["_id"])
    start_date = _normalize_start_date(data.start_date).date().isoformat()
    class_names, priorities = await _collect_planner_context(db, user_id, start_date)
    prompt = _build_planner_prompt(start_date, data.days, class_names, priorities)

    try:
        response_text = await llm_client.async_generate(
            prompt=prompt,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            temperature=0.2,
        )
    except Exception as exc:
        logger.error("Planner generation request failed: %s", exc)
        raise HTTPException(status_code=500, detail="AI planner generation failed before a schedule was returned.") from exc

    try:
        schedule_data = await _parse_smart_plan_payload(llm_client, response_text)
        raw_day_count, raw_task_count = _count_raw_schedule_items(schedule_data)
        generated_days = _normalize_generated_schedule(schedule_data)
        logger.info(
            "Planner raw AI schedule: requested_days=%s raw_days=%s raw_tasks=%s normalized_days=%s normalized_tasks=%s",
            data.days,
            raw_day_count,
            raw_task_count,
            len(generated_days),
            sum(len(day["tasks"]) for day in generated_days),
        )
        completed_days, completion_stats = _complete_generated_schedule(
            start_date,
            data.days,
            generated_days,
            priorities,
        )
    except ValueError as exc:
        logger.error("Failed to generate or parse Smart Plan: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    total_tasks = 0
    for day in completed_days:
        planner_day = await planner_service.get_or_create_planner_day(
            db, user_id, day["date"], template="empty", auto_fill=False
        )
        day_id = planner_day["id"]
        for task in day["tasks"]:
            await planner_service.add_task(
                db=db,
                planner_day_id=day_id,
                title=task["title"],
                category=task["category"],
                start_time=task["start_time"],
                end_time=task["end_time"],
                notes=task["notes"],
            )
            total_tasks += 1

    logger.info(
        "Planner completed schedule persisted: requested_days=%s final_days=%s final_tasks=%s synthesized_days=%s fallback_tasks=%s",
        data.days,
        len(completed_days),
        total_tasks,
        completion_stats["missing_days"],
        completion_stats["fallback_tasks_added"],
    )

    return {
        "status": "success",
        "message": f"Generated {total_tasks} tasks across {len(completed_days)} days.",
        "days_processed": len(completed_days),
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
    except ValueError as exc:
        raise HTTPException(404, str(exc))


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
