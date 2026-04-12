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

def _split_structural_units(text: str) -> List[str]:
    """Prefer paragraph and list boundaries before falling back to sentence-ish blocks."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", text) if block.strip()]
    if not blocks:
        return []

    units: List[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) > 1 and sum(1 for line in lines if re.match(r"^([\-*•]|\d+[.)])\s+", line)) >= max(1, len(lines) // 2):
            units.extend(lines)
            continue

        sentence_like = [
            segment.strip()
            for segment in re.split(r"(?<=[.!?])\s+|(?<=[:;])\s+|\n", block)
            if segment.strip()
        ]
        units.extend(sentence_like or [block])

    return units


def _dedupe_nearby_chunks(chunks: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for chunk in chunks:
        fingerprint = re.sub(r"\s+", " ", chunk).strip().lower()
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(chunk)
    return deduped


def chunk_text(text: str, chunk_size: int = 600, chunk_overlap: int = 100) -> List[str]:
    """Structure-aware chunking with bounded overlap for better retrieval coherence."""
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    units = _split_structural_units(text)
    if not units:
        return [text]

    chunks: List[str] = []
    current_units: List[str] = []
    current_length = 0

    def flush_chunk() -> None:
        nonlocal current_units, current_length
        if not current_units:
            return
        chunk = "\n".join(current_units).strip()
        if chunk:
            chunks.append(chunk)

        if chunk_overlap > 0:
            overlap_units: List[str] = []
            overlap_length = 0
            for unit in reversed(current_units):
                projected = overlap_length + len(unit) + (1 if overlap_units else 0)
                if projected > chunk_overlap and overlap_units:
                    break
                overlap_units.insert(0, unit)
                overlap_length = projected
                if overlap_length >= chunk_overlap:
                    break
            current_units = overlap_units
            current_length = sum(len(unit) for unit in current_units) + max(0, len(current_units) - 1)
        else:
            current_units = []
            current_length = 0

    for unit in units:
        unit = unit.strip()
        if not unit:
            continue

        if len(unit) > chunk_size:
            if current_units:
                flush_chunk()

            start = 0
            while start < len(unit):
                end = min(start + chunk_size, len(unit))
                boundary_region = unit[start:min(len(unit), end + 80)]
                boundary_match = None
                for pattern in (r"\n\s*\n", r"(?<=[.!?])\s", r"\n", r"(?<=[;:])\s"):
                    matches = list(re.finditer(pattern, boundary_region))
                    if matches:
                        boundary_match = start + matches[-1].end()
                        break
                slice_end = boundary_match if boundary_match and boundary_match > start else end
                fragment = unit[start:slice_end].strip()
                if fragment:
                    chunks.append(fragment)
                next_start = max(slice_end - chunk_overlap, start + 1)
                if next_start <= start:
                    next_start = slice_end
                start = next_start
            current_units = []
            current_length = 0
            continue

        projected_length = current_length + len(unit) + (1 if current_units else 0)
        if projected_length > chunk_size and current_units:
            flush_chunk()

        current_units.append(unit)
        current_length = sum(len(item) for item in current_units) + max(0, len(current_units) - 1)

    if current_units:
        flush_chunk()

    return _dedupe_nearby_chunks(chunks)


def analyze_chunk_set(chunks: List[str]) -> Dict[str, Any]:
    if not chunks:
        return {
            "chunk_count": 0,
            "avg_chunk_size": 0.0,
            "min_chunk_size": 0,
            "max_chunk_size": 0,
            "short_chunk_count": 0,
            "duplicate_chunk_count": 0,
            "duplicate_rate": 0.0,
        }

    sizes = [len(chunk) for chunk in chunks]
    normalized = [re.sub(r"\s+", " ", chunk).strip().lower() for chunk in chunks]
    unique_count = len(set(normalized))
    duplicate_count = len(chunks) - unique_count

    return {
        "chunk_count": len(chunks),
        "avg_chunk_size": round(sum(sizes) / len(sizes), 2),
        "min_chunk_size": min(sizes),
        "max_chunk_size": max(sizes),
        "short_chunk_count": sum(1 for size in sizes if size < max(80, settings.chunk_size * 0.25)),
        "duplicate_chunk_count": duplicate_count,
        "duplicate_rate": round(duplicate_count / len(chunks), 4),
    }

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
