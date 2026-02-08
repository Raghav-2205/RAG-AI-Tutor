# backend/api/__init__.py
"""
API Router package - exports all routers for main.py
"""

from fastapi import APIRouter
from . import auth, chat, feedback, ingest, quiz, upload

__all__ = ["auth", "chat", "feedback", "ingest", "quiz", "upload"]
