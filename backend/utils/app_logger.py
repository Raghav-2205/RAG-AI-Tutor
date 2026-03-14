import logging
import sys
import os

# Windows UTF-8 fix
if os.name == 'nt':
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('backend.log', encoding='utf-8')
    ]
)

app_logger = logging.getLogger('RAG-AI-Tutor')
app_logger.info("Logger ready - Backend starting")

__all__ = ['app_logger']
