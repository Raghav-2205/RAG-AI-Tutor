
import chromadb
from chromadb.config import Settings

def test_connection():
    try:
        print("Attempting to connect to ChromaDB at localhost:8001...")
        client = chromadb.HttpClient(host="localhost", port=8001)
        print("Client created.")
        
        heartbeat = client.heartbeat()
        print(f"Heartbeat: {heartbeat}")
        
        # Try to create a dummy collection
        collection = client.get_or_create_collection(name="test_connection_collection")
        print(f"Collection created: {collection.name}")
        
        # Add a dummy item
        collection.add(
            documents=["This is a test document"],
            metadatas=[{"source": "test"}],
            ids=["test_id_1"]
        )
        print("item added.")
        
        # Query
        results = collection.query(
            query_texts=["test"],
            n_results=1
        )
        print(f"Query results: {results}")
        
        # cleanup
        client.delete_collection("test_connection_collection")
        print("Cleanup complete.")
        print("✅ ChromaDB connection successful!")
        return True
    except Exception as e:
        print(f"❌ Failed to connect to ChromaDB: {e}")
        return False

if __name__ == "__main__":
    test_connection()
