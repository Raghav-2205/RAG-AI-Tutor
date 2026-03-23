import requests
import json

BASE_URL = "http://127.0.0.1:8000/api"

def test_quiz():
    session = requests.Session()
    
    # 1. Login (Reuse same credentials)
    print("1. Logging in...")
    login_data = {"username": "test_valid@example.com", "password": "password123"}
    r = session.post(f"{BASE_URL}/auth/login", data=login_data)
    if r.status_code != 200:
        print(f"❌ Login Failed: {r.text}")
        return
    token = r.json()['access_token']
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Generate Quiz
    print("2. Generating Quiz about 'Stardust'...")
    # The subject can be anything, but let's use a keyword from our previous upload
    payload = {
        "subject": "stardust",
        "num_questions": 3,
        "difficulty": "easy"
    }
    
    r = session.post(f"{BASE_URL}/quiz/generate", headers=headers, json=payload)
    
    if r.status_code == 200:
        data = r.json()
        print("\n⬇️ Quiz Generated ⬇️")
        print(json.dumps(data, indent=2))
        
        if len(data.get("questions", [])) > 0:
            print("\n✅ Quiz Generation Success")
        else:
            print("\n⚠️ Quiz Generation Warning: No questions returned.")
    else:
        print(f"❌ Quiz Request Failed: {r.status_code} - {r.text}")

if __name__ == "__main__":
    test_quiz()
