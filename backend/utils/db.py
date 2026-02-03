from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure
import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Unified database manager for MongoDB"""
    
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        
    async def connect(self, mongo_uri: str = None):
        """Connect to MongoDB"""
        if not mongo_uri:
            mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
            
        try:
            self.client = AsyncIOMotorClient(mongo_uri)
            # Test connection
            await self.client.admin.command('ping')
            self.db = self.client.rag_ai_tutor
            logger.info("Connected to MongoDB successfully")
            return True
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")
    
    def get_collection(self, name: str):
        """Get a collection from the database"""
        if self.db is None:
            raise RuntimeError("Database not connected")
        return self.db[name]
    
    async def get_database(self):
        """Get database instance - for compatibility"""
        if self.db is None:
            await self.connect()
        return self.db
    
    async def create_indexes(self):
        """Create database indexes for better performance"""
        try:
            # User indexes
            users = self.get_collection("users")
            await users.create_index("email", unique=True)
            
            # Document indexes
            documents = self.get_collection("documents")
            await documents.create_index("user_id")
            await documents.create_index("subject")
            
            # Chat indexes
            chats = self.get_collection("chats")
            await chats.create_index("user_id")
            await chats.create_index("session_id")
            await chats.create_index("created_at")
            
            # Quiz indexes
            quizzes = self.get_collection("quizzes")
            await quizzes.create_index("user_id")
            await quizzes.create_index("document_id")
            
            # Feedback indexes
            feedback = self.get_collection("feedback")
            await feedback.create_index("user_id")
            await feedback.create_index("created_at")
            
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")

# Global database manager instance
db_manager = DatabaseManager()

async def get_database():
    """Dependency to get database instance"""
    return await db_manager.get_database()

async def get_db():
    """Dependency to get database instance - compatibility function"""
    return await db_manager.get_database()

async def init_db():
    """Initialize database connection and indexes"""
    await db_manager.connect()
    await db_manager.create_indexes()
