# RAG AI Tutor / OpenLearnHub — 10-Day Build Plan

**Purpose:** Build the full RAG AI Tutor (OpenLearnHub) from the current repo in 10 days, with the correct order of work and clear daily milestones.

---

## 1. Project & Workflow Summary

### What the project is
- **Product:** RAG-based AI tutoring platform (README: "RAG AI Tutor"; frontend: "OpenLearnHub").
- **Users:** School, Intermediate, Engineering students.
- **Core features:** Document upload (PDF/DOCX/TXT/images + OCR), Socratic AI chat, hybrid search (BM25 + dense + rerank), quiz generation, feedback, multi-subject (Math, Science, CS, ML, Physics, Chemistry).

### Repo and “which repo to start”
- **Single repo:** `RAG-AI-Tutor`. There is only one repository; start here and build backend first, then frontend, then integration.
- **Correct process:** Backend (API + DB + RAG pipeline) → Config & env → Frontend missing pages/JS → Wire frontend to API → Docker & docs.

### Current state (as of plan creation)

| Layer | Status | Notes |
|-------|--------|--------|
| **README** | Complete | Describes FastAPI, MongoDB, ChromaDB, Gemini, hybrid RAG, API surface. |
| **Backend** | Stub only | `backend/config.py`, `file_handler.py`, `preprocessing.py`, `vector_db.py`, `feedback.py` exist but are **empty**. No `main.py`, no `api/`, `core/`, `models/`, `utils/`. |
| **requirements.txt** | Missing | Referenced in README only. |
| **Config** | Empty files | `config/models_config.yaml`, `production.yaml`, `subjects_config.yaml`, `development.yaml` exist but empty. |
| **.env.example** | Empty | No template for API keys / DB. |
| **docker-compose.yml** | Empty | No services defined. |
| **Scripts** | Stubs | `scripts/setup.py`, `download_models.py`, `preprocess_data.py`, `deploy.sh` exist but empty. |
| **Frontend – HTML** | Partial | `index.html`, `login.html`, `signup.html`, `subjects.html` are implemented. **Missing:** `chatbot.html`, `doubts.html`. |
| **Frontend – JS** | Partial | `auth.js` (JWT, login/signup, `OLH_AUTH`), `subjects.js` (grid, voice search, links to `chatbot.html?subject=...`). Other JS (chat, upload, quiz, feedback, voice) may exist as stubs. |
| **Frontend – CSS** | Done | `main.css`, `components.css`, `auth.css` — full glassmorphic design + chat/doubts/upload styles. |
| **API contract** | Implied | Frontend uses `http://localhost:5000/api`; README says app on 8000. **Decision:** Standardize on **one port** (e.g. 8000 for FastAPI serving frontend + API). |

### High-level workflow (target)

1. **Backend:** FastAPI app → MongoDB (users, sessions, feedback) → ChromaDB (vectors) → RAG pipeline (ingest → embed → hybrid search → LLM).
2. **Frontend:** Static HTML/JS/CSS served by FastAPI (or same origin); auth via JWT; chat, upload, doubts, quiz call backend API.
3. **Run:** `python -m backend.main` or `uvicorn backend.main:app --reload` → one origin (e.g. `http://localhost:8000`) for UI + API.

---

## 2. Standardization Decisions Before Building

- **Single port:** Use **8000** for the app (FastAPI serves both static frontend and `/api`). Update frontend `API_BASE` from `http://localhost:5000/api` to `/api` (relative) or `http://localhost:8000/api`.
- **Backend structure:** Create `backend/main.py`, `backend/api/`, `backend/core/`, `backend/models/`, `backend/utils/` as in README; implement the existing stub files under this layout.
- **Config:** Populate YAML and `.env.example` so that Day 1–2 setup is unambiguous.

---

## 3. 10-Day Build Plan (Day-by-Day)

### Day 1 — Repo foundation and backend skeleton
**Goal:** One command to run the app (backend only) and open API docs.

- Create `requirements.txt` with: `fastapi`, `uvicorn[standard]`, `python-multipart`, `pydantic`, `pydantic-settings`, `python-dotenv`, `pyyaml`, `motor` (or `pymongo`), `chromadb`, `sentence-transformers`, and placeholders for OCR/LLM (e.g. `pypdf2`, `python-docx`, `pillow`, `google-generativeai` — exact list in section 4).
- Add `backend/main.py`: FastAPI app, mount static files from `frontend/public` at `/`, serve `index.html` at `/` and route other HTML; include CORS if needed.
- Create `backend/api/` with `__init__.py` and empty routers: `auth.py`, `upload.py`, `chat.py`, `quiz.py`, `feedback.py`; register them in `main.py` under `/api`.
- Create `backend/config.py`: load from `.env` and YAML (e.g. `config/development.yaml` / `config/production.yaml`), expose settings (MongoDB URI, Chroma path, API keys, JWT secret).
- Populate `.env.example` with: `GEMINI_API_KEY`, `MONGODB_URI`, `SECRET_KEY`, `JWT_SECRET_KEY`, `DEBUG`, optional `GROQ_API_KEY`, `OPENAI_API_KEY`.
- **Deliverable:** `uvicorn backend.main:app --reload` runs; `http://localhost:8000/docs` shows Swagger; `http://localhost:8000` serves `index.html`.

---

### Day 2 — Database and auth API
**Goal:** MongoDB connected; register/login and `/api/auth/me` work with JWT.

- Add `backend/models/` (e.g. `user.py`, `schemas.py`): Pydantic schemas for register/login/me; user document shape (email, hashed password, name, level).
- Implement `backend/utils/db.py`: MongoDB connection (single client/DB); optional dependency injection for request scope.
- Implement `backend/utils/auth.py`: hash passwords (e.g. bcrypt), verify, create/verify JWT (e.g. `python-jose` or PyJWT).
- Implement `backend/api/auth.py`: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`; use same request/response shape as frontend `auth.js` (e.g. `token`, `user` with name, email, level).
- **Deliverable:** Register and login from API docs or curl; `GET /api/auth/me` with Bearer token returns current user. Frontend not yet wired (optional: point `API_BASE` to 8000 and smoke-test login from browser).

---

### Day 3 — Config, embeddings, and vector DB
**Goal:** Config and embedding pipeline ready; ChromaDB initialized; no LLM yet.

- Populate `config/models_config.yaml` (embedding model name, dimensions); `config/subjects_config.yaml` (subject ids and names); keep `development.yaml` / `production.yaml` minimal (e.g. env overrides).
- Implement `backend/core/embeddings.py`: load Sentence Transformer (e.g. `all-MiniLM-L6-v2`), function `embed(texts: list[str]) -> list[list[float]]`.
- Implement `backend/vector_db.py`: ChromaDB client; create/get collection; `add_documents(ids, texts, metadatas)`, `query(embedding, n_results, where)`.
- Implement `backend/preprocessing.py`: chunking (e.g. 600 chars, 100 overlap), normalize whitespace; optional: extract text from PDF/DOCX/TXT (stub image/OCR for later).
- **Deliverable:** Script or endpoint that: takes a short text, chunks it, embeds, stores in Chroma, runs a query and returns matches. No HTTP upload yet.

---

### Day 4 — Document upload and ingestion
**Goal:** Upload PDF/DOCX/TXT; store file metadata in MongoDB; extract text, chunk, embed, store in Chroma.

- Implement `backend/file_handler.py`: extract text (PyPDF2, python-docx, plain text); optional: image path → stub or simple OCR (e.g. Tesseract) for later.
- Implement `backend/api/upload.py`: `POST /api/upload/` (multipart file); validate type/size; save file or content; create document record in MongoDB (user_id, filename, subject, status); run preprocessing + embedding + `vector_db.add_documents` (link chunks to document_id).
- Add `GET /api/upload/` (list user’s documents), `DELETE /api/upload/{document_id}` (remove from MongoDB and Chroma).
- **Deliverable:** Upload a PDF via API docs; document appears in MongoDB and relevant chunks in Chroma. Frontend upload page can be wired on Day 7.

---

### Day 5 — RAG retrieval and LLM
**Goal:** Hybrid retrieval (BM25 + dense + rerank) and one LLM provider (e.g. Gemini) producing Socratic-style answers.

- Implement `backend/core/search.py`: BM25 (e.g. `rank_bm25`) over chunk texts; dense search via Chroma; fusion (e.g. RRF); optional reranker (e.g. cross-encoder). Input: query + optional filters (user_id, document_id, subject).
- Implement `backend/core/llm.py`: load config (Gemini key); function `generate(context: str, query: str, system_prompt: str)` returning string; system prompt encourages Socratic tutoring.
- Implement RAG pipeline in `backend/core/rag.py` or inside chat: query → embed → hybrid search → top-k chunks → build context string → LLM generate → return answer + citations (chunk ids/metadata).
- **Deliverable:** Server-side or script: given a query, get RAG response with citations. No streaming yet.

---

### Day 6 — Chat API and streaming (optional)
**Goal:** Chat API with history and optional streaming.

- Implement `backend/models/` (or schemas) for chat: session, message (role, content, sources).
- Implement `backend/api/chat.py`: `POST /api/chat/` (message + session_id); load or create session; run RAG; append user message and assistant message; save to MongoDB; return full response. Optional: `GET /api/chat/stream` or streaming response in POST.
- Endpoints: `GET /api/chat/sessions`, `GET /api/chat/sessions/{id}`.
- **Deliverable:** Send a message via API; get RAG reply and session persisted. Frontend chat UI can be wired on Day 7.

---

### Day 7 — Frontend: chatbot and doubts pages + API wiring
**Goal:** All main frontend pages exist and call the backend on port 8000.

- Create `frontend/public/chatbot.html`: layout consistent with existing pages; chat container, messages area, input; optional subject from `?subject=...`; load `chat_utils.js` (or inline) to call `POST /api/chat/` and render messages/citations.
- Create `frontend/public/doubts.html`: upload area (image/file), list of “doubt” items; load `upload.js` and optional `feedback.js` to call `POST /api/upload/` and list documents/doubts.
- Add or update `frontend/src/js/chat_utils.js`: use `OLH_AUTH.apiFetch` and `/api/chat/`; optional streaming handling.
- Add or update `frontend/src/js/upload.js`: file picker/drag-drop; `POST /api/upload/` with FormData and auth token; list from `GET /api/upload/`.
- Set frontend `API_BASE` to `/api` (relative) or `http://localhost:8000/api` in `auth.js` and `subjects.js` (and any other JS that calls the API).
- **Deliverable:** From browser: login → subjects → open chatbot by subject → send message and see reply; open doubts → upload file and see it in list.

---

### Day 8 — Quiz and feedback APIs + frontend
**Goal:** Quiz generation and submission; feedback collection; frontend buttons wired.

- Implement `backend/api/quiz.py`: `POST /api/quiz/generate` (e.g. document_ids or subject, difficulty, num_questions); call LLM to generate questions/options; save quiz in MongoDB; return quiz id and questions. `GET /api/quiz/`, `GET /api/quiz/{id}`, `POST /api/quiz/{id}/submit` (answers) → score and store result.
- Implement `backend/api/feedback.py`: `POST /api/feedback/` (rating, optional text, message_id/session_id); `GET /api/feedback/` (admin or filtered). Reuse or implement `backend/feedback.py` as service layer.
- Add or update `frontend/src/js/quiz_handler.js`: call generate, render quiz, submit, show score.
- Add or update `frontend/src/js/feedback.js`: submit rating/feedback after chat or quiz.
- **Deliverable:** Generate quiz from API/frontend; submit answers; post feedback; see results.

---

### Day 9 — Scripts, config, and polish
**Goal:** Setup repeatable; config and env documented; optional model download.

- Implement `scripts/setup.py`: create dirs (e.g. `data/`, `data/chroma`), copy `.env.example` to `.env` if missing, print next steps (install deps, set API keys, run MongoDB).
- Implement `scripts/download_models.py`: download Sentence Transformer (and optional reranker) so first run is faster.
- Fill `config/models_config.yaml` and `config/subjects_config.yaml` with final model names and subject list.
- Add `README` section: “Quick start (10 days build)”: clone → `pip install -r requirements.txt` → `python scripts/setup.py` → set `.env` → start MongoDB → `uvicorn backend.main:app --reload`.
- **Deliverable:** New clone can follow README and run app; models pre-downloadable.

---

### Day 10 — Docker and final checks
**Goal:** Run full stack with Docker; document deployment.

- Implement `docker-compose.yml`: services `backend` (build from Dockerfile), `mongodb` (image mongo:7.0), optional `frontend` (nginx or serve from backend). Backend env: `MONGODB_URI=mongodb://mongodb:27017`, API keys from env.
- Add `Dockerfile` for backend: Python 3.11, install requirements, copy backend + frontend, run uvicorn.
- Update README: Docker run instructions; note that ChromaDB can use a volume for persistence.
- **Deliverable:** `docker-compose up` brings up app and MongoDB; open `http://localhost:8000` and run through: register → login → upload → chat → quiz → feedback.

---

## 4. Suggested `requirements.txt` (Starter)

```text
# Core
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
python-multipart>=0.0.6
pydantic>=2.0
pydantic-settings>=2.0
python-dotenv>=1.0.0
pyyaml>=6.0

# Database
motor>=3.3.0
pymongo>=4.6.0

# Vector & ML
chromadb>=0.4.0
sentence-transformers>=2.2.0

# Documents & OCR (optional)
pypdf2>=3.0.0
python-docx>=1.0.0
pillow>=10.0.0
# pytesseract  # uncomment if using OCR

# LLM
google-generativeai>=0.3.0

# Auth
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4

# Search (BM25)
rank_bm25>=0.2.2
```

Adjust versions and add reranker/OpenAI/Groq as needed.

---

## 5. Order of Work (Summary)

1. **Repo:** Only this repo; no separate “backend repo” or “frontend repo.”
2. **Start with backend:** Days 1–2 (app + auth), then 3–6 (config, RAG, upload, chat).
3. **Then frontend:** Day 7 (chatbot + doubts + API base URL), Day 8 (quiz + feedback).
4. **Then ops and polish:** Day 9 (scripts, config), Day 10 (Docker, README).

---

## 6. Risk and Mitigation

- **Scope creep:** Stick to one LLM (Gemini) and simple BM25 + Chroma first; add reranker/OpenAI later.
- **Port/API mismatch:** Fix once on Day 1 (use 8000 and relative `/api` or full URL in frontend).
- **Empty files:** Treat existing stub files as placeholders; implement under the structure in README (e.g. `backend/core/`, `backend/api/`).
- **Missing frontend JS:** If `chat_utils.js`, `upload.js`, etc. are missing, create them on Day 7 using `auth.js` and `components.css` patterns.

---

## 7. Definition of Done (End of Day 10)

- [ ] One command runs the app (`uvicorn backend.main:app` or `docker-compose up`).
- [ ] User can register, login, and use JWT for authenticated requests.
- [ ] User can upload a document (PDF/DOCX/TXT); it is chunked, embedded, and stored in Chroma + metadata in MongoDB.
- [ ] User can chat in the UI; backend runs RAG (hybrid search + LLM) and returns Socratic-style answers with citations.
- [ ] User can generate and submit a quiz and post feedback.
- [ ] README and scripts allow a fresh clone to be set up and run (with API keys and MongoDB).

This plan is the “correct process” to build the project in 10 days from the current repo: start with the backend in this repo, then frontend, then integration and deployment.
