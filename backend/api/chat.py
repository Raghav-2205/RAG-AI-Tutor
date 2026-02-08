# backend/api/chat.py
"""
Chat API with Session-Based Storage (ChatGPT-style)

Supports:
- Chat sessions with persistent message history
- Creating new chat sessions
- Appending messages to existing sessions
- Listing all user sessions
- Retrieving full chat history for a session
"""

from datetime import datetime
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.rag_tutor import answer_query_with_rag
from backend.utils.helpers import doc_to_dict
from backend.core.feedback_analyzer import FeedbackAnalyzer
import logging
import uuid

router = APIRouter()
logger = logging.getLogger(__name__)


# ===== REQUEST/RESPONSE MODELS =====

class ChatRequest(BaseModel):
    message: str
    subject: Optional[str] = "general"
    chat_id: Optional[str] = None  # NEW: Optional chat session ID


class ChatResponse(BaseModel):
    answer: str
    citations: List[int]
    chat_id: str  # Always return chat_id
    session_id: Optional[str] = None  # For backward compatibility


class ChatSessionSummary(BaseModel):
    chat_id: str
    title: str
    updated_at: str
    message_count: int


class ChatSessionDetail(BaseModel):
    chat_id: str
    title: str
    subject: str
    messages: List[Dict]
    created_at: str
    updated_at: str


# ===== HELPER FUNCTIONS =====

def generate_title(first_message: str) -> str:
    """Generate chat title from first user message"""
    if len(first_message) <= 50:
        return first_message
    
    # Try to find first sentence
    for delimiter in ['.', '?', '!']:
        idx = first_message.find(delimiter)
        if 0 < idx <= 50:
            return first_message[:idx+1]
    
    # Truncate with ellipsis
    return first_message[:47] + "..."


# ===== ENDPOINTS =====

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Send a chat message.
    
    - If chat_id provided: Append to existing session
    - If no chat_id: Create new session
    """
    user_id = str(current_user["_id"])
    chat_id = request.chat_id
    
    # --- STEP 1: GET OR CREATE CHAT SESSION ---
    if chat_id:
        # Load existing session
        session = await db.chat_sessions.find_one({"chat_id": chat_id, "user_id": user_id})
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        logger.info(f"[CHAT] Appending to existing session {chat_id}")
    else:
        # Create new session
        chat_id = str(uuid.uuid4())
        session = {
            "chat_id": chat_id,
            "user_id": user_id,
            "subject": request.subject,
            "title": generate_title(request.message),
            "messages": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await db.chat_sessions.insert_one(session)
        logger.info(f"[CHAT] Created new session {chat_id}")
    
    # --- STEP 2: BUILD CHAT HISTORY FOR RAG ---
    chat_history = []
    for msg in session.get("messages", []):
        chat_history.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    
    # --- STEP 3: ANALYZE FEEDBACK & GET ADAPTIVE CONTEXT ---
    feedback_analyzer = FeedbackAnalyzer(db)
    should_adjust, reason = await feedback_analyzer.should_adjust_prompt(user_id)
    
    feedback_context = ""
    feedback_adjusted = False
    if should_adjust:
        feedback_context = await feedback_analyzer.get_adaptive_context(user_id)
        feedback_adjusted = True
        logger.info(f"[FEEDBACK] Adjusting prompt for user {user_id}: {reason}")
    
    # --- STEP 4: CALL RAG PIPELINE ---
    rag_result = answer_query_with_rag(
        user_id=user_id,
        query=request.message,
        subject=request.subject,
        history=chat_history,
        feedback_context=feedback_context
    )
    
    # --- STEP 5: APPEND MESSAGES TO SESSION ---
    user_message = {
        "role": "user",
        "content": request.message,
        "timestamp": datetime.utcnow()
    }
    
    assistant_message = {
        "role": "assistant",
        "content": rag_result["answer"],
        "timestamp": datetime.utcnow(),
        "citations": rag_result["citations"],
        "chunks": rag_result.get("chunks", []),
        "feedback_adjusted": feedback_adjusted
    }
    
    await db.chat_sessions.update_one(
        {"chat_id": chat_id},
        {
            "$push": {
                "messages": {
                    "$each": [user_message, assistant_message]
                }
            },
            "$set": {
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    # --- STEP 6: LOG FEEDBACK INFLUENCE ---
    if feedback_adjusted:
        await feedback_analyzer.log_feedback_influence(
            user_id=user_id,
            reference_id=chat_id,
            adjustment_type="prompt_adjustment",
            details={"reason": reason, "subject": request.subject}
        )
    
    return ChatResponse(
        answer=rag_result["answer"],
        citations=rag_result["citations"],
        chat_id=chat_id,
        session_id=chat_id  # For backward compatibility
    )


@router.get("/sessions", response_model=List[ChatSessionSummary])
async def list_sessions(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    List all chat sessions for the authenticated user.
    Sorted by most recent first.
    """
    user_id = str(current_user["_id"])
    
    sessions_cursor = db.chat_sessions.find({
        "user_id": user_id
    }).sort("updated_at", -1).limit(100)
    
    sessions = await sessions_cursor.to_list(length=100)
    
    result = []
    for s in sessions:
        result.append(ChatSessionSummary(
            chat_id=s["chat_id"],
            title=s["title"],
            updated_at=s["updated_at"].isoformat(),
            message_count=len(s.get("messages", []))
        ))
    
    return result


@router.get("/sessions/{chat_id}", response_model=ChatSessionDetail)
async def get_session(
    chat_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Get full chat history for a specific session.
    """
    user_id = str(current_user["_id"])
    
    session = await db.chat_sessions.find_one({
        "chat_id": chat_id,
        "user_id": user_id
    })
    
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    # Format messages for response
    messages = []
    for msg in session.get("messages", []):
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
            "timestamp": msg["timestamp"].isoformat(),
            "citations": msg.get("citations", []),
            "chunks": msg.get("chunks", [])
        })
    
    return ChatSessionDetail(
        chat_id=session["chat_id"],
        title=session["title"],
        subject=session["subject"],
        messages=messages,
        created_at=session["created_at"].isoformat(),
        updated_at=session["updated_at"].isoformat()
    )