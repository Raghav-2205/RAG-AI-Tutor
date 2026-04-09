import asyncio
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

from test.test_integration_api_flows import FakeDatabase, _install_stub_modules


class AcademicFakeDatabase(FakeDatabase):
    def __getitem__(self, name: str):
        return getattr(self, name)


def _build_authz_client():
    _install_stub_modules()

    from backend.api import academic, auth, lms
    from backend.utils.db import db_manager, get_db

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
    app.include_router(lms.router, prefix="/api/lms", tags=["LMS"])
    app.include_router(academic.router, prefix="/api/academic", tags=["Academic"])

    fake_db = AcademicFakeDatabase()
    db_manager.db = fake_db

    async def override_get_db():
        return fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.state.db = fake_db
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

    return response.json()


def _login(client: TestClient, email: str, password: str):
    response = client.post("/api/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_student_cannot_access_teacher_or_admin_routes():
    with _build_authz_client() as client:
        _register_user(client, "student@example.com", "secret123", "Student User")
        student_headers = _auth_headers(_login(client, "student@example.com", "secret123"))

        create_class_response = client.post(
            "/api/lms/classes",
            headers=student_headers,
            json={"name": "Physics", "section": "A", "subject": "Science"},
        )
        assert create_class_response.status_code == 403

        teacher_dashboard_response = client.get("/api/academic/teacher/dashboard/today", headers=student_headers)
        assert teacher_dashboard_response.status_code == 403

        list_users_response = client.get("/api/auth/users", headers=student_headers)
        assert list_users_response.status_code == 403


def test_teacher_cannot_access_admin_routes_but_can_use_teacher_routes():
    with _build_authz_client() as client:
        _register_user(client, "teacher@example.com", "secret123", "Teacher User", role="teacher")
        teacher_headers = _auth_headers(_login(client, "teacher@example.com", "secret123"))

        teacher_dashboard_response = client.get("/api/academic/teacher/dashboard/today", headers=teacher_headers)
        assert teacher_dashboard_response.status_code == 200

        list_users_response = client.get("/api/auth/users", headers=teacher_headers)
        assert list_users_response.status_code == 403


def test_student_only_lms_actions_stay_student_only():
    with _build_authz_client() as client:
        _register_user(client, "teacher@example.com", "secret123", "Teacher User", role="teacher")
        teacher_headers = _auth_headers(_login(client, "teacher@example.com", "secret123"))

        class_response = client.post(
            "/api/lms/classes",
            headers=teacher_headers,
            json={"name": "Algebra", "section": "B", "subject": "Math"},
        )
        assert class_response.status_code == 200
        class_id = class_response.json()["id"]
        join_code = class_response.json()["join_code"]

        assignment_response = client.post(
            "/api/lms/assignments",
            headers=teacher_headers,
            json={"class_id": class_id, "title": "Worksheet 1", "max_points": 20},
        )
        assert assignment_response.status_code == 200
        assignment_id = assignment_response.json()["id"]

        quiz_response = client.post(
            f"/api/lms/classes/{class_id}/quizzes",
            headers=teacher_headers,
            json={
                "title": "Quick Quiz",
                "questions": [
                    {
                        "question": "2 + 2 = ?",
                        "type": "mcq",
                        "points": 1,
                        "options": [
                            {"label": "A", "text": "4", "is_correct": True},
                            {"label": "B", "text": "5", "is_correct": False},
                        ],
                    }
                ],
            },
        )
        assert quiz_response.status_code == 200
        quiz_id = quiz_response.json()["id"]

        _register_user(client, "student@example.com", "secret123", "Student User")
        student_headers = _auth_headers(_login(client, "student@example.com", "secret123"))

        enroll_response = client.post(
            "/api/lms/classes/enroll",
            headers=student_headers,
            json={"join_code": join_code},
        )
        assert enroll_response.status_code == 200

        teacher_enroll_response = client.post(
            "/api/lms/classes/enroll",
            headers=teacher_headers,
            json={"join_code": join_code},
        )
        assert teacher_enroll_response.status_code == 403

        submit_assignment_response = client.post(
            f"/api/lms/assignments/{assignment_id}/submit",
            headers={**student_headers, "Content-Type": "application/json"},
            json={"content": "My assignment submission"},
        )
        assert submit_assignment_response.status_code == 200

        student_submissions_response = client.get("/api/lms/students/me/submissions", headers=student_headers)
        assert student_submissions_response.status_code == 200
        assert len(student_submissions_response.json()) == 1

        teacher_submissions_response = client.get("/api/lms/students/me/submissions", headers=teacher_headers)
        assert teacher_submissions_response.status_code == 403

        quiz_detail_response = client.get(f"/api/lms/quizzes/{quiz_id}", headers=student_headers)
        assert quiz_detail_response.status_code == 200
        question_id = quiz_detail_response.json()["questions"][0]["id"]

        teacher_attempt_response = client.post(
            f"/api/lms/quizzes/{quiz_id}/attempt",
            headers={**teacher_headers, "Content-Type": "application/json"},
            json={"answers": {question_id: "A"}},
        )
        assert teacher_attempt_response.status_code == 403

        student_attempt_response = client.post(
            f"/api/lms/quizzes/{quiz_id}/attempt",
            headers={**student_headers, "Content-Type": "application/json"},
            json={"answers": {question_id: "A"}},
        )
        assert student_attempt_response.status_code == 200

        student_attendance_response = client.get("/api/lms/students/me/attendance", headers=student_headers)
        assert student_attendance_response.status_code == 200

        teacher_attendance_response = client.get("/api/lms/students/me/attendance", headers=teacher_headers)
        assert teacher_attendance_response.status_code == 403


def test_legacy_mixed_case_teacher_roles_still_work_during_rollout():
    with _build_authz_client() as client:
        _register_user(client, "legacy-teacher@example.com", "secret123", "Legacy Teacher")
        asyncio.run(
            client.app.state.db.users.update_one(
                {"email": "legacy-teacher@example.com"},
                {"$set": {"role": "Teacher"}},
            )
        )

        teacher_headers = _auth_headers(_login(client, "legacy-teacher@example.com", "secret123"))

        teacher_dashboard_response = client.get("/api/academic/teacher/dashboard/today", headers=teacher_headers)
        assert teacher_dashboard_response.status_code == 200

        create_class_response = client.post(
            "/api/lms/classes",
            headers=teacher_headers,
            json={"name": "Legacy Math", "section": "C", "subject": "Math"},
        )
        assert create_class_response.status_code == 200
