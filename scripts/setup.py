#!/usr/bin/env python3
"""
Complete project setup script for RAG AI Tutor
Installs dependencies, initializes DB, downloads models
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, cwd=None):
    """Run shell command with error handling"""
    try:
        result = subprocess.run(cmd, shell=True, check=True, 
                              capture_output=True, text=True, cwd=cwd)
        print(f"✅ {cmd}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ {cmd}: {e.stderr}")
        sys.exit(1)

def main():
    print("🚀 Setting up RAG AI Tutor...")
    
    # 1. Create virtual environment
    if not Path(".venv").exists():
        run_command("python3 -m venv .venv")
        run_command(".venv/bin/pip install --upgrade pip")
    
    # 2. Install dependencies
    run_command(".venv/bin/pip install -r requirements.txt")
    
    # 3. Download models
    run_command("python3 scripts/download_models.py")
    
    # 4. Initialize database
    run_command("python3 -c 'from backend.database import init_db; init_db()'")
    
    # 5. Setup frontend (if exists)
    if Path("frontend").exists():
        os.chdir("frontend")
        run_command("npm install")
        os.chdir("..")
    
    # 6. Make scripts executable
    run_command("chmod +x scripts/*.sh")
    
    print("\n🎉 Setup complete!")
    print("Run: .venv/bin/activate && uvicorn backend.main:app --reload")

if __name__ == "__main__":
    main()
