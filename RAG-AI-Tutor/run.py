import uvicorn
import os
import sys
import warnings

# 1. Suppress warnings to keep logs clean
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

if __name__ == "__main__":
    # 2. Add the project directory to Python path explicitly
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(current_dir)
    
    print("------------------------------------------------")
    print("🚀 Initializing RAG AI Tutor Server...")
    print(f"📂 Project Root: {current_dir}")
    print("------------------------------------------------")

    try:
        # 3. Test import BEFORE starting server to catch crash early
        from backend.main import app
        print("✅ Backend App imported successfully.")
        
        print("🔌 Starting Server on http://127.0.0.1:8000")
        print("   (Press Ctrl+C to stop)")
        
        # 4. Run Uvicorn
        uvicorn.run(
            "backend.main:app", 
            host="127.0.0.1", 
            port=8002, 
            reload=False,  # False is more stable on Windows
            log_level="info"
        )
        
    except ImportError as e:
        print(f"\n❌ CRITICAL IMPORT ERROR: {e}")
        print("   Did you rename a file or folder?")
    except Exception as e:
        print(f"\n❌ SERVER CRASHED: {e}")
        import traceback
        traceback.print_exc()
        
    input("\nPress Enter to exit...")