# backend/models/document.py
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime


class DocumentCreate(BaseModel):
    filename: str = Field(..., max_length=255)
    subject: Optional[str] = None


class DocumentPublic(BaseModel):
    id: str
    filename: str
    subject: Optional[str]
    chunks_count: int
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
