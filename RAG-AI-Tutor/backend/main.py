import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import sys
from pathlib import Path

# Add project root to sys.path to allow absolute imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Config & DB
from backend.config import settings
from backend.utils.db import init_db, db_manager
# Routers
from backend.api import auth, chat, upload, quiz, feedback, ingest, rag, dashboard


# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting RAG AI Tutor...")
    await init_db()
    os.makedirs(settings.upload_dir, exist_ok=True)
    yield
    # Shutdown
    logger.info("🛑 Shutting down...")
    await db_manager.disconnect()

app = FastAPI(title="RAG AI Tutor", lifespan=lifespan)

# --- CRITICAL FIX: ALLOW ALL ORIGINS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows localhost:3000, 127.0.0.1, etc.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
app.include_router(quiz.router, prefix="/api/quiz", tags=["Quiz"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["Ingest"])
app.include_router(rag.router, prefix="/api", tags=["RAG"])

from backend.api import evaluation
app.include_router(evaluation.router, prefix="/api/evaluation", tags=["Evaluation"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])


@app.get("/health")
async def health_check():
    return {"status": "active", "database": "connected"}

# Serve Frontend (LAST)
# Serve Frontend (LAST)
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "public")
if os.path.exists(frontend_path):
    logger.info(f"📂 Mounting Frontend from: {frontend_path}")
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")
else:
    logger.warning(f"⚠️ Frontend directory not found at: {frontend_path}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)