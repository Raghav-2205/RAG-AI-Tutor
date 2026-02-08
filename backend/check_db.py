# check_db.py
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# This should match your .env or config.py
URI = "mongodb://localhost:27017"
DB_NAME = "rag_ai_tutor"

async def check():
    print(f"Connecting to {URI}...")
    client = AsyncIOMotorClient(URI)
    db = client[DB_NAME]
    
    # Check Users
    count = await db.users.count_documents({})
    print(f"✅ Connected! Found {count} users in database '{DB_NAME}'")
    
    if count > 0:
        print("\n--- User List ---")
        async for user in db.users.find():
            print(f"ID: {user.get('_id')} | Email: {user.get('email')} | Name: {user.get('name')}")
    else:
        print("⚠️ No users found. Try registering in the app now.")

if __name__ == "__main__":
    asyncio.run(check())