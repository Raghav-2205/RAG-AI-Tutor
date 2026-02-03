# backend/vector_db.py
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path
import uuid
from typing import List, Dict, Any, Optional
from backend.config import settings

# Setup Chroma path
CHROMA_DATA_PATH = Path(settings.chroma_persist_directory)
CHROMA_DATA_PATH.mkdir(exist_ok=True)

_client = None

def get_vector_db() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DATA_PATH))
    return _client

def get_or_create_collection(client, user_id: str, subject: Optional[str] = None):
    # Unique collection per user (and subject if provided)
    if subject:
        name = f"user_{user_id}_{subject.lower()}"
    else:
        name = f"user_{user_id}_general"
        
    # Using the standard SentenceTransformer for embeddings
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=settings.embedding_model
    )
    
    return client.get_or_create_collection(
        name=name,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"}
    )

def add_chunks_to_collection(collection, chunks: List[Dict[str, Any]]) -> List[str]:
    if not chunks:
        return []

    documents = [c["text"] for c in chunks]
    metadatas = [{"source": c["source"], "doc_id": c["doc_id"]} for c in chunks]
    ids = [str(uuid.uuid4()) for _ in chunks]
    
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    return ids