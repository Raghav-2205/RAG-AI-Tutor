
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def check_db():
    client = AsyncIOMotorClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("DATABASE_NAME", "rag_tutor")]
    
    count = await db.rag_answer_validations.count_documents({})
    print(f"Total validation logs: {count}")
    
    logs = await db.rag_answer_validations.find().sort("timestamp", -1).limit(5).to_list(length=5)
    for l in logs:
        print(f"[{l.get('timestamp')}] Q: {l.get('question')} | User: {l.get('user_id')}")

if __name__ == "__main__":
    asyncio.run(check_db())
