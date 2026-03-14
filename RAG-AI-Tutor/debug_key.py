import google.generativeai as genai
import os
from dotenv import load_dotenv

# 1. Load your .env file
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

print("------------------------------------------------")
print(f"🔑 Testing API Key: {api_key[:10]}... (Hidden)")
print("------------------------------------------------")

if not api_key:
    print("❌ ERROR: API Key is missing from .env file!")
    exit()

try:
    # 2. Configure
    genai.configure(api_key=api_key)
    
    # 3. List ALL Models (No filters)
    print("📡 Contacting Google to list models...")
    models = list(genai.list_models())
    
    if not models:
        print("\n❌ FATAL ERROR: Google returned 0 models.")
        print("   This means the 'Generative Language API' is DISABLED in your Google Cloud Console.")
        print("   See Step 2 below to fix this.")
    else:
        print(f"\n✅ Google returned {len(models)} models. Here are the valid ones:")
        valid_found = False
        for m in models:
            print(f"   - {m.name}")
            if "generateContent" in m.supported_generation_methods:
                print(f"     ✅ SUPPORTS TEXT GENERATION")
                valid_found = True
        
        if valid_found:
            print("\n🎉 Your key works! Update your code to use one of the names above.")
        else:
            print("\n⚠️ Models found, but none support text generation.")

except Exception as e:
    print(f"\n❌ CONNECTION ERROR: {e}")
    if "400" in str(e) or "403" in str(e):
        print("👉 Your API Key is invalid or has expired.")