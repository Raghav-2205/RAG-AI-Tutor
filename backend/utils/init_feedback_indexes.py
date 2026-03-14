# backend/utils/init_feedback_indexes.py
"""
Initialize MongoDB indexes for the feedback collection.
Run this once to ensure optimal query performance.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from backend.utils.db import init_db, db_manager


async def create_feedback_indexes():
    """Create indexes for the feedback collection"""
    print("🔧 Creating feedback collection indexes...")
    
    await init_db()
    db = db_manager.db
    
    # Create indexes
    await db.feedback.create_index("user_id")
    print("✅ Created index on 'user_id'")
    
    await db.feedback.create_index("subject")
    print("✅ Created index on 'subject'")
    
    await db.feedback.create_index("source")
    print("✅ Created index on 'source'")
    
    await db.feedback.create_index("reference_id")
    print("✅ Created index on 'reference_id'")
    
    await db.feedback.create_index("timestamp")
    print("✅ Created index on 'timestamp'")
    
    # Create compound index for common queries
    await db.feedback.create_index([("user_id", 1), ("source", 1)])
    print("✅ Created compound index on 'user_id' + 'source'")
    
    await db.feedback.create_index([("user_id", 1), ("subject", 1)])
    print("✅ Created compound index on 'user_id' + 'subject'")
    
    print("\n✅ All feedback indexes created successfully!")
    
    # List all indexes
    indexes = await db.feedback.list_indexes().to_list(length=100)
    print("\n📋 Current indexes on feedback collection:")
    for idx in indexes:
        print(f"   - {idx['name']}: {idx.get('key', {})}")
    
    await db_manager.disconnect()


if __name__ == "__main__":
    asyncio.run(create_feedback_indexes())
