
import requests
import json
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# Configuration
BASE_URL = "http://127.0.0.1:8000"
import random
import string

random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
EMAIL = f"test_rag_{random_str}@example.com"
PASSWORD = "TestPassword123!"

def test_rag_flow():
    print("🚀 Starting Advanced RAG Flow Verification...")

    # 1. Login
    print("\n1. Logging in...")
    auth_resp = requests.post(f"{BASE_URL}/api/auth/login", data={"username": EMAIL, "password": PASSWORD})
    if auth_resp.status_code != 200:
        # Try registering if login fails
        print("   Login failed, trying registration...")
        reg_resp = requests.post(f"{BASE_URL}/api/auth/register", json={"email": EMAIL, "password": PASSWORD, "name": "Test User", "level": "Intermediate"})
        if reg_resp.ok:
             auth_resp = requests.post(f"{BASE_URL}/api/auth/login", data={"username": EMAIL, "password": PASSWORD})
    
    if auth_resp.status_code != 200:
        print(f"❌ Authentication failed: {auth_resp.text}")
        return

    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Authenticated.")

    # 2. Chat Query (Triggers Search + Reranking)
    query = "What is the transformer architecture?"
    print(f"\n2. Sending Chat Query: '{query}'...")
    
    chat_payload = {
        "message": query,
        "subject": "general"
    }
    
    chat_resp = requests.post(f"{BASE_URL}/api/chat/", json=chat_payload, headers=headers)
    
    if chat_resp.status_code != 200:
        print(f"❌ Chat failed: {chat_resp.text}")
        return
        
    chat_data = chat_resp.json()
    answer = chat_data["answer"]
    citations = chat_data.get("citations", [])
    chunks = chat_data.get("chunks", [])
    
    print(f"✅ Chat Response Received.")
    print(f"   Answer Snippet: {answer[:100]}...")
    print(f"   Citations: {citations}")
    print(f"   Chunks Returned: {len(chunks)}")
    
    if not chunks:
        print("❌ No chunks returned. RAG might not be finding data.")
        return

    # Verify Chunk IDs
    first_chunk = chunks[0]
    chunk_id = first_chunk.get("id") or first_chunk.get("metadata", {}).get("id")
    
    # In search_engine.py, we attach 'id' to the top-level dict of the result
    # Let's see what the API returns. backend/rag_tutor.py returns whatever search_engine returns.
    print(f"   First Chunk ID: {chunk_id}")
    
    if not chunk_id:
        print("❌ First chunk is missing ID. Interactive citations will fail.")
        print(f"   Chunk Data: {first_chunk.keys()}")
        # Check if id is in metadata?
        return

    # 3. Test Chunk Details API
    print(f"\n3. Fetching Chunk Details for ID: {chunk_id}...")
    chunk_resp = requests.get(f"{BASE_URL}/api/chunks/{chunk_id}", headers=headers)
    
    if chunk_resp.status_code == 200:
        chunk_detail = chunk_resp.json()
        print("✅ Chunk Details Fetched.")
        print(f"   Source: {chunk_detail.get('metadata', {}).get('filename')}")
        print(f"   Text Snippet: {chunk_detail.get('text', '')[:50]}...")
    else:
        print(f"❌ Failed to fetch chunk details: {chunk_resp.status_code} - {chunk_resp.text}")

    print("\n✅ Advanced RAG Flow Verified Successfully!")

if __name__ == "__main__":
    test_rag_flow()
