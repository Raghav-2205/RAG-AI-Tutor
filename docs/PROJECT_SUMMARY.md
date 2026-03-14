# RAG AI Tutor — Full Project Understanding

## What It Is
An **AI-powered educational tutor** that answers student questions using your own uploaded documents (RAG), with real-time streaming, quiz generation, and quality evaluation.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| LLM | Google Gemini REST API (`gemini-2.5-flash`) |
| Vector DB | ChromaDB (Docker, port 8001) |
| Document DB | MongoDB (Docker, port 27017) |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Frontend | Vanilla HTML + CSS + JavaScript (SPA) |

---

## How to Run

```powershell
# 1. Start Docker containers first
docker start mongo chromadb

# 2. Start the combined server (frontend + backend)
cd "c:\Users\AAIUSER\Downloads\RAG-AI-Tutor (2)\RAG-AI-Tutor"
venv\Scripts\python.exe run.py
```

**URLs:**
- App → http://127.0.0.1:8002
- API Docs → http://127.0.0.1:8002/docs

---

## Project Structure

```
RAG-AI-Tutor/
├── run.py                    ← Entry point (starts Uvicorn on port 8002)
├── .env                      ← All config (API keys, DB URLs, tokens)
├── backend/
│   ├── main.py               ← FastAPI app, router registration, static files
│   ├── config.py             ← Pydantic settings (reads .env)
│   ├── auth.py               ← JWT token creation + bcrypt password hashing
│   ├── rag_tutor.py          ← 3-tier RAG pipeline (core brain)
│   ├── file_handler.py       ← PDF/DOCX/PPTX/image/audio text extraction
│   ├── ingest.py             ← Document chunking + vector DB indexing
│   ├── vector_db.py          ← ChromaDB REST client wrapper
│   ├── preprocessing.py      ← Text cleaning before chunking
│   ├── quiz_generator.py     ← (legacy) top-level quiz entry
│   ├── feedback.py           ← (legacy) top-level feedback entry
│   ├── user.py               ← User model helpers
│   ├── api/
│   │   ├── auth.py           ← POST /api/auth/{register,login,me}
│   │   ├── chat.py           ← POST /api/chat/, POST /api/chat/stream
│   │   │                        GET/DELETE /api/chat/sessions/{id}
│   │   ├── upload.py         ← POST /api/upload/ (file ingestion trigger)
│   │   ├── quiz.py           ← POST /api/quiz/generate, submit, history, stats
│   │   ├── feedback.py       ← POST/GET /api/feedback/, stats, analytics
│   │   ├── evaluation.py     ← GET /api/evaluation/metrics, logs, report
│   │   ├── rag.py            ← GET /api/chunks/{chunk_id}
│   │   └── ingest.py         ← GET /api/ingest/ (health)
│   ├── core/
│   │   ├── llm_interface.py  ← Gemini REST client (sync/async/stream)
│   │   ├── search_engine.py  ← HybridSearchEngine (BM25 + vector + RRF + reranker)
│   │   ├── embedding_service.py ← Sentence-transformer embeddings
│   │   ├── feedback_analyzer.py ← Adaptive prompt injection from feedback
│   │   ├── quiz_generator.py ← MCQ generation from chunks
│   │   ├── ocr_service.py    ← Tesseract OCR wrapper
│   │   ├── student_profile.py ← Student learning profile tracking
│   │   └── evaluation/
│   │       ├── validator.py      ← Full validation pipeline
│   │       ├── metrics.py        ← Faithfulness, BERTScore, cosine, citations
│   │       ├── run_evaluation.py ← Benchmark runner
│   │       └── report_generator.py ← Evaluation reports
│   ├── models/
│   │   ├── user.py           ← UserCreate, UserPublic Pydantic models
│   │   ├── chat_history.py   ← ChatSession models
│   │   └── evaluation.py     ← ValidationResult Pydantic model
│   └── utils/
│       ├── db.py             ← MongoDB connection manager
│       └── helpers.py        ← doc_to_dict, etc.
└── frontend/
    └── public/
        ├── index.html        ← Redirects to home.html
        ├── views/
        │   ├── home.html     ← Landing/redirect page
        │   ├── login.html    ← Login form
        │   ├── signup.html   ← Registration form
        │   ├── subjects.html ← MAIN CHAT UI (largest file, ~1200 lines)
        │   ├── quiz.html     ← Quiz interface
        │   ├── evaluation.html ← Evaluation dashboard
        │   └── evaldoc.html  ← Single validation result detail viewer
        └── assets/
            ├── js/
            │   ├── ai.js     ← AIManager class (sendMessage + sendMessageStream)
            │   ├── auth.js   ← AuthManager class (login, register, logout)
            │   └── config.js ← API base URL configuration
            └── css/          ← Stylesheets
```

---

## Core Flow: How a Chat Message Works

```
User types question → subjects.html sendMessage()
    │
    ▼
POST /api/chat/stream  (SSE streaming endpoint)
    │
    ├── [1] Get/create chat session in MongoDB
    ├── [2] Build chat history from session
    ├── [3] FeedbackAnalyzer: should_adjust_prompt(user_id)?
    │       → adaptive system prompt if struggling
    ├── [4] retrieve_chunks_for_streaming()
    │       → search_engine.search() (HybridSearch)
    │           ├── BM25 keyword search on all chunks
    │           ├── Vector semantic search (ChromaDB)
    │           ├── RRF Fusion
    │           └── CrossEncoder reranking
    │       → Build RAG prompt from chunks
    │
    │   SSE: {"type":"meta", "chat_id":..., "citations":..., "chunks":...}
    │
    ├── [5] llm_client.async_stream_generate(prompt)
    │       → Gemini streamGenerateContent?alt=sse
    │   SSE: {"type":"token", "text":"..."} × N
    │
    ├── [6] ValidationEngine.validate_answer()
    │       → faithfulness (LLM-as-Judge)
    │       → BERTScore, cosine similarity, citation alignment, answer relevance
    │       → Decision: VERIFIED / WARNING / REJECTED
    │       → Save to MongoDB rag_answer_validations
    │   SSE: {"type":"validation", "data":{...}}
    │
    │   SSE: {"type":"done"}
    │
    └── [7] Save full conversation to MongoDB chat_sessions
```

---

## RAG 3-Tier Routing (rag_tutor.py)

| Tier | When | Source |
|---|---|---|
| 1 — Document | `document_id` provided | User's specific uploaded file |
| 2 — Knowledge Base | No doc, but chunks exist | Global KB (7867 docs) + user docs |
| 3 — Gemini Fallback | No chunks found | Pure Gemini (no RAG) |

---

## Evaluation Metrics (validator.py + metrics.py)

| Metric | How |
|---|---|
| **Faithfulness** | LLM-as-Judge: fraction of answer sentences supported by context |
| **BERTScore** | Semantic token overlap between answer and context |
| **Cosine Similarity** | Embedding-level similarity |
| **Citation Alignment** | References to `[CHUNK N]` matched to actual chunks |
| **Answer Relevance** | LLM: does the answer address the question? |
| **Final RAG Score** | Weighted composite of all above |
| **Status** | VERIFIED (faith≥0.85), WARNING, REJECTED, INSUFFICIENT_CONTEXT |

---

## Document Upload Flow

```
User uploads file → POST /api/upload/
    → file_handler.extract_text_from_file()
        PDF → pypdf pages
        DOCX → python-docx paragraphs
        PPTX → pptx slides
        Image → Gemini Vision REST → Tesseract fallback
        Audio → google-generativeai upload (genai SDK)
    → ingest.py chunk_text() (600 chars, 100 overlap)
    → vector_db.add_chunks_to_collection()
        → embedding_service.embed_text() [all-MiniLM-L6-v2]
        → ChromaDB REST POST /collections/{id}/add
    → MongoDB: save document metadata
```

---

## Quiz Flow

```
GET /api/quiz/generate
    → get_all_chunks("global", "general") [7867 docs]
    → _select_diverse_chunks() [round-robin by source]
    → _build_quiz_generation_prompt()
    → llm_client.generate() [sync Gemini]
    → _parse_quiz_response() [regex Q1:, A), ANSWER:]
    → return {quiz_id, questions[{question, options[4], correct_index}]}

POST /api/quiz/submit
    → score answers, compute percentage
    → identify weak topics
    → generate feedback string
```

---

## Adaptive Learning (feedback_analyzer.py)

When [should_adjust_prompt()](file:///c:/Users/AAIUSER/Downloads/RAG-AI-Tutor%20%282%29/RAG-AI-Tutor/backend/core/feedback_analyzer.py#83-109) detects the user is struggling (>40% negative feedback in last 24h), it injects extra instructions into the system prompt:
- Be more detailed and thorough
- Break concepts into smaller steps
- Provide concrete examples
- Use simpler language

This is applied to EVERY subsequent request until feedback improves.

---

## MongoDB Collections

| Collection | Purpose |
|---|---|
| [users](file:///c:/Users/AAIUSER/Downloads/RAG-AI-Tutor%20%282%29/RAG-AI-Tutor/backend/api/auth.py#94-102) | User accounts (bcrypt passwords, level) |
| `chat_sessions` | Full chat history with messages, citations, chunks |
| [feedback](file:///c:/Users/AAIUSER/Downloads/RAG-AI-Tutor%20%282%29/RAG-AI-Tutor/backend/core/feedback_analyzer.py#255-258) | 👍/👎 ratings with subject and comment |
| `rag_answer_validations` | Evaluation results per answer |
| `response_chunks` | Which chunks were used per response |
| `feedback_influence_log` | When feedback triggered prompt adjustment |
| `quiz_results` | Quiz scores and weak topics |

---

## API Endpoints Summary

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Get JWT token (12hr) |
| GET | `/api/auth/me` | Current user info |
| POST | `/api/chat/` | Chat (sync, returns full response) |
| POST | `/api/chat/stream` | Chat (**SSE streaming** — primary) |
| GET | `/api/chat/sessions` | List user's chat sessions |
| GET | `/api/chat/sessions/{id}` | Get full chat history |
| DELETE | `/api/chat/sessions/{id}` | Delete session |
| POST | `/api/upload/` | Upload + index a document |
| GET | `/api/upload/` | List user's documents |
| POST | `/api/quiz/generate` | Generate MCQ quiz |
| POST | `/api/quiz/submit` | Submit quiz answers |
| POST | `/api/feedback/` | Submit 👍/👎 rating |
| GET | `/api/evaluation/metrics` | Aggregated RAG metrics |
| GET | `/api/evaluation/logs` | Per-answer validation logs |
| GET | `/api/chunks/{chunk_id}` | Chunk detail for citation preview |
| GET | `/health` | Server health check |

---

## Key Config (.env)

```ini
GEMINI_API_KEY=...
MONGODB_URI=mongodb://localhost:27017/
CHROMA_API_URL=http://localhost:8001/api/v2   ← must include /api/v2
ACCESS_TOKEN_EXPIRE_MINUTES=720                ← 12 hours
LLM_MODEL=gemini-1.5-flash
CHUNK_SIZE=600
TOP_K_RETRIEVAL=6
```

---

## Known ChromaDB Collections (with data)

| Collection | Doc Count | Used For |
|---|---|---|
| `user_global_general` | 7,867 | System-wide knowledge base |
| `user_system_dataset_v1_general` | 2,847 | Benchmark/eval dataset |
| `user_69871e5bbafa9262c5fc6216_general` | 265 | One user's private docs |
