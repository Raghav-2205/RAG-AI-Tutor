# RAG AI Tutor / LMS V2 Project Summary

## Overview
This repository is a full-stack educational platform built around two connected ideas:

1. A RAG-based AI tutor that answers questions from uploaded learning material.
2. A lightweight LMS that manages classes, assignments, quizzes, attendance, planning, analytics, and communication.

The current codebase is no longer just a "chat with documents" app. It is an LMS-shaped product with AI tutoring at the center.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python, FastAPI, Uvicorn |
| Database | MongoDB |
| Vector Store | ChromaDB |
| LLM | Google Gemini REST API |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`) |
| Reranking | Cross Encoder (`ms-marco-MiniLM-L-6-v2`) |
| Frontend | Static HTML, CSS, and Vanilla JavaScript |
| Deployment Shape | Combined FastAPI app serving API + static frontend |

## Top-Level Structure

```text
backend/
  api/                FastAPI routers
  core/               retrieval, LLM, evaluation, embeddings
  services/           LMS, planner, analytics, notifications, gamification
  models/             Pydantic and response models
  utils/              DB and shared helpers
frontend/public/
  assets/js/          shared browser-side helpers
  views/              page-level HTML/JS screens
docs/
  production and architecture notes
run.py                local app entrypoint
docker-compose.yml    MongoDB + ChromaDB dependencies
```

## Main Product Areas

### 1. Authentication and Roles
- JWT auth lives in `backend/api/auth.py`.
- The platform uses role-based behavior for `Admin`, `Teacher`, and `Student`.

### 2. RAG Tutor
- Upload flow starts in `backend/api/upload.py`.
- Files are parsed, chunked, embedded, stored in ChromaDB, and indexed in MongoDB.
- Chat flow lives in `backend/api/chat.py` and `backend/rag_tutor.py`.
- Retrieval uses hybrid search in `backend/core/search_engine.py`.
- Answers can stream back with citations and validation metadata.

### 3. LMS
- Core LMS routes live in `backend/api/lms.py`.
- Core LMS business logic lives in `backend/services/lms_service.py`.
- Supported entities include:
  - classes
  - enrollments
  - units and materials
  - assignments and submissions
  - quizzes and quiz attempts
  - attendance

### 4. Planner and Calendar
- Planner routes live in `backend/api/planner.py`.
- Calendar and schedule aggregation come from planner and LMS data.
- Students can generate plans, log activity, and view upcoming work.

### 5. Analytics, Suggestions, and Gamification
- Dashboard aggregation is in `backend/api/dashboard.py`.
- Analytics and recommendations are split across:
  - `backend/services/analytics_service.py`
  - `backend/services/suggestion_service.py`
  - `backend/services/gamification_service.py`

### 6. Communication Layer
- Notices, events, announcements, forum/community, and notifications are implemented through dedicated API routes and services.

## Current Frontend Shape
- The frontend is not React. It is page-based HTML with inline scripts and shared JS helpers.
- Shared helpers live under `frontend/public/assets/js/`.
- Major pages include:
  - `views/subjects.html` for document chat
  - `views/dashboard.html` for student overview
  - `views/student_lms.html` for student LMS flows
  - `views/teacher_portal.html` for teacher workflows
  - `views/lms.html` for a broader LMS shell
  - `views/lms_quiz.html` and `views/quiz.html` for quiz flows

## Important Architectural Reality
The repo is currently in a transition state between older "RAG tutor" code and newer LMS code.

The biggest source of bugs has been schema drift:
- old collection names vs new collection names
- old quiz flows vs LMS quiz flows
- old frontend API assumptions vs current FastAPI routes
- inconsistent response field names across pages

This means the app already has many real features, but some flows still depend on mixed generations of code.

## Stabilization Work Already Completed
Recent stabilization work in this branch has focused on high-confidence runtime issues:
- calendar ownership and user ID fixes
- planner/calendar aggregation fixes for assignments and quizzes
- dashboard migration from legacy quiz collections to LMS quiz attempts
- notifications API and mark-as-read ownership fixes
- feedback validation fixes against current chat and LMS quiz data
- RAG citation lookup fixes across user collections
- frontend API base URL cleanup for shared JS helpers
- attendance route conflict removal
- LMS quiz hardening:
  - fixed broken LMS fetch paths in `views/quiz.html`
  - stopped leaking quiz answer keys from the quiz detail API to students
  - returned review-safe quiz result data after submission
  - aligned student quiz lists with actual submission status
- automated verification:
  - added isolated API integration coverage for auth, upload, chat, standalone quiz, LMS, planner, dashboard, and notifications
  - added static serving smoke coverage for the main LMS and tutor page entrypoints
  - added a real Mongo-backed LMS smoke path for class and quiz persistence
  - wired both suites into GitHub Actions workflows

## Main Risks Still Remaining

### 1. Dual Quiz Systems
There are still two quiz paths in the repo:
- `backend/api/quiz.py` for the older standalone AI quiz flow
- `backend/api/lms.py` for the LMS quiz flow

These should eventually be unified or explicitly separated with clean contracts.

### 2. Frontend Duplication
Many pages duplicate:
- API request logic
- token handling
- rendering logic
- empty/error/loading states

This increases regression risk and makes small backend changes expensive.

### 3. Partial Automated Test Coverage
The project now has meaningful automated backend coverage, but still needs:
- broader unit tests around service modules
- browser-level interaction coverage for major student/teacher journeys
- live external-service validation for Chroma and Gemini paths

### 4. Production Hardening Gaps
The repo still needs stronger:
- permissions and authorization coverage
- deployment environment separation
- monitoring and structured logging
- CI/CD checks
- rollback and recovery workflow

## Production Readiness Priorities
The detailed rollout plan lives in `docs/PRODUCTION_READINESS_PLAN.md`.

The recommended implementation order is:

1. Stabilize data models and API contracts.
2. Close remaining authorization and security gaps.
3. Add automated tests around the stabilized contracts.
4. Consolidate duplicated frontend logic.
5. Finish deployment, observability, and release workflows.

## Local Run Notes
Typical local development uses:

```powershell
docker compose up -d
python run.py
```

The app is served through the FastAPI process, which also serves the static frontend.
Default local URL: `http://127.0.0.1:8003`

Startup checklist:
- MongoDB must be running before auth and LMS routes will work
- Gemini-backed chat features require `GEMINI_API_KEY`
- Retrieval-backed document flows depend on valid Chroma configuration

## Recommended Next Engineering Slice
The next high-value slice is:

1. Add browser or page-level smoke coverage for the main LMS and tutor screens.
2. Validate one live end-to-end RAG path with real Mongo + Chroma dependencies.
3. Audit remaining references to the legacy standalone quiz system.
4. Validate the core user journeys end to end:
   - register/login
   - upload and ask a question
   - join or create a class
   - submit an assignment
   - take an LMS quiz
   - open dashboard, planner, and notifications
