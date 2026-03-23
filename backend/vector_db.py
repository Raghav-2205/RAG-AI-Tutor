
# backend/vector_db.py
import requests
import json
import uuid
import logging
from typing import List, Dict, Any, Optional
from backend.config import settings

logger = logging.getLogger(__name__)

class ChromaCollection:
    def __init__(self, name: str, collection_id: str, client: 'ChromaDBClient'):
        self.name = name
        self.id = collection_id
        self.client = client
        self.api_url = client.api_url
        self.tenant = client.tenant
        self.database = client.database
        self.base_path = f"{self.api_url}/tenants/{self.tenant}/databases/{self.database}/collections/{self.id}"

    def add(self, documents: List[str], metadatas: List[Dict], ids: List[str], embeddings: List[List[float]] = None):
        """Add documents to the collection via REST API"""
        url = f"{self.base_path}/add"
        
        # If embeddings are missing, we MUST compute them because we are using REST API 
        # and likely the server side embedding function is not configured or we want control.
        # The existing SimpleVectorDB logic computed them if missing.
        if embeddings is None:
            # We need to import here to avoid circular imports if possible, or just standard import
            from backend.core.embedding_service import embedding_service
            embeddings = embedding_service.embed_text(documents)
            
        payload = {
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
            "embeddings": embeddings
        }
        try:
            resp = requests.post(url, json=payload)
            if resp.status_code not in [200, 201]:
                logger.error(f"Failed to add documents to ChromaDB: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Error adding to ChromaDB: {e}")

    def query(self, query_embeddings: List[List[float]], n_results: int = 6, include: List[str] = None, where: Dict = None) -> Dict:
        """Query the collection"""
        url = f"{self.base_path}/query"
        
        if include is None:
            include = ["documents", "metadatas", "distances"]
            
        payload = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
            "include": include
        }
        
        # Add where clause for document-scoped filtering
        if where:
            payload["where"] = where
        
        try:
            resp = requests.post(url, json=payload)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error(f"Failed to query ChromaDB: {resp.status_code} - {resp.text}")
                return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}
        except Exception as e:
            logger.error(f"Error querying ChromaDB: {e}")
            return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}

    def get(self, ids: List[str] = None, where: Dict = None, limit: int = None, offset: int = None, include: List[str] = None) -> Dict:
        """Get items from the collection"""
        url = f"{self.base_path}/get"
        
        if include is None:
            include = ["documents", "metadatas"]
            
        payload = {
            "include": include
        }
        
        if ids:
            payload["ids"] = ids
        if where:
            payload["where"] = where
        if limit:
            payload["limit"] = limit
        if offset:
            payload["offset"] = offset
            
        try:
            # The Chroma REST API expects a POST request for 'get' with a JSON body
            resp = requests.post(url, json=payload)
            if resp.status_code in [200, 201]:
                # logger.debug(f"Successfully retrieved documents from ChromaDB.")
                return resp.json()
            else:
                logger.error(f"Failed to get from ChromaDB: {resp.status_code} - {resp.text}")
                return {"ids": [], "metadatas": [], "documents": []}
        except Exception as e:
            logger.error(f"Error getting from ChromaDB: {e}")
            return {"ids": [], "metadatas": [], "documents": []}


class ChromaDBClient:
    def __init__(self):
        self.api_url = settings.chroma_api_url
        self.tenant = settings.chroma_tenant
        self.database = settings.chroma_database
        self.collections_url = f"{self.api_url}/tenants/{self.tenant}/databases/{self.database}/collections"

    def get_or_create_collection(self, name: str) -> ChromaCollection:
        # Try to create, if 409 (exists) or 200 (created/got), we get ID.
        # Actually API has "get_or_create": true param
        payload = {"name": name, "get_or_create": True}
        
        try:
            resp = requests.post(self.collections_url, json=payload)
            if resp.status_code in [200, 201]:
                data = resp.json()
                return ChromaCollection(name, data["id"], self)
            else:
                logger.error(f"Failed to get_or_create collection {name}: {resp.status_code} - {resp.text}")
                # Fallback? Raise?
                raise Exception(f"Failed to init collection {name}")
        except Exception as e:
            logger.error(f"Connection error to ChromaDB: {e}")
            raise

    def list_collections(self) -> List[Dict]:
        try:
            resp = requests.get(self.collections_url)
            if resp.status_code == 200:
                return resp.json()
            return []
        except:
            return []

    def delete_collection(self, name: str):
        # Delete by name
        url = f"{self.collections_url}/{name}"
        try:
            requests.delete(url)
        except Exception as e:
            logger.error(f"Error deleting collection {name}: {e}")

# Singleton
_db_instance = ChromaDBClient()

def get_vector_db():
    return _db_instance

# --- Helper Functions (Same Interface) ---

def get_or_create_collection(client, user_id: str, subject: Optional[str] = None):
    # Normalized name
    if subject:
        name = f"user_{user_id}_{subject.lower().replace(' ', '_')}"
    else:
        name = f"user_{user_id}_general"
        
    # Chroma collection names must be valid. Length constraints etc.
    # We assume simplified names for now.
    return client.get_or_create_collection(name)

def add_chunks_to_collection(collection, chunks: List[Dict[str, Any]]) -> List[str]:
    if not chunks:
        return []

    documents = [c["text"] for c in chunks]
    metadatas = [c.get("metadata", {
        "source": c.get("source", "Unknown"),
        "doc_id": c.get("doc_id", "Unknown"),
        "chunk_index": c.get("chunk_index", 0)
    }) for c in chunks]
    ids = [str(uuid.uuid4()) for _ in chunks]
    
    # Collection.add will handle embedding if needed
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    return ids

def get_all_chunks(user_id: str, subject: Optional[str] = None, where: Optional[Dict] = None) -> List[Dict[str, Any]]:
    client = get_vector_db()
    try:
        collection = get_or_create_collection(client, user_id, subject)
        results = collection.get(include=["documents", "metadatas"], where=where)
        
        chunks = []
        if type(results) is dict and "ids" in results and results["ids"]:
             # Results structure from get: {"ids": [...], "documents": [...], "metadatas": [...]}
             # Note: simple get usually returns flat lists, not list of lists like query
             ids = results["ids"]
             docs = results.get("documents", [])
             metas = results.get("metadatas", [])
             
             for i, uid in enumerate(ids):
                 chunks.append({
                     "id": uid,
                     "text": docs[i] if docs else "",
                     "metadata": metas[i] if metas else {}
                 })
        return chunks
    except Exception as e:
        logger.error(f"Error fetching all chunks: {e}")
        return []

def query_user_collection(user_id: str, subject: Optional[str], query_embedding: List[float], top_k: int = 6, where: Optional[Dict] = None) -> List[Dict[str, Any]]:
    client = get_vector_db()
    collection = get_or_create_collection(client, user_id, subject)
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"]  # 'ids' removed - returned by default in v2
    )
    
    hits = []
    # results structure is list of lists
    if results["ids"] and results["ids"][0]:
        for i, doc in enumerate(results["documents"][0]):
            hits.append({
                "id": results["ids"][0][i],
                "text": doc,
                "metadata": results["metadatas"][0][i],
                "score": 1 - results["distances"][0][i] # default l2 distance?
                # Wait, Chroma defaults to L2 (Squared L2). 
                # Distance 0 = identical. 
                # Similarity = 1 / (1 + dist) or specialized logic?
                # If using L2, larger is worse.
                # If using Cosine (default for some models), dist = 1 - sim.
                # We should assume some reasonable conversion. 1 - dist is common for Cosine distance.
            })
    return hits

def clear_user_data(client: ChromaDBClient, user_id: str):
    """Clear all vector data for a specific user"""
    collections = client.list_collections()
    count = 0
    prefix = f"user_{user_id}_"
    
    for col in collections:
        name = col.get("name")
        if name and name.startswith(prefix):
            client.delete_collection(name)
            count += 1
    return count