# backend/api/upload.py

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import List
import uuid
from datetime import datetime

from backend.utils import get_db, get_current_user, api_logger
from backend.file_handler import save_upload_to_disk, extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection


router = APIRouter(tags=["upload"])


@router.post("/")
async def upload_document(
    file: UploadFile = File(...),
    subject: str = None,
    current_user=Depends(get_current_user),
    db=Depends(get_db)
):
    """
    COMPLETE PIPELINE: upload → save → extract → chunk → vectorize → store
    """
    user_id = str(current_user["_id"])
    
    # 1. Validate file
    if not file.content_type.startswith('application/'):
        raise HTTPException(400, "Only PDF/DOCX/TXT files supported")
    
    # 2. Save to disk
    file_path = save_upload_to_disk(file.filename, await file.read(), user_id)
    
    # 3. Extract text
    raw_text = extract_text_from_file(file_path)
    
    # 4. Create chunks
    doc_id = str(uuid.uuid4())
    chunks = create_chunks(raw_text, file.filename, doc_id)
    
    # 5. Store in ChromaDB
    client = get_vector_db()
    collection = get_or_create_collection(client, user_id, subject)
    chunk_ids = add_chunks_to_collection(collection, chunks)
    
    # 6. Save metadata to MongoDB
    doc_record = {
        "user_id": current_user["_id"],
        "filename": file.filename,
        "doc_id": doc_id,
        "subject": subject,
        "chunks_count": len(chunks),
        "file_path": str(file_path),
        "status": "processed",
        "created_at": datetime.utcnow(),
    }
    db.documents.insert_one(doc_record)
    
    api_logger.info(f"User {user_id} uploaded {file.filename}: {len(chunks)} chunks")
    
    return {
        "filename": file.filename,
        "chunks_count": len(chunks),
        "doc_id": doc_id,
        "status": "processed"
    }


@router.get("/")
async def list_documents(db=Depends(get_db), current_user=Depends(get_current_user)):
    docs = list(db.documents.find({"user_id": current_user["_id"]}))
    return [doc_to_dict(d) for d in docs]
