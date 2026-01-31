"""
User model and Pydantic schemas for auth API.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Request body for register."""
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=6)
    level: str = Field(default="school")  # school | intermediate | engineering


class UserLogin(BaseModel):
    """Request body for login."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User data returned to client (no password)."""
    id: str
    name: str
    email: str
    level: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


def user_doc_to_response(doc: dict) -> UserResponse:
    """Convert MongoDB user document to UserResponse."""
    ca = doc.get("created_at")
    if ca is not None and hasattr(ca, "isoformat"):
        ca = ca.isoformat()
    return UserResponse(
        id=str(doc["_id"]),
        name=doc["name"],
        email=doc["email"],
        level=doc.get("level", "school"),
        created_at=ca,
    )
