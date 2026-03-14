# backend/models/feedback.py
from pydantic import BaseModel, Field
from typing import Optional


class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    message: Optional[str] = Field(None, max_length=1000)
    chat_session_id: Optional[str] = None


class FeedbackPublic(BaseModel):
    id: str
    rating: int
    message: Optional[str]
    created_at: str
