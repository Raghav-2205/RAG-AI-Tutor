import requests
import time

BASE_URL = "http://127.0.0.1:8000/api"

def test_rag_flow():
    session = requests.Session()
    
    # 1. Login
    print("1. Logging in...")
    login_data = {"username": "test_valid@example.com", "password": "password123"}
    r = session.post(f"{BASE_URL}/auth/login", data=login_data)
    if r.status_code != 200:
        print(f"❌ Login Failed: {r.text}")
        return
    token = r.json()['access_token']
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Upload "Secret" Knowledge
    print("2. Uploading Knowledge...")
    secret_fact = "The secret ingredient of the special sauce is stardust."
    files = {
        'file': ('secret.txt', secret_fact, 'text/plain')
    }
    r = session.post(f"{BASE_URL}/upload/", headers=headers, files=files)
    if r.status_code != 200:
        print(f"❌ Upload Failed: {r.text}")
        return
    print("✅ Upload Success")
    
    # Wait / Sleep briefly? (SimpleVectorDB is instant/synchronous typically, but let's be safe)
    time.sleep(1)
    
    # 3. Ask Question
    print("3. Asking Question...")
    query = "What is the secret ingredient of the special sauce?"
    payload = {
        "message": query,
        "history": []
    }
    
    r = session.post(f"{BASE_URL}/chat/", headers=headers, json=payload)
    
    if r.status_code == 200:
        data = r.json()
        answer = data.get('answer', '')
        print("\n⬇️ RAG Response ⬇️")
        print(answer)
        
        if "stardust" in answer.lower():
            print("\n✅ RAG SUCCESS: Answer contained the secret fact.")
        else:
            print("\n⚠️ RAG WARNING: Answer might not have retrieved the correct context.")
    else:
        print(f"❌ Chat Request Failed: {r.status_code} - {r.text}")

if __name__ == "__main__":
    test_rag_flow()
