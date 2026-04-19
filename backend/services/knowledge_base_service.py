"""
backend/services/knowledge_base_service.py

Auto-indexes the base_dataset folder into the global ChromaDB collection
so that all new chat sessions have access to the shared knowledge base.

Called at app startup (non-blocking) and can also be triggered manually.
"""

import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Must match search_engine.py GLOBAL_USER_ID so the search engine can find them
GLOBAL_USER_ID = "global"
GLOBAL_SUBJECT = "general"

# Path to the shared knowledge base documents
BASE_DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "base_dataset"

# Extensions that can be successfully parsed by the existing file_handler
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".pptx", ".ppt"}


def _get_indexed_count() -> int:
    """Return how many chunks are currently stored in the global collection."""
    try:
        from backend.vector_db import get_vector_db, get_or_create_collection

        client = get_vector_db()
        collection = get_or_create_collection(client, GLOBAL_USER_ID, GLOBAL_SUBJECT)
        result = collection.get(include=["documents"], limit=1)
        # A non-empty 'ids' list means at least one chunk exists
        ids = result.get("ids") or []
        # ChromaDB /get returns a flat list of ids. Any positive length = indexed.
        return len(ids)
    except Exception as exc:
        logger.warning("[KB] Could not check global collection count: %s", exc)
        return -1  # Unknown – skip indexing to be safe


def index_base_dataset(force: bool = False) -> dict:
    """
    Index every supported document in data/base_dataset/ into the 'global/general'
    ChromaDB collection.

    Args:
        force: If True, re-index even when chunks already exist.

    Returns:
        Summary dict with counts.
    """
    from backend.file_handler import extract_text_from_file
    from backend.preprocessing import create_chunks
    from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection

    if not BASE_DATASET_DIR.exists():
        logger.warning("[KB] base_dataset directory not found at %s – skipping auto-index.", BASE_DATASET_DIR)
        return {"status": "skipped", "reason": "directory_not_found"}

    # Skip if already indexed (unless forced)
    if not force:
        existing = _get_indexed_count()
        if existing > 0:
            logger.info("[KB] Global knowledge base already has %s chunks – skipping re-index.", existing)
            return {"status": "skipped", "reason": "already_indexed", "existing_chunks": existing}

    # Collect all supported files (deduplicated)
    files = list(
        {
            f
            for ext in SUPPORTED_EXTENSIONS
            for f in BASE_DATASET_DIR.glob(f"**/*{ext}")
        }
    )

    if not files:
        logger.warning("[KB] No supported documents found in %s", BASE_DATASET_DIR)
        return {"status": "skipped", "reason": "no_files_found"}

    logger.info("[KB] Indexing %s documents into global knowledge base…", len(files))

    client = get_vector_db()
    collection = get_or_create_collection(client, GLOBAL_USER_ID, GLOBAL_SUBJECT)

    total_chunks = 0
    successful = 0
    failed = []

    for file_path in files:
        try:
            pages = extract_text_from_file(file_path)
            if not pages:
                failed.append((file_path.name, "no_text_extracted"))
                continue

            doc_id = str(uuid.uuid4())
            chunks = create_chunks(pages, file_path.name, doc_id)
            if not chunks:
                failed.append((file_path.name, "no_chunks_created"))
                continue

            add_chunks_to_collection(collection, chunks)
            total_chunks += len(chunks)
            successful += 1
            logger.info("[KB]  ✅ %s → %s chunks", file_path.name, len(chunks))

        except Exception as exc:
            logger.warning("[KB]  ❌ %s: %s", file_path.name, str(exc)[:120])
            failed.append((file_path.name, str(exc)[:80]))

    summary = {
        "status": "completed",
        "total_files": len(files),
        "successful": successful,
        "failed_count": len(failed),
        "total_chunks_added": total_chunks,
        "failed_files": [f[0] for f in failed[:10]],
    }
    logger.info("[KB] Indexing complete: %s", summary)
    return summary


async def auto_index_on_startup() -> None:
    """
    Asynchronous wrapper called from the FastAPI lifespan.
    Runs the indexer in a thread-pool executor so it does not block the event loop.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    try:
        summary = await loop.run_in_executor(None, index_base_dataset)
        logger.info("[KB] Startup knowledge-base check: %s", summary)
    except Exception as exc:
        # Never crash the server because of a KB indexing failure
        logger.error("[KB] Startup indexing failed (non-fatal): %s", exc)
