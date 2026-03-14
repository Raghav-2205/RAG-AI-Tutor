import re
from typing import List, Dict, Any
from pathlib import Path
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

def create_chunks(pages: List[Dict[str, Any]], filename: str, doc_id: str) -> List[Dict[str, Any]]:
    """Processing pipeline: Clean -> Chunk -> Format"""
    formatted_chunks = []
    file_type = Path(filename).suffix.lower().replace('.', '')
    
    chunk_index = 0
    
    for page_data in pages:
        raw_text = page_data.get("text", "")
        page_num = page_data.get("page", 1)
        
        cleaned = clean_text(raw_text)
        if not cleaned:
            continue
            
        text_chunks = chunk_text(cleaned, settings.chunk_size, settings.chunk_overlap)
        
        for chunk_content in text_chunks:
            chunk_id = f"{doc_id}_p{page_num}_c{chunk_index}"
            formatted_chunks.append({
                "id": chunk_id,
                "text": chunk_content,
                "source": filename,
                "doc_id": doc_id,
                "chunk_index": chunk_index,
                "chunk_size": len(chunk_content),
                "metadata": {
                    "source": filename,
                    "page": page_num,
                    "type": file_type,
                    "chunk_id": chunk_id,
                    "doc_id": doc_id
                }
            })
            chunk_index += 1
            
    return formatted_chunks