# backend/utils/db.py
from motor.motor_asyncio import AsyncIOMotorClient
from backend.config import settings
import logging

class DatabaseManager:
    client: AsyncIOMotorClient = None
    db = None

    async def connect(self):
        logging.info("Connecting to MongoDB...")
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        self.db = self.client[settings.database_name]
        logging.info("Connected to MongoDB.")

    async def disconnect(self):
        logging.info("Closing MongoDB connection...")
        if self.client:
            self.client.close()
            logging.info("MongoDB connection closed.")

db_manager = DatabaseManager()

async def init_db():
    await db_manager.connect()

async def get_db():
    if db_manager.db is None:
        await db_manager.connect()
    return db_manager.db

# ALIAS to fix ImportError
get_database = get_db