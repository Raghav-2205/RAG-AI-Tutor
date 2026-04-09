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

from datetime import datetime, timezone
from typing import Optional, List, Dict, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.utils.db import get_db, db_manager
from backend.api.auth import get_current_user
from backend.rag_tutor import answer_query_with_rag, retrieve_chunks_for_streaming
from backend.utils.helpers import doc_to_dict
from backend.core.feedback_analyzer import FeedbackAnalyzer
from backend.core.llm_interface import llm_client, SOCRATIC_SYSTEM_PROMPT
import logging
import uuid
import json
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


UTC_MIN = datetime.min.replace(tzinfo=timezone.utc)


# ===== REQUEST/RESPONSE MODELS =====

class ChatRequest(BaseModel):
    message: str
    subject: Optional[str] = "general"
    chat_id: Optional[str] = None  # Optional chat session ID
    class_id: Optional[str] = None  # NEW: link to LMS class


class ChatResponse(BaseModel):
    answer: str
    citations: List[int]
    chat_id: str  # Always return chat_id
    session_id: Optional[str] = None  # For backward compatibility
    validation: Optional[Dict] = None # Validation summary
    source_mode: Optional[str] = None  # NEW: Track answer source (document/knowledge_base/gemini_fallback)


class ChatSessionSummary(BaseModel):
    chat_id: str
    title: str
    updated_at: str
    message_count: int
    document_id: Optional[str] = None   # NEW
    document_name: Optional[str] = None # NEW


class ChatSessionDetail(BaseModel):
    chat_id: str
    title: str
    subject: str
    messages: List[Dict]
    created_at: str
    updated_at: str
    document_id: Optional[str] = None   # NEW
    document_name: Optional[str] = None # NEW


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
            "class_id": request.class_id,  # NEW: store LMS class context
            "title": generate_title(request.message),
            "messages": [],
            "created_at": _utcnow(),
            "updated_at": _utcnow()
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
    
    doc_ids = session.get("document_ids", [])
    if session.get("document_id") and session.get("document_id") not in doc_ids:
        doc_ids.append(session.get("document_id"))
    file_count = session.get("file_count", len(doc_ids))

    # --- STEP 4: CALL RAG PIPELINE (ASYNC) ---
    rag_result = await answer_query_with_rag(
        user_id=user_id,
        query=request.message,
        subject=request.subject,
        history=chat_history,
        feedback_context=feedback_context,
        strict_mode=False,
        document_ids=doc_ids,  # PASS DOCUMENT SCOPE
        file_count=file_count,
        chat_id=chat_id
    )
    
    # --- STEP 4.5: VALIDATE ANSWER (Handled in rag_tutor) ---
    validation_data = rag_result.get("validation")
    
    regenerated = False
    
    # REGENERATION LOGIC (ASYNC)
    hallucination_rate = validation_data.get("hallucination_rate", 0.0) if validation_data else 0.0
    
    if hallucination_rate > 0.15:
        logger.warning(f"[VALIDATION] High hallucination rate ({hallucination_rate:.2f}). Regenerating...")
        
        # Regenerate with strict mode
        rag_result = await answer_query_with_rag(
            user_id=user_id,
            query=request.message,
            subject=request.subject,
            history=chat_history,
            feedback_context=feedback_context,
            strict_mode=True,
            document_ids=doc_ids,
            file_count=file_count,
            chat_id=chat_id
        )
        validation_data = rag_result.get("validation")
        regenerated = True
        
        # Optional: Validate again? 
        # For performance, we might skip or just log. 
        # Let's trust strict mode for this iteration to avoid double latency.
    
    # --- STEP 5: APPEND MESSAGES TO SESSION ---
    user_message = {
        "role": "user",
        "content": request.message,
        "timestamp": _utcnow()
    }
    
    assistant_message = {
        "role": "assistant",
        "content": rag_result["answer"],
        "timestamp": _utcnow(),
        "citations": rag_result["citations"],
        "chunks": rag_result.get("chunks", []),
        "feedback_adjusted": feedback_adjusted,
        "validation_result": validation_data, # Store validation metadata
        "regenerated": regenerated
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
                "updated_at": _utcnow()
            }
        }
    )
    
    # --- STEP 6: LOG FEEDBACK INFLUENCE + ACTIVITY LOG ---
    if feedback_adjusted:
        await feedback_analyzer.log_feedback_influence(
            user_id=user_id,
            reference_id=chat_id,
            adjustment_type="prompt_adjustment",
            details={"reason": reason, "subject": request.subject}
        )

    # Log chat interaction as activity (feeds engagement analytics)
    try:
        await db.activity_logs.insert_one({
            "user_id": user_id,
            "category": "chat",
            "class_id": session.get("class_id") or request.class_id,
            "date": _utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "data": {"subject": request.subject, "chat_id": chat_id}
        })
    except Exception:
        pass  # Non-critical
    
    response = ChatResponse(
        answer=rag_result["answer"],
        citations=rag_result["citations"],
        chat_id=chat_id,
        session_id=chat_id,  # For backward compatibility
        validation=validation_data,
        source_mode=rag_result.get("source_mode")  # NEW: Pass source mode to frontend
    )
    
    # Helper to attach validation info to response if needed by frontend
    # For now, frontend only sees answer/citations. 
    # If we want to show validation status, we need to update ChatResponse model.
    # The user didn't explicitly ask for frontend change on ChatResponse, but "Return warning to user".
    # I'll prepend the warning to the answer if it was rejected/regenerated? 
    # "System Note: This answer was verified/regenerated..."
    # Or just let the dashboard show it.
    # I will stick to returning standard response but maybe log it.
    
    return response


# ===== STREAMING ENDPOINT =====

@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    ChatGPT-style streaming chat endpoint using Server-Sent Events (SSE).

    SSE event types:
      {"type": "meta",  "chat_id": "...", "citations": [...], "chunks": [...]}  <- sent first
      {"type": "token", "text": "..."}   <- one per LLM token chunk
      {"type": "done"}                   <- signals end of stream
      {"type": "error", "message": ".."}  <- on failure
    """
    user_id = str(current_user["_id"])
    chat_id = request.chat_id

    # --- STEP 1: GET OR CREATE CHAT SESSION ---
    if chat_id:
        session = await db.chat_sessions.find_one({"chat_id": chat_id, "user_id": user_id})
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
    else:
        chat_id = str(uuid.uuid4())
        session = {
            "chat_id": chat_id,
            "user_id": user_id,
            "subject": request.subject,
            "title": generate_title(request.message),
            "messages": [],
            "created_at": _utcnow(),
            "updated_at": _utcnow()
        }
        await db.chat_sessions.insert_one(session)

    # --- STEP 2: BUILD CHAT HISTORY ---
    chat_history = [
        {"role": m["role"], "content": m["content"]}
        for m in session.get("messages", [])
    ]

    # --- STEP 3: FEEDBACK CONTEXT ---
    feedback_analyzer = FeedbackAnalyzer(db)
    should_adjust, reason = await feedback_analyzer.should_adjust_prompt(user_id)
    feedback_context = ""
    feedback_adjusted = False
    if should_adjust:
        feedback_context = await feedback_analyzer.get_adaptive_context(user_id)
        feedback_adjusted = True

    doc_ids = session.get("document_ids", [])
    if session.get("document_id") and session.get("document_id") not in doc_ids:
        doc_ids.append(session.get("document_id"))
    file_count = session.get("file_count", len(doc_ids))

    # --- STEP 4: RAG RETRIEVAL (get chunks & build prompt, no LLM call yet) ---
    retrieval_result = await retrieve_chunks_for_streaming(
        user_id=user_id,
        query=request.message,
        subject=request.subject,
        history=chat_history,
        feedback_context=feedback_context,
        document_ids=doc_ids,
        file_count=file_count,
        chat_id=chat_id
    )

    chunks = retrieval_result["chunks"]
    prompt = retrieval_result["prompt"]
    system_prompt = retrieval_result["system_prompt"]
    citations = retrieval_result["citations"]
    source_mode = retrieval_result["source_mode"]
    graph_context = retrieval_result.get("graph_context", "")


    async def event_generator() -> AsyncGenerator[str, None]:
        # Send metadata first so frontend can set chat_id immediately
        meta_event = json.dumps({
            "type": "meta",
            "chat_id": chat_id,
            "citations": citations,
            "chunks": chunks,
            "source_mode": source_mode
        })
        yield f"data: {meta_event}\n\n"

        full_answer = ""
        validation_payload = None
        try:
            async for token in llm_client.async_stream_generate(
                prompt=prompt,
                system_prompt=system_prompt
            ):
                full_answer += token
                token_event = json.dumps({"type": "token", "text": token})
                yield f"data: {token_event}\n\n"

            # --- DONE: send immediately so UI renders the response ---
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            # --- VALIDATION: runs AFTER done while stream is still open ---
            # The SSE connection stays open until the generator returns,
            # so the frontend will still receive the validation event.
            if full_answer and chunks:
                try:
                    from backend.core.evaluation.validator import ValidationEngine
                    if db_manager.db is not None:
                        validator = ValidationEngine(db_manager.db)
                        validation_result = await validator.validate_answer(
                            question=request.message,
                            answer=full_answer,
                            retrieved_chunks=chunks,
                            user_id=user_id,
                            subject=request.subject or "general",
                            chat_id=chat_id,
                            graph_context=graph_context
                        )

                        if validation_result:
                            val_dict = validation_result.model_dump()
                            if "_id" in val_dict and val_dict["_id"] is not None:
                                val_dict["_id"] = str(val_dict["_id"])
                            # Convert all datetime fields to ISO format
                            for k, v in val_dict.items():
                                if hasattr(v, "isoformat"):
                                    val_dict[k] = v.isoformat()
                            validation_payload = val_dict
                            validation_event = json.dumps({
                                "type": "validation",
                                "data": val_dict
                            })
                            yield f"data: {validation_event}\n\n"
                            logger.info(f"[STREAM] Validation emitted for session {chat_id}")
                except Exception as ve:
                    logger.warning(f"[STREAM] Validation skipped: {ve}")

        except Exception as e:
            logger.error(f"[STREAM] Generation error: {e}")
            error_event = json.dumps({"type": "error", "message": str(e)})
            yield f"data: {error_event}\n\n"

        finally:
            # Save complete conversation to MongoDB after streaming
            if full_answer:
                user_msg = {
                    "role": "user",
                    "content": request.message,
                    "timestamp": _utcnow()
                }
                assistant_msg = {
                    "role": "assistant",
                    "content": full_answer,
                    "timestamp": _utcnow(),
                    "citations": citations,
                    "chunks": chunks,
                    "validation_result": validation_payload,
                    "feedback_adjusted": feedback_adjusted,
                    "source_mode": source_mode
                }
                await db.chat_sessions.update_one(
                    {"chat_id": chat_id},
                    {
                        "$push": {"messages": {"$each": [user_msg, assistant_msg]}},
                        "$set": {"updated_at": _utcnow()}
                    }
                )
                logger.info(f"[STREAM] Saved answer for session {chat_id}")

                if feedback_adjusted:
                    await feedback_analyzer.log_feedback_influence(
                        user_id=user_id,
                        reference_id=chat_id,
                        adjustment_type="prompt_adjustment",
                        details={"reason": reason, "subject": request.subject}
                    )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
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
            message_count=len(s.get("messages", [])),
            document_id=s.get("document_id"),       # NEW
            document_name=s.get("document_name")    # NEW
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
        updated_at=session["updated_at"].isoformat(),
        document_id=session.get("document_id"),       # NEW
        document_name=session.get("document_name")    # NEW
    )


@router.delete("/sessions/{chat_id}", status_code=204)
async def delete_chat_session(
    chat_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Delete a chat session.
    
    - Verifies user owns the chat
    - Removes chat document from MongoDB
    - Returns 204 No Content on success
    - Returns 404 if chat not found or unauthorized
    """
    user_id = str(current_user["_id"])
    
    # Delete the chat session
    result = await db.chat_sessions.delete_one({
        "chat_id": chat_id,
        "user_id": user_id
    })
    
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Chat session not found or you don't have permission to delete it"
        )
    
    logger.info(f"[DELETE] Chat session {chat_id} deleted by user {user_id}")
    
    # Return 204 No Content (successful deletion)
    from fastapi.responses import Response
    return Response(status_code=204)
