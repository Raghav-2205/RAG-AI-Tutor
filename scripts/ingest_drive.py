import os
import sys
import asyncio
import uuid
from pathlib import Path
from datetime import datetime

# Add project root to path so we can import backend modules
sys.path.append(str(Path(__file__).parent.parent))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Import your existing backend logic
from backend.file_handler import extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection
from backend.utils.db import get_db, db_manager

# CONFIGURATION
CREDENTIALS_FILE = "credentials.json"
# PASTE YOUR FOLDER ID HERE (It's the weird string at the end of your Drive Folder URL)
FOLDER_ID = "1LcfrlQdKipXStx28_5sDWp9jQkjOAZx_"
TEMP_DOWNLOAD_DIR = Path("temp_drive_downloads")

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

async def ingest_drive_folder():
    print(f"🚀 Starting Google Drive Ingestion...")

    # 1. Authenticate with Google Drive
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ Error: {CREDENTIALS_FILE} not found. Please add your service account keys.")
        return

    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)

    # 2. List Files in Folder
    print(f"📂 Scanning folder: {FOLDER_ID}...")
    results = service.files().list(
        q=f"'{FOLDER_ID}' in parents and trashed=false",
        fields="nextPageToken, files(id, name, mimeType)",
        pageSize=100
    ).execute()
    
    files = results.get('files', [])
    if not files:
        print("⚠️ No files found in this folder.")
        return

    print(f"found {len(files)} files. Processing...")
    
    # Ensure temp dir exists
    TEMP_DOWNLOAD_DIR.mkdir(exist_ok=True)
    
    # Connect to DB
    await db_manager.connect()
    db = await get_db()
    
    # Initialize Vector DB
    vdb_client = get_vector_db()

    # 3. Process Each File
    for file in files:
        file_id = file['id']
        name = file['name']
        mime = file['mimeType']
        
        # Skip folders or Google Docs (unless you convert them, sticking to PDF/Docs/Txt for now)
        if "folder" in mime or "apps.googleusercontent" in mime:
            print(f"⏩ Skipping {name} (unsupported type)")
            continue

        print(f"⬇️ Downloading {name}...")
        request = service.files().get_media(fileId=file_id)
        file_path = TEMP_DOWNLOAD_DIR / name
        
        with open(file_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()

        try:
            # A. Extract Text (Using your existing backend)
            print(f"   📖 Reading text...")
            pages = extract_text_from_file(file_path)
            
            # B. Chunking
            doc_id = str(uuid.uuid4())
            chunks = create_chunks(pages, name, doc_id)
            print(f"   🧩 Created {len(chunks)} chunks")

            # C. Store in Vector DB (Chroma)
            # We add them to a "general" collection for the admin/default user
            # You might want to hardcode a specific user_id here or use a "system" ID
            SYSTEM_USER_ID = "system_dataset_v1" 
            
            collection = get_or_create_collection(vdb_client, SYSTEM_USER_ID, "general")
            add_chunks_to_collection(collection, chunks)

            # D. Save Metadata to MongoDB (So it shows in dashboard)
            doc_record = {
                "user_id": SYSTEM_USER_ID, # Or your specific user ID
                "filename": f"[Drive] {name}",
                "doc_id": doc_id,
                "subject": "general",
                "chunks_count": len(chunks),
                "file_path": str(file_path), # Keeping local path ref for now
                "source": "google_drive",
                "drive_id": file_id,
                "status": "processed",
                "created_at": datetime.utcnow()
            }
            await db.documents.insert_one(doc_record)
            print(f"   ✅ Successfully ingested {name}")

        except Exception as e:
            print(f"   ❌ Failed to process {name}: {e}")

    print("\n🎉 Ingestion Complete!")
    await db_manager.disconnect()

if __name__ == "__main__":
    # Install google library if missing: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
    asyncio.run(ingest_drive_folder())