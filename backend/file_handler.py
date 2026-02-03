# backend/file_handler.py

import os
from pathlib import Path
from typing import Tuple

from pypdf import PdfReader
from docx import Document as DocxDocument


# Base folder where uploads are stored, e.g. data/uploads/
BASE_UPLOAD_DIR = Path("data") / "uploads"
BASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def save_upload_to_disk(filename: str, file_bytes: bytes, user_id: str) -> Path:
    """
    Save an uploaded file (from API) to disk under a user-specific folder.

    Returns the full Path to the saved file.
    """
    user_folder = BASE_UPLOAD_DIR / str(user_id)
    user_folder.mkdir(parents=True, exist_ok=True)

    sanitized_name = filename.replace("/", "_").replace("\\", "_")
    full_path = user_folder / sanitized_name

    with open(full_path, "wb") as f:
        f.write(file_bytes)

    return full_path


def extract_text_from_pdf(path: Path) -> str:
    """
    Extract text from a PDF using pypdf.
    """
    reader = PdfReader(str(path))
    texts = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            texts.append(txt)
    return "\n\n".join(texts)


def extract_text_from_docx(path: Path) -> str:
    """
    Extract text from a DOCX file using python-docx.
    """
    doc = DocxDocument(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def extract_text_from_txt(path: Path) -> str:
    """
    Read plain text from a .txt file.
    """
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def detect_file_type(path: Path) -> str:
    """
    Very simple file type detection based on extension.
    Returns: 'pdf', 'docx', 'txt', or 'unknown'.
    """
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in [".docx"]:
        return "docx"
    if ext in [".txt"]:
        return "txt"
    return "unknown"


def extract_text_from_file(file_path: str | Path) -> str:
    """
    Main entrypoint used by upload / ingestion pipeline.

    Given a file path (PDF, DOCX, TXT), returns extracted text as a string.
    Raises ValueError if the file type is not supported or no text could be read.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ftype = detect_file_type(path)

    if ftype == "pdf":
        text = extract_text_from_pdf(path)
    elif ftype == "docx":
        text = extract_text_from_docx(path)
    elif ftype == "txt":
        text = extract_text_from_txt(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    if not text or not text.strip():
        raise ValueError(f"No text could be extracted from file: {path.name}")

    return text
