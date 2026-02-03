import logging
import sys
from pathlib import Path

# Configure logging
def setup_logging():
    """Setup application logging"""
    
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Configure root logger with UTF-8 encoding
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / "rag-ai-backend.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set console handler encoding for Windows
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
            # For Windows console, use a safe format without emojis
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))

# Setup logging on import
setup_logging()

# Create specific loggers
api_logger = logging.getLogger("api")
db_logger = logging.getLogger("database")
auth_logger = logging.getLogger("auth")
rag_logger = logging.getLogger("rag")

# Export commonly used logger
__all__ = ["api_logger", "db_logger", "auth_logger", "rag_logger"]