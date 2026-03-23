# 🧹 Improvement & Refactoring Guide

An honest look at the current codebase with actionable suggestions for moving from "Prototype" to "Production".

---

## ✅ Recent Critical Fixes (Already Implemented)

### ** Explicit Boolean Checks for Database Objects**
**Issue**: The code previously used `if self.db:` to check for database connections. The `pymongo` driver (and some others) throws a `NotImplementedError` when converting database objects to booleans.
**Fix**: All occurrence have been refactored to use `if self.db is not None:`.
**Rule**: **ALWAYS** use explicit `is None` checks for database clients or complex objects in Python.

---

## 🚧 Recommended Refactoring

### 1. **Vector Database Scalability**
*   **Current**: `SimpleVectorDB` uses a JSON file (`simple_vector_store.json`). This loads the entire database into memory.
*   **Risk**: Will crash with OOM (Out of Memory) errors if user uploads large textbooks.
*   **Recommendation**: Migrate to **ChromaDB** (local) or **Pinecone** (cloud). The abstraction layer is already there, so only `backend/vector_db.py` needs to change.

### 2. **Environment Configuration**
*   **Current**: Some settings are hardcoded or mixed in `config.py`.
*   **Recommendation**: Use `pydantic-settings`. It strictly validates `.env` variables on startup, failing fast if keys (like `GEMINI_API_KEY`) are missing.

### 3. **Error Handling in RAG Pipeline**
*   **Current**: If the LLM API fails, the user might see a generic 500 error.
*   **Recommendation**: Implement a **Fallback Strategy**.
    *   If Gemini fails, try a local model (if available) or return the search results directly with a message: *"AI generation unavailable, but here are the relevant text passages."*

### 4. **Frontend Architecture**
*   **Current**: Vanilla JS with separate files. Repeated code for Navbar and Auth checks.
*   **Recommendation**:
    *   Create a `common.js` file for shared logic (Auth checks, API wrappers).
    *   Use a simple component loader to inject the Navbar into every page, so you don't have to edit 6 HTML files to change one menu item.

---

## 🛡️ Security Best Practices

### 1. **Password Hashing**
*   **Status**: Good. Using `bcrypt` via `passlib`.
*   **Action**: Ensure the work factor (rounds) is appropriate for the hardware.

### 2. **Input Sanitization**
*   **Status**: Mixed. Pydantic handles JSON validation.
*   **Action**: Ensure that filenames in `upload.py` are sanitized (`werkzeug.utils.secure_filename`) to prevent path traversal attacks.

### 3. **CORS Restrictions**
*   **Status**: Open (`allow_origins=["*"]`).
*   **Action**: In production, strictly limit `allow_origins` to the actual frontend domain (e.g., `https://my-tutor-app.com`).
