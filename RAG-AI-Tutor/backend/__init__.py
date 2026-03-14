# backend/__init__.py - Fixed imports
print('🚀 Loading RAG AI Tutor Backend...')

# Fix the import path issue
try:
    from .utils.db import db_manager, get_database
    print('✅ Database module loaded')
except ImportError as e:
    print(f'⚠️  Database import warning: {e}')
    db_manager = None
    get_database = None

# Don't import other modules until main.py runs
print('✅ Backend __init__ complete')
