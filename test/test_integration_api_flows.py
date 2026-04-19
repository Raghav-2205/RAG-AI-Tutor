from __future__ import annotations

import asyncio
import copy
import logging
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient


for parent in Path(__file__).resolve().parents:
    if (parent / "backend").exists():
        root = str(parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        break


class FakeInsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeInsertManyResult:
    def __init__(self, inserted_ids):
        self.inserted_ids = inserted_ids


class FakeUpdateResult:
    def __init__(self, matched_count: int, modified_count: int, upserted_id=None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class FakeDeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


def _normalize_sort_value(value):
    if value is None:
        return (1, "")
    return (0, value)


def _deepcopy(doc):
    return copy.deepcopy(doc)


def _get_nested(doc: dict, field: str):
    current = doc
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _matches_condition(actual, expected) -> bool:
    if isinstance(expected, dict):
        for operator, operand in expected.items():
            if operator == "$in":
                if isinstance(actual, list):
                    if not any(item in operand for item in actual):
                        return False
                elif actual not in operand:
                    return False
            elif operator == "$gte":
                if actual is None or actual < operand:
                    return False
            elif operator == "$lte":
                if actual is None or actual > operand:
                    return False
            elif operator == "$not":
                if _matches_condition(actual, operand):
                    return False
            elif operator == "$size":
                if not isinstance(actual, list) or len(actual) != operand:
                    return False
            else:
                if actual != expected:
                    return False
        return True

    if isinstance(actual, list):
        return expected in actual

    return actual == expected


def _matches(doc: dict, query: dict | None) -> bool:
    if not query:
        return True

    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue

        actual = _get_nested(doc, key)
        if not _matches_condition(actual, expected):
            return False

    return True


def _apply_projection(doc: dict, projection: dict | None) -> dict:
    if not projection:
        return _deepcopy(doc)

    include_fields = [field for field, enabled in projection.items() if enabled]
    if not include_fields:
        return _deepcopy(doc)

    projected = {}
    for field in include_fields:
        if field in doc:
            projected[field] = _deepcopy(doc[field])
    if "_id" in doc and projection.get("_id", 1):
        projected["_id"] = _deepcopy(doc["_id"])
    return projected


class FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = [_deepcopy(doc) for doc in docs]
        self._limit = None
        self._skip = 0

    def sort(self, key, direction=None):
        if isinstance(key, list):
            sort_fields = key
        else:
            sort_fields = [(key, direction)]

        for field, order in reversed(sort_fields):
            reverse = (order or 1) < 0
            self._docs.sort(key=lambda doc: _normalize_sort_value(_get_nested(doc, field)), reverse=reverse)
        return self

    def limit(self, limit: int):
        self._limit = limit
        return self

    def skip(self, count: int):
        self._skip = count
        return self

    async def to_list(self, length=None):
        docs = self._docs
        if self._skip:
            docs = docs[self._skip :]
        if self._limit is not None:
            docs = docs[: self._limit]
        if length is not None:
            docs = docs[:length]
        return [_deepcopy(doc) for doc in docs]


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict):
        stored = _deepcopy(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return FakeInsertOneResult(stored["_id"])

    async def insert_many(self, docs: list[dict]):
        inserted_ids = []
        for doc in docs:
            result = await self.insert_one(doc)
            inserted_ids.append(result.inserted_id)
        return FakeInsertManyResult(inserted_ids)

    async def find_one(self, query: dict | None = None, projection: dict | None = None):
        for doc in self.docs:
            if _matches(doc, query):
                return _apply_projection(doc, projection)
        return None

    def find(self, query: dict | None = None, projection: dict | None = None):
        matches = [_apply_projection(doc, projection) for doc in self.docs if _matches(doc, query)]
        return FakeCursor(matches)

    async def update_one(self, query: dict, update: dict, upsert: bool = False):
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                modified = self._apply_update(doc, update)
                self.docs[index] = doc
                return FakeUpdateResult(1, 1 if modified else 0)

        if upsert:
            new_doc = {}
            for key, value in query.items():
                if not key.startswith("$"):
                    new_doc[key] = _deepcopy(value)
            self._apply_update(new_doc, update)
            result = await self.insert_one(new_doc)
            return FakeUpdateResult(0, 1, upserted_id=result.inserted_id)

        return FakeUpdateResult(0, 0)

    async def update_many(self, query: dict, update: dict):
        matched = 0
        modified = 0
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                matched += 1
                if self._apply_update(doc, update):
                    modified += 1
                self.docs[index] = doc
        return FakeUpdateResult(matched, modified)

    async def delete_many(self, query: dict):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, query)]
        return FakeDeleteResult(before - len(self.docs))

    async def count_documents(self, query: dict | None = None):
        return sum(1 for doc in self.docs if _matches(doc, query))

    async def create_index(self, *args, **kwargs):
        return None

    def _apply_update(self, doc: dict, update: dict) -> bool:
        modified = False

        for operator, payload in update.items():
            if operator == "$set":
                for key, value in payload.items():
                    if doc.get(key) != value:
                        doc[key] = _deepcopy(value)
                        modified = True
            elif operator == "$push":
                for key, value in payload.items():
                    doc.setdefault(key, [])
                    if isinstance(value, dict) and "$each" in value:
                        doc[key].extend(_deepcopy(value["$each"]))
                    else:
                        doc[key].append(_deepcopy(value))
                    modified = True
            elif operator == "$pull":
                for key, value in payload.items():
                    existing = doc.get(key, [])
                    if isinstance(existing, list):
                        filtered = [item for item in existing if item != value]
                        if filtered != existing:
                            doc[key] = filtered
                            modified = True
            else:
                raise NotImplementedError(f"Unsupported update operator: {operator}")

        return modified


class FakeDatabase:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


def _install_stub_modules():
    logging_module = types.ModuleType("backend.utils.logging")
    logging_module.api_logger = logging.getLogger("test.api")
    logging_module.db_logger = logging.getLogger("test.db")
    logging_module.auth_logger = logging.getLogger("test.auth")
    logging_module.rag_logger = logging.getLogger("test.rag")
    sys.modules["backend.utils.logging"] = logging_module

    rag_tutor = types.ModuleType("backend.rag_tutor")

    async def answer_query_with_rag(**kwargs):
        return {
            "answer": f"Stub answer for: {kwargs['query']}",
            "citations": [1],
            "chunks": [{"text": "Stub chunk", "metadata": {"source": "stub.txt"}}],
            "validation": {"hallucination_rate": 0.0, "validation_status": "VERIFIED"},
            "source_mode": "knowledge_base",
        }

    async def retrieve_chunks_for_streaming(**kwargs):
        return {
            "chunks": [],
            "prompt": "stub",
            "system_prompt": "stub",
            "citations": [],
            "source_mode": "knowledge_base",
        }

    async def _validate_generated_answer(**kwargs):
        return None

    rag_tutor.answer_query_with_rag = answer_query_with_rag
    rag_tutor.retrieve_chunks_for_streaming = retrieve_chunks_for_streaming
    rag_tutor._validate_generated_answer = _validate_generated_answer
    sys.modules["backend.rag_tutor"] = rag_tutor

    feedback_module = types.ModuleType("backend.core.feedback_analyzer")

    class FeedbackAnalyzer:
        def __init__(self, db):
            self.db = db

        async def should_adjust_prompt(self, user_id):
            return False, ""

        async def get_adaptive_context(self, user_id):
            return ""

        async def track_response_quality(self, **kwargs):
            return None

        async def log_feedback_influence(self, **kwargs):
            return None

    feedback_module.FeedbackAnalyzer = FeedbackAnalyzer
    sys.modules["backend.core.feedback_analyzer"] = feedback_module

    llm_module = types.ModuleType("backend.core.llm_interface")

    class StubLLMClient:
        async def async_generate(self, *args, **kwargs):
            return "{}"

    llm_module.llm_client = StubLLMClient()
    llm_module.SOCRATIC_SYSTEM_PROMPT = "Stub prompt"
    sys.modules["backend.core.llm_interface"] = llm_module

    search_engine_module = types.ModuleType("backend.core.search_engine")

    class StubSearchEngine:
        def __init__(self):
            self.raise_error = False

        def search(self, user_id: str, subject: str, query: str, top_k: int = 6, document_ids=None):
            if self.raise_error:
                raise RuntimeError("search unavailable")
            return [
                {
                    "id": f"{subject}-chunk-1",
                    "text": f"{subject} reference material for {query}",
                    "metadata": {"source": f"{subject}.pdf"},
                    "score": 0.91,
                }
            ]

    search_engine_module.search_engine = StubSearchEngine()
    sys.modules["backend.core.search_engine"] = search_engine_module

    file_handler = types.ModuleType("backend.file_handler")
    file_handler.save_upload_to_disk = lambda filename, file_bytes, user_id: f"/tmp/{filename}"
    file_handler.extract_text_from_file = lambda file_path: [{"page": 1, "text": "Algebra foundations and equations"}]
    sys.modules["backend.file_handler"] = file_handler

    preprocessing = types.ModuleType("backend.preprocessing")

    def create_chunks(pages, filename, doc_id):
        return [
            {
                "id": "chunk-1",
                "text": "Algebra foundations and equations",
                "metadata": {"source": filename, "doc_id": doc_id},
            }
        ]

    preprocessing.create_chunks = create_chunks
    sys.modules["backend.preprocessing"] = preprocessing

    vector_db = types.ModuleType("backend.vector_db")
    vector_db.get_vector_db = lambda: object()
    vector_db.get_or_create_collection = lambda client, user_id, subject: object()
    vector_db.add_chunks_to_collection = lambda collection, chunks: None
    sys.modules["backend.vector_db"] = vector_db

    grag_service = types.ModuleType("backend.services.grag_service")

    async def build_or_update_knowledge_graph(db, chat_id, user_id, full_text, source=None):
        return None

    async def ensure_grag_for_session(db, chat_id, user_id, new_text=None, source=None, chunks=None, force_rebuild=False):
        return None

    async def graph_retrieve(db, chat_id, query):
        return []

    async def get_grag_session_state(db, chat_id):
        return {
            "session": {},
            "user_id": None,
            "document_ids": [],
            "document_names": [],
            "uploaded_documents": [],
            "file_count": 0,
            "grag_enabled": False,
        }

    def session_supports_grag(file_count=0, document_ids=None):
        return int(file_count or 0) >= 2 or len(document_ids or []) >= 2

    grag_service.build_or_update_knowledge_graph = build_or_update_knowledge_graph
    grag_service.ensure_grag_for_session = ensure_grag_for_session
    grag_service.graph_retrieve = graph_retrieve
    grag_service.get_grag_session_state = get_grag_session_state
    grag_service.session_supports_grag = session_supports_grag
    sys.modules["backend.services.grag_service"] = grag_service

    quiz_generator = types.ModuleType("backend.core.quiz_generator")

    def generate_quiz_from_chunks(user_id: str, subject: str, num_questions: int):
        questions = []
        for index in range(num_questions):
            questions.append(
                {
                    "question": f"{subject.title()} question {index + 1}",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correct_index": 0,
                    "chunk_source": f"{subject}_chunk_{index + 1}",
                }
            )
        return {
            "quiz_id": f"{subject}-quiz-{num_questions}",
            "subject": subject,
            "questions": questions,
        }

    quiz_generator.generate_quiz_from_chunks = generate_quiz_from_chunks
    sys.modules["backend.core.quiz_generator"] = quiz_generator

    student_profile = types.ModuleType("backend.core.student_profile")

    class StudentProfile:
        def __init__(self, user_id: str, db):
            self.user_id = user_id
            self.db = db

        async def update_from_quiz(self, quiz_result):
            await self.db.student_profiles.update_one(
                {"user_id": self.user_id},
                {
                    "$set": {
                        "user_id": self.user_id,
                        "last_quiz_id": quiz_result["quiz_id"],
                        "last_score": quiz_result["score"],
                        "last_total_questions": quiz_result["total_questions"],
                    }
                },
                upsert=True,
            )

        async def get_learning_stats(self):
            submissions = await self.db.quiz_submissions.find({"user_id": self.user_id}).to_list(None)
            avg_score = 0.0
            if submissions:
                avg_score = sum(s.get("percentage", 0) for s in submissions) / len(submissions)
            return {
                "user_id": self.user_id,
                "quizzes_taken": len(submissions),
                "average_percentage": round(avg_score, 1),
            }

    student_profile.StudentProfile = StudentProfile
    sys.modules["backend.core.student_profile"] = student_profile


def _build_test_client():
    _install_stub_modules()
    os.environ["DEBUG"] = "true"

    from backend.api import analytics, auth, upload, chat, lms, planner, dashboard, notifications, quiz, gamification
    from backend.utils.db import get_db

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
    app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
    app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
    app.include_router(quiz.router, prefix="/api/quiz", tags=["Quiz"])
    app.include_router(lms.router, prefix="/api/lms", tags=["LMS"])
    app.include_router(planner.router, prefix="/api/planner", tags=["Planner"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
    app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
    app.include_router(gamification.router, prefix="/api/gamification", tags=["Gamification"])

    fake_db = FakeDatabase()

    async def override_get_db():
        return fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.state.fake_db = fake_db
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

    payload = response.json()
    payload["role"] = normalized_role
    return payload


def _login(client: TestClient, email: str, password: str):
    response = client.post("/api/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_auth_register_login_and_me_flow():
    with _build_test_client() as client:
        _register_user(client, "student@example.com", "secret123", "Student User")
        token = _login(client, "student@example.com", "secret123")

        me_response = client.get("/api/auth/me", headers=_auth_headers(token))

        assert me_response.status_code == 200
        payload = me_response.json()
        assert payload["email"] == "student@example.com"
        assert payload["role"] == "student"


def test_upload_chat_and_dashboard_flow():
    with _build_test_client() as client:
        _register_user(client, "learner@example.com", "secret123", "Learner")
        token = _login(client, "learner@example.com", "secret123")
        headers = _auth_headers(token)

        upload_response = client.post(
            "/api/upload/",
            headers=headers,
            data={"subject": "math"},
            files={"file": ("notes.txt", b"equations and variables", "text/plain")},
        )

        assert upload_response.status_code == 200
        upload_payload = upload_response.json()
        assert upload_payload["status"] == "success"
        assert upload_payload["chunks"] == 1

        chat_response = client.post(
            "/api/chat/",
            headers=headers,
            json={
                "message": "What is algebra?",
                "subject": "math",
                "chat_id": upload_payload["chat_id"],
            },
        )

        assert chat_response.status_code == 200
        assert "Stub answer for: What is algebra?" in chat_response.json()["answer"]

        summary_response = client.get("/api/dashboard/summary", headers=headers)
        assert summary_response.status_code == 200
        summary = summary_response.json()
        assert summary["doc_count"] == 1
        assert summary["total_questions"] == 1

        activity_response = client.get("/api/dashboard/activity", headers=headers)
        assert activity_response.status_code == 200
        activity = activity_response.json()
        assert activity["recent_documents"][0]["filename"] == "notes.txt"
        assert activity["recent_chats"][0]["message_count"] == 1


def test_lms_planner_and_notifications_flow():
    with _build_test_client() as client:
        teacher = _register_user(client, "teacher@example.com", "secret123", "Teacher", role="Teacher")
        teacher_token = _login(client, "teacher@example.com", "secret123")
        teacher_headers = _auth_headers(teacher_token)

        class_response = client.post(
            "/api/lms/classes",
            headers=teacher_headers,
            json={"name": "Algebra I", "section": "A", "subject": "Mathematics"},
        )
        assert class_response.status_code == 200
        class_payload = class_response.json()

        quiz_response = client.post(
            f"/api/lms/classes/{class_payload['id']}/quizzes",
            headers=teacher_headers,
            json={
                "title": "Linear Equations Quiz",
                "description": "Subject-specific quiz",
                "time_limit": 15,
                "questions": [
                    {
                        "question": "Solve x + 2 = 4",
                        "type": "mcq",
                        "points": 1,
                        "explanation": "Subtract 2 from both sides.",
                        "options": [
                            {"label": "A", "text": "x = 2", "is_correct": True},
                            {"label": "B", "text": "x = 4", "is_correct": False},
                            {"label": "C", "text": "x = 6", "is_correct": False},
                            {"label": "D", "text": "x = 0", "is_correct": False},
                        ],
                    }
                ],
            },
        )
        assert quiz_response.status_code == 200
        quiz_id = quiz_response.json()["id"]

        _register_user(client, "student2@example.com", "secret123", "Student Two")
        student_token = _login(client, "student2@example.com", "secret123")
        student_headers = _auth_headers(student_token)

        enroll_response = client.post(
            "/api/lms/classes/enroll",
            headers=student_headers,
            json={"join_code": class_payload["join_code"]},
        )
        assert enroll_response.status_code == 200

        quiz_list_response = client.get("/api/lms/quizzes", headers=student_headers)
        assert quiz_list_response.status_code == 200
        quiz_list = quiz_list_response.json()
        assert quiz_list[0]["submitted"] is False

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
        assert len(attempt_payload["question_results"]) == 1

        quiz_list_after_response = client.get("/api/lms/quizzes", headers=student_headers)
        quiz_list_after = quiz_list_after_response.json()
        assert quiz_list_after[0]["submitted"] is True
        assert quiz_list_after[0]["score"] == 100.0

        create_plan_response = client.post(
            "/api/planner/plans",
            headers=student_headers,
            json={"date": "2026-04-01", "template": "study_day"},
        )
        assert create_plan_response.status_code == 200

        plan_response = client.get("/api/planner/plans/2026-04-01", headers=student_headers)
        assert plan_response.status_code == 200
        plan_payload = plan_response.json()
        assert len(plan_payload["tasks"]) > 0

        log_activity_response = client.post(
            "/api/planner/activities",
            headers={**student_headers, "Content-Type": "application/json"},
            json={
                "date": "2026-04-01",
                "category": "study",
                "data": {"topics": ["linear equations"], "duration_min": 45},
            },
        )
        assert log_activity_response.status_code == 200

        activity_summary_response = client.get("/api/planner/activities/summary/2026-04-01", headers=student_headers)
        assert activity_summary_response.status_code == 200
        assert activity_summary_response.json()["study"]["total_duration_min"] == 45

        db = client.app.state.fake_db
        user_id = next(doc["_id"] for doc in db.users.docs if doc["email"] == "student2@example.com")
        asyncio.run(
            db.notifications.insert_one(
                {
                    "id": "notif-1",
                    "user_id": str(user_id),
                    "type": "quiz",
                    "title": "Quiz graded",
                    "message": "Your quiz has been graded",
                    "is_read": False,
                }
            )
        )

        notifications_response = client.get("/api/notifications/?unread=true", headers=student_headers)
        assert notifications_response.status_code == 200
        notifications_payload = notifications_response.json()
        assert len(notifications_payload) == 1
        assert notifications_payload[0]["id"] == "notif-1"

        mark_read_response = client.post("/api/notifications/notif-1/read", headers=student_headers)
        assert mark_read_response.status_code == 200

        notifications_after_response = client.get("/api/notifications/?unread=true", headers=student_headers)
        assert notifications_after_response.status_code == 200
        assert notifications_after_response.json() == []


def test_standalone_quiz_and_dashboard_contracts():
    with _build_test_client() as client:
        _register_user(client, "quizuser@example.com", "secret123", "Quiz User")
        token = _login(client, "quizuser@example.com", "secret123")
        headers = _auth_headers(token)

        generate_response = client.post(
            "/api/quiz/generate",
            headers={**headers, "Content-Type": "application/json"},
            json={"subject": "science", "num_questions": 3},
        )
        assert generate_response.status_code == 200
        generated_quiz = generate_response.json()
        assert generated_quiz["subject"] == "science"
        assert len(generated_quiz["questions"]) == 3
        assert "correct_index" not in generated_quiz["questions"][0]

        submit_response = client.post(
            "/api/quiz/submit",
            headers={**headers, "Content-Type": "application/json"},
            json={"quiz_id": generated_quiz["quiz_id"], "answers": [0, 1, 0]},
        )
        assert submit_response.status_code == 200
        result = submit_response.json()
        assert result["score"] == 2
        assert result["total"] == 3
        assert round(result["percentage"], 2) == round((2 / 3) * 100, 2)
        assert result["level"] == "Intermediate"
        assert len(result["correct_answers"]) == 3
        assert len(result["weak_topics"]) == 1

        history_response = client.get("/api/quiz/history", headers=headers)
        assert history_response.status_code == 200
        history = history_response.json()
        assert len(history) == 1
        assert history[0]["quiz_id"] == generated_quiz["quiz_id"]

        stats_response = client.get("/api/quiz/stats", headers=headers)
        assert stats_response.status_code == 200
        stats = stats_response.json()
        assert stats["quizzes_taken"] == 1
        assert round(stats["average_percentage"], 1) == 66.7

        db = client.app.state.fake_db
        user_doc = next(doc for doc in db.users.docs if doc["email"] == "quizuser@example.com")
        user_id = str(user_doc["_id"])
        now = datetime.now(timezone.utc)

        asyncio.run(
            db.classes.insert_one(
                {
                    "id": "class-bio",
                    "name": "Biology",
                    "subject": "Biology",
                    "teacher_id": "teacher-1",
                    "students": [user_id],
                    "is_active": True,
                }
            )
        )
        asyncio.run(
            db.lms_quizzes.insert_one(
                {
                    "id": "lms-quiz-low",
                    "class_id": "class-bio",
                    "title": "Cells Quiz",
                    "time_limit": 10,
                }
            )
        )
        asyncio.run(
            db.quiz_attempts.insert_one(
                {
                    "id": "attempt-low",
                    "quiz_id": "lms-quiz-low",
                    "student_id": user_id,
                    "score": 1,
                    "max_score": 5,
                    "percentage": 20.0,
                    "submitted_at": now,
                    "is_complete": True,
                }
            )
        )
        asyncio.run(
            db.feedback.insert_many(
                [
                    {"id": "fb-1", "user_id": user_id, "rating": "negative", "timestamp": now},
                    {"id": "fb-2", "user_id": user_id, "rating": "1", "timestamp": now},
                ]
            )
        )
        asyncio.run(
            db.rag_answer_validations.insert_many(
                [
                    {
                        "id": "val-1",
                        "user_id": user_id,
                        "faithfulness_score": 0.4,
                        "final_rag_score": 0.45,
                        "answer_relevance": 0.5,
                        "hallucination_rate": 0.3,
                        "validation_status": "VERIFIED",
                        "timestamp": now,
                    },
                    {
                        "id": "val-2",
                        "user_id": user_id,
                        "faithfulness_score": 0.35,
                        "final_rag_score": 0.4,
                        "answer_relevance": 0.48,
                        "hallucination_rate": 0.4,
                        "validation_status": "REJECTED",
                        "timestamp": now,
                    },
                    {
                        "id": "val-3",
                        "user_id": user_id,
                        "faithfulness_score": 0.5,
                        "final_rag_score": 0.52,
                        "answer_relevance": 0.55,
                        "hallucination_rate": 0.25,
                        "validation_status": "VERIFIED",
                        "timestamp": now,
                    },
                ]
            )
        )

        mastery_response = client.get("/api/dashboard/mastery", headers=headers)
        assert mastery_response.status_code == 200
        mastery_payload = mastery_response.json()
        assert mastery_payload["mastery"][0]["subject"] == "Biology"
        assert mastery_payload["mastery"][0]["mastery_pct"] == 20.0

        quality_response = client.get("/api/dashboard/quality", headers=headers)
        assert quality_response.status_code == 200
        quality_payload = quality_response.json()
        assert quality_payload["has_data"] is True
        assert quality_payload["total_validated"] == 3
        assert quality_payload["status_breakdown"]["VERIFIED"] == 2
        assert quality_payload["status_breakdown"]["REJECTED"] == 1

        recommendations_response = client.get("/api/dashboard/recommendations", headers=headers)
        assert recommendations_response.status_code == 200
        recommendation_types = {item["type"] for item in recommendations_response.json()["recommendations"]}
        assert {"weak_topic", "feedback_pattern", "upload_prompt", "quality_alert"}.issubset(recommendation_types)


def test_student_analytics_and_gamification_contracts():
    with _build_test_client() as client:
        _register_user(client, "analyticsuser@example.com", "secret123", "Analytics User")
        token = _login(client, "analyticsuser@example.com", "secret123")
        headers = _auth_headers(token)

        db = client.app.state.fake_db
        user_doc = next(doc for doc in db.users.docs if doc["email"] == "analyticsuser@example.com")
        user_id = str(user_doc["_id"])
        now = datetime.now(timezone.utc)

        asyncio.run(
            db.classes.insert_one(
                {
                    "id": "class-math",
                    "name": "Algebra I",
                    "subject": "Mathematics",
                    "teacher_id": "teacher-analytics",
                    "students": [user_id],
                    "is_active": True,
                }
            )
        )
        asyncio.run(
            db.lms_quizzes.insert_one(
                {
                    "id": "lms-quiz-analytics",
                    "class_id": "class-math",
                    "title": "Linear Equations",
                    "time_limit": 15,
                }
            )
        )
        asyncio.run(
            db.quiz_attempts.insert_many(
                [
                    {
                        "id": "attempt-datetime",
                        "quiz_id": "lms-quiz-analytics",
                        "student_id": user_id,
                        "score": 2,
                        "max_score": 5,
                        "percentage": 40.0,
                        "submitted_at": now,
                        "is_complete": True,
                    },
                    {
                        "id": "attempt-iso",
                        "quiz_id": "lms-quiz-analytics",
                        "student_id": user_id,
                        "score": 3,
                        "max_score": 5,
                        "percentage": 60.0,
                        "submitted_at": now.isoformat(),
                        "is_complete": True,
                    },
                    {
                        "id": "attempt-bad-shape",
                        "quiz_id": "lms-quiz-analytics",
                        "student_id": user_id,
                        "score": 5,
                        "max_score": 5,
                        "percentage": 100.0,
                        "submitted_at": "not-a-date",
                        "is_complete": True,
                    },
                ]
            )
        )
        asyncio.run(
            db.activity_logs.insert_one(
                {
                    "id": "study-log-1",
                    "user_id": user_id,
                    "category": "study",
                    "date": now.isoformat(),
                    "data": {"duration_min": 45},
                }
            )
        )
        asyncio.run(
            db.user_stats.insert_one(
                {
                    "id": "stats-analytics",
                    "user_id": user_id,
                    "total_points": 120,
                    "max_streak": 4,
                }
            )
        )

        analytics_response = client.get("/api/analytics/student", headers=headers)
        assert analytics_response.status_code == 200
        analytics_payload = analytics_response.json()
        assert analytics_payload["analytics"]["weak_subjects"][0]["subject"] == "Mathematics"
        assert analytics_payload["analytics"]["weak_subjects"][0]["average"] == 50.0
        assert len(analytics_payload["analytics"]["performance_trend"]) == 2
        assert analytics_payload["analytics"]["total_study_minutes"] == 45
        assert analytics_payload["recommendations"][0]["subject"] == "Mathematics"

        badge_stats_before = client.get("/api/gamification/my-stats", headers=headers)
        assert badge_stats_before.status_code == 200
        assert badge_stats_before.json()["badge_count"] == 0

        badge_refresh_response = client.post("/api/gamification/badges/check", headers=headers)
        assert badge_refresh_response.status_code == 200
        assert badge_refresh_response.json()["count"] >= 1

        badge_stats_after = client.get("/api/gamification/my-stats", headers=headers)
        assert badge_stats_after.status_code == 200
        badge_payload = badge_stats_after.json()
        assert badge_payload["total_points"] == 120
        assert badge_payload["badge_count"] >= 1
        assert "quiz_master" in {badge["badge_id"] for badge in badge_payload["badges"]}

        search_engine = sys.modules["backend.services.suggestion_service"].search_engine
        search_engine.raise_error = True
        try:
            analytics_fallback_response = client.get("/api/analytics/student", headers=headers)
        finally:
            search_engine.raise_error = False

        assert analytics_fallback_response.status_code == 200
        fallback_payload = analytics_fallback_response.json()
        assert fallback_payload["analytics"]["weak_subjects"][0]["subject"] == "Mathematics"
        assert len(fallback_payload["analytics"]["performance_trend"]) == 2
        assert fallback_payload["recommendations"] == []


def test_lms_gradebook_attendance_invite_and_timetable_contracts():
    with _build_test_client() as client:
        _register_user(client, "teacher3@example.com", "secret123", "Teacher Three", role="Teacher")
        _register_user(client, "student3@example.com", "secret123", "Student Three")

        teacher_token = _login(client, "teacher3@example.com", "secret123")
        student_token = _login(client, "student3@example.com", "secret123")
        teacher_headers = _auth_headers(teacher_token)
        student_headers = _auth_headers(student_token)

        class_response = client.post(
            "/api/lms/classes",
            headers=teacher_headers,
            json={"name": "Physics I", "section": "B", "subject": "Physics"},
        )
        assert class_response.status_code == 200
        class_payload = class_response.json()
        class_id = class_payload["id"]

        existing_invite_response = client.post(
            f"/api/lms/classes/{class_id}/students/invite",
            headers=teacher_headers,
            json={"student_email": "student3@example.com"},
        )
        assert existing_invite_response.status_code == 200
        existing_invite_payload = existing_invite_response.json()
        assert existing_invite_payload["mode"] == "enrolled_existing"

        new_invite_response = client.post(
            f"/api/lms/classes/{class_id}/students/invite",
            headers=teacher_headers,
            json={"student_email": "newstudent@example.com", "student_name": "New Student"},
        )
        assert new_invite_response.status_code == 200
        new_invite_payload = new_invite_response.json()
        assert new_invite_payload["mode"] == "invited"
        assert "invite_token" in new_invite_payload
        assert "invite_url" in new_invite_payload

        db = client.app.state.fake_db
        assert any(doc["student_email"] == "newstudent@example.com" for doc in db.class_invitations.docs)

        _register_user(client, "newstudent@example.com", "secret123", "New Student")
        invited_user_doc = next(doc for doc in db.users.docs if doc["email"] == "newstudent@example.com")
        refreshed_class_doc = next(doc for doc in db.classes.docs if doc["id"] == class_id)
        accepted_invite_doc = next(doc for doc in db.class_invitations.docs if doc["student_email"] == "newstudent@example.com")
        assert str(invited_user_doc["_id"]) in refreshed_class_doc["students"]
        assert accepted_invite_doc["status"] == "accepted"

        assignment_response = client.post(
            "/api/lms/assignments",
            headers=teacher_headers,
            json={
                "class_id": class_id,
                "title": "Lab Report",
                "description": "Dynamics write-up",
                "max_points": 20,
            },
        )
        assert assignment_response.status_code == 200
        assignment_id = assignment_response.json()["id"]

        quiz_response = client.post(
            f"/api/lms/classes/{class_id}/quizzes",
            headers=teacher_headers,
            json={
                "title": "Newton Quiz",
                "time_limit": 20,
                "questions": [
                    {
                        "question": "Force equals?",
                        "type": "mcq",
                        "points": 2,
                        "options": [
                            {"label": "A", "text": "m * a", "is_correct": True},
                            {"label": "B", "text": "m / a", "is_correct": False},
                        ],
                    }
                ],
            },
        )
        assert quiz_response.status_code == 200
        quiz_id = quiz_response.json()["id"]

        submit_assignment_response = client.post(
            f"/api/lms/assignments/{assignment_id}/submit",
            headers={**student_headers, "Content-Type": "application/json"},
            json={"content": "Submitted report"},
        )
        assert submit_assignment_response.status_code == 200

        submissions_response = client.get("/api/lms/submissions", headers=teacher_headers)
        assert submissions_response.status_code == 200
        submission_id = submissions_response.json()[0]["submission_id"]

        grade_response = client.post(
            "/api/lms/submissions/grade",
            headers={**teacher_headers, "Content-Type": "application/json"},
            json={"submission_id": submission_id, "marks": 18, "feedback": "Strong work"},
        )
        assert grade_response.status_code == 200

        quiz_detail_response = client.get(f"/api/lms/quizzes/{quiz_id}", headers=student_headers)
        assert quiz_detail_response.status_code == 200
        question_id = quiz_detail_response.json()["questions"][0]["id"]

        quiz_attempt_response = client.post(
            f"/api/lms/quizzes/{quiz_id}/attempt",
            headers={**student_headers, "Content-Type": "application/json"},
            json={"answers": {question_id: "A"}},
        )
        assert quiz_attempt_response.status_code == 200

        attendance_update_response = client.put(
            f"/api/lms/classes/{class_id}/attendance/2026-04-15",
            headers={**teacher_headers, "Content-Type": "application/json"},
            json={
                "date": "2026-04-15",
                "records": [{"student_id": existing_invite_payload["student_id"], "status": "late"}],
            },
        )
        assert attendance_update_response.status_code == 200

        attendance_dates_response = client.get(
            f"/api/lms/classes/{class_id}/attendance/dates",
            headers=teacher_headers,
        )
        assert attendance_dates_response.status_code == 200
        attendance_dates_payload = attendance_dates_response.json()
        assert attendance_dates_payload[0]["date"] == "2026-04-15"
        assert attendance_dates_payload[0]["status_breakdown"]["late"] == 1

        my_attendance_response = client.get("/api/lms/students/me/attendance", headers=student_headers)
        assert my_attendance_response.status_code == 200
        my_attendance_payload = my_attendance_response.json()
        assert my_attendance_payload[0]["status"] == "late"

        attendance_stats_response = client.get(
            f"/api/lms/classes/{class_id}/attendance/stats",
            headers=student_headers,
        )
        assert attendance_stats_response.status_code == 200
        attendance_stats_payload = attendance_stats_response.json()
        assert attendance_stats_payload["present"] == 1
        assert attendance_stats_payload["overall_percentage"] == 100.0
        assert attendance_stats_payload["status_breakdown"]["late"] == 1

        gradebook_response = client.get(
            f"/api/lms/classes/{class_id}/gradebook",
            headers=teacher_headers,
        )
        assert gradebook_response.status_code == 200
        gradebook_payload = gradebook_response.json()
        assert gradebook_payload["class_name"] == "Physics I"
        assert gradebook_payload["assignments"][0]["title"] == "Lab Report"
        assert gradebook_payload["quizzes"][0]["title"] == "Newton Quiz"
        assert gradebook_payload["students"][0]["assignment_average"] == 90.0
        assert gradebook_payload["students"][0]["quiz_average"] == 100.0
        assert round(gradebook_payload["students"][0]["overall_percentage"], 1) == 90.9
        assert gradebook_payload["students"][0]["attendance_percentage"] == 100.0

        today_name = datetime.now().strftime("%A")
        asyncio.run(
            db.timetable.insert_one(
                {
                    "id": "slot-1",
                    "day_of_week": today_name,
                    "subject_id": "PHY101",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "room": "Lab-1",
                }
            )
        )

        timetable_response = client.get("/api/lms/students/me/timetable", headers=student_headers)
        assert timetable_response.status_code == 200
        timetable_payload = timetable_response.json()
        assert timetable_payload["today"] == today_name
        assert timetable_payload["classes"][0]["subject_id"] == "PHY101"
