# backend/api/chat.py

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List
from bson import ObjectId

from backend.utils import get_db, get_current_user, api_logger
from backend.rag_tutor import answer_query_with_rag
from backend.utils.helpers import doc_to_dict


router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    subject: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    citations: List[int] = []
    session_id: Optional[str] = None


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, 
               db=Depends(get_db),
               current_user=Depends(get_current_user)):
    """
    MAIN RAG CHAT ENDPOINT - uses all your RAG pipeline!
    """
    user_id = str(current_user["_id"])
    api_logger.info(f"User {user_id} asked: {request.message[:50]}...")
    
    # 🔥 THIS CALLS YOUR FULL RAG PIPELINE:
    rag_result = answer_query_with_rag(
        user_id=user_id,
        query=request.message,
        subject=request.subject,
    )
    
    # Save chat session to MongoDB
    session_doc = {
        "user_id": current_user["_id"],
        "subject": request.subject,
        "message": request.message,
        "answer": rag_result["answer"],
        "citations": rag_result["citations"],
        "created_at": datetime.utcnow(),
    }
    result = db.chats.insert_one(session_doc)
    session_doc["_id"] = result.inserted_id
    
    api_logger.info(f"Chat response saved for user {user_id}")
    
    return ChatResponse(
        answer=rag_result["answer"],
        citations=rag_result["citations"],
        session_id=str(session_doc["_id"])
    )


@router.get("/sessions")
async def list_sessions(db=Depends(get_db), current_user=Depends(get_current_user)):
    """List user's chat sessions"""
    sessions = list(db.chats.find({"user_id": current_user["_id"]})
                   .sort("created_at", -1).limit(50))
    return [doc_to_dict(s) for s in sessions]
