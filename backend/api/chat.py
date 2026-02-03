# backend/api/chat.py
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.rag_tutor import answer_query_with_rag
from backend.utils.helpers import doc_to_dict
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class ChatRequest(BaseModel):
    message: str
    subject: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    citations: List[int]
    session_id: Optional[str] = None

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    user_id = str(current_user["_id"])
    logger.info(f"User {user_id} asked: {request.message[:50]}...")

    # CALL RAG PIPELINE
    rag_result = answer_query_with_rag(
        user_id=user_id,
        query=request.message,
        subject=request.subject
    )

    # Save session to MongoDB
    session_doc = {
        "user_id": current_user["_id"],
        "subject": request.subject,
        "message": request.message,
        "answer": rag_result["answer"],
        "citations": rag_result["citations"],
        "created_at": datetime.utcnow()
    }
    
    result = await db.chats.insert_one(session_doc)
    
    return ChatResponse(
        answer=rag_result["answer"],
        citations=rag_result["citations"],
        session_id=str(result.inserted_id)
    )

@router.get("/sessions")
async def list_sessions(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    sessions = await db.chats.find(
        {"user_id": current_user["_id"]}
    ).sort("created_at", -1).limit(50).to_list(length=50)
    
    return [doc_to_dict(s) for s in sessions]