# RAG AI Tutor / LMS Context (Token-Efficient)

This repo implements an educational product with two tightly coupled goals:
1. A **RAG AI Tutor** that answers questions grounded in user-uploaded course materials (with citations + answer validation).
2. A lightweight **LMS** that manages classes, assignments, quizzes, attendance, planning, analytics, and communication.

The codebase is in a stabilization state: features exist, but some flows still suffer from **schema drift** and **dual “quiz” systems**. This context file is designed so other AI models can understand the important contracts quickly, without re-reading the whole repo.

---

## 1) High-Level Architecture

### Frontend (Vanilla JS, page-based)
- Static HTML views in `frontend/public/views/`
- Shared browser helpers in `frontend/public/assets/js/`
- Runs as a SPA-like experience by loading/rendering content with vanilla JS (no React/Vue).

### Backend (FastAPI)
- Main entry: `backend/main.py`
- Backend routers:
  - Auth: `backend/api/auth.py`
  - Chat + RAG: `backend/api/chat.py`
  - Upload + ingestion: `backend/api/upload.py`
  - Citations chunk lookup: `backend/api/rag.py`
  - LMS: `backend/api/lms.py`
  - Planner: `backend/api/planner.py`
  - Notifications: `backend/api/notifications.py`
  - Analytics/Dashboard/Recommendations/Gamification: `backend/api/*.py` + `backend/services/*`

### Storage
- **MongoDB** (async via `motor`): user profiles, chat sessions, feedback, LMS data.
- **ChromaDB** (REST via `backend/vector_db.py`): chunk vectors + chunk text/metadata.

---

## 2) Middleware / Request Lifecycle

### CORS
- Defined in `backend/main.py` via `CORSMiddleware`
- Current behavior: `allow_origins=["*"]` (dev-friendly, production needs tightening).

### JWT auth + roles
- Login/register: `backend/api/auth.py`
- JWT decode dependency: `backend/api/auth.py:get_current_user`
- Role gate helper: `backend/api/auth.py:require_role(...)`
- Protected routes typically call `get_current_user` and then check `role`.

### Database init
- Lifespan hook in `backend/main.py`:
  - `init_db()` connects to Mongo
  - creates MongoDB indexes via `create_indexes()`
  - mounts static frontend at `/` (serves `frontend/public`).

---

## 3) RAG Tutor (Core AI Path)

### Retrieval Pipeline (Hybrid Search + Reranking)
- Retrieval code: `backend/core/search_engine.py`
- Approach:
  1. Fetch candidate chunks from:
     - user chunks
     - (optional) system “global” chunks
     - optional **document-scoped** filtering using `document_ids`
  2. **Hybrid search**:
     - BM25 keyword search
     - Vector search (embeddings)
  3. Fuse via **RRF** (Reciprocal Rank Fusion)
  4. Optional **Cross-Encoder reranking**:
     - `cross-encoder/ms-marco-MiniLM-L-6-v2`

### Orchestration (Prompting + Answer Generation)
- Main orchestrator: `backend/rag_tutor.py`
- Tiered routing (see `answer_query_with_rag`):
  1. **Document-scoped RAG** if `document_ids` provided
  2. **Knowledge base RAG** if user/system chunks exist
  3. **Gemini fallback** if no context available

### Streaming
- SSE endpoint in `backend/api/chat.py`:
  - `POST /api/chat/stream`
  - emits `meta`, then `token` events, then `done`, and (optionally) a `validation` event.

### Validation
- Answer validation uses `backend/core/evaluation/validator.py` (via `ValidationEngine`)
- In non-stream chat (`POST /api/chat/`), validation occurs inside `backend/rag_tutor.py`.
- In streaming, validation can be emitted after the `done` event.

---

## 4) GRAG (Graph-Augmented RAG)

- Graph pipeline code: `backend/core/grag.py` and services in `backend/services/grag_service.py`
- In `backend/rag_tutor.py`, GRAG is used when:
  - `file_count >= 2` and `chat_id` is present
- GRAG behavior (simplified):
  - build a knowledge graph from chunk text (LLM-extracted JSON)
  - traverse/aggregate graph context to enrich the prompt

---

## 5) Upload / Ingestion Pipeline

Primary upload route: `backend/api/upload.py`

Sequence:
1. Save uploaded file to disk: `backend/file_handler.py:save_upload_to_disk`
2. Extract text by file type: `backend/file_handler.py:extract_text_from_file`
   - PDF/DOCX/PPTX/TXT extraction
   - image/audio use Gemini vision/transcription with fallback OCR
3. Chunking:
   - `backend/preprocessing.py:create_chunks`
   - sliding window chunking with configured `chunk_size` + `chunk_overlap`
4. Indexing:
   - `backend/vector_db.py` stores chunk vectors into Chroma via REST
5. Metadata in Mongo:
   - document record inserted into Mongo (e.g., `documents` collection)
6. Chat session association:
   - uploads can create a new `chat_sessions` document-scoped session or append to an existing one
   - stores `document_ids`, `document_names`, and `file_count`-relevant fields for later GRAG behavior.

---

## 6) Citations (Chunk Lookup)

- Endpoint: `backend/api/rag.py`
- Route: `GET /api/chunks/{chunk_id}`
- Used by frontend citation UI to fetch the exact chunk text + metadata for display in a modal.

---

## 7) Adaptive Feedback Loop

- Feedback submission is handled in `backend/api/feedback.py` (stored in Mongo `feedback`).
- The RAG prompt may be adjusted based on feedback patterns:
  - `backend/core/feedback_analyzer.py` computes negative/positive ratios over the last 24h
  - `backend/rag_tutor.py` appends adaptive instructions when `should_adjust_prompt()` returns true.

---

## 8) LMS Domain (Classes, Assignments, Quizzes, Attendance)

- Main LMS router: `backend/api/lms.py`
- Role/authorization:
  - teacher/admin typically create/manage
  - student accesses only enrolled class resources

Key resources handled in `backend/api/lms.py`:
- Classes + enrollments
- Curriculum units + materials
- Assignments + submissions + grading (teacher/admin)
- Quizzes:
  - teacher creates quizzes
  - student attempts quizzes
  - teacher/admin sees answers depending on authorization
- Attendance:
  - mark attendance (teacher)
  - view own attendance (student)

Important repo risk (from existing project docs):
- There are **dual quiz paths** (legacy quiz API vs LMS quiz API). Future work should unify or clearly separate them.

---

## 9) Frontend Shape (Where to look)

Major view screens:
- `frontend/public/views/dashboard.html`
- `frontend/public/views/subjects.html` (chat workspace + citations)
- `frontend/public/views/upload.html`
- `frontend/public/views/quiz.html` and `frontend/public/views/lms_quiz.html`
- `frontend/public/views/student_lms.html`, `frontend/public/views/teacher_portal.html`

Shared helpers:
- `frontend/public/assets/js/` (auth config, chat formatting, upload handling, notifications).

---

## 10) Improvement Opportunities (Already Documented)

This repo already contains a stabilization and production hardening plan in `docs/PRODUCTION_READINESS_PLAN.md` and refactoring notes in `docs/IMPROVEMENTS.md`.

Top practical improvement themes:
1. **Stabilize contracts** (canonical Mongo collections + canonical response shapes)
2. **Remove or isolate schema drift** between “legacy” and “new” LMS/RAG code
3. Consolidate duplicated frontend fetch/auth/render logic
4. Increase automated coverage (contract tests + API integration tests for core journeys)
5. Security/reliability hardening:
   - tighten CORS
   - reduce broad exception handling
   - structured logging + safer default secrets
   - timeouts/retries/fallbacks for LLM + Chroma interactions

---

## 11) Where to Find “Authoritative” Repo Notes (for other AI models)

If you are trying to understand or modify the system without re-reading everything:
- `docs/PROJECT_SUMMARY.md` (product goals + current reality)
- `docs/SYSTEM_FLOW.md` (end-to-end flow visualization)
- `docs/ARCHITECTURE.md` (how RAG works)
- `docs/CODE_ARCHITECTURE_MAPPING.md` (component-to-file map + endpoint-to-frontend map)
- `docs/IMPROVEMENTS.md` (refactoring + safety gaps)
- `docs/PRODUCTION_READINESS_PLAN.md` (phased execution plan)

