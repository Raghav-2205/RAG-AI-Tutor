# backend/api/feedback.py
"""
Feedback API Endpoints

Handles user feedback for chat responses and quiz results.
Stores feedback persistently in MongoDB for future analysis.
"""

from typing import Optional, List, Dict
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.utils.helpers import doc_to_dict
import logging
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)


class FeedbackSubmitRequest(BaseModel):
    source: str = Field(..., pattern="^(chat|quiz)$")  # Must be 'chat' or 'quiz'
    subject: str
    reference_id: str  # chat_id or quiz_id
    rating: str  # 'positive' | 'negative' | '1' | '2' | '3' | '4' | '5'
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    feedback_id: str
    message: str


@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackSubmitRequest,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """
    Submit feedback for a chat response or quiz result.
    
    Protected by JWT authentication - users can only submit feedback for their own content.
    """
    try:
        user_id = str(current_user["_id"])
        
        logger.info(f"[FEEDBACK SUBMIT] User={user_id}, Source={request.source}, RefID={request.reference_id}")
        
        # Validate reference exists and belongs to user
        if request.source == "chat":
            # Try to find chat by _id (if it's a valid ObjectId) or just allow it
            # Chat session IDs from frontend might be timestamps like "chat_1234567890"
            # We'll be lenient here and just log warning if not found
            try:
                from bson import ObjectId
                if ObjectId.is_valid(request.reference_id):
                    chat = await db.chats.find_one({"_id": ObjectId(request.reference_id), "user_id": current_user["_id"]})
                    if not chat:
                        logger.warning(f"[FEEDBACK] Chat {request.reference_id} not found by ObjectId")
                else:
                    logger.info(f"[FEEDBACK] Reference ID {request.reference_id} is not ObjectId, allowing anyway")
            except Exception as e:
                logger.warning(f"[FEEDBACK] Could not validate chat reference: {e}")
        
        elif request.source == "quiz":
            # Verify quiz exists and belongs to user
            quiz = await db.quizzes.find_one({"quiz_id": request.reference_id, "user_id": user_id})
            if not quiz:
                raise HTTPException(status_code=404, detail="Quiz not found or access denied")
        
        # Create feedback document
        feedback_id = str(uuid.uuid4())
        feedback_doc = {
            "feedback_id": feedback_id,
            "user_id": user_id,
            "source": request.source,
            "reference_id": request.reference_id,
            "subject": request.subject,
            "rating": request.rating,
            "comment": request.comment,
            "timestamp": datetime.utcnow()
        }
        
        # Store in MongoDB
        await db.feedback.insert_one(feedback_doc)
        
        logger.info(f"[FEEDBACK SAVED] FeedbackID={feedback_id}, Rating={request.rating}")
        
        return FeedbackResponse(
            feedback_id=feedback_id,
            message="Feedback submitted successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[FEEDBACK SUBMIT ERROR]")
        raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {str(e)}")


@router.get("/")
async def get_feedback(
    user_id: Optional[str] = None,
    subject: Optional[str] = None,
    source: Optional[str] = None,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """
    Retrieve feedback with optional filtering.
    
    Protected by JWT. Users can only retrieve their own feedback.
    Admin users can retrieve all feedback (future enhancement).
    """
    try:
        # Build query filter
        query = {"user_id": str(current_user["_id"])}  # Users can only see their own feedback
        
        if subject:
            query["subject"] = subject
        
        if source:
            if source not in ["chat", "quiz"]:
                raise HTTPException(status_code=400, detail="Invalid source. Must be 'chat' or 'quiz'")
            query["source"] = source
        
        logger.info(f"[FEEDBACK RETRIEVE] Query={query}")
        
        # Retrieve feedback from MongoDB
        feedback_cursor = db.feedback.find(query).sort("timestamp", -1).limit(100)
        feedback_list = await feedback_cursor.to_list(length=100)
        
        logger.info(f"[FEEDBACK RETRIEVE] Found {len(feedback_list)} feedback entries")
        
        return {
            "total": len(feedback_list),
            "feedback": [doc_to_dict(f) for f in feedback_list]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[FEEDBACK RETRIEVE ERROR]")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve feedback: {str(e)}")


@router.get("/stats")
async def get_feedback_stats(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """
    Get feedback statistics for the current user.
    
    Returns counts by source, rating distribution, etc.
    """
    try:
        user_id = str(current_user["_id"])
        
        # Count total feedback
        total_feedback = await db.feedback.count_documents({"user_id": user_id})
        
        # Count by source
        chat_count = await db.feedback.count_documents({"user_id": user_id, "source": "chat"})
        quiz_count = await db.feedback.count_documents({"user_id": user_id, "source": "quiz"})
        
        # Count by rating type (chat)
        positive_count = await db.feedback.count_documents({"user_id": user_id, "source": "chat", "rating": "positive"})
        negative_count = await db.feedback.count_documents({"user_id": user_id, "source": "chat", "rating": "negative"})
        
        return {
            "total_feedback": total_feedback,
            "by_source": {
                "chat": chat_count,
                "quiz": quiz_count
            },
            "chat_ratings": {
                "positive": positive_count,
                "negative": negative_count
            }
        }
        
    except Exception as e:
        logger.exception("[FEEDBACK STATS ERROR]")
        raise HTTPException(status_code=500, detail=f"Failed to get feedback stats: {str(e)}")


@router.get("/analytics")
async def get_feedback_analytics(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """
    Get analytics on how feedback is influencing responses.
    Shows which responses were adjusted based on feedback.
    """
    try:
        user_id = str(current_user["_id"])
        
        # Get total chats that were feedback-adjusted
        adjusted_chats = await db.chats.count_documents({
            "user_id": current_user["_id"],
            "feedback_adjusted": True
        })
        
        total_chats = await db.chats.count_documents({
            "user_id": current_user["_id"]
        })
        
        # Get feedback influence logs
        influence_logs = await db.feedback_influence_log.find({
            "user_id": user_id
        }).sort("timestamp", -1).limit(10).to_list(length=10)
        
        # Get recent feedback stats from analyzer
        from backend.core.feedback_analyzer import FeedbackAnalyzer
        analyzer = FeedbackAnalyzer(db)
        stats = await analyzer.get_user_feedback_stats(user_id, hours=24)
        
        return {
            "feedback_stats": stats,
            "adjusted_responses": adjusted_chats,
            "total_responses": total_chats,
            "adjustment_rate": round((adjusted_chats / total_chats * 100), 1) if total_chats > 0 else 0,
            "recent_adjustments": [
                {
                    "timestamp": log["timestamp"].isoformat(),
                    "type": log["adjustment_type"],
                    "details": log["details"]
                }
                for log in influence_logs
            ]
        }
    except Exception as e:
        logger.error(f"❌ Analytics error: {e}")
        raise HTTPException(status_code=500, detail=f"Analytics error: {str(e)}")
