# backend/api/quiz.py
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.quiz_generator import generate_quiz_for_user
from backend.utils.helpers import doc_to_dict

router = APIRouter()

class QuizGenerateRequest(BaseModel):
    subject: Optional[str] = None
    num_questions: int = 5
    difficulty: str = "medium"

@router.post("/generate")
async def generate_quiz_endpoint(
    request: QuizGenerateRequest,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        quiz_data = generate_quiz_for_user(
            user_id=str(current_user["_id"]),
            subject=request.subject,
            num_questions=request.num_questions,
            difficulty=request.difficulty
        )
        
        # Save to DB
        result = await db.quizzes.insert_one(quiz_data)
        quiz_data["id"] = str(result.inserted_id)
        if "_id" in quiz_data: del quiz_data["_id"]
        
        return quiz_data
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
async def list_quizzes(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    quizzes = await db.quizzes.find(
        {"user_id": str(current_user["_id"])}
    ).sort("created_at", -1).to_list(length=20)
    
    return [doc_to_dict(q) for q in quizzes]