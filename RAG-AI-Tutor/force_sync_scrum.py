
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def force_sync():
    client = AsyncIOMotorClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("DATABASE_NAME", "rag_tutor")]
    
    from backend.core.evaluation.validator import ValidationEngine
    validator = ValidationEngine(db)
    
    print("🚀 Re-running sync for Scrum questions specifically...")
    sessions = await db.chat_sessions.find().to_list(length=1000)
    
    for s in sessions:
        user_id = s.get("user_id")
        messages = s.get("messages", [])
        for i in range(1, len(messages)):
            msg = messages[i]
            prev = messages[i-1]
            if "scrum" in prev.get("content", "").lower() and msg.get("chunks"):
                # Always re-validate for this test
                print(f"Validating: {prev['content']} (User: {user_id})")
                await validator.validate_answer(
                    question=prev["content"],
                    answer=msg["content"],
                    retrieved_chunks=msg["chunks"],
                    user_id=user_id,
                    subject=s.get("subject", "general")
                )
    print("✅ Done.")

if __name__ == "__main__":
    asyncio.run(force_sync())
