# backend/main.py
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Config & DB
from backend.config import settings
from backend.utils.db import init_db, db_manager
# Routers
from backend.api import auth, chat, upload, quiz, feedback, ingest

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting RAG AI Tutor application...")
    await init_db()
    os.makedirs(settings.upload_dir, exist_ok=True)
    logger.info("Application startup complete")
    yield
    # Shutdown
    logger.info("Shutting down application...")
    await db_manager.disconnect()
    logger.info("Application shutdown complete")

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan
)

# CORS Config
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth.router, prefix=f"{settings.api_prefix}/auth", tags=["Authentication"])
app.include_router(chat.router, prefix=f"{settings.api_prefix}/chat", tags=["Chat"])
app.include_router(upload.router, prefix=f"{settings.api_prefix}/upload", tags=["Upload"])
app.include_router(quiz.router, prefix=f"{settings.api_prefix}/quiz", tags=["Quiz"])
app.include_router(feedback.router, prefix=f"{settings.api_prefix}/feedback", tags=["Feedback"])
app.include_router(ingest.router, prefix=f"{settings.api_prefix}/ingest", tags=["Ingest"])

@app.get("/health")
async def health_check():
    from datetime import datetime
    try:
        # Ping DB
        db = await db_manager.get_database()
        await db.command("ping")
        return {
            "status": "healthy",
            "version": settings.version,
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")

# Serve Frontend (Must be last)
if os.path.exists("frontend/public"):
    app.mount("/", StaticFiles(directory="frontend/public", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )