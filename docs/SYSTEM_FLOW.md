# 🔄 System Flow Documentation

This document visualizes how data moves through the RAG AI Tutor system during key operations.

---

## Flow 1: Authentication 🔐

**Goal**: Securely log the user in and provide a token for future requests.

1.  **User Action**: Enters credentials on `login.html`.
2.  **Frontend**: Sends `POST /api/auth/login` (email, password).
3.  **Backend (Auth Router)**:
    *   Finds user by email in MongoDB `users` collection.
    *   Verifies password hash using `bcrypt`.
    *   Generates a **JWT** (signed with `JWT_SECRET`).
    *   Returns token to Frontend.
4.  **Frontend**: Stores token in `localStorage`.
5.  **Subsequent Request**: Frontend adds header `Authorization: Bearer <token>`.
6.  **Backend Middleware**: Decodes token, finds user ID, and attaches `current_user` to the request.

---

## Flow 2: Document Upload & Ingestion 📄 -> 🧠

**Goal**: Convert a raw file into searchable vectors.

1.  **User Action**: Uploads `lecture.pdf` on `upload.html`.
2.  **Backend (Upload Router)**: Receives file stream.
3.  **File Handler**: Saves file to disk (`data/uploads/`).
4.  **Extraction**: Opens PDF, extracts text content.
5.  **Preprocessing**:
    *   Splits text into **Chunks** (e.g., 500 characters, 50 overlap).
    *   *Result*: 1 Document -> 50 Chunks.
6.  **Embedding Service**:
    *   Input: Chunk Text.
    *   Process: Runs `sentence-transformers` model.
    *   Output: 384-dimensional List[float] (Vector).
7.  **Storage**:
    *   **MongoDB**: Stores metadata (filename, upload date).
    *   **Vector DB**: Stores `{ "id": chunk_id, "vector": [...] }`.

---

## Flow 3: RAG Chat 💬

**Goal**: Answer a question using the uploaded documents.

1.  **User Action**: Types "What is the mitochondria?"
2.  **Backend (Chat Router)**:
    *   Receives message.
    *   **Embeds** the query using the same embedding model.
3.  **Search Engine**:
    *   **Vector Search**: Finds vectors closest to the query vector (Cosine Similarity).
    *   **Keyword Search (BM25)**: Finds chunks containing specific words (e.g., "mitochondria").
    *   **Fusion**: Ranks the top results.
4.  **Context Construction**:
    *   Takes top 5 chunks.
    *   Formats them into a string: `[Source: lecture.pdf] ...text...`
5.  **LLM Generation**:
    *   sends Prompt: *"User asked: X. Context: Y. Answer X using Y."* to Gemini/LLM.
6.  **Response**:
    *   Saves interaction to MongoDB `chat_history`.
    *   Returns answer + citations to Frontend.

---

## Flow 4: Adaptive Quiz 📝

**Goal**: Test user knowledge and adapt.

1.  **User Action**: Requests a quiz on "Biology".
2.  **Backend (Quiz Generator)**:
    *   Queries Vector DB for random chunks tagged with "Biology".
    *   Asks LLM: *"Generate an MCQ based on this text."*
    *   Parses generated JSON.
    *   Stores pending quiz in MongoDB.
3.  **User Action**: Submits answers.
4.  **Backend (Quiz Submission)**:
    *   Compares user answers vs. correct keys.
    *   Calculates Score %.
    *   **Profile Update**:
        *   If score < 50%, adds topic to `weak_topics`.
        *   If score > 80%, may upgrade user level to "Intermediate".

---

## Flow 5: Feedback Loop 🗣️

**Goal**: Improve system based on user satisfaction.

1.  **User Action**: Clicks "Thumbs Down" on a chat answer.
2.  **Backend (Feedback Router)**:
    *   Stores rating and optional comment in MongoDB `feedback` collection.
3.  **Analysis (Async/Scheduled)**:
    *   `FeedbackAnalyzer` checks for patterns.
    *   *Scenario*: If users constantly downvote answers about "History", the system might flag that the retrieval strategy needs adjustment or that more "History" documents are needed.
