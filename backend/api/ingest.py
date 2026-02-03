# backend/api/ingest.py

from fastapi import APIRouter, Depends, BackgroundTasks
from typing import Optional

from backend.utils import get_current_user, api_logger
from backend.ingest import ingest_document_pipeline


router = APIRouter(tags=["ingest"])


@router.post("/start")
async def start_ingestion(
    doc_id: str,
    subject: Optional[str] = None,
    current_user=Depends(get_current_user),
    background_tasks: BackgroundTasks = None
):
    """
    Trigger document ingestion pipeline (async)
    """
    user_id = str(current_user["_id"])
    api_logger.info(f"User {user_id} starting ingestion for doc {doc_id}")
    
    background_tasks.add_task(
        ingest_document_pipeline,
        user_id=user_id,
        doc_id=doc_id,
        subject=subject
    )
    
    return {"status": "ingestion_started", "doc_id": doc_id}
