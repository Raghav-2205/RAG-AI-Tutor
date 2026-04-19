# backend/api/upload.py

import uuid
import logging
from datetime import datetime, timezone
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

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
    chat_id: Optional[str] = Form(None),
    class_id: Optional[str] = Form(None),
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
        pages = extract_text_from_file(file_path)
    except Exception as e:
        logger.exception("[EXTRACTION ERROR]")
        raise HTTPException(400, f"Could not extract text: {str(e)}")

    if not pages:
        raise HTTPException(400, "No readable text found in document.")

    full_text = "\n".join(
        page.get("text", "") if isinstance(page, dict) else str(page)
        for page in pages
    )

    # ================= CHUNK =================

    doc_id = str(uuid.uuid4())
    chunks = create_chunks(pages, file.filename, doc_id)

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
        "created_at": _utcnow(),
    }

    await db.documents.insert_one(doc_record)

    # ================= CREATE OR UPDATE CHAT SESSION =================
    if chat_id:
        session = await db.chat_sessions.find_one({"chat_id": chat_id, "user_id": user_id})
        if session:
            doc_ids = list(session.get("document_ids", []))
            doc_names = list(session.get("document_names", []))
             
            # backward compatibility for single document setup
            if "document_id" in session and session["document_id"] and session["document_id"] not in doc_ids:
                doc_ids.append(session["document_id"])
                doc_names.append(session.get("document_name", "Unknown"))

            previous_file_count = max(int(session.get("file_count") or 0), len(doc_ids))

            if doc_id not in doc_ids:
                doc_ids.append(doc_id)
                doc_names.append(file.filename)

            resulting_file_count = len(doc_ids)
            legacy_document_id = doc_ids[0] if resulting_file_count == 1 else None
            legacy_document_name = doc_names[0] if resulting_file_count == 1 else ", ".join(doc_names)
             
            await db.chat_sessions.update_one(
                {"chat_id": chat_id},
                {"$set": {
                    "scope_mode": "document_scoped",
                    "document_ids": doc_ids,
                    "document_names": doc_names,
                    "file_count": resulting_file_count,
                    "document_id": legacy_document_id,
                    "document_name": legacy_document_name,
                }}
            )
            logger.info(f"[UPLOAD] Appended doc {doc_id} to chat session {chat_id}")

            if resulting_file_count >= 2:
                try:
                    from backend.services.grag_service import ensure_grag_for_session

                    await ensure_grag_for_session(
                        db,
                        chat_id,
                        user_id,
                        new_text=full_text,
                        source=file.filename,
                        chunks=chunks,
                        force_rebuild=previous_file_count < 2,
                    )
                except Exception as e:
                    logger.warning(f"Failed to update GRAG knowledge graph: {e}")

            return {
                "status": "success",
                "doc_id": doc_id,
                "chat_id": chat_id,
                "filename": file.filename,
                "chunks": len(chunks),
            }

    # Fallback to creating a new one
    chat_id = str(uuid.uuid4())
    chat_session = {
        "chat_id": chat_id,
        "user_id": str(current_user["_id"]),  # CONVERT TO STRING
        "scope_mode": "document_scoped",
        "document_ids": [doc_id],
        "document_names": [file.filename],
        "file_count": 1,
        "document_id": doc_id,
        "document_name": file.filename, # For UI
        "subject": subject,
        "class_id": class_id, # Added LMS context
        "title": f"Chat about {file.filename}",
        "messages": [],
        "created_at": _utcnow(),
        "updated_at": _utcnow()
    }
    
    await db.chat_sessions.insert_one(chat_session)
    logger.info(f"[UPLOAD] Created document-scoped chat session {chat_id} for doc {doc_id}")

    return {
        "status": "success",
        "doc_id": doc_id,
        "chat_id": chat_id,             # RETURN CHAT ID
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
