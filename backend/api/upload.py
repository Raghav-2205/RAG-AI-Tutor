# backend/api/upload.py
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from typing import Optional

from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.file_handler import save_upload_to_disk, extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/")
async def upload_document(
    file: UploadFile = File(...),
    subject: Optional[str] = Form("general"),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    user_id = str(current_user["_id"])
    logger.info(f"User {user_id} uploading {file.filename}")

    # 1. Validation
    if not file.content_type.startswith(('application/', 'text/')):
         raise HTTPException(400, "Invalid file type. Please upload PDF, DOCX, or TXT.")

    # 2. Save to Disk
    try:
        file_bytes = await file.read()
        file_path = save_upload_to_disk(file.filename, file_bytes, user_id)
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        raise HTTPException(500, "Failed to save file to disk.")

    # 3. Extract Text
    try:
        raw_text = extract_text_from_file(file_path)
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        # Update DB status if you had created a record earlier, but here we just fail
        raise HTTPException(400, f"Could not extract text: {str(e)}")

    # 4. Create Chunks
    doc_id = str(uuid.uuid4())
    chunks = create_chunks(raw_text, file.filename, doc_id)
    
    if not chunks:
        raise HTTPException(400, "File is empty or contains no readable text.")

    # 5. Store in Vector DB (Chroma)
    try:
        client = get_vector_db()
        collection = get_or_create_collection(client, user_id, subject)
        add_chunks_to_collection(collection, chunks)
    except Exception as e:
        logger.error(f"Vector DB error: {e}")
        raise HTTPException(500, "Failed to index document.")

    # 6. Save Metadata to MongoDB
    doc_record = {
        "user_id": current_user["_id"],
        "filename": file.filename,
        "doc_id": doc_id,
        "subject": subject,
        "chunks_count": len(chunks),
        "file_path": str(file_path),
        "status": "processed",
        "created_at": datetime.utcnow()
    }
    await db.documents.insert_one(doc_record)

    return {
        "status": "success",
        "doc_id": doc_id,
        "filename": file.filename,
        "chunks": len(chunks)
    }

@router.get("/")
async def list_documents(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    docs = await db.documents.find(
        {"user_id": current_user["_id"]}
    ).sort("created_at", -1).to_list(length=100)
    
    # Helper to convert ObjectId to string if needed
    for d in docs:
        d["_id"] = str(d["_id"])
        d["user_id"] = str(d["user_id"])
        
    return docs