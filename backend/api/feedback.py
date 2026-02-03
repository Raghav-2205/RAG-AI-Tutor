# backend/api/feedback.py
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.utils.helpers import doc_to_dict

router = APIRouter()

class FeedbackCreate(BaseModel):
    rating: int # 1-5
    message: Optional[str] = None

@router.post("/", status_code=201)
async def create_feedback(
    feedback: FeedbackCreate,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    doc = {
        "user_id": str(current_user["_id"]),
        "rating": feedback.rating,
        "message": feedback.message,
        "created_at": datetime.utcnow()
    }
    result = await db.feedback.insert_one(doc)
    return doc_to_dict(doc)