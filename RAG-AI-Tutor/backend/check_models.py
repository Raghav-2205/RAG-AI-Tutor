import requests
import os
from backend.config import settings

def list_models():
    api_key = settings.gemini_api_key
    if not api_key:
        print("Error: No API Key found.")
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            print("Available Models:")
            for m in data.get('models', []):
                print(f"- {m['name']} ({m.get('supportedGenerationMethods', [])})")
        else:
            print(f"Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Request Failed: {e}")

if __name__ == "__main__":
    list_models()
