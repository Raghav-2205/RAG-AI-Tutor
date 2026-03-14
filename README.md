# 🚀 RAG AI Tutor

> **A Production-Grade Adaptive Learning System with Advanced RAG Architecture**

The RAG AI Tutor is a sophisticated educational platform that personalizes learning by combining Large Language Models (LLMs) with Retrieval-Augmented Generation (RAG). It dynamically adapts to a student's proficiency level, provides real-time feedback, and grounds all AI responses in verified course materials.

---

## 🎯 Project Objectives

The primary goal of this project is to build an intelligent tutoring system that overcomes the limitations of generic LLMs.

### 1. **High-Precision Retrieval (Advanced RAG)**
*   **Objective**: Eliminate hallucinations and ensure answers are grounded in course material.
*   **Implementation**: A multi-stage pipeline using **Hybrid Search** (BM25 + Vector) for broad recall, followed by **Cross-Encoder Reranking** for deep semantic precision.

### 2. **Self-Correcting Feedback Loop**
*   **Objective**: Enable the system to learn from its mistakes and improve over time.
*   **Implementation**: A **Feedback Loop** where user ratings (Thumbs Up/Down) adjust the "reputation score" of document chunks, demoting poor-quality content in future searches.

### 3. **Adaptive User Personalization**
*   **Objective**: Tailor the learning experience to individual student needs.
*   **Implementation**: Dynamic **System Prompts** that adjust complexity (Beginner/Intermediate/Advanced) based on quiz performance and interaction history.

### 4. **Interactive & Trustworthy UI**
*   **Objective**: Provide transparency in AI reasoning.
*   **Implementation**: **Interactive Citations** that allow students to click on references (`[CHUNK 1]`) and view the exact source text used to generate the answer.


---

##  Key Features

-   **Adaptive Learning**: The implementation of a difficulty-aware AI that adjusts explanations based on user levels (Beginner, Intermediate, Advanced).
-   **Advanced RAG Pipeline**:
    -   **Hybrid Search**: Combines BM25 (keyword) and Dense Vector Retrieval (semantic) for optimal recall.
    -   **Cross-Encoder Reranking**: Uses a second-stage neural model to re-score documents, dramatically reducing hallucinations.
    -   **Recursive Ingestion**: Automatically indexes PDFs, DOCX, PPTX, and TXT files with intelligent chunking.
-   **Interactive Citations**: Chat responses include clickable citations (`[CHUNK 1]`) that reveal the exact source text and metadata in a modal.
-   **Full-Stack Architecture**: Built with a scalable FastAPI backend, MongoDB for persistence, ChromaDB for vector storage, and a responsive Vanilla JS frontend.
-   **Feedback Loop**: Captures user feedback to refine retrieval quality and adapt system prompts over time.

---

## 🛠️ Technology Stack

### **Frontend**
-   **Core**: HTML5, Vanilla JavaScript (ES6+), CSS3 (Custom Variables).
-   **Architecture**: SPA-like navigation with dynamic view loading.
-   **Visuals**: Modern Glassmorphism UI, Responsive Design.

### **Backend**
-   **Framework**: FastAPI (Python 3.10+).
-   **Authentication**: JWT (JSON Web Tokens) with `OAuth2PasswordBearer`.
-   **Database**: MongoDB (User profiles, Chat History, Feedback).
-   **Vector Store**: ChromaDB (REST API mode) for high-performance embedding storage.
-   **LLM Integration**: Google Gemini API (`gemini-1.5-flash`).

### **AI & ML Pipeline**
-   **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (384d).
-   **Reranking**: `cross-encoder/ms-marco-MiniLM-L-6-v2`.
-   **Search**: BM25 + Vector Search with Reciprocal Rank Fusion (RRF).

---

## 📂 Project Structure

```
RAG-AI-Tutor/
├── backend/                # FastAPI Application
│   ├── api/                # Route Controllers (Auth, Chat, Upload)
│   ├── core/               # RAG Logic (Search, Embeddings, LLM)
│   ├── models/             # Pydantic & MongoDB Models
│   └── utils/              # Database & Helper functions
├── frontend/               # User Interface
│   ├── public/             # Static Assets (HTML, CSS, JS)
│   └── src/                # Source files (if build step used)
├── scripts/                # Utility Scripts (Ingestion, Testing)
├── data/                   # Raw Dataset for Ingestion
├── docs/                   # Documentation
└── requirements.txt        # Python Dependencies
```

---

## 📚 Documentation

Detailed documentation for developers and architects:

1.  **[System Architecture](docs/ARCHITECTURE.md)**: Deep dive into the RAG pipeline, Hybrid Search, and System Design.
2.  **[Backend Guide](docs/BACKEND_GUIDE.md)**: API reference, Authentication lifecycle, and Database schemas.
3.  **[Frontend Guide](docs/FRONTEND_GUIDE.md)**: UI Component architecture, State Management, and Interactivity.
4.  **[Deployment & Setup](docs/DEPLOYMENT.md)**: Step-by-step guide to run locally or deploying with Docker.
5.  **[Feedback & Adaptation](docs/FEEDBACK_LOOP.md)**: How the self-correcting learning loop functions.

---

## Run On Another System

Use these steps on a fresh Windows machine to clone the `v1` branch and start the full project with one command.

### 1. Install the prerequisites

Make sure these are installed first:
- Git
- Docker Desktop
- Python 3.11 or newer

### 2. Clone the repository

```powershell
git clone --branch v1 --single-branch https://github.com/Raghav-2205/RAG-AI-Tutor.git
cd RAG-AI-Tutor
```

### 3. Run the one-command setup

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

That single script now does all of this:
- creates `venv` if it does not exist
- upgrades `pip`
- installs `requirements.txt`
- creates `.env` from `.env.example` if needed
- downloads the embedding and reranker models
- creates and starts the Docker containers for MongoDB and Chroma
- waits for MongoDB and Chroma to become reachable
- starts the FastAPI app with `run.py`

When setup finishes, open:

```text
http://127.0.0.1:8002
```

### 4. Update `.env`

Before using Gemini-powered features, edit `.env` and set your real key:

```env
GEMINI_API_KEY=your-real-gemini-api-key
```

The important local defaults are:

```env
MONGODB_URI=mongodb://localhost:27017
CHROMA_API_URL=http://127.0.0.1:8001/api/v2
CHROMA_TENANT=default_tenant
CHROMA_DATABASE=default_database
API_HOST=127.0.0.1
RUN_PORT=8002
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

### 5. Optional setup flags

Skip model warmup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -SkipModelWarmup
```

Prepare everything but do not launch the app:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -SkipAppStart
```

### 6. Verify everything is running

Check the backend health endpoint:

```powershell
Invoke-WebRequest http://127.0.0.1:8002/health -UseBasicParsing
```

Useful Docker checks:

```powershell
docker ps
docker logs rag-mongodb --tail 20
docker logs rag-chroma --tail 20
```

### 7. Stop or restart services later

Stop the app with `Ctrl + C`.

The Docker containers keep running after the app stops. You can manage them with:

```powershell
docker start rag-mongodb rag-chroma
docker stop rag-mongodb rag-chroma
```

If you used `-SkipAppStart`, or you want to start the app manually later:

```powershell
.\venv\Scripts\Activate.ps1
python run.py
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\venv\Scripts\Activate.ps1
```

### Quick Start Summary

```powershell
git clone --branch v1 --single-branch https://github.com/Raghav-2205/RAG-AI-Tutor.git
cd RAG-AI-Tutor
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```
