# backend/vector_db.py
import os
import json
import numpy as np
from typing import List, Dict, Any, Optional
import uuid
from pathlib import Path
from backend.config import settings

# Setup storage path
CHROMA_DATA_PATH = Path(settings.chroma_persist_directory)
CHROMA_DATA_PATH.mkdir(parents=True, exist_ok=True)
DB_FILE = CHROMA_DATA_PATH / "simple_vector_store.json"

class SimpleCollection:
    def __init__(self, name: str, data: Dict):
        self.name = name
        self.data = data # Reference to main DB data for this collection
        # data structure: {"documents": [], "metadatas": [], "ids": [], "embeddings": []}
        if "documents" not in self.data:
            self.data["documents"] = []
            self.data["metadatas"] = []
            self.data["ids"] = []
            self.data["embeddings"] = []

    def add(self, documents: List[str], metadatas: List[Dict], ids: List[str], embeddings: List[List[float]] = None):
        # In this simple implementation, we assume embeddings are passed or we don't store them if not provided?
        # Chroma calculates them if not provided.
        # But here, we can't calculate them easily without the model.
        # Wait, the original code used `embedding_function` in `get_or_create_collection`.
        # I should probably accept embeddings being passed?
        # Original `add_chunks_to_collection` passed `documents`, `metadatas`, `ids`.
        # It relied on `collection.add` to compute embeddings via `embedding_function`.
        
        # We need to replicate that.
        # We can use `backend.core.embedding_service`!
        from backend.core.embedding_service import embedding_service
        
        if embeddings is None:
            # Compute embeddings
            embeddings = embedding_service.embed_text(documents)
            
        self.data["documents"].extend(documents)
        self.data["metadatas"].extend(metadatas)
        self.data["ids"].extend(ids)
        self.data["embeddings"].extend(embeddings)
        self._save()

    def query(self, query_embeddings: List[List[float]], n_results: int = 6, include: List[str] = None) -> Dict:
        # Perform cosine similarity
        if not self.data["embeddings"]:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

        # Convert to numpy
        db_vecs = np.array(self.data["embeddings"])
        query_vec = np.array(query_embeddings[0]) # Assume single query for now
        
        # Cosine similarity: (A . B) / (|A| |B|)
        # Assuming normalized vectors from sentence-transformers?
        # If not, we normalize.
        norm_db = np.linalg.norm(db_vecs, axis=1)
        norm_query = np.linalg.norm(query_vec)
        
        # Avoid div by zero
        norm_db[norm_db == 0] = 1e-10
        if norm_query == 0: norm_query = 1e-10
        
        dot_product = np.dot(db_vecs, query_vec)
        cosine_sim = dot_product / (norm_db * norm_query)
        
        # Sort by similarity (descending)
        # We want distances? Chroma returns distances usually (L2) or Cosine distance (1 - sim).
        # We prefer cosine distance: 1 - sim.
        cosine_dist = 1 - cosine_sim
        
        top_indices = np.argsort(cosine_dist)[:n_results]
        
        res_docs = [self.data["documents"][i] for i in top_indices]
        res_metas = [self.data["metadatas"][i] for i in top_indices]
        res_dists = [cosine_dist[i] for i in top_indices]
        
        return {
            "documents": [res_docs],
            "metadatas": [res_metas],
            "distances": [res_dists]
        }

    def get(self, include: List[str] = None) -> Dict:
        return {
            "documents": self.data["documents"],
            "metadatas": self.data["metadatas"],
            "ids": self.data["ids"]
        }

    def _save(self):
        # Save entire DB to disk
        # This is inefficient but functional for demo
        global _db_instance
        _db_instance.save()

class SimpleVectorDB:
    def __init__(self):
        self.collections = {}
        self.load()

    def load(self):
        if DB_FILE.exists():
            try:
                with open(DB_FILE, 'r') as f:
                    self.collections = json.load(f)
            except:
                self.collections = {}
        else:
            self.collections = {}

    def save(self):
        with open(DB_FILE, 'w') as f:
            json.dump(self.collections, f)

    def get_or_create_collection(self, name: str) -> SimpleCollection:
        if name not in self.collections:
            self.collections[name] = {"documents": [], "metadatas": [], "ids": [], "embeddings": []}
        return SimpleCollection(name, self.collections[name])

_db_instance = SimpleVectorDB()

def get_vector_db():
    return _db_instance

def get_or_create_collection(client, user_id: str, subject: Optional[str] = None):
    if subject:
        name = f"user_{user_id}_{subject.lower().replace(' ', '_')}"
    else:
        name = f"user_{user_id}_general"
    return client.get_or_create_collection(name)

def add_chunks_to_collection(collection, chunks: List[Dict[str, Any]]) -> List[str]:
    if not chunks:
        return []

    documents = [c["text"] for c in chunks]
    metadatas = [{
        "source": c["source"], 
        "doc_id": c["doc_id"],
        "chunk_index": c["chunk_index"]
    } for c in chunks]
    ids = [str(uuid.uuid4()) for _ in chunks]
    
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    return ids

def get_all_chunks(user_id: str, subject: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_vector_db()
    try:
        collection = get_or_create_collection(client, user_id, subject)
        results = collection.get(include=["documents", "metadatas"])
        
        chunks = []
        if results["documents"]:
            for i, doc in enumerate(results["documents"]):
                chunks.append({
                    "text": doc,
                    "metadata": results["metadatas"][i]
                })
        return chunks
    except Exception as e:
        print(f"Error fetching all chunks: {e}")
        return []

def query_user_collection(user_id: str, subject: Optional[str], query_embedding: List[float], top_k: int = 6) -> List[Dict[str, Any]]:
    client = get_vector_db()
    collection = get_or_create_collection(client, user_id, subject)
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    
    hits = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            hits.append({
                "text": doc,
                "metadata": results["metadatas"][0][i],
                "score": 1 - results["distances"][0][i] # Convert distance to similarity
            })
    return hits


def clear_user_data(client: SimpleVectorDB, user_id: str):
    """Clear all vector data for a specific user"""
    # Find and delete all collections that match this user
    collections_to_delete = []
    for name in list(client.db.keys()):
        if name.startswith(f"user_{user_id}_"):
            collections_to_delete.append(name)
    
    for name in collections_to_delete:
        del client.db[name]
    
    client._save()
    return len(collections_to_delete)