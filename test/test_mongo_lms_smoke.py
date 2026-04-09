from __future__ import annotations

import asyncio
import logging
import os
import sys
import types
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient


for parent in Path(__file__).resolve().parents:
    if (parent / "backend").exists():
        root = str(parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        break


def _install_logging_stub():
    logging_module = types.ModuleType("backend.utils.logging")
    logging_module.api_logger = logging.getLogger("test.api")
    logging_module.db_logger = logging.getLogger("test.db")
    logging_module.auth_logger = logging.getLogger("test.auth")
    logging_module.rag_logger = logging.getLogger("test.rag")
    sys.modules["backend.utils.logging"] = logging_module


def _build_test_client(db):
    _install_logging_stub()
    os.environ["DEBUG"] = "true"

    from backend.api import auth, lms
    from backend.utils.db import get_db

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
    app.include_router(lms.router, prefix="/api/lms", tags=["LMS"])

    async def override_get_db():
        return db

    app.dependency_overrides[get_db] = override_get_db
    app.state.db = db
    return TestClient(app)


def _register_user(client: TestClient, email: str, password: str, name: str, role: str = "student"):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "name": name,
            "level": "undergraduate",
            "role": role,
        },
    )
    assert response.status_code == 201

    normalized_role = str(role or "student").strip().lower()
    if normalized_role != "student":
        asyncio.run(
            client.app.state.db.users.update_one(
                {"email": email.lower()},
                {"$set": {"role": normalized_role}},
            )
        )

    payload = response.json()
    payload["role"] = normalized_role
    return payload


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.skipif(os.getenv("RUN_MONGO_SMOKE") != "1", reason="Mongo smoke test is opt-in")
def test_lms_quiz_flow_with_real_mongo():
    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        pytest.skip("MONGODB_URI is not configured")

    db_name = f"rag_ai_tutor_smoke_{uuid.uuid4().hex}"
    mongo_client = AsyncIOMotorClient(mongo_uri)
    db = mongo_client[db_name]

    try:
        with _build_test_client(db) as client:
            teacher = _register_user(client, "mongo-teacher@example.com", "secret123", "Mongo Teacher", role="Teacher")
            teacher_token = _login(client, "mongo-teacher@example.com", "secret123")
            teacher_headers = _auth_headers(teacher_token)

            class_response = client.post(
                "/api/lms/classes",
                headers=teacher_headers,
                json={"name": "Chemistry", "section": "B", "subject": "Science"},
            )
            assert class_response.status_code == 200
            class_payload = class_response.json()

            quiz_response = client.post(
                f"/api/lms/classes/{class_payload['id']}/quizzes",
                headers=teacher_headers,
                json={
                    "title": "Atoms Quiz",
                    "time_limit": 10,
                    "questions": [
                        {
                            "question": "What is the center of an atom called?",
                            "type": "mcq",
                            "points": 1,
                            "options": [
                                {"label": "A", "text": "Nucleus", "is_correct": True},
                                {"label": "B", "text": "Electron", "is_correct": False},
                                {"label": "C", "text": "Orbit", "is_correct": False},
                                {"label": "D", "text": "Shell", "is_correct": False},
                            ],
                        }
                    ],
                },
            )
            assert quiz_response.status_code == 200
            quiz_id = quiz_response.json()["id"]

            _register_user(client, "mongo-student@example.com", "secret123", "Mongo Student")
            student_token = _login(client, "mongo-student@example.com", "secret123")
            student_headers = _auth_headers(student_token)

            enroll_response = client.post(
                "/api/lms/classes/enroll",
                headers=student_headers,
                json={"join_code": class_payload["join_code"]},
            )
            assert enroll_response.status_code == 200

            quiz_list_response = client.get("/api/lms/quizzes", headers=student_headers)
            assert quiz_list_response.status_code == 200
            assert quiz_list_response.json()[0]["submitted"] is False

            quiz_detail_response = client.get(f"/api/lms/quizzes/{quiz_id}", headers=student_headers)
            assert quiz_detail_response.status_code == 200
            quiz_detail = quiz_detail_response.json()
            question_id = quiz_detail["questions"][0]["id"]
            assert "is_correct" not in quiz_detail["questions"][0]["options"][0]

            attempt_response = client.post(
                f"/api/lms/quizzes/{quiz_id}/attempt",
                headers={**student_headers, "Content-Type": "application/json"},
                json={"answers": {question_id: "A"}},
            )
            assert attempt_response.status_code == 200
            attempt_payload = attempt_response.json()
            assert attempt_payload["percentage"] == 100.0
            assert attempt_payload["correct_count"] == 1

            quiz_list_after_response = client.get("/api/lms/quizzes", headers=student_headers)
            assert quiz_list_after_response.status_code == 200
            assert quiz_list_after_response.json()[0]["submitted"] is True

            stored_student = asyncio.run(db.users.find_one({"email": "mongo-student@example.com"}))
            stored_attempt = asyncio.run(
                db.quiz_attempts.find_one(
                    {
                        "quiz_id": quiz_id,
                        "student_id": str(stored_student["_id"]),
                        "is_complete": True,
                    }
                )
            )
            assert stored_attempt is not None
            assert stored_attempt["percentage"] == 100.0
    finally:
        asyncio.run(mongo_client.drop_database(db_name))
        mongo_client.close()
