# backend/tests/test_rag_tutor.py
import pytest
import shutil
from backend.rag_tutor import answer_query_with_rag
from backend.vector_db import get_vector_db


@pytest.fixture(scope="function")
def clean_vector_db():
    """Clean ChromaDB between tests"""
    client = get_vector_db()
    client.delete_collection("test_user_math")
    yield
    client.delete_collection("test_user_math")


def test_rag_pipeline(clean_vector_db):
    """End-to-end RAG test with sample data"""
    
    # Add test chunks
    test_chunks = [
        {"text": "Newton's 1st law: objects stay at rest unless acted upon", "source": "physics.pdf"},
        {"text": "F=ma is Newton's 2nd law", "source": "physics.pdf"}
    ]
    
    # Test RAG query
    result = answer_query_with_rag(
        user_id="test_user",
        query="What is Newton's first law?",
        subject="physics",
        test_chunks=test_chunks  # Mock chunks for test
    )
    
    assert result["answer"]
    assert "Newton's 1st law" in result["answer"]
    assert len(result["citations"]) > 0
