# backend/core/search_engine.py
from rank_bm25 import BM25Okapi
from typing import List, Dict, Any
from backend.core.embedding_service import embedding_service
from backend.vector_db import query_user_collection, get_all_chunks

from sentence_transformers import CrossEncoder

class HybridSearchEngine:
    def __init__(self):
        self.bm25_weight = 0.5
        self.dense_weight = 0.5
        self.system_id = "global"  # Matches scripts/index_data_folder.py GLOBAL_USER_ID
        # Load Cross-Encoder for Reranking
        # We use a lightweight but effective model
        try:
            self.cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            self.use_reranker = True
        except Exception as e:
            print(f"WARNING: API/Model Error loading CrossEncoder: {e}. Reranking disabled.")
            self.use_reranker = False

    def search(self, user_id: str, subject: str, query: str, top_k: int = 6, document_id: str = None) -> List[Dict]:
        """
        Performs Hybrid Search. 
        If document_id is provided, strictly scopes search to that document.
        """
        # 1. FETCH CHUNKS (User + System)
        if document_id:
            # STRICT MODE: Only search the specific document
            user_chunks = get_all_chunks(user_id, subject, where={"doc_id": document_id})
            all_docs = user_chunks # Ignore system chunks
            print(f"DEBUG: Scoped search for doc {document_id}. Found {len(all_docs)} candidate chunks.")
        else:
            # GLOBAL MODE: User + System
            # We assume system data is always stored under subject="general"
            user_chunks = get_all_chunks(user_id, subject)
            system_chunks = get_all_chunks(self.system_id, "general") 
            all_docs = user_chunks + system_chunks
        
        # If absolutely no data exists, return empty
        if not all_docs:
            print("DEBUG: No documents found in database.")
            return []

        # Retrieve more candidates for RRF and Reranking
        initial_k = top_k * 5 

        # 2. BM25 SEARCH (Keyword)
        bm25_results = self._bm25_search(query, all_docs, initial_k)

        # 3. VECTOR SEARCH (Semantic)
        query_vec = embedding_service.embed_text(query)
        
        if document_id:
            # Scoped Vector Search
            all_vec_results = query_user_collection(user_id, subject, query_vec, initial_k, where={"doc_id": document_id})
        else:
            # Global Vector Search
            # Search User's Private Data
            user_vec_results = query_user_collection(user_id, subject, query_vec, initial_k)
            
            # Search System's Public Data
            system_vec_results = query_user_collection(self.system_id, "general", query_vec, initial_k)
            
            # Combine vector results
            all_vec_results = user_vec_results + system_vec_results
        
        # 4. FUSE RESULTS (RRF)
        # We pass a larger pool to RRF
        rrf_results = self._rrf_fusion(bm25_results, all_vec_results, initial_k)
        
        # 5. RERANKING
        if self.use_reranker and rrf_results:
            final_results = self._rerank_results(query, rrf_results, top_k)
        else:
            final_results = rrf_results[:top_k]
        
        print(f"DEBUG: Found {len(final_results)} relevant chunks for query: '{query}'")
        return final_results

    def _rerank_results(self, query: str, documents: List[Dict], top_k: int) -> List[Dict]:
        """
        Reranks the candidates using a Cross-Encoder.
        """
        if not documents:
            return []
            
        # Prepare pairs for Cross-Encoder
        pairs = [[query, doc["text"]] for doc in documents]
        
        # Predict scores
        scores = self.cross_encoder.predict(pairs)
        
        # Attach scores and sort
        for i, doc in enumerate(documents):
            doc["rerank_score"] = float(scores[i])
            
        # Sort by rerank score descending
        reranked = sorted(documents, key=lambda x: x["rerank_score"], reverse=True)
        
        return reranked[:top_k]

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
                    "id": documents[i].get("id"),
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