#!/usr/bin/env python3
"""
Test script to verify frontend-backend-database connections
"""
import asyncio
import sys
import os
import requests
import time
from pathlib import Path
from _bootstrap import ensure_project_root

ensure_project_root()

async def test_database_connection():
    """Test MongoDB connection"""
    print("🔍 Testing database connection...")
    try:
        from backend.utils.db import db_manager
        success = await db_manager.connect()
        if success:
            print("✅ Database connection successful")
            await db_manager.disconnect()
            return True
        else:
            print("❌ Database connection failed")
            return False
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return False

def test_backend_startup():
    """Test if backend can start"""
    print("🔍 Testing backend startup...")
    try:
        from backend.config import settings
        print(f"✅ Configuration loaded: {settings.app_name}")
        
        from backend.main import app
        print("✅ FastAPI app created successfully")
        return True
    except Exception as e:
        print(f"❌ Backend startup error: {e}")
        return False

def test_frontend_files():
    """Test if frontend files exist"""
    print("🔍 Testing frontend files...")
    
    required_files = [
        "frontend/public/index.html",
        "frontend/public/assets/js/config.js",
        "frontend/public/assets/js/auth.js",
        "frontend/public/assets/js/ai.js",
        "frontend/public/views/login.html",
        "frontend/public/views/signup.html"
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print(f"❌ Missing frontend files: {missing_files}")
        return False
    else:
        print("✅ All required frontend files exist")
        return True

def test_api_health(port=8000, timeout=5):
    """Test API health endpoint"""
    print(f"🔍 Testing API health on port {port}...")
    try:
        response = requests.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ API health check passed: {data.get('status')}")
            return True
        else:
            print(f"❌ API health check failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ API not reachable: {e}")
        return False

def test_environment_config():
    """Test environment configuration"""
    print("🔍 Testing environment configuration...")
    
    # Check if .env exists
    env_exists = os.path.exists(".env")
    env_example_exists = os.path.exists(".env.example")
    
    print(f"📄 .env file exists: {env_exists}")
    print(f"📄 .env.example file exists: {env_example_exists}")
    
    if not env_example_exists:
        print("❌ .env.example file missing")
        return False
    
    # Test config loading
    try:
        from backend.config import settings
        print(f"✅ Config loaded successfully")
        print(f"   - App: {settings.app_name}")
        print(f"   - MongoDB URI: {settings.mongodb_uri}")
        print(f"   - API Host: {settings.api_host}:{settings.api_port}")
        return True
    except Exception as e:
        print(f"❌ Config loading error: {e}")
        return False

async def run_all_tests():
    """Run all connection tests"""
    print("🚀 Starting RAG AI Tutor Connection Tests\n")
    
    tests = [
        ("Environment Config", test_environment_config),
        ("Frontend Files", test_frontend_files),
        ("Backend Startup", test_backend_startup),
        ("Database Connection", test_database_connection),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"Running: {test_name}")
        print('='*50)
        
        if asyncio.iscoroutinefunction(test_func):
            results[test_name] = await test_func()
        else:
            results[test_name] = test_func()
    
    # Summary
    print(f"\n{'='*50}")
    print("TEST SUMMARY")
    print('='*50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name:<25} {status}")
        if result:
            passed += 1
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Your RAG AI Tutor is ready to run.")
        print("\nNext steps:")
        print("1. Copy .env.example to .env and configure your settings")
        print("2. Install dependencies: pip install -r requirements.txt")
        print("3. Start the server: python -m uvicorn backend.main:app --reload")
        print("4. Open http://127.0.0.1:8000 in your browser")
    else:
        print(f"\n⚠️  {total - passed} tests failed. Please fix the issues above.")
    
    return passed == total

if __name__ == "__main__":
    # Run tests
    success = asyncio.run(run_all_tests())
    
    # Optional: Test running server if requested
    if len(sys.argv) > 1 and sys.argv[1] == "--test-server":
        print("\n" + "="*50)
        print("TESTING RUNNING SERVER")
        print("="*50)
        print("Make sure the server is running with:")
        print("python -m uvicorn backend.main:app --reload")
        print("\nWaiting 3 seconds...")
        time.sleep(3)
        
        server_ok = test_api_health()
        if server_ok:
            print("🎉 Server is running and healthy!")
        else:
            print("❌ Server test failed. Make sure it's running.")
    
    sys.exit(0 if success else 1)
