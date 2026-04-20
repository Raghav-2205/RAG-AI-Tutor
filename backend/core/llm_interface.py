# backend/core/llm_interface.py

"""
Gemini LLM interface with Socratic tutor system prompt.
Used by: rag_tutor.py, quiz_generator.py

UPDATED: Uses Direct REST API via requests to bypass google-generativeai SDK issues on Python 3.14
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Optional

import httpx
import requests

from backend.config import settings

logger = logging.getLogger(__name__)

# Global flag - we strictly use REST now
GENAI_AVAILABLE = False
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
FALLBACK_MODEL_CANDIDATES = ("gemini-2.5-flash", "gemini-2.0-flash")


class LLMInterface:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.llm_model
        self.api_key = settings.gemini_api_key
        self.max_retries = 2
        self.base_retry_delay = 1.0
        self.model_candidates = self._build_model_candidates(self.model_name)

    def _retry_delay_seconds(self, attempt: int) -> float:
        return self.base_retry_delay * (2 ** attempt)

    @staticmethod
    def _build_model_candidates(model_name: Optional[str]) -> list[str]:
        ordered = [model_name or settings.llm_model, *FALLBACK_MODEL_CANDIDATES]
        candidates: list[str] = []
        for candidate in ordered:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        return candidates

    def _build_api_url(self, model_name: str) -> str:
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={self.api_key}"
        )

    def _build_stream_url(self, model_name: str) -> str:
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:streamGenerateContent?alt=sse&key={self.api_key}"
        )

    @staticmethod
    def _is_missing_model_response(status_code: int, body: str) -> bool:
        return status_code == 404 and "models/" in str(body or "").lower()

    @staticmethod
    def _should_retry_status(status_code: int) -> bool:
        return status_code in RETRYABLE_STATUS_CODES

    @staticmethod
    def _build_payload(parts: list, temperature: float) -> dict:
        return {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": settings.max_tokens,
            },
        }

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("Failed to parse Gemini response: %s", data)
            raise ValueError("Error parsing LLM response.") from exc

    def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        """Generate text using direct REST API to avoid SDK issues"""
        return self._send_request(prompt, system_prompt, settings.temperature if temperature is None else temperature)

    async def async_generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        """ASYNCHRONOUS generation using httpx"""
        return await self._send_request_async(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=settings.temperature if temperature is None else temperature,
        )

    def generate_with_image(
        self, 
        prompt: str, 
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        temperature: Optional[float] = None
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
        return self._send_request(parts=parts, temperature=settings.temperature if temperature is None else temperature)

    def _send_request(
        self, 
        prompt: str = None, 
        system_prompt: str = None, 
        temperature: Optional[float] = None,
        parts: list = None
    ) -> str:
        if not self.api_key:
            return "Error: No Gemini API Key provided in settings."

        try:
            if parts is None:
                full_prompt = prompt
                if system_prompt:
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                parts = [{"text": full_prompt}]

            payload = self._build_payload(parts, settings.temperature if temperature is None else temperature)

            headers = {'Content-Type': 'application/json'}

            last_error: Optional[str] = None
            candidate_models = self._build_model_candidates(self.model_name)
            for model_name in candidate_models:
                api_url = self._build_api_url(model_name)
                for attempt in range(self.max_retries + 1):
                    try:
                        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
                        if response.status_code == 200:
                            data = response.json()
                            logger.info("Gemini generate using model: %s", model_name)
                            self.model_name = model_name
                            self.model_candidates = self._build_model_candidates(self.model_name)
                            return self._extract_text(data)

                        last_error = f"LLM API Error: {response.status_code} - {response.text}"
                        logger.error("Gemini API Error %s for %s: %s", response.status_code, model_name, response.text)
                        if self._is_missing_model_response(response.status_code, response.text):
                            logger.warning("Configured Gemini model '%s' is unavailable. Trying fallback model.", model_name)
                            break
                        if attempt < self.max_retries and self._should_retry_status(response.status_code):
                            time.sleep(self._retry_delay_seconds(attempt))
                            continue
                        if self._should_retry_status(response.status_code):
                            logger.warning(
                                "Retryable Gemini error persisted for %s after %s attempts. Trying next fallback model if available.",
                                model_name,
                                attempt + 1,
                            )
                            break
                        return last_error
                    except requests.RequestException as exc:
                        last_error = f"LLM Request Failed: {exc}"
                        logger.warning("LLM request attempt %s failed for %s: %s", attempt + 1, model_name, exc)
                        if attempt < self.max_retries:
                            time.sleep(self._retry_delay_seconds(attempt))
                            continue
                        break
                    except ValueError as exc:
                        return str(exc)

            return last_error or "LLM Request Failed: Unknown error"

        except Exception as exc:
            logger.error("LLM Request Failed: %s", exc)
            return f"LLM Request Failed: {str(exc)}"

    async def _send_request_async(
        self, 
        prompt: str = None, 
        system_prompt: str = None, 
        temperature: Optional[float] = None,
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

            payload = self._build_payload(parts, settings.temperature if temperature is None else temperature)
            last_error: Optional[str] = None

            candidate_models = self._build_model_candidates(self.model_name)
            for model_name in candidate_models:
                api_url = self._build_api_url(model_name)
                for attempt in range(self.max_retries + 1):
                    try:
                        async with httpx.AsyncClient(timeout=60.0) as client:
                            response = await client.post(api_url, json=payload)

                        if response.status_code == 200:
                            data = response.json()
                            logger.info("Gemini async generate using model: %s", model_name)
                            self.model_name = model_name
                            self.model_candidates = self._build_model_candidates(self.model_name)
                            return self._extract_text(data)

                        last_error = f"LLM API Error: {response.status_code}"
                        logger.error("Gemini API Async Error %s for %s: %s", response.status_code, model_name, response.text)
                        if self._is_missing_model_response(response.status_code, response.text):
                            logger.warning("Configured Gemini model '%s' is unavailable. Trying fallback model.", model_name)
                            break
                        if attempt < self.max_retries and self._should_retry_status(response.status_code):
                            await asyncio.sleep(self._retry_delay_seconds(attempt))
                            continue
                        if self._should_retry_status(response.status_code):
                            logger.warning(
                                "Retryable async Gemini error persisted for %s after %s attempts. Trying next fallback model if available.",
                                model_name,
                                attempt + 1,
                            )
                            break
                        return last_error
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        last_error = f"LLM Async Request Failed: {exc}"
                        logger.warning("LLM async attempt %s failed for %s: %s", attempt + 1, model_name, exc)
                        if attempt < self.max_retries:
                            await asyncio.sleep(self._retry_delay_seconds(attempt))
                            continue
                        break
                    except ValueError as exc:
                        return str(exc)

            return last_error or "LLM Async Request Failed: Unknown error"
        except Exception as exc:
            logger.error("LLM Async Request Failed: %s", exc)
            return f"LLM Async Request Failed: {str(exc)}"

    async def async_stream_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
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
                "generationConfig": {
                    "temperature": settings.temperature if temperature is None else temperature,
                    "maxOutputTokens": settings.max_tokens,
                },
            }

            candidate_models = self._build_model_candidates(self.model_name)
            for model_name in candidate_models:
                stream_url = self._build_stream_url(model_name)
                logged_stream_model = False
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST",
                        stream_url,
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    ) as response:
                        if response.status_code != 200:
                            error_body = await response.aread()
                            logger.error("Gemini Stream Error %s for %s: %s", response.status_code, model_name, error_body)
                            if self._is_missing_model_response(response.status_code, error_body.decode(errors="ignore")):
                                logger.warning("Configured Gemini stream model '%s' is unavailable. Trying fallback model.", model_name)
                                continue
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
                                        if not logged_stream_model:
                                            logger.info("Gemini stream using model: %s", model_name)
                                            logged_stream_model = True
                                        self.model_name = model_name
                                        self.model_candidates = self._build_model_candidates(self.model_name)
                                        yield text
                            except (json.JSONDecodeError, IndexError, KeyError):
                                continue
                        return

            yield "[Stream Error: model unavailable]"

        except httpx.ReadTimeout:
            logger.error("Gemini stream timed out for candidate models: %s", self._build_model_candidates(self.model_name))
            yield "\n[Response timed out]"
        except Exception as e:
            logger.error(
                "LLM Stream Failed for model candidates %s: %s (%s)",
                self._build_model_candidates(self.model_name),
                repr(e),
                type(e).__name__,
                exc_info=True,
            )
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
