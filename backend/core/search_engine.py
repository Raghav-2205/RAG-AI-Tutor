# backend/core/search_engine.py
from rank_bm25 import BM25Okapi
from typing import List, Dict, Any
from backend.core.embedding_service import embedding_service
from backend.vector_db import query_user_collection, get_all_chunks

class HybridSearchEngine:
    def __init__(self):
        self.bm25_weight = 0.5
        self.dense_weight = 0.5
        self.system_id = "global"  # Matches scripts/index_data_folder.py GLOBAL_USER_ID

    def search(self, user_id: str, subject: str, query: str, top_k: int = 6) -> List[Dict]:
        """
        Performs Hybrid Search across BOTH User and System datasets.
        """
        # 1. FETCH CHUNKS (User + System)
        # We assume system data is always stored under subject="general"
        user_chunks = get_all_chunks(user_id, subject)
        system_chunks = get_all_chunks(self.system_id, "general") 
        
        all_docs = user_chunks + system_chunks
        
        # If absolutely no data exists, return empty
        if not all_docs:
            print("DEBUG: No documents found in User or System database.")
            return []

        # 2. BM25 SEARCH (Keyword)
        bm25_results = self._bm25_search(query, all_docs, top_k)

        # 3. VECTOR SEARCH (Semantic)
        query_vec = embedding_service.embed_text(query)
        
        # Search User's Private Data
        user_vec_results = query_user_collection(user_id, subject, query_vec, top_k)
        
        # Search System's Public Data
        system_vec_results = query_user_collection(self.system_id, "general", query_vec, top_k)
        
        # Combine vector results
        all_vec_results = user_vec_results + system_vec_results
        
        # 4. FUSE RESULTS (RRF)
        final_results = self._rrf_fusion(bm25_results, all_vec_results, top_k)
        
        print(f"DEBUG: Found {len(final_results)} relevant chunks for query: '{query}'")
        return final_results

    def _bm25_search(self, query: str, documents: List[Dict], top_k: int) -> List[Dict]:
        if not documents: return []
        
        corpus = [d["text"] for d in documents]
        tokenized_corpus = [doc.lower().split() for doc in corpus]
        tokenized_query = query.lower().split()
        
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(tokenized_query)
        
        results = []
        for i, score in enumerate(scores):
            if score > 0.1: # Only keep somewhat relevant matches
                results.append({
                    "text": documents[i]["text"],
                    "metadata": documents[i]["metadata"],
                    "score": score,
                    "type": "bm25"
                })
        
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    def _rrf_fusion(self, bm25_hits: List[Dict], dense_hits: List[Dict], top_k: int) -> List[Dict]:
        k = 60
        scores = {}
        chunk_map = {}

        # Process BM25
        for rank, hit in enumerate(bm25_hits):
            text = hit["text"]
            chunk_map[text] = hit
            scores[text] = scores.get(text, 0) + (1 / (k + rank + 1))

        # Process Dense
        for rank, hit in enumerate(dense_hits):
            text = hit["text"]
            chunk_map[text] = hit
            scores[text] = scores.get(text, 0) + (1 / (k + rank + 1))

        sorted_texts = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        fused_results = []
        for text in sorted_texts[:top_k]:
            hit = chunk_map[text]
            hit["score"] = scores[text]
            fused_results.append(hit)
            
        return fused_results

search_engine = HybridSearchEngine()