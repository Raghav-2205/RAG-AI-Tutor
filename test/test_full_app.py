#!/usr/bin/env python3
"""
Full Application Test Script
Tests the complete RAG AI Tutor application stack
"""

import asyncio
import aiohttp
import json
import time
from pathlib import Path

class AppTester:
    def __init__(self):
        self.base_url = "http://127.0.0.1:8000"
        self.api_url = f"{self.base_url}/api"
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_health(self):
        """Test health endpoint"""
        print("🔍 Testing health endpoint...")
        try:
            async with self.session.get(f"{self.base_url}/health") as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Health check passed: {data['status']}")
                    return True
                else:
                    print(f"❌ Health check failed: {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Health check error: {e}")
            return False
    
    async def test_api_root(self):
        """Test API root endpoint"""
        print("🔍 Testing API root...")
        try:
            async with self.session.get(f"{self.api_url}/") as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ API root accessible: {data['message']}")
                    return True
                else:
                    print(f"❌ API root failed: {response.status}")
                    return False
        except Exception as e:
            print(f"❌ API root error: {e}")
            return False
    
    async def test_frontend(self):
        """Test frontend accessibility"""
        print("🔍 Testing frontend...")
        try:
            async with self.session.get(f"{self.base_url}/") as response:
                if response.status == 200:
                    content = await response.text()
                    if "RAG AI Tutor" in content:
                        print("✅ Frontend accessible")
                        return True
                    else:
                        print("❌ Frontend content invalid")
                        return False
                else:
                    print(f"❌ Frontend failed: {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Frontend error: {e}")
            return False
    
    async def test_auth_endpoints(self):
        """Test authentication endpoints"""
        print("🔍 Testing auth endpoints...")
        
        # Test registration endpoint exists
        try:
            test_user = {
                "email": "test@example.com",
                "password": "testpass123",
                "full_name": "Test User"
            }
            
            async with self.session.post(
                f"{self.api_url}/auth/register",
                json=test_user
            ) as response:
                # We expect this to either work or fail with validation error
                # Both indicate the endpoint is accessible
                if response.status in [200, 201, 400, 422]:
                    print("✅ Auth registration endpoint accessible")
                    return True
                else:
                    print(f"❌ Auth registration failed: {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Auth registration error: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests"""
        print("🚀 Starting Full Application Tests")
        print("=" * 50)
        
        tests = [
            ("Health Check", self.test_health),
            ("API Root", self.test_api_root),
            ("Frontend", self.test_frontend),
            ("Auth Endpoints", self.test_auth_endpoints),
        ]
        
        results = []
        
        for test_name, test_func in tests:
            print(f"\n==== {test_name} ====")
            result = await test_func()
            results.append((test_name, result))
            time.sleep(0.5)  # Small delay between tests
        
        print("\n" + "=" * 50)
        print("TEST SUMMARY")
        print("=" * 50)
        
        passed = 0
        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{test_name:<20} {status}")
            if result:
                passed += 1
        
        print(f"\nResults: {passed}/{len(results)} tests passed")
        
        if passed == len(results):
            print("\n🎉 All tests passed! Your RAG AI Tutor is fully working!")
            print(f"🌐 Access your application at: {self.base_url}")
            print(f"📚 API Documentation: {self.base_url}/docs")
        else:
            print(f"\n⚠️  {len(results) - passed} tests failed. Please check the issues above.")
        
        return passed == len(results)

async def main():
    """Main test function"""
    print("Waiting 3 seconds for server to be ready...")
    await asyncio.sleep(3)
    
    async with AppTester() as tester:
        success = await tester.run_all_tests()
        return success

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ Test runner error: {e}")
        exit(1)