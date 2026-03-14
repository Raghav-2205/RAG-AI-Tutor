#!/usr/bin/env python3
"""
Automated SQLite database backup for RAG AI Tutor
Creates timestamped backups with compression
"""

import sqlite3
import shutil
import os
import datetime
import zipfile
from pathlib import Path

DB_PATH = "rag_ai_tutor.db"
BACKUP_DIR = Path("backups")
LOG_FILE = Path("backup.log")

BACKUP_DIR.mkdir(exist_ok=True)

def create_backup():
    """Create timestamped database backup"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"rag_ai_tutor_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name
    
    try:
        # Create database backup
        shutil.copy2(DB_PATH, backup_path)
        print(f"✅ Database backed up: {backup_path}")
        
        # Create compressed archive
        zip_path = BACKUP_DIR / f"rag_ai_tutor_{timestamp}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(backup_path, backup_name)
        backup_path.unlink()  # Remove uncompressed backup
        
        log_backup(zip_path)
        return str(zip_path)
        
    except Exception as e:
        log_error(f"Backup failed: {e}")
        return None

def log_backup(backup_path):
    """Log successful backup"""
    with open(LOG_FILE, 'a') as f:
        f.write(f"{datetime.datetime.now()}: BACKUP SUCCESS - {backup_path}\n")

def log_error(message):
    """Log backup error"""
    with open(LOG_FILE, 'a') as f:
        f.write(f"{datetime.datetime.now()}: BACKUP ERROR - {message}\n")

if __name__ == "__main__":
    create_backup()
