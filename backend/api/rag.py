
from fastapi import APIRouter, Depends, HTTPException
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.vector_db import get_vector_db
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/chunks/{chunk_id}")
async def get_chunk_details(
    chunk_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Retrieve details for a specific chunk by ID.
    Used for citation previews.
    """
    try:
        client = get_vector_db()
        user_id = str(current_user["_id"])
        collections = client.list_collections()

        candidate_names = ["user_global_general"]
        candidate_names.extend(
            col.get("name")
            for col in collections
            if col.get("name", "").startswith(f"user_{user_id}_")
        )

        seen = set()
        for name in candidate_names:
            if not name or name in seen:
                continue
            seen.add(name)

            collection = client.get_or_create_collection(name)
            result = collection.get(ids=[chunk_id])
            if result and result["ids"] and len(result["ids"]) > 0:
                return {
                    "id": result["ids"][0],
                    "text": result["documents"][0],
                    "metadata": result["metadatas"][0]
                }

        raise HTTPException(status_code=404, detail="Chunk not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching chunk {chunk_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
