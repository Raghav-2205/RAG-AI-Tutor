
import requests
import json
import logging
import sys
import os
from _bootstrap import ensure_project_root

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ensure_project_root()

from backend.vector_db import ChromaDBClient, get_vector_db, get_or_create_collection
from backend.core.embedding_service import embedding_service

def debug_add():
    print("--- Debugging Chroma Add ---")
    
    client = get_vector_db()
    user_id = "debug_user"
    subject = "debug_subject"
    
    # 1. Create Collection
    # Manually to ensure clean state
    url_list = f"{client.api_url}/tenants/{client.tenant}/databases/{client.database}/collections"
    col_name = f"user_{user_id}_{subject}"
    
    # Delete if exists
    try:
        requests.delete(f"{url_list}/{col_name}")
    except:
        pass
        
    print(f"Creating collection {col_name}...")
    resp = requests.post(url_list, json={"name": col_name, "get_or_create": True})
    if resp.status_code != 200:
        print(f"Failed to create collection: {resp.text}")
        return

    col_id = resp.json()["id"]
    print(f"Collection ID: {col_id}")
    
    # 2. Prepare Payload
    documents = ["Test Document 1"]
    metadatas = [{"source": "test", "index": 1}]
    ids = ["id_1"]
    
    print("Generating embeddings...")
    embeddings = embedding_service.embed_text(documents)
    # Check type
    print(f"Embeddings type: {type(embeddings)}")
    print(f"Embeddings[0] type: {type(embeddings[0])}")
    print(f"Embeddings[0][0] type: {type(embeddings[0][0])}")
    
    payload = {
        "ids": ids,
        "documents": documents,
        "metadatas": metadatas,
        "embeddings": embeddings
    }
    
    # 3. Send Request
    url_add = f"{client.api_url}/tenants/{client.tenant}/databases/{client.database}/collections/{col_id}/add"
    print(f"Posting to {url_add}...")
    
    # Serialize manually to safely print
    try:
        json_payload = json.dumps(payload)
        print(f"Payload length: {len(json_payload)}")
        # Print first 500 chars
        print(f"Payload snippet: {json_payload[:500]}...")
    except TypeError as e:
        print(f"Serialization Error: {e}")
        return

    resp = requests.post(url_add, data=json_payload, headers={"Content-Type": "application/json"})
    print(f"Response Status: {resp.status_code}")
    print(f"Response Text: {resp.text}")

if __name__ == "__main__":
    debug_add()
