#!/usr/bin/env python3
"""
Ingest semester 1 study materials from Google Drive
Automates PDF/DOCX processing and vectorization
"""

import os
import pickle
from pathlib import Path
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from backend.document_processor import process_document
from backend.vector_store import VectorStore

DRIVE_FOLDER_ID = "YOUR_GOOGLE_DRIVE_FOLDER_ID"
CREDENTIALS_FILE = "google_drive_credentials.json"

def authenticate_drive():
    """Authenticate with Google Drive API"""
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return build('drive', 'v3', credentials=creds)

def list_drive_files(service, folder_id):
    """List all files in Google Drive folder"""
    files = []
    page_token = None
    
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            spaces='drive',
            fields="nextPageToken, files(id, name, mimeType, size)",
            pageToken=page_token
        ).execute()
        
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    
    return [f for f in files if f['mimeType'] in [
        'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]]

def download_file(service, file_id, file_name):
    """Download file from Google Drive"""
    request = service.files().get_media(fileId=file_id)
    output_path = Path(f"temp_drive/{file_name}")
    output_path.parent.mkdir(exist_ok=True)
    
    with open(output_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
    
    return output_path

def main():
    """Main ingestion pipeline"""
    print("🔄 Ingesting Google Drive files...")
    
    service = authenticate_drive()
    files = list_drive_files(service, DRIVE_FOLDER_ID)
    
    vector_store = VectorStore()
    
    for file in files:
        print(f"📥 Processing {file['name']}...")
        local_path = download_file(service, file['id'], file['name'])
        
        # Process document
        chunks = process_document(str(local_path))
        
        # Vectorize and store
        vector_store.add_documents(chunks, metadata={'source': file['name'], 'drive_id': file['id']})
        
        local_path.unlink()  # Clean up
    
    print("✅ Drive ingestion complete!")

if __name__ == "__main__":
    main()
