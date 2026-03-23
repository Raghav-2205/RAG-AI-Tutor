import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.services import grag_service

logger = logging.getLogger(__name__)
router = APIRouter()

class GragQueryRequest(BaseModel):
    session_id: str
    query: str
    new_file_text: Optional[str] = None

@router.post("/query")
async def process_grag_query(
    request: GragQueryRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Route to manually test the GRAG pipeline pipeline execution.
    Usually invoked inside a core `rag.py` module during live chat instead.
    """
    results = await grag_service.conditional_retrieve(
        db=db,
        session_id=request.session_id,
        user_id=str(current_user["_id"]),
        query=request.query,
        new_file_text=request.new_file_text,
        rag_retrieve_fn=None # You would provide a RAG function here if you are connecting it deeply
    )
    return results
