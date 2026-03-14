# backend/models/chat_history.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    subject: Optional[str] = None


class ChatRequest(ChatMessage):
    session_id: Optional[str] = None


class Citation(BaseModel):
    chunk_index: int
    source: str


class ChatResponse(BaseModel):
    answer: str
    citations: List[int] = []
    session_id: Optional[str] = None


class ChatSession(BaseModel):
    id: str
    user_id: str
    subject: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    
    class Config:
        from_attributes = True
