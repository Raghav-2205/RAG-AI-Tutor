# backend/models/user.py
from typing import Optional, Any
from pydantic import BaseModel, EmailStr, Field, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema
from bson import ObjectId

# Fix for using MongoDB ObjectId with Pydantic V2
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

# What we store in DB
class UserInDB(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    name: str
    email: EmailStr
    hashed_password: str
    roll_number: Optional[str] = None # Added for College LMS
    level: str = "undergraduate"
    role: str = "Student"
    created_at: Any = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

# What the frontend sends to register
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(..., min_length=6)
    roll_number: Optional[str] = None # For bulk enrollment
    level: str = "undergraduate"
    role: str = "Student"

# Simple Login Model (Added back to fix ImportError)
class UserLogin(BaseModel):
    email: Optional[EmailStr] = None
    roll_number: Optional[str] = None # Allow login with roll number
    password: str

# What we return to the frontend
class UserPublic(BaseModel):
    id: str
    name: str
    email: EmailStr
    roll_number: Optional[str] = None
    level: str
    role: str = "Student"