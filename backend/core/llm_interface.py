# backend/core/llm_interface.py

"""
Gemini LLM interface with Socratic tutor system prompt.
Used by: rag_tutor.py, quiz_generator.py

UPDATED: Uses Direct REST API via requests to bypass google-generativeai SDK issues on Python 3.14
"""

from typing import Dict, Any, Optional, AsyncGenerator
from backend.config import settings
import logging
import requests
import httpx
import json

logger = logging.getLogger(__name__)

# Global flag - we strictly use REST now
GENAI_AVAILABLE = False 

class LLMInterface:
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        self.model_name = model_name
        self.api_key = settings.gemini_api_key
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        self.stream_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:streamGenerateContent?alt=sse&key={self.api_key}"

    def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """Generate text using direct REST API to avoid SDK issues"""
        return self._send_request(prompt, system_prompt, temperature)

    async def async_generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """ASYNCHRONOUS generation using httpx"""
        return await self._send_request_async(prompt=prompt, system_prompt=system_prompt, temperature=temperature)

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

    async def _send_request_async(
        self, 
        prompt: str = None, 
        system_prompt: str = None, 
        temperature: float = 0.7,
        parts: list = None
    ) -> str:
        if not self.api_key:
             return "Error: No Gemini API Key provided."

        try:
            if parts is None:
                full_prompt = prompt
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                parts = [{"text": full_prompt}]
            
            payload = {
                "contents": [{ "parts": parts }],
                "generationConfig": { "temperature": temperature }
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(self.api_url, json=payload, timeout=60.0)
                
            if response.status_code != 200:
                logger.error(f"Gemini API Async Error {response.status_code}: {response.text}")
                return f"LLM API Error: {response.status_code}"
                
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            logger.error(f"LLM Async Request Failed: {e}")
            return f"LLM Async Request Failed: {str(e)}"

    async def async_stream_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens from Gemini via SSE using httpx.
        Yields text chunks as they arrive from the model.
        """
        if not self.api_key:
            yield "[Error: No Gemini API Key]"
            return

        try:
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"

            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": temperature}
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    self.stream_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        logger.error(f"Gemini Stream Error {response.status_code}: {error_body}")
                        yield f"[Stream Error: {response.status_code}]"
                        return

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            for part in parts:
                                text = part.get("text", "")
                                if text:
                                    yield text
                        except (json.JSONDecodeError, IndexError, KeyError):
                            # Skip malformed chunks
                            continue

        except httpx.ReadTimeout:
            logger.error("Gemini stream timed out")
            yield "\n[Response timed out]"
        except Exception as e:
            logger.error(f"LLM Stream Failed: {e}")
            yield f"\n[Stream Error: {str(e)}]"


# Global singleton
_llm_client = None


def get_llm_client() -> LLMInterface:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMInterface()
    return _llm_client


# Socratic tutor system prompt (used by rag_tutor.py)
SOCRATIC_SYSTEM_PROMPT = """
You are an educational AI tutor. Answer questions using the information from the provided context chunks.

GUIDELINES FOR HIGH-QUALITY ANSWERS:
1. Base your answer primarily on information explicitly stated in the provided chunks
2. Do NOT add conversational phrases like "That's a great question!", "Does that make sense?", or "Would you like to know more?"
3. Do NOT offer to explain further or ask follow-up questions  
4. Do NOT include pleasantries, encouragement, or engagement tactics
5. If citing information, reference the chunk number (e.g., "According to Chunk 1...")
6. If the context only partially answers the question, provide what information is available and note what's missing
7. Be direct and concise - ground your answer in the source chunks as much as possible

Your answer should be factual, well-structured, and traceable to the source material.
"""


llm_client = get_llm_client()
