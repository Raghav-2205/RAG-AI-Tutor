
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

async def debug_sessions():
    client = AsyncIOMotorClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db = client[os.getenv("DATABASE_NAME", "rag_tutor")]
    
    print("--- CHAT SESSIONS AUDIT ---")
    sessions = await db.chat_sessions.find().to_list(length=100)
    print(f"Total sessions found: {len(sessions)}")
    
    scrum_found = False
    for s in sessions:
        messages = s.get("messages", [])
        for i, m in enumerate(messages):
            if "scrum" in m.get("content", "").lower():
                scrum_found = True
                print(f"\nFOUND SCRUM MESSAGE in session {s.get('chat_id')}")
                print(f"Role: {m.get('role')}")
                print(f"Has Chunks: {'Yes' if m.get('chunks') else 'No'}")
                if m.get('chunks'):
                    print(f"Num Chunks: {len(m.get('chunks'))}")
                
                if i > 0:
                    prev = messages[i-1]
                    print(f"Prev Role: {prev.get('role')}")
                    print(f"Prev Content: {prev.get('content')[:100]}...")
    
    if not scrum_found:
        print("\nNo messages containing 'scrum' found in chat_sessions.")

if __name__ == "__main__":
    asyncio.run(debug_sessions())
