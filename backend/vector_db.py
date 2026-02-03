# backend/vector_db.py

import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional
from pathlib import Path
import uuid
import numpy as np

from backend.config import settings
from backend.core.embedding_service import embedding_service


# Where ChromaDB stores its data files (creates chroma_data/ folder)
CHROMA_DATA_PATH = Path("chroma_data")
CHROMA_DATA_PATH.mkdir(exist_ok=True)

# Global Chroma client (singleton pattern)
_client = None


def get_vector_db() -> chromadb.PersistentClient:
    """
    Returns the global ChromaDB client. Creates it if needed.
    """
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DATA_PATH),
            settings=chromadb.Settings(
                anonymized_telemetry=False,
            )
        )
    return _client


def get_or_create_collection(
    client: chromadb.PersistentClient,
    user_id: str,
    subject: Optional[str] = None,
) -> chromadb.Collection:
    """
    Get existing collection or create new one.
    Collection names: "user_abc123" or "user_abc123_math"
    """
    if subject:
        collection_name = f"user_{user_id}_{subject.lower().replace(' ', '_')}"
    else:
        collection_name = f"user_{user_id}"

    # Use embedding_service from core (SentenceTransformer)
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    try:
        collection = client.get_collection(collection_name)
    except Exception:
        # Create new collection if it doesn't exist
        collection = client.create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
    
    return collection


def add_chunks_to_collection(
    collection: chromadb.Collection,
    chunks: List[Dict[str, Any]],
) -> List[str]:
    """
    Add text chunks + metadata to Chroma collection.
    
    Each chunk should have:
    - "text": the chunk content
    - "source": filename
    - "doc_id": document ID
    - optional other metadata
    """
    documents = [chunk["text"] for chunk in chunks]
    metadatas = [{"source": chunk["source"], "doc_id": chunk["doc_id"]} for chunk in chunks]
    ids = [str(uuid.uuid4()) for _ in chunks]

    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids,
    )
    
    return ids


def query_user_collection(
    user_id: str,
    subject: Optional[str],
    query_embedding: List[float],
    top_k: int = 6,
    min_score: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    MAIN QUERY FUNCTION used by rag_tutor.py
    
    Returns top_k relevant chunks as dicts:
    [
        {"text": "...", "source": "math.pdf", "score": 0.87, "chunk_id": "..."},
        ...
    ]
    """
    client = get_vector_db()
    collection = get_or_create_collection(client, user_id, subject)
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k + 5,  # Get extra, filter by score later
        include=["documents", "metadatas", "distances"],
    )
    
    # Chroma returns distances (smaller = more similar), convert to scores
    hits = []
    for i, doc in enumerate(results["documents"][0]):
        distance = results["distances"][0][i]
        score = 1 - distance  # Simple cosine distance → similarity score
        
        if score < min_score:
            continue  # Skip low-relevance chunks
            
        hit = {
            "text": doc,
            "source": results["metadatas"][0][i]["source"],
            "doc_id": results["metadatas"][0][i]["doc_id"],
            "score": score,
            "chunk_id": results["ids"][0][i],
        }
        hits.append(hit)
    
    return hits[:top_k]  # Return at most top_k
