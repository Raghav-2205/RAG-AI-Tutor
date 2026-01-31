# Run backend and chat with RAG AI Tutor

## Fix: use port **8000** (not 80001)

Port **80001** is wrong. Use **8000**.

---

## Quick run (PowerShell)

```powershell
cd "C:\Users\RAGHAVENDRA SWAMY\Documents\GitHub\RAG-AI-Tutor"
.\run_backend.ps1
```

Then open **http://localhost:8000/chatbot.html** in your browser to use the chat interface.

---

## Steps (manual)

### 1. Open terminal in project folder

```powershell
cd "C:\Users\RAGHAVENDRA SWAMY\Documents\GitHub\RAG-AI-Tutor"
```

### 2. Install dependencies (once)

```powershell
pip install -r requirements.txt
```

If you get permission errors, use a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. (Optional) Set Gemini API key for real AI replies

Create `.env` from the example and add your key:

```powershell
copy .env.example .env
# Edit .env and set: GEMINI_API_KEY=your_key_here
```

Without `GEMINI_API_KEY`, the chat still works and returns a friendly placeholder message.

### 4. Start the backend on port **8000**

```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

(Use `python -m uvicorn` if `uvicorn` is not on PATH. Omit `--reload` if you see Windows permission errors with the reloader.)

Expected output:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process ...
INFO:     Application startup complete.
```

### 5. Open the chat interface in your browser

- **Chat UI:** http://localhost:8000/chatbot.html  
- **Home:** http://localhost:8000  
- **API docs:** http://localhost:8000/docs  

Type a message in the chat box and click Send (or press Enter). You’ll get a reply from the RAG AI Tutor (Gemini if `GEMINI_API_KEY` is set, otherwise a short placeholder).

---

## What was fixed and added

| Item | Change |
|------|--------|
| **Port** | Use **8000** (you had 80001). |
| **Chat API** | `POST /api/chat` with `{ "message": "..." }` → `{ "reply": "...", "session_id": "..." }`. |
| **LLM** | `backend/core/llm_interface.py` — Gemini if `GEMINI_API_KEY` set, else placeholder. |
| **Chat UI** | `frontend/public/chatbot.html` + `frontend/src/js/chat_utils.js` — messages area, input, send. |
| **Routes** | `main.py` serves `/chatbot.html` and includes chat router at `/api/chat`. |

You can now run the backend on port **8000** and chat with the RAG AI Tutor in the browser at http://localhost:8000/chatbot.html .
