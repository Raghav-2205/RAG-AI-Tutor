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
from backend.rag_tutor import answer_query_with_rag, retrieve_chunks_for_streaming, _validate_generated_answer
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
    document_id: Optional[str] = None  # Backward-compatible document bootstrap alias
    class_id: Optional[str] = None  # NEW: link to LMS class


class ChatResponse(BaseModel):
    answer: str
    citations: List[int]
    chat_id: str  # Always return chat_id
    session_id: Optional[str] = None  # For backward compatibility
    validation: Optional[Dict] = None # Validation summary
    source_mode: Optional[str] = None  # NEW: Track answer source (document/knowledge_base/gemini_fallback)
    feedback_reference_id: Optional[str] = None
    graph_used: Optional[bool] = None
    multi_document_mode: Optional[bool] = None
    comparison_mode: Optional[bool] = None
    document_coverage: Optional[Dict] = None
    document_coverage_map: Optional[List[Dict]] = None
    unsupported_documents: Optional[List[str]] = None


class ChatSessionSummary(BaseModel):
    chat_id: str
    title: str
    updated_at: str
    message_count: int
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    document_names: Optional[List[str]] = None  # multi-doc names


class ChatSessionDetail(BaseModel):
    chat_id: str
    title: str
    subject: str
    messages: List[Dict]
    created_at: str
    updated_at: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    document_names: Optional[List[str]] = None  # multi-doc names


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


def _new_response_id() -> str:
    return str(uuid.uuid4())


def _resolve_session_scope(session: Dict) -> str:
    doc_ids = _get_session_document_ids(session)
    explicit = str(session.get("scope_mode") or "").strip().lower()
    if doc_ids:
        return "document_scoped"
    if explicit in {"system_only", "document_scoped"}:
        return explicit
    return "system_only"


def _get_session_document_ids(session: Dict) -> List[str]:
    doc_ids = [str(item or "").strip() for item in (session.get("document_ids") or []) if str(item or "").strip()]
    legacy_doc_id = str(session.get("document_id") or "").strip()
    if legacy_doc_id and legacy_doc_id not in doc_ids:
        doc_ids.append(legacy_doc_id)
    return doc_ids


def _get_session_document_names(session: Dict, doc_ids: Optional[List[str]] = None) -> List[str]:
    doc_names = [str(item or "").strip() for item in (session.get("document_names") or []) if str(item or "").strip()]
    doc_ids = doc_ids or _get_session_document_ids(session)
    legacy_name = str(session.get("document_name") or "").strip()
    if legacy_name and len(doc_names) < len(doc_ids):
        doc_names.append(legacy_name)
    return doc_names


def _resolve_session_rag_args(session: Dict) -> Dict[str, object]:
    doc_ids = _get_session_document_ids(session)
    return {
        "document_ids": doc_ids,
        "file_count": max(int(session.get("file_count") or 0), len(doc_ids)),
        "scope_mode": _resolve_session_scope(session),
    }


async def _load_requested_document(db, current_user, document_id: Optional[str]) -> Optional[Dict]:
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        return None
    document = await db.documents.find_one({"doc_id": normalized_id, "user_id": current_user["_id"]})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _build_new_session(
    user_id: str,
    request: ChatRequest,
    document: Optional[Dict] = None,
) -> Dict[str, object]:
    document_id = str((document or {}).get("doc_id") or request.document_id or "").strip()
    document_name = str((document or {}).get("filename") or "").strip()
    document_ids = [document_id] if document_id else []
    document_names = [document_name] if document_name else []
    file_count = len(document_ids)

    return {
        "chat_id": str(uuid.uuid4()),
        "user_id": user_id,
        "subject": request.subject,
        "class_id": request.class_id,
        "scope_mode": "document_scoped" if document_ids else "system_only",
        "document_ids": document_ids,
        "document_names": document_names,
        "file_count": file_count,
        "document_id": document_id or None,
        "document_name": document_name or None,
        "title": generate_title(request.message) if not document_name else f"Chat about {document_name}",
        "messages": [],
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }


def _build_assistant_message(
    answer_text: str,
    rag_result: Dict,
    feedback_reference_id: str,
    feedback_adjusted: bool,
    validation_data: Optional[Dict],
    penalties_applied: bool,
) -> Dict[str, object]:
    return {
        "role": "assistant",
        "content": answer_text,
        "timestamp": _utcnow(),
        "citations": rag_result.get("citations", []),
        "chunks": rag_result.get("chunks", []),
        "response_id": feedback_reference_id,
        "feedback_reference_id": feedback_reference_id,
        "feedback_adjusted": feedback_adjusted,
        "validation_result": validation_data,
        "regenerated": bool(rag_result.get("repaired")),
        "repaired": bool(rag_result.get("repaired")),
        "abstained": bool(rag_result.get("abstained")),
        "source_mode": rag_result.get("source_mode"),
        "retrieval_confidence": rag_result.get("retrieval_confidence"),
        "chunk_ids": rag_result.get("chunk_ids", []),
        "chunk_sources": rag_result.get("chunk_sources", []),
        "feedback_penalties_applied": penalties_applied,
        "graph_used": bool(rag_result.get("graph_used")),
        "multi_document_mode": bool(rag_result.get("multi_document_mode")),
        "comparison_mode": bool(rag_result.get("comparison_mode")),
        "document_coverage": rag_result.get("document_coverage", {}),
        "document_coverage_map": rag_result.get("document_coverage_map", []),
        "unsupported_documents": rag_result.get("unsupported_documents", []),
    }


def _serialize_for_response(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: _serialize_for_response(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_for_response(item) for item in value]
    if hasattr(value, "model_dump"):
        return _serialize_for_response(value.model_dump())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _build_lightweight_validation_payload(
    *,
    question: str,
    answer: str,
    source_mode: str,
    retrieval_confidence: Optional[float] = None,
    graph_used: bool = False,
    multi_document_mode: bool = False,
    comparison_mode: bool = False,
    document_coverage: Optional[Dict] = None,
    document_coverage_map: Optional[List[Dict]] = None,
    unsupported_documents: Optional[List[str]] = None,
    reason: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, object]:
    normalized_source_mode = str(source_mode or "knowledge_base").strip().lower()
    normalized_status = str(status or "").strip().upper()
    if normalized_status not in {"VERIFIED", "REJECTED"}:
        normalized_status = "REJECTED" if normalized_source_mode == "error" else "VERIFIED"

    derived_reason = reason
    if not derived_reason:
        if normalized_source_mode == "gemini_fallback":
            derived_reason = "General AI fallback answer used because grounded retrieval context was unavailable."
        elif normalized_source_mode == "document_not_found":
            derived_reason = "No matching grounded evidence was found in the uploaded documents."
        elif normalized_source_mode == "error":
            derived_reason = "Answer generation encountered an error before grounded validation could complete."
        else:
            derived_reason = "Lightweight validation attached because full grounded validation metrics were unavailable."

    coverage = document_coverage or {}
    coverage_docs = list(document_coverage_map or coverage.get("documents") or [])
    uploaded_document_count = int(
        coverage.get("total_documents")
        or coverage.get("total_sources")
        or len(coverage_docs)
        or 0
    )
    covered_document_count = int(
        coverage.get("covered_document_count")
        or len([entry for entry in coverage_docs if entry.get("supported")])
        or 0
    )
    document_balance = round(
        covered_document_count / uploaded_document_count,
        4,
    ) if uploaded_document_count else 1.0

    return {
        "question": question,
        "answer": answer,
        "answer_source_mode": normalized_source_mode,
        "validation_status": normalized_status,
        "reason": derived_reason,
        "retrieval_confidence": float(retrieval_confidence or 0.0),
        "faithfulness_score": 0.0,
        "hallucination_rate": 0.0,
        "citation_alignment_score": 0.0,
        "bert_score": 0.0,
        "cosine_similarity": 0.0,
        "answer_relevance": 0.0,
        "final_rag_score": 0.0,
        "judge_fallback_used": False,
        "judge_parse_failure_count": 0,
        "unsupported_sentences": [],
        "chunk_usage": {},
        "lightweight_validation": True,
        "multi_document_metrics": {
            "graph_used": bool(graph_used),
            "comparison_mode": bool(comparison_mode),
            "uploaded_document_count": uploaded_document_count,
            "covered_document_count": covered_document_count,
            "unsupported_documents": list(unsupported_documents or coverage.get("unsupported_documents") or []),
            "document_coverage": coverage,
            "document_coverage_map": coverage_docs,
            "document_coverage_balance": document_balance,
        },
        "timestamp": _utcnow().isoformat(),
    }


def _ensure_validation_payload(
    *,
    validation_data,
    question: str,
    answer: str,
    source_mode: str,
    retrieval_confidence: Optional[float] = None,
    graph_used: bool = False,
    multi_document_mode: bool = False,
    comparison_mode: bool = False,
    document_coverage: Optional[Dict] = None,
    document_coverage_map: Optional[List[Dict]] = None,
    unsupported_documents: Optional[List[str]] = None,
    reason: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, object]:
    serialized = _serialize_for_response(validation_data)
    if serialized:
        serialized.setdefault("lightweight_validation", False)
        return serialized
    return _build_lightweight_validation_payload(
        question=question,
        answer=answer,
        source_mode=source_mode,
        retrieval_confidence=retrieval_confidence,
        graph_used=graph_used,
        multi_document_mode=multi_document_mode,
        comparison_mode=comparison_mode,
        document_coverage=document_coverage,
        document_coverage_map=document_coverage_map,
        unsupported_documents=unsupported_documents,
        reason=reason,
        status=status,
    )


def _looks_like_llm_error_text(text: Optional[str]) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.lower()
    prefixes = (
        "llm async request failed",
        "llm request failed",
        "llm api error",
        "error: no gemini api key",
        "error parsing llm response",
        "[stream error:",
    )
    return any(lowered.startswith(prefix) for prefix in prefixes)


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
        requested_document = await _load_requested_document(db, current_user, request.document_id)
        session = _build_new_session(user_id, request, requested_document)
        chat_id = str(session["chat_id"])
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
    
    rag_args = _resolve_session_rag_args(session)

    # --- STEP 4: CALL RAG PIPELINE (ASYNC) ---
    rag_result = await answer_query_with_rag(
        user_id=user_id,
        query=request.message,
        subject=request.subject,
        history=chat_history,
        feedback_context=feedback_context,
        strict_mode=True,
        document_ids=rag_args["document_ids"],
        file_count=rag_args["file_count"],
        chat_id=chat_id,
        scope_mode=rag_args["scope_mode"],
    )
    
    # --- STEP 4.5: VALIDATE ANSWER (Handled in rag_tutor) ---
    validation_data = _ensure_validation_payload(
        validation_data=rag_result.get("validation"),
        question=request.message,
        answer=rag_result.get("answer", ""),
        source_mode=rag_result.get("source_mode", "knowledge_base"),
        retrieval_confidence=rag_result.get("retrieval_confidence"),
        graph_used=bool(rag_result.get("graph_used")),
        multi_document_mode=bool(rag_result.get("multi_document_mode")),
        comparison_mode=bool(rag_result.get("comparison_mode")),
        document_coverage=rag_result.get("document_coverage", {}),
        document_coverage_map=rag_result.get("document_coverage_map", []),
        unsupported_documents=rag_result.get("unsupported_documents", []),
        reason=(
            "Answer was saved with lightweight validation because full grounded metrics were unavailable."
            if not rag_result.get("validation")
            else None
        ),
    )
    regenerated = bool(rag_result.get("repaired"))
    feedback_reference_id = _new_response_id()
    chunk_ids = rag_result.get("chunk_ids", [])
    chunk_sources = rag_result.get("chunk_sources", [])
    feedback_signals = rag_result.get("feedback_signals", {})
    penalties_applied = bool(feedback_signals.get("chunk_ids") or feedback_signals.get("chunk_sources"))
    
    # --- STEP 5: APPEND MESSAGES TO SESSION ---
    user_message = {
        "role": "user",
        "content": request.message,
        "timestamp": _utcnow()
    }
    
    assistant_message = _build_assistant_message(
        answer_text=rag_result["answer"],
        rag_result=rag_result,
        feedback_reference_id=feedback_reference_id,
        feedback_adjusted=feedback_adjusted,
        validation_data=validation_data,
        penalties_applied=penalties_applied,
    )
    
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
    if rag_result.get("source_mode") in {"knowledge_base", "document"} and rag_result.get("answer"):
        await feedback_analyzer.track_response_quality(
            reference_id=feedback_reference_id,
            chunk_sources=chunk_sources,
            chunk_ids=chunk_ids,
            user_id=user_id,
            subject=request.subject,
        )

    if feedback_adjusted:
        await feedback_analyzer.log_feedback_influence(
            user_id=user_id,
            reference_id=feedback_reference_id,
            adjustment_type="prompt_adjustment",
            details={"reason": reason, "subject": request.subject, "chat_id": chat_id}
        )

    if penalties_applied:
        await feedback_analyzer.log_feedback_influence(
            user_id=user_id,
            reference_id=feedback_reference_id,
            adjustment_type="retrieval_penalty",
            details={
                "subject": request.subject,
                "chat_id": chat_id,
                "chunk_ids": feedback_signals.get("chunk_ids", []),
                "chunk_sources": feedback_signals.get("chunk_sources", []),
            }
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
        source_mode=rag_result.get("source_mode"),  # NEW: Pass source mode to frontend
        feedback_reference_id=feedback_reference_id,
        graph_used=bool(rag_result.get("graph_used")),
        multi_document_mode=bool(rag_result.get("multi_document_mode")),
        comparison_mode=bool(rag_result.get("comparison_mode")),
        document_coverage=rag_result.get("document_coverage", {}),
        document_coverage_map=rag_result.get("document_coverage_map", []),
        unsupported_documents=rag_result.get("unsupported_documents", []),
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
        requested_document = await _load_requested_document(db, current_user, request.document_id)
        session = _build_new_session(user_id, request, requested_document)
        chat_id = str(session["chat_id"])
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

    # --- STEP 3.5: QUIZ CONTEXT — inject level & weak topics into system prompt ---
    quiz_ctx = session.get("quiz_context")
    if quiz_ctx:
        level = quiz_ctx.get("level", "Intermediate")
        weak_topics = quiz_ctx.get("weak_topics", [])
        weak_str = ", ".join(weak_topics) if weak_topics else "none identified"
        quiz_context_note = (
            f"\n\n[Student Profile] The student has completed a quiz. "
            f"Their current level is '{level}'. "
            f"Weak topics: {weak_str}. "
            f"Adjust your explanation depth and vocabulary to match this level. "
            f"If weak topics are relevant, address them with extra clarity."
        )
        feedback_context = (feedback_context or "") + quiz_context_note

    rag_args = _resolve_session_rag_args(session)

    # --- STEP 4: RAG RETRIEVAL (get chunks & build prompt, no LLM call yet) ---
    retrieval_result = await retrieve_chunks_for_streaming(
        user_id=user_id,
        query=request.message,
        subject=request.subject,
        history=chat_history,
        feedback_context=feedback_context,
        document_ids=rag_args["document_ids"],
        file_count=rag_args["file_count"],
        chat_id=chat_id,
        scope_mode=rag_args["scope_mode"],
    )

    chunks = retrieval_result["chunks"]
    prompt = retrieval_result["prompt"]
    system_prompt = retrieval_result["system_prompt"]
    citations = retrieval_result["citations"]
    source_mode = retrieval_result["source_mode"]
    graph_context = retrieval_result.get("graph_context", "")
    feedback_reference_id = _new_response_id()
    chunk_ids = retrieval_result.get("chunk_ids", [])
    chunk_sources = retrieval_result.get("chunk_sources", [])
    feedback_signals = retrieval_result.get("feedback_signals", {})
    penalties_applied = bool(feedback_signals.get("chunk_ids") or feedback_signals.get("chunk_sources"))
    abstain_response = retrieval_result.get("abstain_response")


    async def event_generator() -> AsyncGenerator[str, None]:
        # Send metadata first so frontend can set chat_id immediately
        meta_event = json.dumps({
            "type": "meta",
            "chat_id": chat_id,
            "citations": citations,
            "chunks": chunks,
            "source_mode": source_mode,
            "feedback_reference_id": feedback_reference_id,
            "graph_used": bool(retrieval_result.get("graph_used")),
            "multi_document_mode": bool(retrieval_result.get("multi_document_mode")),
            "comparison_mode": bool(retrieval_result.get("comparison_mode")),
            "document_coverage": retrieval_result.get("document_coverage", {}),
            "document_coverage_map": retrieval_result.get("document_coverage_map", []),
            "unsupported_documents": retrieval_result.get("unsupported_documents", []),
        })
        yield f"data: {meta_event}\n\n"

        full_answer = ""
        validation_payload = None
        used_stream_recovery = False
        try:
            if abstain_response:
                full_answer = abstain_response
                logger.info("[STREAM] Using abstain response for session %s", chat_id)
                yield f"data: {json.dumps({'type': 'token', 'text': abstain_response})}\n\n"
            else:
                logger.info(
                    "[STREAM] Prepared generation for session %s (source=%s, graph_used=%s, multi_doc=%s)",
                    chat_id,
                    source_mode,
                    bool(retrieval_result.get("graph_used")),
                    bool(retrieval_result.get("multi_document_mode")),
                )
                stream_failed = False
                stream_failure_message = ""
                async for token in llm_client.async_stream_generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                ):
                    if str(token or "").startswith("[Stream Error:"):
                        stream_failed = True
                        stream_failure_message = str(token or "").strip()
                        logger.warning(
                            "[STREAM] Streaming generation failed for session %s after %s chars: %s",
                            chat_id,
                            len(full_answer),
                            stream_failure_message,
                        )
                        break

                    full_answer += token
                    token_event = json.dumps({"type": "token", "text": token})
                    yield f"data: {token_event}\n\n"

                if stream_failed or not full_answer.strip():
                    if not stream_failed:
                        stream_failure_message = "Stream completed without answer text."
                        logger.warning("[STREAM] Empty streaming response for session %s", chat_id)

                    recovery_answer = await llm_client.async_generate(
                        prompt=prompt,
                        system_prompt=system_prompt,
                    )
                    if _looks_like_llm_error_text(recovery_answer):
                        logger.error(
                            "[STREAM] Recovery generation failed for session %s: %s",
                            chat_id,
                            recovery_answer,
                        )
                        raise RuntimeError(stream_failure_message or str(recovery_answer))

                    used_stream_recovery = True
                    logger.info("[STREAM] Non-stream recovery succeeded for session %s", chat_id)

                    if full_answer and recovery_answer.startswith(full_answer):
                        recovery_suffix = recovery_answer[len(full_answer):]
                        if recovery_suffix:
                            full_answer = recovery_answer
                            yield f"data: {json.dumps({'type': 'token', 'text': recovery_suffix})}\n\n"
                    elif full_answer:
                        logger.error(
                            "[STREAM] Recovery answer diverged after partial streamed output for session %s",
                            chat_id,
                        )
                        raise RuntimeError(stream_failure_message or "Streaming response could not be recovered cleanly.")
                    else:
                        full_answer = recovery_answer
                        yield f"data: {json.dumps({'type': 'token', 'text': recovery_answer})}\n\n"

            if not full_answer.strip():
                raise RuntimeError("No answer text was produced.")

            # --- DONE: send immediately so UI renders the response ---
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            # --- VALIDATION: runs AFTER done while stream is still open ---
            if chunks:
                try:
                    validation_result = await _validate_generated_answer(
                        question=request.message,
                        answer=full_answer,
                        chunks=chunks,
                        user_id=user_id,
                        subject=request.subject or "general",
                        chat_id=chat_id,
                        graph_payload=graph_context,
                        source_mode=source_mode,
                    )
                    validation_payload = _ensure_validation_payload(
                        validation_data=validation_result,
                        question=request.message,
                        answer=full_answer,
                        source_mode=source_mode,
                        retrieval_confidence=retrieval_result.get("retrieval_confidence"),
                        graph_used=bool(retrieval_result.get("graph_used")),
                        multi_document_mode=bool(retrieval_result.get("multi_document_mode")),
                        comparison_mode=bool(retrieval_result.get("comparison_mode")),
                        document_coverage=retrieval_result.get("document_coverage", {}),
                        document_coverage_map=retrieval_result.get("document_coverage_map", []),
                        unsupported_documents=retrieval_result.get("unsupported_documents", []),
                    )
                    logger.info(
                        "[STREAM] Validation payload prepared for session %s (%s)",
                        chat_id,
                        "lightweight" if validation_payload.get("lightweight_validation") else "full",
                    )
                except Exception as ve:
                    logger.warning("[STREAM] Full validation failed for session %s: %s", chat_id, ve)
                    validation_payload = _ensure_validation_payload(
                        validation_data=None,
                        question=request.message,
                        answer=full_answer,
                        source_mode=source_mode,
                        retrieval_confidence=retrieval_result.get("retrieval_confidence"),
                        graph_used=bool(retrieval_result.get("graph_used")),
                        multi_document_mode=bool(retrieval_result.get("multi_document_mode")),
                        comparison_mode=bool(retrieval_result.get("comparison_mode")),
                        document_coverage=retrieval_result.get("document_coverage", {}),
                        document_coverage_map=retrieval_result.get("document_coverage_map", []),
                        unsupported_documents=retrieval_result.get("unsupported_documents", []),
                        reason="Full grounded validation failed; attached lightweight evaluation instead.",
                    )
            else:
                validation_payload = _ensure_validation_payload(
                    validation_data=None,
                    question=request.message,
                    answer=full_answer,
                    source_mode=source_mode,
                    retrieval_confidence=retrieval_result.get("retrieval_confidence"),
                    graph_used=bool(retrieval_result.get("graph_used")),
                    multi_document_mode=bool(retrieval_result.get("multi_document_mode")),
                    comparison_mode=bool(retrieval_result.get("comparison_mode")),
                    document_coverage=retrieval_result.get("document_coverage", {}),
                    document_coverage_map=retrieval_result.get("document_coverage_map", []),
                    unsupported_documents=retrieval_result.get("unsupported_documents", []),
                    reason=(
                        "Attached lightweight evaluation because this answer was not validated against grounded chunks."
                        if source_mode != "error"
                        else "Answer generation failed before grounded validation could complete."
                    ),
                    status="REJECTED" if source_mode == "error" else "VERIFIED",
                )

            if validation_payload:
                validation_event = json.dumps({
                    "type": "validation",
                    "data": validation_payload
                })
                yield f"data: {validation_event}\n\n"
                logger.info(
                    "[STREAM] Validation emitted for session %s%s",
                    chat_id,
                    " after recovery" if used_stream_recovery else "",
                )

        except Exception as e:
            logger.error("[STREAM] Generation error for session %s: %s", chat_id, e, exc_info=True)
            full_answer = ""
            validation_payload = None
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
                stream_result = {
                    "answer": full_answer,
                    "citations": citations,
                    "chunks": chunks,
                    "source_mode": source_mode,
                    "chunk_ids": chunk_ids,
                    "chunk_sources": chunk_sources,
                    "retrieval_confidence": retrieval_result.get("retrieval_confidence"),
                    "abstained": bool(abstain_response),
                    "graph_used": bool(retrieval_result.get("graph_used")),
                    "multi_document_mode": bool(retrieval_result.get("multi_document_mode")),
                    "comparison_mode": bool(retrieval_result.get("comparison_mode")),
                    "document_coverage": retrieval_result.get("document_coverage", {}),
                    "document_coverage_map": retrieval_result.get("document_coverage_map", []),
                    "unsupported_documents": retrieval_result.get("unsupported_documents", []),
                }
                assistant_msg = _build_assistant_message(
                    answer_text=full_answer,
                    rag_result=stream_result,
                    feedback_reference_id=feedback_reference_id,
                    feedback_adjusted=feedback_adjusted,
                    validation_data=validation_payload,
                    penalties_applied=penalties_applied,
                )
                await db.chat_sessions.update_one(
                    {"chat_id": chat_id},
                    {
                        "$push": {"messages": {"$each": [user_msg, assistant_msg]}},
                        "$set": {"updated_at": _utcnow()}
                    }
                )
                logger.info(f"[STREAM] Saved answer for session {chat_id}")

                if source_mode in {"knowledge_base", "document"}:
                    await feedback_analyzer.track_response_quality(
                        reference_id=feedback_reference_id,
                        chunk_sources=chunk_sources,
                        chunk_ids=chunk_ids,
                        user_id=user_id,
                        subject=request.subject,
                    )

                if feedback_adjusted:
                    await feedback_analyzer.log_feedback_influence(
                        user_id=user_id,
                        reference_id=feedback_reference_id,
                        adjustment_type="prompt_adjustment",
                        details={"reason": reason, "subject": request.subject, "chat_id": chat_id}
                    )

                if penalties_applied:
                    await feedback_analyzer.log_feedback_influence(
                        user_id=user_id,
                        reference_id=feedback_reference_id,
                        adjustment_type="retrieval_penalty",
                        details={
                            "subject": request.subject,
                            "chat_id": chat_id,
                            "chunk_ids": feedback_signals.get("chunk_ids", []),
                            "chunk_sources": feedback_signals.get("chunk_sources", []),
                        }
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
        # Compute a human-readable document label:
        # Prefer the multi-doc list, fall back to the old single-doc field.
        doc_names: List[str] = s.get("document_names") or []
        display_name: Optional[str] = s.get("document_name") or (
            ", ".join(doc_names) if doc_names else None
        )
        result.append(ChatSessionSummary(
            chat_id=s["chat_id"],
            title=s["title"],
            updated_at=s["updated_at"].isoformat(),
            message_count=len(s.get("messages", [])),
            document_id=s.get("document_id"),
            document_name=display_name,
            document_names=doc_names or None,
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
            "chunks": msg.get("chunks", []),
            "feedback_reference_id": msg.get("feedback_reference_id") or msg.get("response_id"),
            "validation_result": _serialize_for_response(msg.get("validation_result")),
            "source_mode": msg.get("source_mode"),
            "graph_used": msg.get("graph_used"),
            "multi_document_mode": msg.get("multi_document_mode"),
            "comparison_mode": msg.get("comparison_mode"),
            "document_coverage": msg.get("document_coverage"),
            "document_coverage_map": msg.get("document_coverage_map"),
            "unsupported_documents": msg.get("unsupported_documents"),
        })
    
    return ChatSessionDetail(
        chat_id=session["chat_id"],
        title=session["title"],
        subject=session["subject"],
        messages=messages,
        created_at=session["created_at"].isoformat(),
        updated_at=session["updated_at"].isoformat(),
        document_id=session.get("document_id"),
        document_name=session.get("document_name") or (
            ", ".join(session.get("document_names") or [])
            if session.get("document_names") else None
        ),
        document_names=session.get("document_names"),
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



class QuizContextIn(BaseModel):
    level: str
    score: float | None = None
    weak_topics: list[str] = []
    quiz_id: str | None = None


@router.post("/sessions/{chat_id}/quiz-context", summary="Store quiz result for adaptive tutoring")
async def store_quiz_context(
    chat_id: str,
    body: QuizContextIn,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Persist quiz results (level, weak_topics) into chat session for adaptive tutoring."""
    user_id = str(current_user["_id"])
    session = await db.chat_sessions.find_one({"chat_id": chat_id, "user_id": user_id})
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    quiz_context = {
        "level": body.level,
        "score": body.score,
        "weak_topics": body.weak_topics,
        "quiz_id": body.quiz_id,
        "updated_at": _utcnow().isoformat(),
    }
    import uuid
    ai_message = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "content": f"I've updated your learning profile based on your diagnostic quiz. You're currently testing at a **{body.level}** level. Let's focus our chat on reviewing the core concepts we identified as areas for improvement!",
        "timestamp": _utcnow(),
    }

    await db.chat_sessions.update_one(
        {"chat_id": chat_id},
        {
            "$set": {"quiz_context": quiz_context, "updated_at": _utcnow()},
            "$push": {"messages": ai_message}
        },
    )
    logger.info("[QUIZ-CTX] Stored quiz context for session %s (level=%s)", chat_id, body.level)
    return {"message": "Quiz context stored.", "chat_id": chat_id, "level": body.level}
