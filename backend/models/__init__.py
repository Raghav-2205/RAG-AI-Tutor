# backend/models/__init__.py
"""
Pydantic models for API validation and MongoDB serialization.
"""

from .user import UserCreate, UserLogin, UserPublic, UserInDB
from .document import DocumentCreate, DocumentPublic
from .chat_history import ChatMessage, ChatSession, ChatResponse
from .feedback import FeedbackCreate, FeedbackPublic
from .quiz import QuizGenerateRequest, QuizQuestion, QuizPublic, QuizSubmitRequest

__all__ = [
    "UserCreate", "UserLogin", "UserPublic", "UserInDB",
    "DocumentCreate", "DocumentPublic", 
    "ChatMessage", "ChatSession", "ChatResponse",
    "FeedbackCreate", "FeedbackPublic",
    "QuizGenerateRequest", "QuizQuestion", "QuizPublic", "QuizSubmitRequest",
]
