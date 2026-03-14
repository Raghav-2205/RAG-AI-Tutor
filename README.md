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