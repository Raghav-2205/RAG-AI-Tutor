# backend/feedback.py

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from bson import ObjectId

from backend.utils.db import get_db
from backend.auth import get_current_user


router = APIRouter(prefix="/api/feedback", tags=["feedback"])


# ----- Helpers for ObjectId -----

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


# ----- Pydantic models -----


class FeedbackCreate(BaseModel):
    """
    What the frontend sends when user submits feedback.
    """
    rating: int = Field(..., ge=1, le=5, description="1–5 rating")
    message: Optional[str] = Field(None, description="Optional feedback text")
    # Optional links to a specific chat or quiz
    chat_session_id: Optional[str] = None
    quiz_id: Optional[str] = None


class FeedbackInDB(BaseModel):
    """
    How feedback is stored in MongoDB.
    """
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId
    rating: int
    message: Optional[str] = None
    chat_session_id: Optional[PyObjectId] = None
    quiz_id: Optional[PyObjectId] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class FeedbackPublic(BaseModel):
    """
    What we return to the frontend.
    """
    id: str
    rating: int
    message: Optional[str]
    chat_session_id: Optional[str]
    quiz_id: Optional[str]
    created_at: datetime


def feedback_doc_to_public(doc: dict) -> FeedbackPublic:
    return FeedbackPublic(
        id=str(doc["_id"]),
        rating=doc["rating"],
        message=doc.get("message"),
        chat_session_id=str(doc["chat_session_id"]) if doc.get("chat_session_id") else None,
        quiz_id=str(doc["quiz_id"]) if doc.get("quiz_id") else None,
        created_at=doc["created_at"],
    )


# ----- Routes -----


@router.post("/", response_model=FeedbackPublic, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    feedback_in: FeedbackCreate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Save a feedback entry for the currently logged-in user.
    """
    feedback_col = db["feedback"]

    doc = {
        "user_id": current_user["_id"],
        "rating": feedback_in.rating,
        "message": feedback_in.message,
        "created_at": datetime.utcnow(),
    }

    if feedback_in.chat_session_id:
        try:
            doc["chat_session_id"] = ObjectId(feedback_in.chat_session_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid chat_session_id")

    if feedback_in.quiz_id:
        try:
            doc["quiz_id"] = ObjectId(feedback_in.quiz_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid quiz_id")

    result = feedback_col.insert_one(doc)
    doc["_id"] = result.inserted_id

    return feedback_doc_to_public(doc)


@router.get("/", response_model=List[FeedbackPublic])
async def list_feedback(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    List all feedback entries for the current user.
    """
    feedback_col = db["feedback"]

    cursor = feedback_col.find({"user_id": current_user["_id"]}).sort("created_at", -1)
    docs = list(cursor)

    return [feedback_doc_to_public(d) for d in docs]
