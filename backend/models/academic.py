# backend/models/academic.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import date, datetime
from pydantic_core import core_schema
from typing import Any
from pydantic import GetJsonSchemaHandler
from bson import ObjectId

# Re-use PyObjectId from user.py or redefine for independent usage
class PyObjectId(str):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: GetJsonSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema([
                core_schema.is_instance_schema(ObjectId),
                core_schema.str_schema(),
            ]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: str(x)
            ),
        )

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

# 🏫 1. Semester Schema
class Semester(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    name: str               # e.g., "BE - VIII Semester (CSE-1)"
    start_date: date        # e.g., "2026-01-19"
    end_date: date
    is_active: bool = True
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

# 📚 2. Subject & Faculty Schema
class Subject(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    name: str               # e.g., "Environmental Science"
    short_code: str         # e.g., "ES"
    semester_id: str
    teacher_id: str         # Links to User schema role="teacher"
    is_practical: bool = False # True for Project Part-II

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

# 📅 3. Timetable Schema (Stores fixed weekly slots)
class TimetableSlot(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    semester_id: str
    day_of_week: str        # e.g., "Wednesday", "Thursday"
    period_number: int      # 1 to 6
    start_time: str         # e.g., "09:10"
    end_time: str           # e.g., "10:10"
    subject_id: str
    teacher_id: str
    room: str               # e.g., "C-212"

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

# ✅ 4. Attendance Schema (Real-time tracking)
class AttendanceRecord(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    timetable_slot_id: str
    date: date              # Exact date of the class
    subject_id: str
    teacher_id: str
    present_roll_numbers: List[str] # Validates against 160122733xxx
    absent_roll_numbers: List[str]

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

# 📝 5. Academic Profile (Added to existing Student User model)
class StudentProfile(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    user_id: str            # Links back to User collection
    roll_number: str        # e.g., "160122733001"
    semester_id: str
    enrolled_subjects: List[str]
    fee_status: str = "Pending" # "Paid", "Pending"

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

# 📝 6. LMS Class Mode
class LMSClass(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    teacher_id: str
    class_name: str
    subject: str
    students: List[str] = []
    created_at: date = Field(default_factory=date.today)

# 📝 7. SlipTest (Timed Quizzes)
class SlipTestQuestion(BaseModel):
    question: str
    options: List[str]
    correct_answer: str

class SlipTest(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    class_id: str
    title: str
    questions: List[SlipTestQuestion]
    duration: int # minutes
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

# 📝 8. Test Submission
class TestSubmission(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    student_id: str
    test_id: str
    answers: Dict[str, str] # e.g. {"q1": "Option A"}
    score: float
    submitted_at: datetime = Field(default_factory=datetime.utcnow)

# 📝 9. Interaction Log (For Engagement Analytics)
class InteractionLog(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    student_id: str
    class_id: str
    messages_count: int = 0
    last_active: datetime = Field(default_factory=datetime.utcnow)
    engagement_score: float = 0.0
