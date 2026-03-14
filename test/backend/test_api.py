# backend/tests/test_api.py
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.utils import get_db

client = TestClient(app)


@pytest.fixture(scope="module")
def test_db():
    """Test MongoDB database"""
    db = get_db()
    # Clean test data
    db.users.delete_many({})
    db.documents.delete_many({})
    yield db
    # Cleanup
    db.users.delete_many({})
    db.documents.delete_many({})


def test_register_user(test_db):
    """Test user registration API"""
    response = client.post("/api/auth/register", json={
        "email": "test@example.com",
        "password": "testpass123",
        "name": "Test User",
        "level": "college"
    })
    assert response.status_code == 201
    assert response.json()["email"] == "test@example.com"


def test_chat_endpoint(test_db):
    """Test RAG chat API (requires uploaded docs)"""
    # First register user
    reg_resp = client.post("/api/auth/register", json={
        "email": "chat@test.com", "password": "pass123", 
        "name": "Chat User", "level": "college"
    })
    assert reg_resp.status_code == 201
    
    # Get token
    login_resp = client.post("/api/auth/login", data={
        "username": "chat@test.com", "password": "pass123"
    })
    token = login_resp.json()["access_token"]
    
    # Test chat (will use empty vector store)
    resp = client.post("/api/chat", 
                      json={"message": "test", "subject": "math"},
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "answer" in resp.json()


def test_upload_file():
    """Test document upload pipeline"""
    # Mock file upload test
    pass
