# backend/api/ingest.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def ingest_health():
    return {"status": "Ingestion service ready"}