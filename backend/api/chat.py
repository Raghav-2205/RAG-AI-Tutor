"""
Chat API: send message, get RAG AI Tutor reply.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from backend.core.llm_interface import generate_reply
from backend.api.auth import get_current_user_id
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter(tags=["chat"])
security = HTTPBearer(auto_error=False)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[str] = Field(default=None)
    subject: Optional[str] = Field(default=None)


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    user_id: Optional[str] = Depends(get_current_user_id),
):
    """Send a message and get RAG AI Tutor reply. Auth optional."""
    # For now no RAG retrieval — just LLM. Context can be added later from vector store.
    reply = generate_reply(body.message, context=None)
    session_id = body.session_id or "default"
    return ChatResponse(reply=reply, session_id=session_id)
