# backend/core/search_engine.py

"""
Hybrid search: BM25 (keywords) + Dense (embeddings) + RRF fusion.
Used by: rag_tutor.py (advanced version)
"""

import rank_bm25
from typing import List, Dict, Any
from backend.core.embedding_service import embedding_service


class HybridSearchEngine:
    def __init__(self):
        self.bm25_weight = 0.3
        self.dense_weight = 0.7
        
    def search(
        self,
        user_id: str,
        subject: str,
        query: str,
        documents: List[Dict],
        top_k: int = 6
    ) -> List[Dict]:
        """
        Hybrid BM25 + Dense search with Reciprocal Rank Fusion (RRF)
        """
        if not documents:
            return []
        
        # 1. BM25 keyword search
        bm25_scores = self._bm25_search(query, documents)
        
        # 2. Dense vector search - get from vector_db at runtime to avoid circular import
        dense_results = self._get_dense_results(user_id, subject, query, top_k)
        
        # 3. RRF fusion
        fused_results = self._rrf_fusion(bm25_scores, dense_results, top_k)
        return fused_results
    
    def _get_dense_results(self, user_id: str, subject: str, query: str, top_k: int) -> List[Dict]:
        """Get dense vector search results - import at runtime to avoid circular import"""
        try:
            from backend.vector_db import query_user_collection
            query_embedding = embedding_service.embed_text(query)
            return query_user_collection(user_id, subject, query_embedding, top_k=top_k*2)
        except ImportError:
            return []
    
    def _bm25_search(self, query: str, documents: List[Dict]) -> List[Dict]:
        """BM25 keyword matching"""
        corpus = [doc["text"] for doc in documents]
        tokenized_corpus = [doc["text"].split() for doc in documents]
        
        bm25 = rank_bm25.BM25Okapi(tokenized_corpus)
        query_tokens = query.split()
        scores = bm25.get_scores(query_tokens)
        
        results = []
        for i, score in enumerate(scores):
            results.append({
                "text": documents[i]["text"],
                "source": documents[i]["source"], 
                "score": score,
                "method": "bm25"
            })
        return sorted(results, key=lambda x: x["score"], reverse=True)[:6]
    
    def _rrf_fusion(self, bm25_results: List, dense_results: List, top_k: int) -> List[Dict]:
        """Reciprocal Rank Fusion of BM25 + Dense results"""
        scores = {}
        
        # BM25 scores
        for rank, result in enumerate(bm25_results, 1):
            doc_id = f"{result['source']}_{rank}"
            scores[doc_id] = scores.get(doc_id, 0) + self.bm25_weight / (60 + rank)
        
        # Dense scores  
        for rank, result in enumerate(dense_results, 1):
            doc_id = f"{result['source']}_{rank}"
            scores[doc_id] = scores.get(doc_id, 0) + self.dense_weight / (60 + rank)
        
        # Sort by fused score
        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        
        # Return actual results
        result_map = {}
        for r in bm25_results + dense_results:
            key = f"{r['source']}_1"  # Simplified key
            if key not in result_map:
                result_map[key] = r
        
        return [result_map.get(f[0], bm25_results[0] if bm25_results else dense_results[0]) for f in fused if result_map.get(f[0])][:top_k]


search_engine = HybridSearchEngine()
