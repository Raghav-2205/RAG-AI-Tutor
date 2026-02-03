# backend/api/feedback.py

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional, List

from backend.utils import get_db, get_current_user
from backend.utils.helpers import doc_to_dict


router = APIRouter(tags=["feedback"])


class FeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    message: Optional[str] = None
    chat_session_id: Optional[str] = None


class FeedbackPublic(BaseModel):
    id: str
    rating: int
    message: Optional[str]
    created_at: str


@router.post("/", response_model=FeedbackPublic, status_code=201)
async def create_feedback(fb: FeedbackCreate,
                         db=Depends(get_db),
                         current_user=Depends(get_current_user)):
    doc = {
        "user_id": current_user["_id"],
        "rating": fb.rating,
        "message": fb.message,
        "chat_session_id": fb.chat_session_id,
        "created_at": datetime.utcnow(),
    }
    result = db.feedback.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc_to_dict(doc)


@router.get("/", response_model=List[FeedbackPublic])
async def list_feedback(db=Depends(get_db), current_user=Depends(get_current_user)):
    docs = list(db.feedback.find({"user_id": current_user["_id"]}))
    return [doc_to_dict(doc) for doc in docs]
