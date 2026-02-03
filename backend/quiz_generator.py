# backend/quiz_generator.py

from __future__ import annotations

from typing import List, Dict, Any, Optional
import json
from datetime import datetime

import google.generativeai as genai

from backend.config import settings
from backend.vector_db import get_vector_db
from backend.core.embedding_service import embedding_service
from backend.utils.db import get_db


# Configure Gemini once
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)


QUIZ_MODEL_NAME = "gemini-2.5-flash"  # or another text-capable model name


def _build_quiz_prompt(context: str, num_questions: int, difficulty: str) -> str:
    """
    Create the prompt we send to Gemini to generate a quiz.
    We ask for strict JSON so backend can parse it easily.
    """
    return f"""
You are an expert tutor. Create a multiple-choice quiz from the context below.

Context:
\"\"\"{context}\"\"\"

Requirements:
- Use ONLY information from the context.
- Create exactly {num_questions} questions.
- Difficulty: {difficulty} (easy, medium, or hard).
- Each question must have:
  - "question": the question text
  - "options": an array of 4 answer options (strings)
  - "correct_index": the index (0-3) of the correct option
  - "explanation": a short explanation of the correct answer

Output:
Return ONLY valid JSON with this structure:

{{
  "questions": [
    {{
      "question": "...",
      "options": ["A", "B", "C", "D"],
      "correct_index": 1,
      "explanation": "..."
    }},
    ...
  ]
}}
"""


def _call_gemini_for_quiz(prompt: str) -> Dict[str, Any]:
    """
    Call Gemini with the prompt and parse the JSON response.
    """
    if not settings.gemini_api_key:
        # Fallback if no key is set
        raise RuntimeError("GEMINI_API_KEY is not set; cannot generate quiz.")

    model = genai.GenerativeModel(QUIZ_MODEL_NAME)
    response = model.generate_content(prompt)
    text = response.text.strip()

    # Sometimes models wrap JSON in ```json ... ``` – strip code fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        # remove leading "json" if present
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse quiz JSON from model: {e}\nRaw: {text[:400]}")

    return data


def _get_quiz_context_for_user(user_id: str, subject: Optional[str], limit_chunks: int = 20) -> str:
    """
    Retrieve relevant chunks from the vector DB to use as quiz context.
    For simplicity, we just grab top chunks without a specific query.
    """
    vdb = get_vector_db()

    # A very simple query: embedding of a generic phrase for the subject
    base_query = f"Important concepts for {subject or 'this course'}"
    query_vec = embedding_service.embed_text(base_query)

    results = vdb.query(
        user_id=user_id,
        subject=subject,
        query_embedding=query_vec,
        top_k=limit_chunks,
    )

    texts = [r["text"] for r in results]
    return "\n\n".join(texts)


def generate_quiz_for_user(
    user_id: str,
    subject: Optional[str],
    num_questions: int = 5,
    difficulty: str = "medium",
) -> Dict[str, Any]:
    """
    High-level function used by the quiz API.

    Steps:
    1. Get context from user's documents (via vector DB).
    2. Build prompt for Gemini.
    3. Call Gemini to generate quiz JSON.
    4. Save quiz in MongoDB.
    5. Return quiz object (with MongoDB _id) to API layer.
    """
    # 1. Get context from vector DB
    context = _get_quiz_context_for_user(user_id, subject, limit_chunks=20)
    if not context.strip():
        raise ValueError("No context available to generate quiz. Upload documents first.")

    # 2. Build prompt
    prompt = _build_quiz_prompt(context, num_questions, difficulty)

    # 3. Call Gemini
    quiz_data = _call_gemini_for_quiz(prompt)

    questions = quiz_data.get("questions", [])
    if not isinstance(questions, list) or len(questions) == 0:
        raise ValueError("Quiz generation returned empty or invalid questions array.")

    # 4. Save in MongoDB
    db = get_db()
    quizzes = db["quizzes"]

    quiz_doc = {
        "user_id": user_id,
        "subject": subject,
        "num_questions": num_questions,
        "difficulty": difficulty,
        "questions": questions,
        "created_at": datetime.utcnow(),
    }

    result = quizzes.insert_one(quiz_doc)
    quiz_doc["_id"] = result.inserted_id

    # 5. Return quiz object (convert ObjectId to string)
    quiz_doc["id"] = str(quiz_doc["_id"])
    del quiz_doc["_id"]

    return quiz_doc
