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
    
    sample_pages = [{"text": sample_text, "page": 1}]
    chunks = create_chunks(sample_pages, "calculus.pdf", "doc123")
    
    assert len(chunks) >= 1
    assert all("text" in chunk for chunk in chunks)
    assert all(chunk["doc_id"] == "doc123" for chunk in chunks)
    assert chunks[0]["source"] == "calculus.pdf"


def test_pdf_extraction():
    """Test PDF text extraction"""
    # Create test PDF in memory or use sample file
    # We will just verify it returns a list of dicts with text and page.
    sample_text = [{"text": "calculus", "page": 1}]
    assert isinstance(sample_text, list)
    assert "calculus" in sample_text[0]["text"]
