# backend/tests/test_preprocessing.py
import pytest
from backend.preprocessing import create_chunks
from backend.file_handler import extract_text_from_file


def test_text_chunking():
    """Test document chunking pipeline"""
    sample_text = """
    Calculus is the mathematical study of continuous change. 
    It has two main branches: differential and integral calculus.
    """
    
    chunks = create_chunks(sample_text, "calculus.pdf", "doc123")
    
    assert len(chunks) >= 1
    assert all("text" in chunk for chunk in chunks)
    assert all(chunk["doc_id"] == "doc123" for chunk in chunks)
    assert chunks[0]["source"] == "calculus.pdf"


def test_pdf_extraction():
    """Test PDF text extraction"""
    # Create test PDF in memory or use sample file
    sample_pdf_path = "tests/sample_calculus.pdf"
    text = extract_text_from_file(sample_pdf_path)
    assert len(text) > 100  # Reasonable PDF length
    assert "calculus" in text.lower()
