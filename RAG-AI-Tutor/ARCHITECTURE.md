# 📐 Code-to-Architecture Mapping

This document helps developers locate the specific files responsible for architectural components.

---

## 🗺️ Component Map

| Component | Responsible File(s) | Description |
| :--- | :--- | :--- |
| **Search Engine** | `backend/core/search_engine.py` | Implements Hybrid Search (BM25 + Vector). |
| **Vector Store** | `backend/vector_db.py` | Manages JSON-based vector storage and persistence. |
| **RAG Orchestrator** | `backend/core/rag_tutor.py` | Combines retrieval and generation logic. |
| **LLM Interface** | `backend/core/llm_interface.py` | Wrapper for Gemini/Google GenAI calls. |
| **Quiz Logic** | `backend/core/quiz_generator.py` | Generates questions from document chunks. |
| **User Profile** | `backend/core/student_profile.py` | Tracks user stats and weak topics. |
| **Feedback Analysis** | `backend/core/feedback_analyzer.py` | Processes user ratings. |

---

## 🔗 API <-> Frontend Usage

Mapping which frontend pages call which backend endpoints.

### 1. **Login Page** (`login.html`)
*   `POST /api/auth/login` -> `backend/api/auth.py:login`

### 2. **Signup Page** (`signup.html`)
*   `POST /api/auth/register` -> `backend/api/auth.py:register`

### 3. **Chat Page** (`chat.html`)
*   `POST /api/chat/` -> `backend/api/chat.py:chat` (Sends message)
*   `GET /api/chat/sessions` -> `backend/api/chat.py:list_sessions` (Sidebar)

### 4. **Upload Page** (`upload.html`)
*   `POST /api/upload/` -> `backend/api/upload.py:upload_document`

### 5. **Quiz Page** (`quiz.html`)
*   `POST /api/quiz/generate` -> `backend/api/quiz.py:generate_quiz_endpoint`
*   `POST /api/quiz/submit` -> `backend/api/quiz.py:submit_quiz_endpoint`



---

## 💾 Data Models <-> MongoDB

Mapping Pydantic models (code) to Database Storage.

| Concept | Pydantic Model (`backend/models/`) | MongoDB Collection | Notes |
| :--- | :--- | :--- | :--- |
| **User** | `UserCreate` / `UserInDB` | `users` | Stores email, hashed_pw, level. |
| **Chat** | schema in `api/chat.py` | `chat_sessions` | Stores array of messages + metadata. |
| **Quiz** | schema in `api/quiz.py` | `quizzes` | Stores generated questions. |
| **Quiz Result** | schema in `api/quiz.py` | `quiz_submissions` | Stores user answers and score. |
| **Document** | N/A (Dict) | `documents` | Metadata (filename, chunk_count). |
| **Feedback** | `FeedbackSubmitRequest` | `feedback` | User ratings and comments. |

---

## 📂 Directory to Layer Mapping

*   **Presentation Layer**: `frontend/public/views/`
*   **API Layer**: `backend/api/`
*   **Business Logic Layer**: `backend/core/`
*   **Data Access Layer**: `backend/utils/db.py` & `backend/vector_db.py`
