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
    """Sliding window chunking with lightweight boundary awareness."""
    if len(text) <= chunk_size:
        return [text]

    def find_boundary(window_start: int, window_end: int) -> int:
        search_start = max(window_start + int(chunk_size * 0.6), window_start)
        search_end = min(window_end + 80, text_len)
        boundary_region = text[search_start:search_end]

        boundary_patterns = [
            r'\n\s*\n',     # paragraph break
            r'(?<=[.!?])\s',
            r'\n',
            r'(?<=[;:])\s',
        ]

        for pattern in boundary_patterns:
            matches = list(re.finditer(pattern, boundary_region))
            if matches:
                return search_start + matches[-1].end()
        return window_end

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size

        # Try to find a sentence or paragraph boundary near the end of the window.
        if end < text_len:
            end = find_boundary(start, end)

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Move forward, keeping the overlap
        next_start = end - chunk_overlap
        if next_start <= start:
            next_start = end
        start = next_start

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
