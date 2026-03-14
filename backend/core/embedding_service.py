# backend/core/embedding_service.py
from typing import List, Union

from sentence_transformers import SentenceTransformer

from backend.config import settings

class EmbeddingService:
    def __init__(self):
        self.model = None
        self.model_name = settings.embedding_model

    def _get_model(self):
        if self.model is not None:
            return self.model

        last_error = None
        for kwargs in ({"local_files_only": True}, {}):
            try:
                self.model = SentenceTransformer(self.model_name, **kwargs)
                return self.model
            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            f"Failed to load embedding model '{self.model_name}'."
        ) from last_error

    def embed_text(self, text: Union[str, List[str]]) -> List[float]:
        model = self._get_model()
        if isinstance(text, str):
            return model.encode(text).tolist()
        return model.encode(text).tolist()

# Singleton instance
embedding_service = EmbeddingService()
