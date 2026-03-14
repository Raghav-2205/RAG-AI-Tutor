# backend/models/quiz.py
from pydantic import BaseModel, Field
from typing import List, Optional


class QuizQuestion(BaseModel):
    question: str
    options: List[str] = Field(..., min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str


class QuizGenerateRequest(BaseModel):
    num_questions: int = Field(5, ge=1, le=20)
    difficulty: str = Field("medium", pattern="^(easy|medium|hard)$")
    subject: Optional[str] = None


class QuizPublic(BaseModel):
    id: str
    num_questions: int
    difficulty: str
    subject: Optional[str]
    questions: List[QuizQuestion]


class QuizSubmitRequest(BaseModel):
    answers: List[int]  # indices of selected answers
