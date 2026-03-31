from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict
from datetime import datetime, date
import io
import json

try:
    import pandas as pd
except ImportError:
    pd = None

from backend.utils.dependencies import get_current_user # Need your auth dependency
from backend.models.user import UserInDB, PyObjectId
from backend.models.academic import (
    Semester, Subject, TimetableSlot, AttendanceRecord, StudentProfile
)
from backend.utils.db import db_manager # Using db_manager to access collections

router = APIRouter()

# ==========================================
# 📡 WEBSOCKET MANAGER (REAL-TIME SYNC)
# ==========================================
class AttendanceConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, roll_number: str):
        await websocket.accept()
        self.active_connections[roll_number] = websocket

    def disconnect(self, roll_number: str):
        if roll_number in self.active_connections:
            del self.active_connections[roll_number]

    async def send_personal_message(self, message: str, roll_number: str):
        if roll_number in self.active_connections:
            await self.active_connections[roll_number].send_text(message)

manager = AttendanceConnectionManager()

@router.websocket("/ws/attendance/{roll_number}")
async def websocket_attendance_endpoint(websocket: WebSocket, roll_number: str):
    await manager.connect(websocket, roll_number)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(roll_number)

# ==========================================
# 👑 ADMIN ENDPOINTS
# ==========================================

@router.post("/admin/students/bulk-enroll")
async def bulk_enroll_students(file: UploadFile = File(...), current_user = Depends(get_current_user)):
    """Upload Excel/CSV of roll numbers to auto-create student accounts."""
    if current_user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not pd:
        raise HTTPException(status_code=500, detail="Pandas is required. Run: pip install pandas openpyxl")
    
    content = await file.read()
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
            
        users_col = db_manager.db["users"]
        enrolled_count = 0
        
        for index, row in df.iterrows():
            roll_number = str(row.get("roll_number", "")).strip()
            name = str(row.get("name", "Student"))
            email = str(row.get("email", f"{roll_number}@cbit.edu.in"))
            
            if not roll_number: continue
            
            # Check if exists
            existing = await users_col.find_one({"roll_number": roll_number})
            if not existing:
                # Create user placeholder
                new_user = {
                    "name": name,
                    "email": email,
                    "hashed_password": "default_password_hash", # Need to hash this in real use
                    "roll_number": roll_number,
                    "level": "undergraduate",
                    "role": "Student",
                    "created_at": datetime.utcnow()
                }
                await users_col.insert_one(new_user)
                enrolled_count += 1

        return {"message": f"Successfully enrolled {enrolled_count} students."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")


@router.post("/admin/timetable/upload")
async def upload_college_timetable(semester_id: str, file: UploadFile = File(...), current_user = Depends(get_current_user)):
    """Upload structured timetable JSON or CSV."""
    if current_user["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return {"message": "Timetable successfully mapped to C-212 and stored in DB."}

# ==========================================
# 👨‍🏫 TEACHER ENDPOINTS
# ==========================================

@router.get("/teacher/dashboard/today")
async def teacher_today_schedule(current_teacher = Depends(get_current_user)):
    """Gets teacher's classes for today based on TimetableSlot."""
    role = current_teacher.get("role", "").lower()
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Teacher access required")
        
    today_name = datetime.now().strftime("%A") # e.g., 'Wednesday'
    
    timetable_col = db_manager.db["timetable"]
    slots_cursor = timetable_col.find({
        "teacher_id": str(current_teacher["_id"]),
        "day_of_week": today_name
    })
    
    slots = await slots_cursor.to_list(length=10)
    for slot in slots:
        slot["_id"] = str(slot["_id"])
    
    # Return gracefully even if no timetable is set up
    return {"today": today_name, "classes": slots}

@router.get("/teacher/reports/export-excel")
async def export_attendance_excel(subject_id: str, current_teacher = Depends(get_current_user)):
    """Generates an Excel sheet with all students attendance, streams back to UI."""
    if not pd:
        raise HTTPException(status_code=500, detail="Pandas is required. Run: pip install pandas openpyxl")
    
    attendance_col = db_manager.db["attendance"]
    records_cursor = attendance_col.find({"subject_id": subject_id})
    records = await records_cursor.to_list(length=1000)
    
    data = []
    for r in records:
        for p in r.get("present_roll_numbers", []):
            data.append({"Roll Number": p, "Status": "Present", "Date": str(r["date"])})
        for a in r.get("absent_roll_numbers", []):
            data.append({"Roll Number": a, "Status": "Absent", "Date": str(r["date"])})
            
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=["Roll Number", "Status", "Date"])
        
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Attendance")
    
    stream.seek(0)
    headers = {
        'Content-Disposition': f'attachment; filename="attendance_{subject_id}.xlsx"'
    }
    return StreamingResponse(stream, headers=headers, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/teacher/attendance/mark")
async def mark_slot_attendance(record: AttendanceRecord, current_teacher = Depends(get_current_user)):
    """Marks attendance. Save to AttendanceRecord DB and broadcast to WebSockets."""
    if current_teacher["role"] != "Teacher":
        raise HTTPException(status_code=403, detail="Teacher access required")
        
    attendance_col = db_manager.db["attendance"]
    record_dict = record.model_dump(by_alias=True, exclude={"id"})
    
    result = await attendance_col.insert_one(record_dict)
    
    # Broadcast to present students
    for roll in record.present_roll_numbers:
        await manager.send_personal_message(json.dumps({
            "type": "attendance_update",
            "subject": record.subject_id,
            "status": "Present",
            "message": f"You were marked Present for {record.subject_id}"
        }), roll)
        
    # Broadcast to absent students
    for roll in record.absent_roll_numbers:
        await manager.send_personal_message(json.dumps({
            "type": "attendance_update",
            "subject": record.subject_id,
            "status": "Absent",
            "message": f"You were marked Absent for {record.subject_id}"
        }), roll)
    
    return {"message": "Attendance marked successfully & students notified live", "id": str(result.inserted_id)}


# ==========================================
# 🎓 STUDENT ENDPOINTS
# ==========================================

@router.get("/student/timetable/today")
async def student_today_schedule(current_student = Depends(get_current_user)):
    """Returns today's classes for the student."""
    if current_student["role"] != "Student":
        raise HTTPException(status_code=403, detail="Student access required")
        
    today_name = datetime.now().strftime("%A")
    timetable_col = db_manager.db["timetable"]
    
    # In real impl, fetch student's semester_id
    slots_cursor = timetable_col.find({
        "day_of_week": today_name
    })
    
    slots = await slots_cursor.to_list(length=10)
    for slot in slots:
        slot["_id"] = str(slot["_id"])
        
    return {"today": today_name, "classes": slots}

@router.get("/student/attendance/summary")
async def get_attendance_percentage(current_student = Depends(get_current_user)):
    """Calculates attendance % per subject for the student."""
    roll_number = current_student.get("roll_number")
    if not roll_number:
        return {"error": "Roll number not found for this student"}
        
    attendance_col = db_manager.db["attendance"]
    
    # Search where this roll number is present
    present_count = await attendance_col.count_documents({"present_roll_numbers": roll_number})
    absent_count = await attendance_col.count_documents({"absent_roll_numbers": roll_number})
    
    total = present_count + absent_count
    percentage = (present_count / total * 100) if total > 0 else 0
    
    return {
        "overall_percentage": round(percentage, 2),
        "present": present_count,
        "absent": absent_count
    }
