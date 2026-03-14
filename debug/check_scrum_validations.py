
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def check_validations():
    client = AsyncIOMotorClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("DATABASE_NAME", "rag_tutor")]
    
    print("--- VALIDATIONS AUDIT ---")
    query = {"question": {"$regex": "scrum", "$options": "i"}}
    validations = await db.rag_answer_validations.find(query).to_list(length=100)
    print(f"Total 'scrum' validations found: {len(validations)}")
    
    for v in validations:
        print(f"[{v.get('timestamp')}] Q: {v.get('question')} | Status: {v.get('validation_status')}")

if __name__ == "__main__":
    asyncio.run(check_validations())
