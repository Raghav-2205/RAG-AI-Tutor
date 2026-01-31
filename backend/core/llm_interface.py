"""
LLM interface: Gemini (or fallback) for RAG AI Tutor.
"""
from typing import Optional
from backend.config import settings

SYSTEM_PROMPT = """You are a helpful Socratic AI tutor for students (School, Intermediate, Engineering).
Answer clearly and encourage thinking. Use examples when helpful. Keep responses concise but complete."""


def generate_reply(user_message: str, context: Optional[str] = None) -> str:
    """Generate a reply using Gemini if API key is set, else return a friendly placeholder."""
    if not settings.gemini_api_key:
        return (
            "I'm your RAG AI Tutor. To enable live AI responses, set GEMINI_API_KEY in your .env file. "
            "You can still chat here — once the key is set, I'll use it to answer. "
            f"You said: \"{user_message[:100]}\" — try uploading documents and asking questions after configuring the key!"
        )
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = SYSTEM_PROMPT + "\n\n"
        if context:
            prompt += f"Relevant context:\n{context}\n\n"
        prompt += f"Student question: {user_message}\n\nYour response:"
        response = model.generate_content(prompt)
        if response and response.text:
            return response.text.strip()
        return "I couldn't generate a response. Please try rephrasing."
    except Exception as e:
        return f"I ran into an issue: {str(e)}. Check your GEMINI_API_KEY and try again."
