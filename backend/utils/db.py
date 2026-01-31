"""
MongoDB connection singleton.
"""
from backend.config import settings
from pymongo import MongoClient
from pymongo.database import Database

_client: MongoClient | None = None
_db: Database | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(settings.mongodb_uri)
    return _client


def get_db() -> Database:
    global _db
    if _db is None:
        _db = get_client().get_database("rag_tutor")
    return _db
