from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import os

# Import configuration and database
from backend.config import settings
from backend.utils.db import init_db, db_manager, get_database

# Import API routers
from backend.api import auth, chat, upload, quiz, feedback, ingest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("🚀 Starting RAG AI Tutor application...")
    
    # Initialize database
    await init_db()
    
    # Create upload directory
    os.makedirs(settings.upload_dir, exist_ok=True)
    
    logger.info("✅ Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down application...")
    await db_manager.disconnect()
    logger.info("✅ Application shutdown complete")

# Create FastAPI app with lifespan
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router, prefix=f"{settings.api_prefix}/auth", tags=["Authentication"])
app.include_router(chat.router, prefix=f"{settings.api_prefix}/chat", tags=["Chat"])
app.include_router(upload.router, prefix=f"{settings.api_prefix}/upload", tags=["Upload"])
app.include_router(quiz.router, prefix=f"{settings.api_prefix}/quiz", tags=["Quiz"])
app.include_router(feedback.router, prefix=f"{settings.api_prefix}/feedback", tags=["Feedback"])
app.include_router(ingest.router, prefix=f"{settings.api_prefix}/ingest", tags=["Ingest"])

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db = await get_database()
        await db.command("ping")
        
        from datetime import datetime
        
        return {
            "status": "healthy",
            "version": settings.version,
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")

@app.get(f"{settings.api_prefix}/")
async def api_root():
    """API root endpoint"""
    return {
        "message": f"Welcome to {settings.app_name} API",
        "version": settings.version,
        "docs": f"{settings.api_prefix}/docs"
    }

# Serve static files (frontend) - MUST be last to avoid catching API routes
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
