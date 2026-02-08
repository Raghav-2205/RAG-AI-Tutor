# backend/core/llm_interface.py

"""
Gemini LLM interface with Socratic tutor system prompt.
Used by: rag_tutor.py, quiz_generator.py

UPDATED: Uses Direct REST API via requests to bypass google-generativeai SDK issues on Python 3.14
"""

from typing import Dict, Any, Optional
from backend.config import settings
import logging
import requests
import json

logger = logging.getLogger(__name__)

# Global flag - we strictly use REST now
GENAI_AVAILABLE = False 

class LLMInterface:
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name
        self.api_key = settings.gemini_api_key
        # Base URL for Gemini 
        # Note: model_name should NOT include 'models/' prefix if we add it here, 
        # but the list returned 'models/gemini-2.5-flash'. 
        # The endpoint expects /models/{model_id}:generateContent
        # If input is 'gemini-2.5-flash', we construct .../models/gemini-2.5-flash...
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"

    def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """Generate text using direct REST API to avoid SDK issues"""
        return self._send_request(prompt, system_prompt, temperature)

    def generate_with_image(
        self, 
        prompt: str, 
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        temperature: float = 0.7
    ) -> str:
        """Generate text from image using direct REST API"""
        import base64
        b64_data = base64.b64encode(image_bytes).decode('utf-8')
        
        parts = [
            {"text": prompt},
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": b64_data
                }
            }
        ]
        return self._send_request(parts=parts, temperature=temperature)

    def _send_request(
        self, 
        prompt: str = None, 
        system_prompt: str = None, 
        temperature: float = 0.7,
        parts: list = None
    ) -> str:
        if not self.api_key:
             return "Error: No Gemini API Key provided in settings."

        try:
            # Construct payload
            if parts is None:
                # Text-only mode
                full_prompt = prompt
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                parts = [{"text": full_prompt}]
            
            payload = {
                "contents": [{
                    "parts": parts
                }],
                "generationConfig": {
                    "temperature": temperature
                }
            }

            headers = {'Content-Type': 'application/json'}
            
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            
            if response.status_code != 200:
                logger.error(f"Gemini API Error {response.status_code}: {response.text}")
                return f"LLM API Error: {response.status_code} - {response.text}"
                
            data = response.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError) as e:
                logger.error(f"Failed to parse Gemini response: {data}")
                return "Error parsing LLM response."

        except Exception as e:
            logger.error(f"LLM Request Failed: {e}")
            return f"LLM Request Failed: {str(e)}"


# Global singleton
_llm_client = None


def get_llm_client() -> LLMInterface:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMInterface()
    return _llm_client


# Socratic tutor system prompt (used by rag_tutor.py)
SOCRATIC_SYSTEM_PROMPT = """
You are an educational AI tutor helping students learn from their course materials.
- Answer questions clearly based on the provided context
- If citing specific information, mention which chunk or source it came from
- Break down complex concepts into simpler explanations
- Ask follow-up questions to deepen understanding when appropriate
- If the context doesn't contain the answer, say so honestly
- Be encouraging and supportive
"""


llm_client = get_llm_client()
