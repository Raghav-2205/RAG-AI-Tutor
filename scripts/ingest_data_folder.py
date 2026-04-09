
import os
import sys
import glob
import logging
import uuid
from typing import List, Dict, Any
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.config import settings
from backend.vector_db import get_vector_db, get_or_create_collection, add_chunks_to_collection
from backend.file_handler import extract_text_from_file
from backend.preprocessing import create_chunks

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.getcwd(), "data", "base_dataset")
SYSTEM_USER_ID = "global" # System-wide data
COLLECTION_NAME = "general" # System-wide subject

def recursive_find_files(directory: str) -> List[str]:
    extensions = ['*.pdf', '*.docx', '*.txt', '*.pptx']
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(directory, '**', ext), recursive=True))
    return files

def ingest_folder():
    logger.info(f"Starting ingestion from {DATA_DIR}")
    
    if not os.path.exists(DATA_DIR):
        logger.error(f"Data directory not found: {DATA_DIR}")
        return

    files = recursive_find_files(DATA_DIR)
    logger.info(f"Found {len(files)} files.")
    
    # Connect to DB
    client = get_vector_db()
    # verify connectivity
    try:
        client.list_collections()
    except Exception as e:
        logger.error(f"Cannot connect to ChromaDB: {e}")
        return

    # Get Collection
    # We use a specific system user ID for the base dataset
    collection = get_or_create_collection(client, SYSTEM_USER_ID, COLLECTION_NAME)
    logger.info(f"Target Collection: {collection.name}")
    
    total_chunks = 0
    
    for file_path in files:
        filename = os.path.basename(file_path)
        logger.info(f"Processing: {filename}")
        
        try:
            # 1. Extract
            pages = extract_text_from_file(file_path)
            if not pages:
                logger.warning(f"No pages extracted from {filename}")
                continue
                
            # 2. Chunk
            doc_id = str(uuid.uuid4())
            chunks = create_chunks(pages, filename, doc_id)
            
            if not chunks:
                logger.warning(f"No chunks created for {filename}")
                continue
                
            logger.info(f"  > Created {len(chunks)} chunks.")
            
            # 3. Index
            # add_chunks_to_collection handles embeddings via embedding_service
            add_chunks_to_collection(collection, chunks)
            
            total_chunks += len(chunks)
            
        except Exception as e:
            logger.error(f"Failed to process {filename}: {e}")
            
    logger.info(f"Ingestion Complete. Total Chunks Indexed: {total_chunks}")

if __name__ == "__main__":
    ingest_folder()
