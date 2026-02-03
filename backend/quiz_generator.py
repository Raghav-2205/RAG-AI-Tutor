# backend/quiz_generator.py
import json
import google.generativeai as genai
from typing import List, Dict, Any, Optional
from datetime import datetime
from backend.config import settings
from backend.vector_db import get_vector_db
from backend.core.embedding_service import embedding_service
from backend.utils.db import get_db

if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)

def _build_quiz_prompt(context: str, num_questions: int, difficulty: str) -> str:
    return f"""
    You are an expert tutor. Create a multiple-choice quiz based ONLY on the text below.
    
    Context:
    \"\"\"{context[:10000]}\"\"\"
    
    Requirements:
    1. Create exactly {num_questions} questions.
    2. Difficulty: {difficulty}.
    3. Return valid JSON only. No markdown formatting.
    
    JSON Structure:
    {{
        "questions": [
            {{
                "question": "Question text here?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_index": 0,
                "explanation": "Why A is correct."
            }}
        ]
    }}
    """

def generate_quiz_for_user(user_id: str, subject: Optional[str], num_questions: int = 5, difficulty: str = "medium") -> Dict[str, Any]:
    # 1. Get Context from Vector DB
    vdb = get_vector_db()
    # Query for general concepts in the subject
    query = f"Important concepts and summaries for {subject or 'general'}"
    query_vec = embedding_service.embed_text(query)
    
    results = vdb.query(
        user_id=user_id,
        subject=subject,
        query_embedding=query_vec,
        top_k=10 # Grab plenty of context
    )
    
    if not results:
        raise ValueError("No documents found. Please upload some files first.")
        
    context_text = "\n\n".join([r['text'] for r in results])
    
    # 2. Call Gemini
    prompt = _build_quiz_prompt(context_text, num_questions, difficulty)
    model = genai.GenerativeModel("gemini-1.5-flash") # Or gemini-1.5-pro
    response = model.generate_content(prompt)
    
    # 3. Clean and Parse JSON
    try:
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        data = json.loads(text)
        questions = data.get("questions", [])
    except Exception as e:
        print(f"Quiz generation failed: {e}")
        # Fallback dummy question if AI fails
        questions = [{
            "question": "We couldn't generate a quiz right now. Try again?",
            "options": ["OK", "Retry", "Check Logs", "Upload More"],
            "correct_index": 0,
            "explanation": "AI generation error."
        }]

    # 4. Return Object (Caller handles DB save)
    return {
        "user_id": user_id,
        "subject": subject,
        "difficulty": difficulty,
        "questions": questions,
        "created_at": datetime.utcnow()
    }