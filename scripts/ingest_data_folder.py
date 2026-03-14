
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
from backend.file_handler import extract_text_from_file # Reuse existing extraction logic if possible? 
# Wait, extract_text_from_file in file_handler might be simple. Let's check it or verify imports.
# Actually, I'll implement robust extraction here or import if it's good.
# backend.file_handler.extract_text_from_file uses pdfplumber etc.
# Requirements has pypdf, python-docx, python-pptx.
# Let's see if backend.file_handler is available and good. 

# Re-implementing extraction here to be sure and self-contained for the script (or reusing is better DRY).
# Let's import it.
from backend.file_handler import extract_text_from_file

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
DATA_DIR = os.path.join(os.getcwd(), "data", "base_dataset")
SYSTEM_USER_ID = "global" # System-wide data
COLLECTION_NAME = "general" # System-wide subject

def recursive_find_files(directory: str) -> List[str]:
    extensions = ['*.pdf', '*.docx', '*.txt', '*.pptx']
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(directory, '**', ext), recursive=True))
    return files

def create_chunks(pages: List[Dict[str, Any]], filename: str, doc_id: str) -> List[Dict[str, Any]]:
    chunks = []
    if not pages:
        return chunks
        
    chunk_index = 0
    file_type = Path(filename).suffix.lower().replace('.', '')
    
    for page_data in pages:
        text = page_data.get("text", "")
        page_num = page_data.get("page", 1)
        
        if not text:
            continue
            
        text_len = len(text)
        start = 0
        
        while start < text_len:
            end = start + CHUNK_SIZE
            
            # Try to find a sentence boundary
            if end < text_len:
                # Look for period, newline, or question mark
                # simple lookahead
                next_period = text.find('.', end - 50, end + 50)
                if next_period != -1:
                    end = next_period + 1
                else:
                    next_newline = text.find('\n', end - 50, end + 50)
                    if next_newline != -1:
                        end = next_newline + 1
            
            chunk_text = text[start:end].strip()
            
            if chunk_text:
                chunk_id = f"{doc_id}_p{page_num}_c{chunk_index}"
                chunks.append({
                    "id": chunk_id,
                    "text": chunk_text,
                    "source": filename,
                    "doc_id": doc_id,
                    "chunk_index": chunk_index,
                    "start_offset": start,
                    "end_offset": end,
                    "metadata": {
                        "source": filename,
                        "page": page_num,
                        "type": file_type,
                        "chunk_id": chunk_id,
                        "doc_id": doc_id
                    }
                })
                chunk_index += 1
                
            start = end - CHUNK_OVERLAP
            if start < 0: start = 0 # Should not happen if overlap < size
            
            # Prevent infinite loop if we aren't advancing
            if start >= end:
                start = end
                
    return chunks

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
