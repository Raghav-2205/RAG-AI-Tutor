# 🏗️ System Architecture

This document outlines the architectural design of the **RAG AI Tutor**. It explains how data flows through the system, from user interaction to AI response generation, highlighting the advanced RAG pipeline.

---

## 🌐 High-Level Overview

The system follows a modern **Client-Server Architecture**:

1.  **Frontend (Vanilla JS)**: A Single Page Application (SPA) that handles user interactions, manages state, and communicates with the backend via REST API.
2.  **Backend (FastAPI)**: The core logic engine that manages authentication, data processing, and orchestrates the RAG pipeline.
3.  **Vector Store (ChromaDB)**: A dedicated database for storing and retrieving high-dimensional vector embeddings of course materials.
4.  **NoSQL Database (MongoDB)**: Stores relational-like data such as User Profiles, Chat History, and Feedback logs.
5.  **LLM Service (Gemini API)**: The generative engine that synthesizes answers based on retrieved context.

---

## ⚙️ Backend Structure (`backend/`)

The backend is organized for scalability and separation of concerns:

-   **`main.py`**: The application entry point. Configures the FastAPI app, CORS middleware, database connections, and registers API routers.
-   **`api/`**: Contains route handlers (Controllers).
    -   `auth.py`: User registration and JWT login.
    -   `chat.py`: Endpoints for sending messages and retrieving chat history.
    -   `rag.py`: Endpoint for fetching chunk details for citations.
    -   `upload.py`: Handles file uploads and triggers ingestion.
    -   `feedback.py`: Processes user feedback for adaptive learning.
-   **`core/`**: Core business logic and RAG implementation.
    -   `search_engine.py`: Implements **Hybrid Search** (BM25 + Vector) and **Cross-Encoder Reranking**.
    -   `embedding_service.py`: Generates embeddings using `sentence-transformers`.
    -   `llm_interface.py`: Wrapper for the Gemini API.
-   **`models/`**: Pydantic models for API validation and MongoDB schemas.
-   **`utils/`**: Helper functions (e.g., database connection managers).

---

## 🧠 Advanced RAG Pipeline Flow

The Retrieval-Augmented Generation (RAG) pipeline is the heart of the system. Here is the step-by-step flow:

### 1. Data Ingestion
*   **Trigger**: A recursive script (`scripts/ingest_data_folder.py`) or user upload (`api/upload.py`) initiates the process.
*   **Extraction**: Text is extracted from PDF, DOCX, PPTX, or TXT files.
*   **Chunking**: Documents are split into **600-800 character** chunks with **150-character overlap** to preserve context across boundaries.
*   **Embedding**: Each chunk is converted into a 384-dimensional vector using `all-MiniLM-L6-v2`.
*   **Storage**: Vectors are stored in ChromaDB, while metadata (filename, page number) is indexed for retrieval.

### 2. Retrieval (Hybrid Search)
When a user asks a question:
*   **Query Analysis**: The system analyzes the student's proficiency level to adjust the search strategy.
*   **Parallel Search**:
    1.  **BM25 (Keyword Search)**: Finds documents containing exact keywords from the query.
    2.  **Vector Search (Semantic Search)**: Finds conceptually similar documents using cosine similarity.
*   **Fusion**: Results from both methods are combined using **Reciprocal Rank Fusion (RRF)** to balance keyword matching with semantic understanding.

### 3. Reranking (Cross-Encoder)
*   **Candidate Selection**: The top ~20 results from the fusion step are selected.
*   **Scoring**: A **Cross-Encoder** (`ms-marco-MiniLM-L-6-v2`) examines the full query-document pair and assigns a relevance score.
*   **Filtering**: Only the highest-scoring chunks (e.g., Top 5) are passed to the next stage, effectively filtering out irrelevant "distractors."

### 4. Generation & Response
*   **Prompt Construction**: A context-rich prompt is built, including:
    -   The retrieved chunks (labeled as `[CHUNK 1]`, `[CHUNK 2]`, etc.).
    -   The student's chat history (for conversational continuity).
    -   An adaptive system prompt based on the student's level.
*   **Synthesis**: The Gemini LLM generates a response, explicitly citing the provided chunks.
*   **Interactive Citation**: The backend returns the answer along with metadata for the cited chunks, allowing the frontend to render actionable citation links.

---

## 🔄 Adaptive Feedback Loop
The system learns from user interaction:
1.  **Feedback Collection**: Users can rate answers (Thumbs Up/Down).
2.  **Score Adjustment**: Negative feedback lowers the "reputation score" of the cited chunks for that specific query.
3.  **Future Retrieval**: In future queries, low-scoring chunks are penalized in the ranking algorithm, improving long-term accuracy.
