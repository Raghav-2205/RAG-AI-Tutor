import requests
import sys

BASE_URL = "http://127.0.0.1:8000"

def debug_api():
    # 1. Login
    print("🔑 Logging in...")
    try:
        resp = requests.post(f"{BASE_URL}/api/auth/login", data={
            "username": "student@example.com", 
            "password": "password123"
        })
        if resp.status_code != 200:
            print(f"❌ Login failed: {resp.text}")
            # Try registering if login fails
            print("🆕 Registering new user...")
            resp = requests.post(f"{BASE_URL}/api/auth/register", json={
                "name": "Student",
                "email": "student@example.com",
                "password": "password123",
                "level": "beginner"
            })
            if resp.status_code not in [200, 201]:
                print(f"❌ Registration failed: {resp.status_code} {resp.text}")
                # return # Keep trying login just in case
            
            # Login again
            print("🔄 Retrying login...")
            resp = requests.post(f"{BASE_URL}/api/auth/login", data={
                "username": "student@example.com", 
                "password": "password123"
            })
            
        token = resp.json()["access_token"]
        print("✅ Logged in")
        
        # 2. Call Evaluation Run
        print("🚀 Calling /api/evaluation/run...")
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.post(
            f"{BASE_URL}/api/evaluation/run", 
            json={"limit": 1},
            headers=headers
        )
        
        print(f"Status Code: {resp.status_code}")
        print(f"Response: {resp.text}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    debug_api()
