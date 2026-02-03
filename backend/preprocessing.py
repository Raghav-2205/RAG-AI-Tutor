# backend/preprocessing.py
import re
from typing import List, Dict, Any
from backend.config import settings

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Normalize whitespace
    text = re.sub(r'[\t]', ' ', text)
    text = re.sub(r'\s*\n\s*', '\n', text)  # Clean newlines
    text = re.sub(r' +', ' ', text)         # Remove double spaces
    return text.strip()

def chunk_text(text: str, chunk_size: int = 600, chunk_overlap: int = 100) -> List[str]:
    """Sliding window chunking."""
    if len(text) <= chunk_size:
        return [text]
        
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        
        # Try to find a sentence boundary (., !, ?, \n) near the end
        if end < text_len:
            # Look for boundary in the last 20% of the chunk
            boundary_search = text[end - 100 : end + 50] 
            # Simple heuristic: look for last period or newline
            last_period = boundary_search.rfind('.')
            if last_period != -1:
                end = (end - 100) + last_period + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
            
        # Move forward, keeping the overlap
        start = end - chunk_overlap
        
        # Prevent infinite loops if no progress
        if start >= text_len:
            break
            
    return chunks

def create_chunks(raw_text: str, filename: str, doc_id: str) -> List[Dict[str, Any]]:
    """Processing pipeline: Clean -> Chunk -> Format"""
    cleaned = clean_text(raw_text)
    if not cleaned:
        return []
        
    text_chunks = chunk_text(cleaned, settings.chunk_size, settings.chunk_overlap)
    
    formatted_chunks = []
    for i, chunk_text in enumerate(text_chunks):
        formatted_chunks.append({
            "text": chunk_text,
            "source": filename,
            "doc_id": doc_id,
            "chunk_index": i,
            "chunk_size": len(chunk_text)
        })
        
    return formatted_chunks