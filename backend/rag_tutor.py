# backend/rag_tutor.py

from __future__ import annotations

from typing import List, Dict, Any, Optional
import textwrap
import google.generativeai as genai

from backend.config import settings
from backend.vector_db import get_vector_db
from backend.core.embedding_service import embedding_service


# Configure Gemini once
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)

RAG_MODEL_NAME = "gemini-2.5-flash"  # or another text-capable model


def _build_context(
    retrieved_chunks: List[Dict[str, Any]],
    max_chars: int = 6000,
) -> str:
    """
    Turn retrieved chunks into a single context string for the prompt.
    Keeps total length under max_chars to avoid blowing up the context window.
    """
    pieces = []
    total = 0

    for i, ch in enumerate(retrieved_chunks, start=1):
        src = ch.get("source", "unknown")
        text = ch.get("text", "")
        # label each chunk so we can cite it in answer
        block = f"[CHUNK {i} | source: {src}]\n{text}\n\n"
        if total + len(block) > max_chars:
            break
        pieces.append(block)
        total += len(block)

    return "".join(pieces)


def _build_rag_prompt(query: str, context: str) -> str:
    """
    Socratic tutoring prompt: ask Gemini to guide the student with explanations
    and cite chunks.
    """
    base = f"""
You are a **Socratic tutor** helping a student understand their course material.

Use ONLY the provided context chunks to answer the question.
If the answer is not in the context, say you don't know and suggest what the student
could review.

Guidelines:
- Ask 1–2 short guiding questions instead of just giving the final answer.
- Explain step by step in simple language.
- Reference chunks in your answer like (CHUNK 1), (CHUNK 2) where relevant.
- Do NOT invent facts that are not supported by the context.

Context:
{context}

Student question:
{query}

Tutor answer (with CHUNK references):
"""
    # remove leading indentation
    return textwrap.dedent(base).strip()


def _call_gemini(prompt: str) -> str:
    """
    Call Gemini model for the actual answer.
    """
    if not settings.gemini_api_key:
        # Fallback if no key is set – useful during local testing
        return (
            "I am configured as a RAG tutor, but no GEMINI_API_KEY is set.\n"
            "Please add your API key in the .env file to get real AI answers."
        )

    model = genai.GenerativeModel(RAG_MODEL_NAME)
    response = model.generate_content(prompt)
    return response.text.strip()


def retrieve_relevant_chunks(
    user_id: str,
    subject: Optional[str],
    query: str,
    top_k: int = 6,
) -> List[Dict[str, Any]]:
    """
    Use the vector DB + embeddings to fetch the most relevant chunks
    for this user's documents and subject.
    """
    vdb = get_vector_db()

    # 1. Embed the query
    query_vec = embedding_service.embed_text(query)

    # 2. Ask vector DB for top_k similar chunks (hybrid search inside vector_db implementation)
    results = vdb.query(
        user_id=user_id,
        subject=subject,
        query_embedding=query_vec,
        top_k=top_k,
    )

    # Each result should be a dict like:
    # {"text": ..., "source": ..., "score": ..., "chunk_id": ...}
    return results


def answer_query_with_rag(
    user_id: str,
    query: str,
    subject: Optional[str] = None,
    top_k: int = 6,
) -> Dict[str, Any]:
    """
    Main function: given a user_id, subject, and question, return:
      - answer text
      - list of citations (chunk indices)
      - the retrieved chunks (for debugging / UI)
    """

    # 1. Retrieve chunks
    chunks = retrieve_relevant_chunks(user_id, subject, query, top_k=top_k)
    if not chunks:
        return {
            "answer": (
                "I couldn't find any relevant content in your uploaded documents. "
                "Please upload course materials first and try again."
            ),
            "citations": [],
            "chunks": [],
        }

    # 2. Build context string for prompt
    context = _build_context(chunks)

    # 3. Build Socratic prompt
    prompt = _build_rag_prompt(query, context)

    # 4. Call LLM
    answer = _call_gemini(prompt)

    # 5. Build simple citation info: [1,2,...] based on chunk order
    citations = list(range(1, len(chunks) + 1))

    return {
        "answer": answer,
        "citations": citations,
        "chunks": chunks,
    }
