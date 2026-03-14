
from fastapi import APIRouter, Depends, HTTPException
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.vector_db import get_vector_db, get_or_create_collection
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
        # We need to search across collections or know which one.
        # For now, we search the system collection ("general") and the user's collection.
        # This is a bit inefficient if we don't know the collection.
        # However, we can try the system collection first, then user.
        
        # Try System Collection
        system_collection = get_or_create_collection(client, "global", "general")
        result = system_collection.get(ids=[chunk_id])
        
        if result and result['ids'] and len(result['ids']) > 0:
            return {
                "id": result['ids'][0],
                "text": result['documents'][0],
                "metadata": result['metadatas'][0]
            }
            
        # Try User Collection
        user_id = str(current_user["_id"])
        # We need to know the subject usually. 
        # But if we don't know it, we might have to iterate? 
        # Ideally, the citation should contain collection info or subject.
        # For this implementation, let's assume we pass subject as a query param or iterate?
        # Actually, let's just check the most likely ones or iterate if feasible.
        
        # Optimization: The chunk_id is UUID.
        
        # If we can't find it easily without subject, we might need to store a mapping in MongoDB?
        # Or, we can just search the user's active subjects. 
        # For now, let's try a default subject "general" for user too.
        
        user_collection = get_or_create_collection(client, user_id, "general")
        result = user_collection.get(ids=[chunk_id])
        
        if result and result['ids'] and len(result['ids']) > 0:
            return {
                "id": result['ids'][0],
                "text": result['documents'][0],
                "metadata": result['metadatas'][0]
            }
            
        # If user has other subjects, we might miss it. 
        # Future improvement: Store source collection in citation metadata.
        
        raise HTTPException(status_code=404, detail="Chunk not found")
        
    except Exception as e:
        logger.error(f"Error fetching chunk {chunk_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
