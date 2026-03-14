# backend/tests/test_quiz_generator.py
import pytest
from backend.quiz_generator import generate_quiz_for_user

@pytest.mark.asyncio
async def test_quiz_generation():
    """Test quiz generation from mock documents"""
    mock_chunks = [
        {"text": "Derivative of x² is 2x", "metadata": {"source": "math.pdf"}},
        {"text": "Integral of 2x is x²", "metadata": {"source": "math.pdf"}}
    ]
    
    quiz = await generate_quiz_for_user(
        user_id="test_user",
        chunks=mock_chunks,
        num_questions=3,
        difficulty="easy"
    )
    
    assert len(quiz["questions"]) == 3
    assert all(q["difficulty"] == "easy" for q in quiz["questions"])
    assert all(len(q["options"]) == 4 for q in quiz["questions"])
