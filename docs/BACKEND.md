# 🔧 Backend Documentation

The backend is a **FastAPI** application structured to be modular and scalable. It handles data processing, AI orchestration, and database management.

## 📂 Project Structure

```
backend/
├── main.py              # Application entry point
├── api/                 # API Route handlers
├── core/                # Core business logic (RAG, Quiz, Profiles)
├── models/              # Pydantic data models
└── utils/               # Database and helper functions
```

---

## 1. Application Entry Point (`main.py`)
### **Responsibility**
*   Initializes the FastAPI app.
*   Configures **CORS** (Cross-Origin Resource Sharing) to allow the frontend to communicate with the backend.
*   **Lifespan Events**: Handles startup (Database connection) and shutdown (Database disconnection) logic.
*   **Router Inclusion**: Mounts all routers from the `api/` folder.

---

## 2. API Modules (`api/`)

### `api/auth.py`
*   **Purpose**: User Authentication.
*   **Key Endpoints**:
    *   `POST /register`: Creates new users. Uses `passlib` to hash passwords.
    *   `POST /login`: Validates credentials and returns a **JWT Access Token**.
    *   `GET /me`: Returns current user details (Protected route).

### `api/chat.py`
*   **Purpose**: Chat interface logic.
*   **Key Endpoints**:
    *   `POST /`: Accepts a message, calls the RAG pipeline, and returns the answer.
    *   `GET /sessions`: Returns list of past conversations.
*   **Logic**: Manages chat history context. It retrieves previous messages for a session so the LLM knows what was discussed earlier.

### `api/upload.py`
*   **Purpose**: File ingestion.
*   **Key Endpoints**:
    *   `POST /`: Accepts files (`UploadFile`).
*   **Logic**:
    1.  Validates file type.
    2.  Saves to `data/uploads/`.
    3.  Calls `extract_text_from_file` (in `file_handler.py`).
    4.  Calls `create_chunks` to split text.
    5.  Calls `vector_db.add` to embed and index.

### `api/quiz.py`
*   **Purpose**: Quiz generation and grading.
*   **Key Endpoints**:
    *   `POST /generate`: Trigger creation of questions.
    *   `POST /submit`: Grades answers.
*   **Logic**: Updates the user's `StudentProfile` based on their score (e.g., leveling up from Beginner to Intermediate).

---

## 3. Core Logic (`core/`)

### `core/rag_tutor.py` & `core/search_engine.py` (The RAG Pipeline)
This is the heart of the application.

1.  **Retrieval (`search_engine.py`)**:
    *   Implements **Hybrid Search**: Combines **BM25** (Keyword match) and **Vector Search** (Semantic match).
    *   **RRF (Reciprocal Rank Fusion)**: Merges the results from BM25 and Vector search to get the "best of both worlds."    
2.  **Generation (`rag_tutor.py`)**:
    *   Takes the retrieved chunks.
    *   Constructs a system prompt: *"You are a helpful tutor. Answer using ONLY the following context..."*
    *   Calls the LLM (via `llm_interface.py`).

### `core/quiz_generator.py`
*   Retrieves random but relevant chunks from the vector store.
*   Prompts the LLM to generate specific question types (Multiple Choice) based on those chunks.
*   Parses the LLM's text output into structured JSON.

### `core/student_profile.py`
*   Manages user metadata.
*   Tracks "Weak Topics" based on failed quiz questions.

### `core/feedback_analyzer.py`
*   Analyzes user feedback (Thumbs Up/Down).
*   Can trigger "Prompt Adjustment" if a user consistently rates answers poorly.

---

## 4. Models (`models/`)
Contains **Pydantic** models that define the shape of valid data.
*   `user.py`: Defines `UserCreate`, `UserLogin`, `UserPublic`.
*   Using Pydantic ensures that if the frontend sends bad data, the API rejects it automatically with a clear error.

---

## 5. Utilities (`utils/`)

### `utils/db.py`
*   **Database Manager**: Wraps `motor` (Async MongoDB driver).
*   Provides `get_db` dependency for FastAPI routes.

### `vector_db.py` (Root or Utils)
*   **SimpleVectorDB**: A custom, lightweight implementation of a Vector Store using JSON files and `numpy` for cosine similarity.
*   *Note*: In a production environment, this would be replaced by Pinecone, Qdrant, or ChromaDB.
