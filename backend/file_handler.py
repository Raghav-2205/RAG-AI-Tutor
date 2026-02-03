# backend/file_handler.py
import os
from pathlib import Path
from pypdf import PdfReader
from docx import Document as DocxDocument
from backend.config import settings

# Create upload directory if it doesn't exist
BASE_UPLOAD_DIR = Path(settings.upload_dir)
BASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def save_upload_to_disk(filename: str, file_bytes: bytes, user_id: str) -> Path:
    """Saves the uploaded file to a user-specific folder."""
    user_folder = BASE_UPLOAD_DIR / str(user_id)
    user_folder.mkdir(parents=True, exist_ok=True)
    
    # Sanitize filename to prevent directory traversal
    sanitized_name = filename.replace("/", "_").replace("\\", "_")
    full_path = user_folder / sanitized_name
    
    with open(full_path, "wb") as f:
        f.write(file_bytes)
        
    return full_path

def extract_text_from_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        texts = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                texts.append(txt)
        return "\n\n".join(texts)
    except Exception as e:
        print(f"Error reading PDF {path}: {e}")
        return ""

def extract_text_from_docx(path: Path) -> str:
    try:
        doc = DocxDocument(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        print(f"Error reading DOCX {path}: {e}")
        return ""

def extract_text_from_file(file_path: Path) -> str:
    """Main entry point to extract text based on extension."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    text = ""

    if ext == ".pdf":
        text = extract_text_from_pdf(path)
    elif ext == ".docx":
        text = extract_text_from_docx(path)
    elif ext == ".txt":
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    if not text.strip():
        raise ValueError("No text could be extracted from file.")
        
    return text