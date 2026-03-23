import sys
import asyncio
from pathlib import Path

for parent in Path(__file__).resolve().parents:
    if (parent / "backend").exists():
        root = str(parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        break

from backend.auth import get_password_hash, create_access_token
from backend.utils.db import get_db, init_db, db_manager
from backend.models.user import UserCreate

async def test_auth():
    print("Testing Password Hash...")
    try:
        pw = "secret"
        hashed = get_password_hash(pw)
        print(f"✅ Hash Success: {hashed[:10]}...")
    except Exception as e:
        print(f"❌ Hash Failed: {e}")

    print("Testing JWT...")
    try:
        token = create_access_token({"sub": "testuser"})
        print(f"✅ JWT Success: {token[:10]}...")
    except Exception as e:
        print(f"❌ JWT Failed: {e}")

    print("Testing DB Insert...")
    try:
        await init_db()
        # Create a dummy user dict manually like in register
        user_dict = {
            "name": "Test User",
            "email": "test@example.com",
            "hashed_password": hashed,
            "level": "undergraduate",
            "created_at": "now"
        }
        # We need the actual db object from db_manager
        db = db_manager.db
        result = await db.users.insert_one(user_dict)
        print(f"✅ DB Insert Success: {result.inserted_id}")
        
        # Cleanup
        await db.users.delete_one({"_id": result.inserted_id})
        print("✅ Cleanup Success")
        
    except Exception as e:
        print(f"❌ DB Insert Failed: {e}")
    finally:
        await db_manager.disconnect()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_auth())
