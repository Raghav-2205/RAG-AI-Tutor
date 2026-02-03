# backend/rag_tutor.py
from typing import List, Dict, Any, Optional
import textwrap
import google.generativeai as genai
from backend.config import settings
from backend.vector_db import get_vector_db
from backend.core.embedding_service import embedding_service

# Configure Gemini
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)

RAG_MODEL_NAME = "gemini-1.5-flash"  # Or your preferred model

def build_context(retrieved_chunks: List[Dict[str, Any]], max_chars: int = 6000) -> str:
    pieces = []
    total = 0
    for i, ch in enumerate(retrieved_chunks, start=1):
        src = ch.get("source", "unknown")
        text = ch.get("text", "")
        # Label chunk for citation
        block = f"[CHUNK {i} source: {src}]\n{text}\n\n"
        if total + len(block) > max_chars:
            break
        pieces.append(block)
        total += len(block)
    return "".join(pieces)

def _build_rag_prompt(query: str, context: str) -> str:
    base = f"""
    You are a **Socratic tutor** helping a student understand their course material.
    Use ONLY the provided context chunks to answer the question.
    If the answer is not in the context, say you don't know and suggest what the student could review.

    Guidelines:
    - Ask 1-2 short guiding questions instead of just giving the final answer immediately.
    - Explain step by step in simple language.
    - Reference chunks in your answer like (CHUNK 1), (CHUNK 2) where relevant.
    - Do NOT invent facts that are not supported by the context.

    Context:
    {context}

    Student question:
    {query}

    Tutor answer (with CHUNK references):
    """
    return textwrap.dedent(base).strip()

def _call_gemini(prompt: str) -> str:
    if not settings.gemini_api_key:
        return "I am configured as a RAG tutor, but no GEMINI API KEY is set. Please check your .env file."
    
    model = genai.GenerativeModel(RAG_MODEL_NAME)
    response = model.generate_content(prompt)
    return response.text.strip()

def retrieve_relevant_chunks(user_id: str, subject: Optional[str], query: str, top_k: int = 6) -> List[Dict[str, Any]]:
    vdb = get_vector_db()
    # 1. Embed query
    query_vec = embedding_service.embed_text(query)
    # 2. Query Vector DB
    results = vdb.query(
        user_id=user_id,
        subject=subject,
        query_embedding=query_vec,
        top_k=top_k
    )
    return results

def answer_query_with_rag(user_id: str, query: str, subject: Optional[str] = None, top_k: int = 6) -> Dict[str, Any]:
    # 1. Retrieve
    chunks = retrieve_relevant_chunks(user_id, subject, query, top_k=top_k)
    
    if not chunks:
        return {
            "answer": "I couldn't find any relevant content in your uploaded documents. Please upload course materials first.",
            "citations": [],
            "chunks": []
        }

    # 2. Build Context
    context = build_context(chunks)
    
    # 3. Build Prompt
    prompt = _build_rag_prompt(query, context)
    
    # 4. Generate Answer
    answer = _call_gemini(prompt)
    
    # 5. Simple citation indices
    citations = list(range(1, len(chunks) + 1))
    
    return {
        "answer": answer,
        "citations": citations,
        "chunks": chunks
    }