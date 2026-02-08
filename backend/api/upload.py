# backend/api/upload.py

import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form

from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.file_handler import save_upload_to_disk, extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import (
    get_vector_db,
    get_or_create_collection,
    add_chunks_to_collection,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# ================= CONFIG =================

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".txt",
    ".pptx", ".ppt",
    ".jpg", ".jpeg", ".png",
}

MAX_FILE_SIZE_MB = 20  # safety limit


# ================= ROUTES =================

@router.post("/")
async def upload_document(
    file: UploadFile = File(...),
    subject: Optional[str] = Form("general"),
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = str(current_user["_id"])

    if not file.filename:
        raise HTTPException(400, "Uploaded file must have a filename.")

    file_ext = "." + file.filename.split(".")[-1].lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Invalid file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    logger.info(f"[UPLOAD] User={user_id} File={file.filename}")

    # ================= READ FILE =================

    try:
        file_bytes = await file.read()
    except Exception as e:
        logger.error(f"[READ ERROR] {e}")
        raise HTTPException(400, "Could not read uploaded file.")

    if not file_bytes:
        raise HTTPException(400, "Uploaded file is empty.")

    if len(file_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            400, f"File too large. Max allowed is {MAX_FILE_SIZE_MB} MB."
        )

    # ================= SAVE =================

    try:
        file_path = save_upload_to_disk(file.filename, file_bytes, user_id)
    except Exception as e:
        logger.exception("[SAVE ERROR]")
        raise HTTPException(500, "Failed to save file to disk.")

    # ================= EXTRACT TEXT =================

    try:
        raw_text = extract_text_from_file(file_path)
    except Exception as e:
        logger.exception("[EXTRACTION ERROR]")
        raise HTTPException(400, f"Could not extract text: {str(e)}")

    if not raw_text.strip():
        raise HTTPException(400, "No readable text found in document.")

    # ================= CHUNK =================

    doc_id = str(uuid.uuid4())
    chunks = create_chunks(raw_text, file.filename, doc_id)

    if not chunks:
        raise HTTPException(400, "Document could not be chunked.")

    # ================= VECTOR DB =================

    try:
        client = get_vector_db()
        collection = get_or_create_collection(client, user_id, subject)
        add_chunks_to_collection(collection, chunks)
    except Exception as e:
        logger.exception("[VECTOR DB ERROR]")
        raise HTTPException(500, "Failed to index document.")

    # ================= METADATA DB =================

    doc_record = {
        "user_id": current_user["_id"],
        "doc_id": doc_id,
        "filename": file.filename,
        "subject": subject,
        "chunks_count": len(chunks),
        "file_path": str(file_path),
        "status": "processed",
        "created_at": datetime.utcnow(),
    }

    await db.documents.insert_one(doc_record)

    return {
        "status": "success",
        "doc_id": doc_id,
        "filename": file.filename,
        "chunks": len(chunks),
    }


@router.get("/")
async def list_documents(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    docs = (
        await db.documents.find(
            {"user_id": current_user["_id"]}
        )
        .sort("created_at", -1)
        .to_list(length=100)
    )

    for d in docs:
        d["_id"] = str(d["_id"])
        d["user_id"] = str(d["user_id"])

    return docs


@router.delete("/all")
async def delete_all_documents(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Delete all documents for the current user"""
    user_id = str(current_user["_id"])
    
    try:
        # Delete from MongoDB
        result = await db.documents.delete_many({"user_id": current_user["_id"]})
        deleted_count = result.deleted_count
        
        # Clear vector store for this user
        try:
            from backend.vector_db import get_vector_db, clear_user_data
            client = get_vector_db()
            clear_user_data(client, user_id)
        except Exception as e:
            logger.warning(f"Could not clear vector store: {e}")
        
        logger.info(f"[DELETE ALL] User={user_id} Deleted={deleted_count} documents")
        
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "message": f"Deleted {deleted_count} documents"
        }
    except Exception as e:
        logger.exception("[DELETE ERROR]")
        raise HTTPException(500, f"Failed to delete documents: {str(e)}")
