# backend/core/llm_interface.py

"""
Gemini LLM interface with Socratic tutor system prompt.
Used by: rag_tutor.py, quiz_generator.py
"""

import google.generativeai as genai
from typing import Dict, Any, Optional
from backend.config import settings


# Configure once globally
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)


class LLMInterface:
    def __init__(self, model_name: str = "gemini-1.5-flash"):
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)
    
    def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """Generate text with optional system prompt"""
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"LLM Error: {str(e)}"


# Global singleton
_llm_client = None


def get_llm_client() -> LLMInterface:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMInterface()
    return _llm_client


# Socratic tutor system prompt (used by rag_tutor.py)
SOCRATIC_SYSTEM_PROMPT = """
You are a Socratic tutor. Guide students with questions and explanations.
- Ask guiding questions instead of giving direct answers
- Cite sources with (CHUNK 1), (CHUNK 2) references  
- Break down concepts step-by-step
- Use simple language appropriate for the student's level
- Never invent information not in the provided context
"""


llm_client = get_llm_client()
