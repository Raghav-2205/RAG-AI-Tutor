import logging
from typing import Optional
from fastapi import APIRouter, Depends
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.services import suggestion_service

# Fallback LLM client mock wrapper for suggestion service since it natively uses it.
# If real LLM integration is available in the project, it can be injected.
try:
    from backend.core.llm_interface import llm_client
except ImportError:
    llm_client = None

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/daily/{date}")
async def get_daily_suggestions(date: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    """
    Generate AI suggestions based on the user's tracked activities for the past 7 days.
    """
    user_id = str(current_user["_id"])
    
    suggestions = await suggestion_service.generate_suggestions(
        db, user_id, llm_client, save=True
    )

    return {
        "date": date,
        "suggestions": [s["suggestion"] for s in suggestions],
        "source": "ai" if llm_client else "fallback"
    }

@router.get("/unread")
async def get_unread_suggestions(limit: int = 5, current_user=Depends(get_current_user), db=Depends(get_db)):
    """
    Fetch unread personalized suggestions.
    """
    user_id = str(current_user["_id"])
    s_docs = await suggestion_service.get_user_suggestions(db, user_id, unread_only=True, limit=limit)
    return s_docs

@router.post("/{suggestion_id}/read")
async def mark_read(suggestion_id: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    """
    Mark a specific suggestion as read.
    """
    user_id = str(current_user["_id"])
    success = await suggestion_service.mark_suggestion_read(db, suggestion_id, user_id)
    return {"success": success}
