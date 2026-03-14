# ⚙️ Backend Developer Guide

The **RAG AI Tutor** backend is a robust REST API built with **FastAPI**. It handles authentication, data processing, and orchestrates the advanced RAG pipeline.

---

## 🏗️ Architecture

The backend follows a **Controller-Service-Repository** pattern (though simplified for FastAPI):

-   **Controllers (`api/`)**: Handle HTTP requests, validate input, and call services.
-   **Services (`core/`)**: Implement business logic (RAG, LLM calls, Embeddings).
-   **Repositories (`db/`)**: Manage database interactions (MongoDB, ChromaDB).
-   **Models (`models/`)**: Define data schemas using Pydantic.

---

## 🔒 Authentication (JWT)

We use **OAuth2 with Password Flow** and **JSON Web Tokens (JWT)**.

### **Lifecycle**
1.  **Login**: User updates POST `/api/auth/login` with `username` (email) and `password`.
2.  **Validation**: Backend hashes password and verifies against MongoDB.
3.  **Token Issue**: If valid, returns an `access_token` (JWT) valid for 30 minutes.
4.  **Protected Routes**: The frontend sends `Authorization: Bearer <token>` for all subsequent requests.
5.  **Dependency**: The `get_current_user` dependency in `api/auth.py` decodes the token and fetches the user from MongoDB.

---

## 🚀 API Reference

### **Authentication** (`/api/auth`)
-   `POST /register`: Create a new user account.
-   `POST /login`: Authenticate and receive JWT.
-   `GET /me`: Get current user profile.

### **Chat & RAG** (`/api/chat`, `/api/rag`)
-   `POST /chat/`: Send a message. Triggers RAG pipeline -> LLM Response.
-   `GET /chat/sessions`: List user's chat history.
-   `GET /chat/sessions/{id}`: Get messages for a specific session.
-   `GET /chunks/{chunk_id}`: **[RAG]** Fetch full text and metadata for a specific citation chunk.

### **Data Management** (`/api/upload`, `/api/ingest`)
-   `POST /upload/`: Upload a file (PDF, DOCX, TXT) to be ingested.
-   `POST /ingest/`: Trigger recursive ingestion of the `data/` folder.
-   `DELETE /upload/all`: Clear user's uploaded documents.

---

## 🗄️ Database Access

### **MongoDB (Main DB)**
-   **Driver**: `motor` (Async Python driver).
-   **Collections**:
    -   `users`: User profiles and hashed passwords.
    -   `chat_sessions`: Metadata for chat history.
    -   `messages`: Individual chat messages.
    -   `feedback`: User ratings on AI responses.

### **ChromaDB (Vector Store)**
-   **Access**: REST API (via `requests` in `backend/vector_db.py`).
-   **Collections**:
    -   `global`: System-wide course materials.
    -   `user_{id}`: User-specific uploaded documents.
-   **Schema**:
    -   `ids`: Unique UUID per chunk.
    -   `embeddings`: 384d vector from `all-MiniLM-L6-v2`.
    -   `metadatas`: `{"filename": "...", "page_number": 0, "source": "..."}`.
    -   `documents`: The raw text content.

---

## 🔄 Request Lifecycle (Chat)

1.  **User Request**: Frontend sends JSON payload (`message`, `subject`) to `/api/chat/`.
2.  **Auth Check**: `get_current_user` verifies the JWT.
3.  **Retrieval**: `HybridSearchEngine` queries ChromaDB for relevant chunks.
4.  **Reranking**: `CrossEncoder` scores the top chunks and selects the best 5.
5.  **Prompting**: Backend constructs a prompt with the user's query and the retrieved chunks.
6.  **Generation**: `llm_client` calls Gemini API using the constructed prompt.
7.  **Response**: The answer and citation metadata are sent back to the frontend.
8.  **Logging**: The interaction is saved to MongoDB `messages` collection.
