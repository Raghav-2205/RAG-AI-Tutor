from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "public"


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/views/login.html",
        "/views/signup.html",
        "/views/dashboard.html",
        "/views/subjects.html",
        "/views/lms.html",
        "/views/student_lms.html",
        "/views/teacher_portal.html",
        "/views/planner.html",
        "/views/lms_quiz.html",
    ],
)
def test_core_pages_are_servable(client: TestClient, path: str):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "<html" in response.text.lower()
    assert len(response.text) > 200


@pytest.mark.parametrize(
    "path, content_fragment",
    [
        ("/assets/js/config.js", "window.config"),
        ("/assets/js/ai.js", "window.ai = new AIManager()"),
        ("/assets/js/notifications.js", "loadNotificationBadge"),
        ("/assets/css/lms.css", "--lms-"),
    ],
)
def test_shared_assets_are_servable(client: TestClient, path: str, content_fragment: str):
    response = client.get(path)
    assert response.status_code == 200
    assert content_fragment in response.text
