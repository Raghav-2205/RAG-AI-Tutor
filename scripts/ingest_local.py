import sys
import asyncio
import uuid
import time  # <--- NEW: For safety delays
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.file_handler import extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection
from backend.utils.db import get_db, db_manager

# --- CONFIG ---
DATASET_DIR = Path("data/base_dataset")
SYSTEM_USER_ID = "system_dataset_v1"
SUPPORTED_EXTS = {'.pdf', '.docx', '.txt', '.pptx', '.ppt'}

async def ingest_safe_mode():
    print(f"🚀 Starting ONE-TIME Database Build from: {DATASET_DIR.resolve()}")
    
    if not DATASET_DIR.exists():
        print(f"❌ Error: Folder '{DATASET_DIR}' not found. Please create it.")
        return

    # 1. Connect to DB
    await db_manager.connect()
    db = await get_db()
    vdb_client = get_vector_db()

    # 2. Get list of files
    files = [f for f in DATASET_DIR.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS]
    print(f"📦 Found {len(files)} files to process.")

    # 3. Process Each File (SLOWLY to avoid Quota Limits)
    for index, file_path in enumerate(files):
        print(f"\n[{index+1}/{len(files)}] Processing: {file_path.name}...")
        
        # Check if already processed
        existing = await db.documents.find_one({
            "user_id": SYSTEM_USER_ID,
            "filename": file_path.name
        })
        
        if existing:
            print(f"   ⏩ Skipping (Already in Database)")
            continue

        try:
            # A. Extract Text
            pages = extract_text_from_file(file_path)
            
            # B. Chunking
            doc_id = str(uuid.uuid4())
            chunks = create_chunks(pages, file_path.name, doc_id)
            
            if not chunks:
                print("   ⚠️ Skipped (Empty text)")
                continue

            # C. Store in Vector DB (The "Permanent File")
            collection = get_or_create_collection(vdb_client, SYSTEM_USER_ID, "general")
            add_chunks_to_collection(collection, chunks)

            # D. Save Metadata
            doc_record = {
                "user_id": SYSTEM_USER_ID,
                "filename": file_path.name,
                "doc_id": doc_id,
                "subject": "general",
                "chunks_count": len(chunks),
                "source": "local_dataset",
                "created_at": datetime.utcnow()
            }
            await db.documents.insert_one(doc_record)
            print(f"   ✅ Saved {len(chunks)} chunks to Database.")

            # E. SLEEP TO SAVE QUOTA (Crucial Step)
            print("   💤 Sleeping 10s to respect Google Limits...")
            time.sleep(10) 

        except Exception as e:
            print(f"   ❌ Error: {e}")

    print("\n🎉 BUILD COMPLETE! The database is now ready for the Chatbot.")
    await db_manager.disconnect()

if __name__ == "__main__":
    asyncio.run(ingest_safe_mode())