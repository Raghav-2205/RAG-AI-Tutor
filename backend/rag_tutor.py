import warnings
import asyncio
from typing import List, Dict, Any
from backend.config import settings
from backend.core.search_engine import search_engine
from backend.core.search_engine import search_engine
from backend.core.llm_interface import llm_client, SOCRATIC_SYSTEM_PROMPT
from backend.utils.db import db_manager
from backend.core.evaluation.validator import ValidationEngine
import logging

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

async def answer_query_with_rag(
    user_id: str, 
    query: str, 
    subject: str = None, 
    history: List = [], 
    top_k: int = None,
    feedback_context: str = "",
    strict_mode: bool = False,
    document_id: str = None  # NEW: Document Scope
):
    """
    Intelligent 3-tier query routing:
    1. Document-scoped RAG (if document_id provided)
    2. Knowledge base RAG (if no document but KB exists)
    3. Gemini fallback (if no context available)
    """
    # Use TOP_K_RETRIEVAL from settings (default 6, not 3)
    if top_k is None:
        top_k = settings.top_k_retrieval

    loop = asyncio.get_event_loop()

    # ========== TIER 1: DOCUMENT-SCOPED RAG ==========
    if document_id:
        chunks = await loop.run_in_executor(None, search_engine.search, user_id, subject, query, top_k, document_id)
        logger.info(f"[TIER 1] Document-scoped search: {len(chunks)} chunks found")
        
        if not chunks:
            # Document scope but no matches → inform user
            return {
                "answer": "I couldn't find information about that in the uploaded document.",
                "citations": [],
                "chunks": [],
                "source_mode": "document_not_found",
                "validation": None
            }
        
        # Generate RAG answer from document
        return await _generate_rag_answer(chunks, query, history, feedback_context, strict_mode, user_id, subject, source_mode="document")
    
    # ========== TIER 2: KNOWLEDGE BASE RAG ==========
    # Try to find chunks from user's uploaded documents OR system knowledge base
    chunks = await loop.run_in_executor(None, search_engine.search, user_id, subject, query, top_k, None)
    logger.info(f"[TIER 2] Knowledge base search: {len(chunks)} chunks found")
    
    if chunks:
        # Generate RAG answer from knowledge base
        return await _generate_rag_answer(chunks, query, history, feedback_context, strict_mode, user_id, subject, source_mode="knowledge_base")
    
    # ========== TIER 3: GEMINI FALLBACK ==========
    logger.info(f"[TIER 3] Gemini fallback triggered (no context available)")
    return await _generate_gemini_fallback(query, history)


async def _generate_rag_answer(chunks, query, history, feedback_context, strict_mode, user_id, subject, source_mode="document"):
    """Generate answer using RAG with validation"""
    
    # Build context from chunks
    context_parts = []
    for i, c in enumerate(chunks, 1):
        source = c.get('metadata', {}).get('source', 'Unknown')
        text = c.get('text', '')
        context_parts.append(f"[CHUNK {i}] (Source: {source})\n{text}")
    context_text = "\n\n".join(context_parts)
    
    # Build history context
    history_text = ""
    if history:
         history_text = "Chat History:\n" + "\n".join([f"{h['role']}: {h['content']}" for h in history[-4:]]) + "\n\n"

    prompt = f"""{history_text}Use the following course materials to answer the question. Cite specific chunks when referencing information.

{context_text}

Student Question: {query}

Provide a helpful, educational answer based on the materials above:"""

    # Generate with adaptive system prompt
    try:
        adaptive_prompt = SOCRATIC_SYSTEM_PROMPT
        if feedback_context:
            adaptive_prompt += "\n" + feedback_context
            
        if strict_mode:
            adaptive_prompt += "\nCRITICAL: STRICT MODE ENABLED. You must ONLY use the provided chunks. Do NOT use outside knowledge."
        
        response_text = await llm_client.async_generate(prompt, system_prompt=adaptive_prompt)
        
        # Validate Answer (only for RAG answers)
        validation_result = None
        try:
            if db_manager.db is not None:
                validator = ValidationEngine(db_manager.db)
                validation_result = await validator.validate_answer(
                    question=query,
                    answer=response_text,
                    retrieved_chunks=chunks,
                    user_id=user_id,
                    subject=subject or "general"
                )
        except Exception as e:
            logger.error(f"Validation failed: {e}")

        return {
            "answer": response_text,
            "citations": list(range(1, len(chunks)+1)),
            "chunks": chunks,
            "validation": validation_result.dict() if validation_result else None,
            "source_mode": source_mode  # NEW: Track source
        }
    except Exception as e:
        logger.error(f"RAG Generation Error: {e}")
        return {
            "answer": f"I encountered an error generating the answer.",
            "citations": [],
            "chunks": [],
            "source_mode": "error"
        }


async def _generate_gemini_fallback(query, history):
    """Generate answer using Gemini without RAG (fallback mode)"""
    
    # Build history context
    history_text = ""
    if history:
        history_text = "Previous conversation:\n" + "\n".join([f"{h['role']}: {h['content']}" for h in history[-4:]]) + "\n\n"
    
    prompt = f"""{history_text}You are a helpful AI tutor. A student has asked you a question.

Student Question: {query}

Provide a comprehensive, student-friendly educational explanation. Break down complex concepts, use examples where helpful, and ensure the student understands the topic."""
    
    try:
        response_text = await llm_client.async_generate(
            prompt, 
            system_prompt="You are a helpful AI tutor. Answer questions clearly and educationally. Be encouraging and supportive."
        )
        
        return {
            "answer": response_text,
            "citations": [],
            "chunks": [],
            "validation": None,  # Skip validation for Gemini fallback
            "source_mode": "gemini_fallback"  # NEW: Track fallback source
        }
    except Exception as e:
        logger.error(f"Gemini Fallback Error: {e}")
        return {
            "answer": "I'm having trouble generating a response right now. Please try again or upload a document for more specific help.",
            "citations": [],
            "chunks": [],
            "source_mode": "error"
        }


async def retrieve_chunks_for_streaming(
    user_id: str,
    query: str,
    subject: str = None,
    history: List = [],
    top_k: int = None,
    feedback_context: str = "",
    document_id: str = None
) -> dict:
    """
    Run RAG retrieval pipeline WITHOUT calling the LLM.
    Returns chunks, the constructed prompt, and system prompt for the streaming endpoint,
    which will call the LLM separately and stream tokens.
    """
    # Use TOP_K_RETRIEVAL from settings (default 6, not 3)
    if top_k is None:
        top_k = settings.top_k_retrieval

    loop = asyncio.get_event_loop()

    # --- RETRIEVAL ---
    if document_id:
        chunks = await loop.run_in_executor(None, search_engine.search, user_id, subject, query, top_k, document_id)
        source_mode = "document"
    else:
        chunks = await loop.run_in_executor(None, search_engine.search, user_id, subject, query, top_k, None)
        source_mode = "knowledge_base" if chunks else "gemini_fallback"

    # --- PROMPT CONSTRUCTION ---
    if chunks:
        context_parts = []
        for i, c in enumerate(chunks, 1):
            src = c.get("metadata", {}).get("source", "Unknown")
            text = c.get("text", "")
            context_parts.append(f"[CHUNK {i}] (Source: {src})\n{text}")
        context_text = "\n\n".join(context_parts)

        history_text = ""
        if history:
            history_text = "Chat History:\n" + "\n".join(
                [f"{h['role']}: {h['content']}" for h in history[-4:]]
            ) + "\n\n"

        prompt = (
            f"{history_text}Use the following course materials to answer the question. "
            f"Cite specific chunks when referencing information.\n\n"
            f"{context_text}\n\nStudent Question: {query}\n\n"
            f"Provide a helpful, educational answer based on the materials above:"
        )

        adaptive_prompt = SOCRATIC_SYSTEM_PROMPT
        if feedback_context:
            adaptive_prompt += "\n" + feedback_context

        citations = list(range(1, len(chunks) + 1))
    else:
        # Gemini fallback prompt
        history_text = ""
        if history:
            history_text = "Previous conversation:\n" + "\n".join(
                [f"{h['role']}: {h['content']}" for h in history[-4:]]
            ) + "\n\n"

        prompt = (
            f"{history_text}You are a helpful AI tutor. A student has asked you a question.\n\n"
            f"Student Question: {query}\n\n"
            f"Provide a comprehensive, student-friendly educational explanation."
        )
        adaptive_prompt = "You are a helpful AI tutor. Answer questions clearly and educationally."
        citations = []

    return {
        "chunks": chunks,
        "prompt": prompt,
        "system_prompt": adaptive_prompt,
        "citations": citations,
        "source_mode": source_mode
    }