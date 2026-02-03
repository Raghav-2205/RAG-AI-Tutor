# backend/database/chromadb/config.py
"""
ChromaDB optimized settings for RAG retrieval
"""

from backend.config import settings
from chromadb.config import DEFAULT_INDEX_METADATA

# Optimal HNSW settings for RAG (tradeoff: speed vs accuracy)
CHROMA_CONFIG = {
    "hnsw:space": "cosine",  # Best for text embeddings
    "hnsw:M": 32,            # Connections per node (16-64 optimal)
    "hnsw:ef_construction": 200,  # Build quality (100-500)
    "hnsw:ef": 100,          # Search quality (50-200)
}

# Per-user + subject collections
COLLECTION_METADATA = {
    "user_id": "string",
    "subject": "string",
    "hnsw:space": "cosine"
}

def get_chroma_config() -> dict:
    return {
        "path": settings.chromadb.path,
        "persist_directory": settings.chromadb.persist_directory,
        **CHROMA_CONFIG
    }
