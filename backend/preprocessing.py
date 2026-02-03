# backend/preprocessing.py

from typing import List, Dict, Any
import re


def clean_text(text: str) -> str:
    """
    Clean raw text from file_handler.py before chunking.
    
    Removes extra whitespace, normalizes newlines, strips weird characters.
    """
    if not text:
        return ""
    
    # Normalize whitespace and newlines
    text = re.sub(r'\n\s*\n', '\n\n', text)  # Multiple newlines → double newline
    text = re.sub(r'[ \t]+', ' ', text)      # Multiple spaces/tabs → single space
    text = re.sub(r'\s*\n\s*', '\n', text)   # Space around newlines
    
    # Remove excessive leading/trailing whitespace
    text = text.strip()
    
    # Optional: remove strange unicode (keep for now)
    # text = text.encode('ascii', 'ignore').decode('ascii')
    
    return text


def chunk_text(
    text: str,
    chunk_size: int = 600,
    chunk_overlap: int = 100,
) -> List[str]:
    """
    Split cleaned text into overlapping chunks.
    
    Simple character-based splitting that tries to break at sentence boundaries.
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        # Calculate end of this chunk
        end = start + chunk_size
        
        # Try to end at sentence boundary (., !, ?, newline)
        if end < len(text):
            for boundary in [".", "!", "?", "\n\n", "\n"]:
                boundary_pos = text.rfind(boundary, start, end)
                if boundary_pos > start + chunk_size // 2:  # Don't break too early
                    end = boundary_pos + len(boundary)
                    break
        
        # Extract chunk
        chunk = text[start:end].strip()
        if chunk:  # Skip empty chunks
            chunks.append(chunk)
        
        # Move start forward (with overlap)
        start += chunk_size - chunk_overlap
        
        # Safety check to avoid infinite loop
        if start >= len(text):
            break
    
    return chunks


def create_chunks(
    raw_text: str,
    source_filename: str,
    doc_id: str,
    chunk_size: int = 600,
    chunk_overlap: int = 100,
) -> List[Dict[str, Any]]:
    """
    MAIN FUNCTION used by upload.py.
    
    Turns raw text → list of chunk dicts ready for vector_db.py.
    
    Each chunk has:
    - "text": the chunk content
    - "source": original filename  
    - "doc_id": unique document ID
    - "chunk_index": position in document (0, 1, 2...)
    """
    
    # 1. Clean the text
    cleaned = clean_text(raw_text)
    if not cleaned:
        return []
    
    # 2. Split into chunks
    text_chunks = chunk_text(cleaned, chunk_size, chunk_overlap)
    
    # 3. Create chunk dicts with metadata
    chunks = []
    for i, chunk_text in enumerate(text_chunks):
        chunk = {
            "text": chunk_text,
            "source": source_filename,
            "doc_id": doc_id,
            "chunk_index": i,
            "chunk_size": len(chunk_text),
        }
        chunks.append(chunk)
    
    return chunks


# Default settings matching your project docs [file:164]
DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100
