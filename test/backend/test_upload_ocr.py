import requests
import os
from PIL import Image, ImageDraw
import io

# Create a dummy image with text
def create_dummy_image():
    img = Image.new('RGB', (200, 100), color = (255, 255, 255))
    # We can't easily draw text without a font file, but we can try default
    # Or just use Tesseract to read it if we had a font. 
    # Actually, Gemini Vision is very good at reading even bad handwriting or patterns.
    # Let's simple check if the ENDPOINT accepts the file.
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def test_ocr():
    # Login first
    login_url = "http://127.0.0.1:8000/api/auth/login"
    login_data = {"username": "test_valid@example.com", "password": "password123"}
    
    session = requests.Session()
    try:
        r = session.post(login_url, data=login_data)
        if r.status_code != 200:
            print("Login failed")
            return
        token = r.json()['access_token']
        headers = {"Authorization": f"Bearer {token}"}
        
        # Upload
        files = {'file': ('test.png', create_dummy_image(), 'image/png')}
        upload_url = "http://127.0.0.1:8000/api/upload/"
        
        print("Uploading image...")
        r = session.post(upload_url, headers=headers, files=files)
        
        if r.status_code == 200:
            print("✅ Upload Success")
            print(r.json())
        else:
            print(f"❌ Upload Failed: {r.status_code} - {r.text}")
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_ocr()
