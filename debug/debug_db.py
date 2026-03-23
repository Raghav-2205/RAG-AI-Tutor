# debug_db.py
import chromadb
from _bootstrap import ensure_project_root

ensure_project_root()

from backend.config import settings

def check():
    path = settings.chroma_persist_directory
    print(f"📂 Checking Database at: {path}")
    
    try:
        client = chromadb.PersistentClient(path=path)
        col_name = "user_system_dataset_v1_general"
        
        try:
            col = client.get_collection(col_name)
            count = col.count()
            print(f"✅ FOUND COLLECTION: '{col_name}'")
            print(f"📊 Total Chunks: {count}")
            
            if count > 0:
                print("🔎 Sample Chunk:")
                print(col.peek(1)['documents'][0][:200] + "...")
            else:
                print("⚠️ Collection exists but is EMPTY.")
                
        except Exception:
            print(f"❌ Collection '{col_name}' NOT FOUND.")
            print("   Did you run 'python scripts/ingest_local.py'?")
            print("   Available collections:", [c.name for c in client.list_collections()])
            
    except Exception as e:
        print(f"❌ Error connecting to DB: {e}")

if __name__ == "__main__":
    check()
