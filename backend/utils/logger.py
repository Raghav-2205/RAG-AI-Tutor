# backend/utils/logger.py

"""
Centralized logging setup.
"""

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

from backend.config import settings


# Create logs/ folder
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def setup_logger(name: str) -> logging.Logger:
    """
    Create logger with file + console output.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO if not settings.debug else logging.DEBUG)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler (always)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if not settings.debug else logging.DEBUG)
    
    # File handler (rotating, 5MB max, keep 3 old files)
    file_handler = RotatingFileHandler(
        LOG_DIR / f"{name}.log",
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


# Convenience loggers
app_logger = setup_logger("rag_tutor_app")
api_logger = setup_logger("rag_tutor_api")
db_logger = setup_logger("rag_tutor_db")
