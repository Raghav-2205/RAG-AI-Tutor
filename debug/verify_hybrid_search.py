
import sys
import os
import logging
from _bootstrap import ensure_project_root

ensure_project_root()

from backend.core.search_engine import search_engine
from backend.vector_db import add_chunks_to_collection, get_vector_db, clear_user_data, get_or_create_collection

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_hybrid_search():
    user_id = "test_user_verify"
    subject = "history"
    
    print(f"\n--- 1. Cleaning up previous test data for User: {user_id} ---")
    client = get_vector_db()
    # Manual cleanup via client if needed, or use helper
    # We can try to delete the specific collection
    collection_name = f"user_{user_id}_{subject}"
    client.delete_collection(collection_name)

    print("\n--- 2. Injecting Unique Needle into ChromaDB ---")
    # A unique fact that definitely wouldn't be in BM25 or pre-trained models easily without context
    unique_fact = "The secret code for the verification protocol is ALPHA-ZULU-999."
    
    chunks = [{
        "text": unique_fact,
        "source": "manual_verification",
        "doc_id": "doc_verify_1",
        "chunk_index": 0
    }]
    
    # helper to add to DB
    collection = get_or_create_collection(client, user_id, subject)
    print(f"DEBUG: Collection Name: {collection.name}")
    print(f"DEBUG: Collection ID: {collection.id}")
    
    add_ids = add_chunks_to_collection(collection, chunks)
    print(f"Added ids: {add_ids}")
    
    # 2.5 VERIFY INSERTION
    print("\n--- 2.5 Verifying Insertion (get) ---")
    stored_chunks = get_all_chunks(user_id, subject)
    print(f"Stored chunks count: {len(stored_chunks)}")
    if stored_chunks:
        print(f"Sample stored: {stored_chunks[0]['text'][:50]}...")
    else:
        print("❌ FATAL: No chunks returned after add!")

    print("\n--- 3. Running Direct Vector Search ---")
    from backend.core.embedding_service import embedding_service
    # Search for the secret code
    query = "What is the secret code for verification?"
    print(f"Query: '{query}'")
    
    q_vec = embedding_service.embed_text(query)
    direct_results = client.get_or_create_collection(collection.name).query([q_vec], n_results=5)
    print(f"Direct Query Raw Results keys: {direct_results.keys()}")
    print(f"Direct Query Documents: {direct_results.get('documents')}")
    
    print("\n--- 3.5 Running Search Engine Search ---")
    results = search_engine.search(user_id, subject, query, top_k=5)
    
    found = False
    print("\n--- 4. Examining Results ---")
    for i, res in enumerate(results):
        print(f"Result {i+1}:")
        print(f"  Text: {res['text'][:100]}...")
        print(f"  Score: {res.get('score')}")
        print(f"  Metadata: {res.get('metadata')}")
        
        if "ALPHA-ZULU-999" in res["text"]:
            found = True
            print("  ✅ MATCH FOUND!")
    
    if found:
        print("\n✅ SUCCESS: Hybrid Search retrieved the specific data from ChromaDB.")
    else:
        print("\n❌ FAILURE: Hybrid Search did NOT retrieve the data.")

    # Cleanup
    print("\n--- 5. Cleanup ---")
    client.delete_collection(collection_name)
    print("Cleanup complete.")

if __name__ == "__main__":
    verify_hybrid_search()
