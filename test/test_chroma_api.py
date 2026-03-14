
import requests
import json
import uuid

BASE_URL = "http://localhost:8001"
TENANT = "default_tenant"
DATABASE = "default_database"

def test_v2_api():
    try:
        print(f"Testing V2 API at {BASE_URL}...")
        
        # 1. List Collections
        url_list = f"{BASE_URL}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections"
        print(f"GET {url_list}")
        resp = requests.post(url_list, json={"limit": 10, "offset": 0}) # List is often POST in some APIs? No, usually GET.
        # But wait, looking at the paths, there isn't a plain list collection path?
        # /api/v2/tenants/{tenant}/databases/{database}/collections is listed.
        
        # Let's try GET first
        resp = requests.get(url_list)
        if resp.status_code == 405:
            # Try POST?
            resp = requests.post(url_list, json={})
            
        print(f"List Collections: {resp.status_code} - {resp.text}")
        
        # 2. Create Collection
        # Usually POST to .../collections
        # With body { "name": "...", "get_or_create": true }
        col_name = "test_v2_col_" + str(uuid.uuid4())[:8]
        print(f"Creating collection {col_name}...")
        
        resp = requests.post(url_list, json={"name": col_name, "get_or_create": True})
        print(f"Create response: {resp.status_code} - {resp.text}")
        
        if resp.status_code == 200:
            col_data = resp.json()
            col_id = col_data["id"] 
            print(f"Collection ID: {col_id}")
            
            # 3. Add Item
            # Path: .../collections/{collection_id}/add
            url_add = f"{BASE_URL}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections/{col_id}/add"
            print(f"Adding to {url_add}...")
            
            add_data = {
                "documents": ["Hello World"],
                "metadatas": [{"source": "test"}],
                "ids": ["id1"],
                "embeddings": [[0.1] * 384]
            }
            resp = requests.post(url_add, json=add_data)
            print(f"Add response: {resp.status_code} - {resp.text}")
            
            # 4. Query
            # Path: .../collections/{collection_id}/query
            url_query = f"{BASE_URL}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections/{col_id}/query"
            print(f"Querying {url_query}...")
            
            query_data = {
                "query_embeddings": [[0.1] * 384],
                "n_results": 1
            }
            resp = requests.post(url_query, json=query_data)
            print(f"Query response: {resp.status_code} - {resp.text}")
            
            # 5. Delete Collection
            # Path: .../collections/{collection_name}? No, usually ID or Name. 
            # The spec showed .../collections/{collection_id}
            # Wait, creating collection returns ID.
            url_del = f"{BASE_URL}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections/{col_name}" 
            # Usually DELETE uses name in URL? Or ID?
            # Let's try name first, as that's typical for Chroma v1.
            print(f"Deleting {col_name}...")
            resp = requests.delete(url_del)
            print(f"Delete response: {resp.status_code} - {resp.text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_v2_api()
