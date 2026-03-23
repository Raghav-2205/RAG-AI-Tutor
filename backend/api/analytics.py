from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Dict

from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.services.analytics_service import get_student_analytics, get_teacher_analytics
from backend.services.suggestion_service import generate_suggestions
from backend.core.llm_interface import llm_client

router = APIRouter()

@router.get("/student", summary="Get personalized student analytics and recommendations")
async def student_analytics(
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user_id = str(current_user["_id"])
    
    # Get both analytics and suggestions (which includes recommendations)
    suggestions_data = await generate_suggestions(db, user_id, llm_client=llm_client)
    
    return suggestions_data

@router.get("/teacher/{class_id}", summary="Get class analytics for teachers")
async def teacher_analytics(
    class_id: str,
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    # Ensure user is teacher/admin (role check)
    role = current_user.get("role", "student").lower()
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers can view class analytics")
    
    try:
        stats = await get_teacher_analytics(db, class_id)
        return stats
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
