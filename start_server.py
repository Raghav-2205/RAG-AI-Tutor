#!/usr/bin/env python3
"""
Startup script for RAG AI Tutor
Handles environment setup and server startup
"""
import os
import sys
import subprocess
import asyncio
from pathlib import Path

def check_requirements():
    """Check if required packages are installed"""
    print("🔍 Checking requirements...")
    
    required_packages = [
        "fastapi",
        "uvicorn",
        "motor",
        "pymongo",
        "pydantic-settings",
        "python-multipart",
        "bcrypt",
        "python-jose[cryptography]",
        "passlib[bcrypt]"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.split('[')[0].replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ Missing packages: {', '.join(missing_packages)}")
        print("Installing missing packages...")
        
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install"
            ] + missing_packages)
            print("✅ Packages installed successfully")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install packages: {e}")
            return False
    else:
        print("✅ All required packages are installed")
    
    return True

def setup_environment():
    """Setup environment configuration"""
    print("🔧 Setting up environment...")
    
    # Check if .env exists, if not copy from .env.example
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            print("📄 Creating .env from .env.example...")
            with open(".env.example", "r") as src, open(".env", "w") as dst:
                dst.write(src.read())
            print("✅ .env file created")
            print("⚠️  Please edit .env file with your configuration")
        else:
            print("❌ .env.example not found")
            return False
    else:
        print("✅ .env file exists")
    
    # Create upload directory
    upload_dir = "uploads"
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        print(f"✅ Created {upload_dir} directory")
    
    # Create chroma data directory
    chroma_dir = "chroma_data"
    if not os.path.exists(chroma_dir):
        os.makedirs(chroma_dir)
        print(f"✅ Created {chroma_dir} directory")
    
    return True

async def test_database():
    """Test database connection"""
    print("🔍 Testing database connection...")
    
    try:
        # Add backend to path
        sys.path.append(str(Path(__file__).parent / "backend"))
        
        from backend.utils.db import db_manager
        success = await db_manager.connect()
        
        if success:
            print("✅ Database connection successful")
            await db_manager.disconnect()
            return True
        else:
            print("❌ Database connection failed")
            print("Make sure MongoDB is running on mongodb://localhost:27017")
            return False
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

def start_server(host="127.0.0.1", port=8000, reload=True):
    """Start the FastAPI server"""
    print(f"🚀 Starting server on http://{host}:{port}")
    
    try:
        cmd = [
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--host", host,
            "--port", str(port)
        ]
        
        if reload:
            cmd.append("--reload")
        
        print(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")

async def main():
    """Main startup sequence"""
    print("🚀 RAG AI Tutor Startup")
    print("=" * 50)
    
    # Step 1: Check requirements
    if not check_requirements():
        print("❌ Requirements check failed")
        return False
    
    # Step 2: Setup environment
    if not setup_environment():
        print("❌ Environment setup failed")
        return False
    
    # Step 3: Test database
    db_ok = await test_database()
    if not db_ok:
        print("⚠️  Database connection failed, but server will still start")
        print("Some features may not work until database is available")
    
    # Step 4: Start server
    print("\n" + "=" * 50)
    print("🎉 Setup complete! Starting server...")
    print("=" * 50)
    print("📱 Frontend: http://127.0.0.1:8000")
    print("📚 API Docs: http://127.0.0.1:8000/docs")
    print("🔍 Health: http://127.0.0.1:8000/health")
    print("=" * 50)
    print("Press Ctrl+C to stop the server")
    print()
    
    start_server()
    return True

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        sys.exit(1)