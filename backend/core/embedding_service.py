# backend/core/embedding_service.py

"""
Simplified embedding service that can work without sentence-transformers initially.
Used by: vector_db.py, rag_tutor.py, search_engine.py
"""

import numpy as np
from typing import List
from functools import lru_cache
import hashlib

# Global singleton (lazy-loaded)
_embedding_model = None


class SimpleEmbeddingService:
    """Simple embedding service using basic text hashing as fallback"""
    
    def __init__(self):
        self.model = None
        self.embedding_dim = 384
        print("⚠️  Using simple hash-based embeddings. Install sentence-transformers for better results.")
    
    def embed_text(self, text: str) -> List[float]:
        """Convert text → 384-dim embedding vector using simple hashing"""
        if isinstance(text, list):
            return [self._hash_to_embedding(t) for t in text]
        return self._hash_to_embedding(text)
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Batch embed multiple texts"""
        return [self._hash_to_embedding(text) for text in texts]
    
    def _hash_to_embedding(self, text: str) -> List[float]:
        """Convert text to embedding using hash-based approach"""
        # Create a deterministic hash-based embedding
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()
        
        # Convert to float array and normalize
        embedding = []
        for i in range(0, min(len(hash_bytes), self.embedding_dim // 8)):
            # Take 8 bytes at a time and convert to float
            chunk = hash_bytes[i:i+8] if i+8 <= len(hash_bytes) else hash_bytes[i:]
            chunk_int = int.from_bytes(chunk.ljust(8, b'\x00'), 'big')
            # Normalize to [-1, 1] range
            embedding.append((chunk_int % 2000 - 1000) / 1000.0)
        
        # Pad to required dimension
        while len(embedding) < self.embedding_dim:
            embedding.append(0.0)
        
        return embedding[:self.embedding_dim]


class SentenceTransformerEmbeddingService:
    """Real embedding service using SentenceTransformers"""
    
    def __init__(self):
        try:
            import sentence_transformers
            self.model = sentence_transformers.SentenceTransformer("all-MiniLM-L6-v2")
            print("✅ Using SentenceTransformers for embeddings")
        except ImportError:
            raise ImportError("sentence-transformers not available")
    
    def embed_text(self, text: str) -> List[float]:
        """Convert text → 384-dim embedding vector"""
        if isinstance(text, list):
            embeddings = self.model.encode(text)
            return embeddings[0].tolist() if len(embeddings) > 0 else []
        return self.model.encode([text])[0].tolist()
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Batch embed multiple texts"""
        return self.model.encode(texts).tolist()


# SINGLE GLOBAL INSTANCE - used everywhere
@lru_cache(maxsize=1)
def get_embedding_service():
    global _embedding_model
    if _embedding_model is None:
        try:
            _embedding_model = SentenceTransformerEmbeddingService()
        except ImportError:
            _embedding_model = SimpleEmbeddingService()
    return _embedding_model


# Convenience export
embedding_service = get_embedding_service()
