# backend/core/__init__.py
"""
Core AI Services - Embeddings, LLM, Search Engine
"""

# Export main services for easy import
from .embedding_service import embedding_service
from .llm_interface import llm_client  
from .search_engine import search_engine
from .ocr_service import ocr_service

__all__ = ["embedding_service", "llm_client", "search_engine", "ocr_service"]
