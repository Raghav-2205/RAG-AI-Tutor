# backend/api/quiz.py

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional, List

from backend.utils import get_db, get_current_user
from backend.quiz_generator import generate_quiz_for_user
from backend.utils.helpers import doc_to_dict


router = APIRouter(tags=["quiz"])


class QuizGenerateRequest(BaseModel):
    num_questions: int = Field(5, ge=1, le=20)
    difficulty: str = Field("medium", pattern="^(easy|medium|hard)$")
    subject: Optional[str] = None


@router.post("/generate", response_model=dict)
async def generate_quiz(request: QuizGenerateRequest,
                       current_user=Depends(get_current_user)):
    """Generate quiz from user's documents"""
    quiz = generate_quiz_for_user(
        user_id=str(current_user["_id"]),
        subject=request.subject,
        num_questions=request.num_questions,
        difficulty=request.difficulty,
    )
    return quiz


@router.get("/", response_model=List[dict])
async def list_quizzes(db=Depends(get_db), current_user=Depends(get_current_user)):
    quizzes = list(db.quizzes.find({"user_id": current_user["_id"]}))
    return [doc_to_dict(q) for q in quizzes]
