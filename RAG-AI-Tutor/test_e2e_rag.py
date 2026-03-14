
import requests
import json
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add project root
sys.path.append(os.getcwd())

from backend.config import settings

# Test against running server to avoid async loop issues
# python start_server.py must be running

BASE_URL = "http://localhost:8000"
client = requests.Session()

def test_upload_and_chat():
    print(f"--- Starting End-to-End RAG Test against {BASE_URL} ---")
    
    # 1. Login to get token
    # We need a user. Let's register a new one or use existing test user.
    # To keep dependencies low, let's mock authentication or use a known user credential?
    # Or just register a new user every time.
    email = f"test_rag_{os.urandom(4).hex()}@example.com"
    password = "password123"
    name = "Test User"
    
    print(f"Registering user {email}...")
    register_payload = {
        "email": email,
        "password": password,
        "name": name,
        "level": "beginner"
    }
    
    try:
        resp = client.post(f"{BASE_URL}/api/auth/register", json=register_payload)
        if resp.status_code != 201:
             # Check if it failed because user exists (unlikely with random email)
             print(f"Register failed or user exists: {resp.text}")
    except Exception as e:
        print(f"Register exception: {e}")
        
    print("Logging in...")
    # OAuth2 form expects 'username' field, which maps to email in our backend
    resp = client.post(f"{BASE_URL}/api/auth/login", data={"username": email, "password": password})
    if resp.status_code != 200:
        print(f"Login failed: {resp.text}")
        return False
        
    token = resp.json().get("access_token")
    if not token:
        print(f"No token returned: {resp.text}")
        return False
    headers = {"Authorization": f"Bearer {token}"}
    print("Logged in.")
    
    # 2. Upload Document
    filename = "test_rag_doc.txt"
    content = "The capital of France is Paris. The capital of Germany is Berlin. The capital of Italy is Rome."
    files = {"file": (filename, content, "text/plain")}
    
    print("Uploading document...")
    # Need to verify if 'subject' works with 'data' param when 'files' is present
    resp = client.post(f"{BASE_URL}/api/upload/", headers=headers, files=files, data={"subject": "geography"})
    
    if resp.status_code != 200:
        print(f"Upload failed: {resp.text}")
        return False
    
    doc_id = resp.json().get("doc_id")
    print(f"Upload success. Doc ID: {doc_id}")
    
    # 3. Chat / Query
    query = "What is the capital of France?"
    print(f"Querying: {query}")
    
    chat_payload = {
        "message": query,
        "subject": "geography"
    }
    
    resp = client.post(f"{BASE_URL}/api/chat/", headers=headers, json=chat_payload)
    
    if resp.status_code != 200:
        print(f"Chat failed: {resp.text}")
        return False
        
    data = resp.json()
    response_text = data.get("response", "")
    sources = data.get("sources", [])
    
    print(f"AI Response: {response_text}")
    print(f"Sources: {sources}")
    
    # Verify retrieval
    if "Paris" in response_text or any("France" in s["text"] for s in sources):
        print("SUCCESS: RAG retrieved correct information.")
    else:
        print("WARNING: RAG might not have retrieved the document correctly.")
        
    # 4. Clean up (Delete docs)
    print("Cleaning up...")
    client.delete(f"{BASE_URL}/api/upload/all", headers=headers)
    
    print("--- End-to-End Test Completed ---")
    return True

if __name__ == "__main__":
    test_upload_and_chat()
