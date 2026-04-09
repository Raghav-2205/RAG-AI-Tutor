# 🚀 Deployment & Setup Guide

This guide details how to set up the **RAG AI Tutor** environment, configure databases, and run the system locally or via Docker.

---

## 📋 Prerequisites

-   **Python 3.10+** (Recommend 3.11 for performance)
-   **MongoDB 7.0+** (Local or Atlas)
-   **Node.js 18+** (Optional, only if using future frontend build tools)
-   **Git**

---

## 🛠️ Local Setup

### 1. Clone & Environment

```bash
git clone https://github.com/your-org/RAG-AI-Tutor.git
cd RAG-AI-Tutor

# Create Virtual Environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Variables

Create a `.env` file in the root directory:

```ini
# Database (MongoDB)
MONGODB_URI=mongodb://localhost:27017/
DATABASE_NAME=rag_ai_tutor

# Security
JWT_SECRET_KEY=your_super_secret_key_change_this
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# LLM (Gemini)
GEMINI_API_KEY=your_gemini_api_key_here

# Vector Store (ChromaDB)
RUN_PORT=8003
CHROMA_API_URL=http://localhost:8001/api/v2
# Chroma stores data in ./chroma_db if running locally without docker
```

---

## 🗄️ Database Setup

### Option A: Local MongoDB (Recommended for Dev)
1.  Install [MongoDB Community Server](https://www.mongodb.com/try/download/community).
2.  Start the service: `mongod`.
3.  The URI is `mongodb://localhost:27017`.

### Option B: Docker (Recommended for Prod)
Run MongoDB in a container:
```bash
docker run -d -p 27017:27017 --name mongodb mongo:7.0
```

---

## 🧠 Vector Store (ChromaDB)
The system uses **ChromaDB** for embedding storage.

### Option A: Embedded (Local)
By default, the backend runs ChromaDB in embedded mode, persisting data to `./chroma_db`. No extra setup needed.

### Option B: Client/Server (Docker)
(Optional) Run ChromaDB as a standalone server:
```bash
docker run -d -p 8000:8000 chromadb/chroma
```
*If using this, update `CHROMA_API_URL` in `.env`.*

---

## 🚀 Running the System

### 1. Start Required Services

Typical local development uses:

```bash
docker compose up -d
```

Minimum checklist:
- MongoDB must be reachable before auth and LMS flows can work
- `GEMINI_API_KEY` is required for live RAG generation
- Chroma settings must be valid for retrieval-backed document flows

### 2. Start the App

Use the repo entrypoint:

```bash
python run.py
```

The app will serve both backend and frontend from:

```bash
http://127.0.0.1:8003
```

You can still run the backend directly with Uvicorn when needed:

```bash
# Development (Auto-reload)
uvicorn backend.main:app --reload --port 8003

# Production
uvicorn backend.main:app --host 0.0.0.0 --port 8003 --workers 4
```

### 3. Start the Frontend

Since the frontend is Vanilla JS, you can serve it via the backend (integrated) or standalone.

**Option A: Integrated (Easiest)**
The FastAPI app automatically serves `frontend/public` at the root URL `http://127.0.0.1:8003`.
Just open `http://127.0.0.1:8003` in your browser.

**Option B: Standalone (For Dev)**
Use a simple HTTP server to serve `frontend/public`:
```bash
cd frontend/public
python -m http.server 3000
```
Open `http://localhost:3000`. *Note: standalone frontend mode still depends on the backend being available at the configured API origin.*

---

## 🔄 Data Ingestion

To populate your RAG vector store:

1.  Place your course documents (PDF, DOCX, TXT) in `data/base_dataset`.
2.  Run the recursive ingestion script:
    ```bash
    python scripts/ingest_data_folder.py
    ```
    This will:
    -   Parse all files.
    -   Chunk text (600 chars).
    -   Generate embeddings.
    -   Store them in ChromaDB.

---

## ✅ Verification

Run the end-to-end test script to verify the pipeline:

```bash
python test_advanced_rag_flow.py
```
This script will:
1.  Register a test user.
2.  Login and get a JWT.
3.  Perform a RAG search query.
4.  Fetch citation details.
5.  Verify the response structure.
