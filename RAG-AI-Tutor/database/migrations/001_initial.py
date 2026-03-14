# backend/database/migrations/001_initial.py
"""
Initial MongoDB schema + indexes for optimal performance
"""

from motor.motor_asyncio import AsyncIOMotorClient
from backend.config import settings
import asyncio

async def run_migration():
    """Create optimal indexes for RAG Tutor"""
    
    client = AsyncIOMotorClient(settings.mongodb.uri)
    db = client[settings.mongodb.db_name]
    
    # 1. USERS - Fast auth lookups
    await db.users.create_index("email", unique=True, name="users_email_unique")
    await db.users.create_index("level", name="users_level")
    
    # 2. DOCUMENTS - Fast user/doc lookups
    await db.documents.create_index("user_id", name="documents_user_id")
    await db.documents.create_index([("user_id", 1), ("subject", 1)], name="documents_user_subject")
    await db.documents.create_index("doc_id", unique=True, name="documents_doc_id_unique")
    await db.documents.create_index("status", name="documents_status")
    
    # 3. CHATS - Fast session retrieval + timeline
    await db.chats.create_index([("user_id", 1), ("created_at", -1)], name="chats_user_timeline")
    await db.chats.create_index("subject", name="chats_subject")
    
    # 4. FEEDBACK - Analytics
    await db.feedback.create_index("user_id", name="feedback_user")
    await db.feedback.create_index("rating", name="feedback_rating")
    await db.feedback.create_index([("chat_session_id", 1), ("created_at", -1)])
    
    # 5. QUIZZES - Fast retrieval
    await db.quizzes.create_index("user_id", name="quizzes_user")
    await db.quizzes.create_index([("user_id", 1), ("created_at", -1)], name="quizzes_user_timeline")
    
    print("✅ Migration 001_initial.py COMPLETE - Optimal indexes created")

if __name__ == "__main__":
    asyncio.run(run_migration())
