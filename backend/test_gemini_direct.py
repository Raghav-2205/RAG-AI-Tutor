import requests
import os
import dotenv

dotenv.load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.5-flash"

def test_gemini():
    if not API_KEY:
        print("❌ No API Key found in .env")
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={API_KEY}"
    
    payload = {
        "contents": [{
            "parts": [{"text": "Hello, this is a test."}]
        }]
    }
    
    headers = {'Content-Type': 'application/json'}
    
    print(f"Testing URL: {url}")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Success!")
            print(response.json()['candidates'][0]['content']['parts'][0]['text'])
        else:
            print(f"❌ Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_gemini()
