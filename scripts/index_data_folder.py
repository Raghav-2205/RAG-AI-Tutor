#!/usr/bin/env python3
"""
Data Folder Indexing Script

Indexes all documents from the data/base_dataset folder into the RAG vector store.
This runs as a one-time setup or can be called to refresh the index.

Usage:
    python scripts/index_data_folder.py
"""

import os
import sys
import uuid
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.file_handler import extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection


# Constants
DATA_FOLDER = Path(__file__).parent.parent / "data" / "base_dataset"
GLOBAL_USER_ID = "global"  # Used for pre-indexed documents available to all users
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".pptx"}


def index_data_folder():
    """Index all supported documents from the data folder."""
    print("=" * 60)
    print("RAG AI Tutor - Data Folder Indexing")
    print("=" * 60)
    
    if not DATA_FOLDER.exists():
        print(f"❌ Data folder not found: {DATA_FOLDER}")
        return
    
    # Get all supported files
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(DATA_FOLDER.glob(f"*{ext}"))
        files.extend(DATA_FOLDER.glob(f"**/*{ext}"))  # Also search subdirectories
    
    files = list(set(files))  # Remove duplicates
    print(f"📂 Found {len(files)} documents to index\n")
    
    if not files:
        print("❌ No supported documents found.")
        return
    
    # Initialize vector store
    client = get_vector_db()
    collection = get_or_create_collection(client, GLOBAL_USER_ID, "general")
    
    total_chunks = 0
    successful_files = 0
    failed_files = []
    
    for i, file_path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] Processing: {file_path.name}")
        
        try:
            # Extract text
            text = extract_text_from_file(file_path)
            
            if not text or not text.strip():
                print(f"   ⚠️ No text extracted (may be scanned/image-based)")
                failed_files.append((file_path.name, "No text extracted"))
                continue
            
            # Create chunks
            doc_id = str(uuid.uuid4())
            chunks = create_chunks(text, file_path.name, doc_id)
            
            if not chunks:
                print(f"   ⚠️ No chunks created")
                failed_files.append((file_path.name, "No chunks created"))
                continue
            
            # Add to vector store
            add_chunks_to_collection(collection, chunks)
            
            print(f"   ✅ Indexed {len(chunks)} chunks")
            total_chunks += len(chunks)
            successful_files += 1
            
        except Exception as e:
            print(f"   ❌ Error: {str(e)[:50]}")
            failed_files.append((file_path.name, str(e)[:50]))
    
    print("\n" + "=" * 60)
    print("INDEXING COMPLETE")
    print("=" * 60)
    print(f"✅ Successfully indexed: {successful_files}/{len(files)} files")
    print(f"📊 Total chunks created: {total_chunks}")
    
    if failed_files:
        print(f"\n⚠️ Failed files ({len(failed_files)}):")
        for name, reason in failed_files[:10]:  # Show first 10
            print(f"   - {name}: {reason}")
        if len(failed_files) > 10:
            print(f"   ... and {len(failed_files) - 10} more")
    
    print("\n🎉 Data folder indexing complete!")
    print("   Users can now ask questions about the indexed documents.")


if __name__ == "__main__":
    index_data_folder()
