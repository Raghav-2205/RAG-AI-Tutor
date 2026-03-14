
import requests
import json
from backend.config import settings

BASE_URL = settings.chroma_api_url
TENANT = settings.chroma_tenant
DATABASE = settings.chroma_database

def check_status():
    print(f"Checking ChromaDB at {BASE_URL}...")
    
    # 1. List Collections
    url_list = f"{BASE_URL}/tenants/{TENANT}/databases/{DATABASE}/collections"
    try:
        resp = requests.get(url_list)
        if resp.status_code != 200:
            print(f"Failed to list collections: {resp.status_code} - {resp.text}")
            return
            
        collections = resp.json()
        print(f"\nFound {len(collections)} collections:")
        
        total_chunks = 0
        
        for col in collections:
            col_id = col["id"]
            col_name = col["name"]
            
            # Get count
            # Path: .../collections/{collection_id}/count ??
            # Spec says: /collections/{collection_id}/count
            url_count = f"{BASE_URL}/tenants/{TENANT}/databases/{DATABASE}/collections/{col_id}/count"
            count_resp = requests.get(url_count)
            count = 0
            if count_resp.status_code == 200:
                count = count_resp.json()
            
            print(f" - Collection: {col_name} (ID: {col_id}) | Count: {count}")
            total_chunks += count
            
            # Optional: Peek at first item
            if count > 0:
                # Query 1 item
                url_get = f"{BASE_URL}/tenants/{TENANT}/databases/{DATABASE}/collections/{col_id}/get"
                payload = {"limit": 1, "include": ["documents", "metadatas"]}
                get_resp = requests.post(url_get, json=payload)
                if get_resp.status_code == 200:
                    data = get_resp.json()
                    if data["documents"]:
                        print(f"   Sample: {data['documents'][0][:50]}...")
        
        print(f"\nTotal Chunks in ChromaDB: {total_chunks}")
        
    except Exception as e:
        print(f"Error checking status: {e}")

if __name__ == "__main__":
    check_status()
