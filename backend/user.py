# backend/user.py

from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(str(v))
        except Exception:
            raise ValueError("Invalid ObjectId")


# What we store in DB
class UserInDB(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str
    email: EmailStr
    hashed_password: str
    level: str = "school"  # e.g. school/college/etc.

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


# What comes FROM client when registering
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    level: str = "school"


# What we return TO client
class UserPublic(BaseModel):
    id: str
    name: str
    email: EmailStr
    level: str

    class Config:
        json_encoders = {ObjectId: str}


def user_in_db_to_public(user: dict) -> UserPublic:
    return UserPublic(
        id=str(user["_id"]),
        name=user["name"],
        email=user["email"],
        level=user.get("level", "school"),
    )
