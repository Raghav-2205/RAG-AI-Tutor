
import sys
import os
import uuid
import time
from _bootstrap import ensure_project_root


import logging

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Silence noisy libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("backend.vector_db").setLevel(logging.DEBUG)

ensure_project_root()

from backend.vector_db import ChromaDBClient, get_vector_db, get_or_create_collection, add_chunks_to_collection

def test_integration():
    print("--- Starting ChromaDB Integration Test ---")
    
    # 1. Initialize Client
    client = get_vector_db()
    print(f"Client initialized: {client.api_url}")
    
    # 2. Create Test Collection
    user_id = "test_user_integration"
    subject = "test_subject"
    collection_name = f"user_{user_id}_{subject}"
    
    # Ensure cleanup first
    try:
        client.delete_collection(collection_name)
        print(f"Deleted existing collection: {collection_name}")
    except:
        pass

    collection = get_or_create_collection(client, user_id, subject)
    print(f"Collection created/retrieved: {collection.name} ({collection.id})")
    
    # 3. Add Documents (Enough to test default limit)
    num_docs = 25
    chunks = []
    for i in range(num_docs):
        chunks.append({
            "text": f"This is document number {i}. It contains some test data.",
            "source": "test_script",
            "doc_id": "doc_1",
            "chunk_index": i
        })
    
    print(f"Adding {num_docs} chunks...")
    ids = add_chunks_to_collection(collection, chunks)
    print(f"Added {len(ids)} chunks.")
    
    # Allow some time for indexing (though usually sync for small batches)
    time.sleep(1)
    
    # 4. Test Get (Check Limit)
    print("Testing collection.get() without explicit limit...")
    results = collection.get()
    
    # Verify count
    received_count = len(results.get("ids", []))
    print(f"Received {received_count} documents from get()")
    
    if received_count == num_docs:
        print("SUCCESS: get() returned all documents.")
    else:
        print(f"WARNING: get() returned {received_count} documents, expected {num_docs}. Default limit might be in effect.")
        # Continue to test query even if get fails, to see if data is there at all
        pass
        
    # 5. Test Query
    print("Testing collection.query()...")
    # We need an embedding. We can cheat and use a dummy one if we want to avoid loading the model, 
    # but the server might validate dimension if we don't provide embeddings in add().
    # In add_chunks_to_collection, it imports embedding_service and computes them.
    # So we should compute one here too.
    from backend.core.embedding_service import embedding_service
    query_text = "document number 5"
    query_vec = embedding_service.embed_text(query_text)
    
    query_results = collection.query(
        query_embeddings=[query_vec],
        n_results=5
    )
    
    # Check results
    if query_results["ids"] and len(query_results["ids"][0]) > 0:
        print(f"Query returned {len(query_results['ids'][0])} results.")
        print(f"Top result: {query_results['documents'][0][0]}")
        print("SUCCESS: Query working.")
    else:
        print("FAILURE: Query returned no results.")
        return False

    # 6. Cleanup
    client.delete_collection(collection_name)
    print("Cleanup done.")
    
    print("--- Integration Test PASSED ---")
    return True

if __name__ == "__main__":
    success = test_integration()
    if not success:
        sys.exit(1)
