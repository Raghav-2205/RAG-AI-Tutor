
import requests
import json

def fetch_spec():
    try:
        url = "http://localhost:8001/openapi.json"
        print(f"Fetching {url}...")
        resp = requests.get(url)
        if resp.status_code == 200:
            data = resp.json()
            paths = list(data.get("paths", {}).keys())
            print("Available Paths:")
            print(json.dumps(paths, indent=2))
        else:
            print(f"Failed to fetch spec: {resp.status_code}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fetch_spec()
