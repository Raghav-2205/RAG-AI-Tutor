# Backend build complete — how to run and see output

## What was built (backend only)

| File | Purpose |
|------|--------|
| `requirements.txt` | Python dependencies (FastAPI, uvicorn, pymongo, auth, etc.) |
| `backend/config.py` | Loads .env; exposes `settings` (MongoDB, JWT, paths) |
| `backend/main.py` | FastAPI app: `/api/auth/*`, `/`, `/login.html`, `/subjects.html`, `/health`, `/docs` |
| `backend/api/__init__.py` | Exports `auth_router` |
| `backend/api/auth.py` | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me` |
| `backend/models/user.py` | UserCreate, UserLogin, UserResponse, user_doc_to_response |
| `backend/utils/db.py` | MongoDB `get_client()`, `get_db()` |
| `backend/utils/auth_utils.py` | JWT create/decode, bcrypt hash/verify |
| `.env.example` | Template for MONGODB_URI, JWT_SECRET_KEY, etc. |

---

## Run the backend and see output in the interface

### 1. Install dependencies (in project root)

```powershell
cd "C:\Users\RAGHAVENDRA SWAMY\Documents\GitHub\RAG-AI-Tutor"
pip install -r requirements.txt
```

If you get permission errors, use a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. (Optional) Create .env

```powershell
copy .env.example .env
# Edit .env and set MONGODB_URI=mongodb://localhost:27017 if MongoDB is local
```

### 3. Start MongoDB (required for register/login)

- **Docker:** `docker run -d -p 27017:27017 --name mongodb mongo:7.0`
- **Or** start your local MongoDB service.

### 4. Start the backend (use port **8000**, not 80001)

```powershell
cd "C:\Users\RAGHAVENDRA SWAMY\Documents\GitHub\RAG-AI-Tutor"
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Note:** Port must be **8000**. Using `80001` will fail (invalid/privileged port or wrong URL in browser).

You should see output like:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process ...
INFO:     Started server process ...
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

---

## See output in the interface

### A. API docs (Swagger)

1. Open in browser: **http://localhost:8000/docs**
2. You’ll see:
   - **GET /health** — health check
   - **POST /api/auth/register** — register
   - **POST /api/auth/login** — login
   - **GET /api/auth/me** — current user (needs Bearer token)

**Try in Swagger:**

- **GET /health** → Execute → Response: `{"status":"ok","service":"rag-ai-tutor"}`
- **POST /api/auth/register** → body:
  ```json
  {"name": "Test User", "email": "test@example.com", "password": "test123", "level": "school"}
  ```
  → Execute → Response: `{"user": {...}, "token": "eyJ..."}`

### B. Web UI (frontend)

1. Open: **http://localhost:8000**
2. You’ll see the OpenLearnHub home page (hero, level cards, nav).
3. Click **Login** → **http://localhost:8000/login.html**
4. Login or Sign up; the frontend calls `/api` on the same port (8000), so register/login work from the UI.

### C. Health check from terminal

```powershell
curl http://localhost:8000/health
```

Expected: `{"status":"ok","service":"rag-ai-tutor"}`

---

## Quick checklist

| Step | Action | Where you see output |
|------|--------|----------------------|
| 1 | Run `uvicorn backend.main:app --reload --port 8000` | Terminal: “Uvicorn running on http://0.0.0.0:8000” |
| 2 | Open http://localhost:8000 | Browser: OpenLearnHub home page |
| 3 | Open http://localhost:8000/docs | Browser: Swagger UI with auth and health |
| 4 | Open http://localhost:8000/health | Browser or curl: `{"status":"ok",...}` |
| 5 | Register/Login from http://localhost:8000/login.html | Browser: redirect to subjects after success |

Backend build stops here; frontend already points at `/api` on the same host, so the interface uses this backend when you run it on port 8000.
