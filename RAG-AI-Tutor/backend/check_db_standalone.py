import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import sys

# Default MongoDB URI
URI = "mongodb://localhost:27017"

async def check_mongo():
    print(f"Testing connection to {URI}...")
    try:
        # Lower timeout to fail fast
        client = AsyncIOMotorClient(URI, serverSelectionTimeoutMS=2000)
        # Force a connection verification
        info = await client.server_info()
        print("✅ MongoDB Connected Successfully!")
        print(f"Server version: {info.get('version')}")
        return True
    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}")
        return False

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(check_mongo())
    except Exception as e:
        print(f"Script Error: {e}")
