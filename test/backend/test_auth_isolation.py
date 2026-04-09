import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

for parent in Path(__file__).resolve().parents:
    if (parent / "backend").exists():
        root = str(parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        break

from backend.auth import get_password_hash, verify_password
from test.test_integration_api_flows import FakeDatabase, _install_stub_modules


def _build_auth_client():
    _install_stub_modules()
    from backend.api import auth
    from backend.utils.db import get_db

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])

    fake_db = FakeDatabase()

    async def override_get_db():
        return fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.state.db = fake_db
    return TestClient(app)


def test_password_hash_round_trip():
    password = "secret123"
    hashed = get_password_hash(password)

    assert hashed
    assert hashed != password
    assert verify_password(password, hashed) is True


def test_register_login_and_me_normalize_public_signup_role():
    with _build_auth_client() as client:
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "auth-check@example.com",
                "password": "secret123",
                "name": "Auth Check",
                "level": "undergraduate",
                "role": "Teacher",
            },
        )

        assert register_response.status_code == 201
        assert register_response.json()["role"] == "student"

        login_response = client.post(
            "/api/auth/login",
            data={"username": "auth-check@example.com", "password": "secret123"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["user"]["role"] == "student"

        token = login_response.json()["access_token"]
        me_response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert me_response.status_code == 200
        assert me_response.json()["role"] == "student"
