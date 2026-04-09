from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime

class ValidationResult(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    question: str
    answer: str
    subject: str = "general"
    user_id: Optional[str] = None
    evaluation_source: str = "live"
    chat_id: Optional[str] = None
    document_id: Optional[str] = None   # NEW
    document_name: Optional[str] = None # NEW
    
    # Retrieval Metrics
    recall_at_5: float = 0.0
    precision_at_5: float = 0.0
    mrr: float = 0.0
    
    # Generation Metrics
    faithfulness_score: float = 0.0
    hallucination_rate: float = 0.0
    citation_alignment_score: float = 0.0
    bert_score: float = 0.0
    cosine_similarity: float = 0.0
    answer_relevance: float = 0.0
    
    # Composite
    final_rag_score: float = 0.0
    
    # Status
    validation_status: str = "PENDING"  # VERIFIED, REJECTED, WARNING, ERROR, INSUFFICIENT_CONTEXT
    reason: Optional[str] = None
    
    # Metadata
    retrieved_chunk_ids: List[str] = []
    retrieved_chunks_text: List[str] = []
    
    # New Metrics for Detailed Dashboard
    retrieval_confidence: float = 0.0
    chunk_usage: Dict[str, Any] = {}  # {retrieved: int, used: int, coverage: float}
    unsupported_sentences: List[str] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @field_validator("id", mode="before")
    @classmethod
    def convert_objectid(cls, v: Any) -> Any:
        from bson import ObjectId
        if isinstance(v, ObjectId):
            return str(v)
        return v

    model_config = {
        "populate_by_name": True,
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }
