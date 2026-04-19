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
from backend.services.knowledge_base_service import auto_index_on_startup
from backend.utils.db import init_db, db_manager
# Routers
from backend.api import auth, chat, upload, quiz, feedback, ingest, rag, dashboard
from backend.api import lms, planner, communication, suggestions, grag, notifications, analytics, calendar
from backend.api import gamification
from backend.api import announcements, events


# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_cors_config() -> tuple[list[str], bool]:
    allowed_origins = settings.cors_origins or ["*"]
    allow_all_origins = allowed_origins == ["*"]
    return allowed_origins, allow_all_origins

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting RAG AI Tutor...")
    await init_db()
    os.makedirs(settings.upload_dir, exist_ok=True)
    await create_indexes()
    # Auto-index the base_dataset into the global knowledge base
    # so every new chat session can query it immediately.
    await auto_index_on_startup()
    yield
    # Shutdown
    logger.info("🛑 Shutting down...")
    await db_manager.disconnect()

async def create_indexes():
    """Create MongoDB indexes for performance."""
    try:
        db = db_manager.db
        await db.classes.create_index("teacher_id")
        await db.classes.create_index("join_code", unique=True, sparse=True)
        await db.classes.create_index("students")
        await db.assignments.create_index("class_id")
        await db.assignments.create_index("due_date")
        await db.submissions.create_index([("assignment_id", 1), ("student_id", 1)])
        await db.lms_quizzes.create_index("class_id")
        await db.quiz_questions.create_index("quiz_id")
        await db.quiz_attempts.create_index([("quiz_id", 1), ("student_id", 1)])
        await db.attendance_records.create_index([("class_id", 1), ("date", 1)])
        await db.attendance_records.create_index("student_id")
        await db.activity_logs.create_index([("user_id", 1), ("date", -1)])
        await db.planner_days.create_index([("user_id", 1), ("date", 1)])
        await db.announcements.create_index([("created_at", -1)])
        await db.announcements.create_index("author_id")
        await db.events.create_index([("date", 1)])
        await db.events.create_index("author_id")
        logger.info("✅ MongoDB indexes created successfully.")
    except Exception as e:
        logger.warning(f"⚠️ Index creation warning (non-fatal): {e}")

app = FastAPI(title="RAG AI Tutor", lifespan=lifespan)

cors_origins, allow_all_origins = _resolve_cors_config()
logger.info("CORS origins configured: %s", cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=not allow_all_origins,
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

# New Modules
app.include_router(lms.router, prefix="/api/lms", tags=["LMS"])
app.include_router(planner.router, prefix="/api/planner", tags=["Planner"])
app.include_router(communication.router, prefix="/api/comm", tags=["Communication"])
app.include_router(suggestions.router, prefix="/api/suggestions", tags=["Suggestions"])
app.include_router(grag.router, prefix="/api/grag", tags=["GRAG"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(calendar.router, prefix="/api", tags=["Calendar"])
app.include_router(gamification.router, prefix="/api/gamification", tags=["Gamification"])
app.include_router(announcements.router, prefix="/api/announcements", tags=["Announcements"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])

from backend.api import academic
app.include_router(academic.router, prefix="/api/academic", tags=["Academic LMS"])


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
