# backend/core/embedding_service.py
from typing import List, Union
from sentence_transformers import SentenceTransformer

class EmbeddingService:
    def __init__(self):
        # This downloads the model automatically on first run
        self.model = SentenceTransformer('all-MiniLM-L6-v2')

    def embed_text(self, text: Union[str, List[str]]) -> List[float]:
        if isinstance(text, str):
            # Return list of floats
            return self.model.encode(text).tolist()
        else:
            # Return list of list of floats
            return self.model.encode(text).tolist()

# Singleton instance
embedding_service = EmbeddingService()