# backend/quiz_generator.py
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from backend.config import settings
from backend.vector_db import query_user_collection
from backend.core.embedding_service import embedding_service
from backend.core.llm_interface import llm_client

logger = logging.getLogger(__name__)

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
    try:
        # Query for general concepts in the subject
        query = f"Important concepts and summaries for {subject or 'general'}"
        query_vec = embedding_service.embed_text(query)
        
        # Use the wrapper function from vector_db.py
        results = query_user_collection(
            user_id=user_id,
            subject=subject,
            query_embedding=query_vec,
            top_k=5 # Grab context
        )
        
        if not results:
            context_text = "No documents found. Using general knowledge."
        else:
            context_text = "\n\n".join([r['text'] for r in results])
            
    except Exception as e:
        logger.error(f"Vector DB error in quiz gen: {e}")
        context_text = "Error retrieving documents."

    # 2. Call Gemini
    prompt = _build_quiz_prompt(context_text, num_questions, difficulty)
    
    # Use safe LLM client
    try:
        response_text = llm_client.generate(prompt)
        
        # 3. Clean and Parse JSON
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        if text.startswith("```"): # Handle ``` without json
            text = text[3:]
            
        text = text.strip()
            
        data = json.loads(text)
        questions = data.get("questions", [])
    except Exception as e:
        logger.error(f"Quiz generation failed: {e}")
        questions = [{
            "question": "We couldn't generate a quiz right now. Try again?",
            "options": ["OK", "Retry", "Check Logs", "Upload More"],
            "correct_index": 0,
            "explanation": f"AI generation error: {str(e)}"
        }]

    # 4. Return Object (Caller handles DB save)
    return {
        "user_id": user_id,
        "subject": subject,
        "difficulty": difficulty,
        "questions": questions,
        "created_at": datetime.utcnow()
    }