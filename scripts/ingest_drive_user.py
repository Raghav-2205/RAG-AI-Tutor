# scripts/ingest_drive_user.py
import asyncio
import uuid
import sys
from pathlib import Path
from datetime import datetime

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from backend.file_handler import extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection
from backend.utils.db import get_db, db_manager

# --- CONFIG ---
CREDENTIALS_FILE = "credentials.json"
FOLDER_ID = "YOUR_DRIVE_FOLDER_ID_HERE"  # <--- PASTE YOUR FOLDER ID
TEMP_DIR = Path("temp_downloads")
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

async def ingest():
    print("🚀 Google Drive User Ingestion")
    
    # 1. Ask for Email to link data
    user_email = input("Enter the email address of the user to link data to: ").strip().lower()

    # 2. Connect DB & Find User
    await db_manager.connect()
    db = await get_db()
    user = await db.users.find_one({"email": user_email})
    
    if not user:
        print(f"❌ User '{user_email}' not found. Please register via the Frontend first.")
        return

    user_id = str(user["_id"])
    print(f"✅ Found User: {user['name']} (ID: {user_id})")

    # 3. Setup Drive
    if not Path(CREDENTIALS_FILE).exists():
        print("❌ credentials.json missing!")
        return
        
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)

    print(f"📂 Scanning Drive Folder...")
    results = service.files().list(
        q=f"'{FOLDER_ID}' in parents and trashed=false",
        fields="files(id, name, mimeType)", pageSize=50
    ).execute()
    files = results.get('files', [])

    if not files:
        print("⚠️ No files found.")
        return

    # 4. Process & Save to User Account
    TEMP_DIR.mkdir(exist_ok=True)
    vdb_client = get_vector_db()
    collection = get_or_create_collection(vdb_client, user_id, "general")

    for file in files:
        name = file['name']
        print(f"⬇️ Processing: {name}")
        
        # Download
        file_path = TEMP_DIR / name
        request = service.files().get_media(fileId=file['id'])
        with open(file_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done: _, done = downloader.next_chunk()

        try:
            # Extract & Chunk
            pages = extract_text_from_file(file_path)
            doc_id = str(uuid.uuid4())
            chunks = create_chunks(pages, name, doc_id)

            # Store Vectors
            add_chunks_to_collection(collection, chunks)

            # Store Metadata (LINKED TO USER_ID)
            doc_record = {
                "user_id": user["_id"],  # Using the actual BSON ObjectId
                "filename": f"[Drive] {name}",
                "doc_id": doc_id,
                "subject": "general",
                "chunks_count": len(chunks),
                "status": "processed",
                "source": "drive",
                "created_at": datetime.utcnow()
            }
            await db.documents.insert_one(doc_record)
            print(f"   ✅ Saved to {user['name']}'s dashboard")

        except Exception as e:
            print(f"   ❌ Error: {e}")

    print("\n🎉 Done! The user can now chat with these files.")
    await db_manager.disconnect()

if __name__ == "__main__":
    asyncio.run(ingest())