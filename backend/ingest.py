# backend/ingest.py

"""
Document ingestion pipeline for background processing
"""

import asyncio
from typing import Optional
from backend.utils.db import get_database
from backend.file_handler import extract_text_from_file
from backend.preprocessing import create_chunks
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection
from backend.utils.helpers import doc_to_dict
import logging

logger = logging.getLogger(__name__)

async def ingest_document_pipeline(user_id: str, doc_id: str, subject: Optional[str] = None):
    """
    Background task to process a document:
    1. Extract text from file
    2. Create chunks
    3. Generate embeddings
    4. Store in vector database
    5. Update document status
    """
    try:
        logger.info(f"Starting ingestion pipeline for doc {doc_id}")
        
        # Get document info from database
        db = await get_database()
        doc = await db.documents.find_one({"_id": doc_id})
        
        if not doc:
            logger.error(f"Document {doc_id} not found")
            return
        
        # Extract text from file
        file_path = doc.get("file_path")
        if not file_path:
            logger.error(f"No file path for document {doc_id}")
            return
        
        logger.info(f"Extracting text from {file_path}")
        text_content = extract_text_from_file(file_path)
        
        if not text_content or len(text_content.strip()) < 10:
            logger.error(f"No text extracted from {file_path}")
            await db.documents.update_one(
                {"_id": doc_id},
                {"$set": {"status": "failed", "error": "No text extracted"}}
            )
            return
        
        # Create chunks
        logger.info(f"Creating chunks for document {doc_id}")
        chunks = create_chunks(text_content, doc["filename"])
        
        if not chunks:
            logger.error(f"No chunks created for document {doc_id}")
            await db.documents.update_one(
                {"_id": doc_id},
                {"$set": {"status": "failed", "error": "No chunks created"}}
            )
            return
        
        # Add doc_id to chunks
        for chunk in chunks:
            chunk["doc_id"] = doc_id
        
        # Store in vector database
        logger.info(f"Storing {len(chunks)} chunks in vector database")
        client = get_vector_db()
        collection = get_or_create_collection(client, user_id, subject)
        chunk_ids = add_chunks_to_collection(collection, chunks)
        
        # Update document status
        await db.documents.update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "status": "processed",
                    "chunks_count": len(chunks),
                    "chunk_ids": chunk_ids
                }
            }
        )
        
        logger.info(f"Successfully processed document {doc_id} with {len(chunks)} chunks")
        
    except Exception as e:
        logger.error(f"Error in ingestion pipeline for doc {doc_id}: {e}")
        
        # Update document status to failed
        try:
            db = await get_database()
            await db.documents.update_one(
                {"_id": doc_id},
                {"$set": {"status": "failed", "error": str(e)}}
            )
        except Exception as update_error:
            logger.error(f"Failed to update document status: {update_error}")


def ingest_document_pipeline_sync(user_id: str, doc_id: str, subject: Optional[str] = None):
    """Synchronous wrapper for the async ingestion pipeline"""
    asyncio.run(ingest_document_pipeline(user_id, doc_id, subject))