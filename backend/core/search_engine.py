# backend/core/search_engine.py
import re
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
        self.cross_encoder = None
        self.use_reranker = None

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9_]+", str(text).lower())

    @staticmethod
    def _hit_key(hit: Dict[str, Any]) -> str:
        metadata = hit.get("metadata") or {}
        return str(
            metadata.get("chunk_id")
            or hit.get("id")
            or hit.get("text")
            or ""
        )

    def _ensure_reranker(self):
        if self.use_reranker is not None:
            return self.use_reranker

        last_error = None
        for kwargs in ({"local_files_only": True}, {}):
            try:
                self.cross_encoder = CrossEncoder(
                    "cross-encoder/ms-marco-MiniLM-L-6-v2",
                    **kwargs,
                )
                self.use_reranker = True
                return True
            except Exception as exc:
                last_error = exc

        print(f"WARNING: API/Model Error loading CrossEncoder: {last_error}. Reranking disabled.")
        self.use_reranker = False
        return False

    def search(self, user_id: str, subject: str, query: str, top_k: int = 6, document_ids: List[str] = None) -> List[Dict]:
        """
        Performs Hybrid Search. 
        If document_ids is provided, strictly scopes search to those documents.
        """
        # 1. FETCH CHUNKS (User + System)
        if document_ids:
            # STRICT MODE: Only search the specific documents
            where_clause = {"doc_id": {"$in": document_ids}} if len(document_ids) > 1 else {"doc_id": document_ids[0]}
            user_chunks = get_all_chunks(user_id, subject, where=where_clause)
            all_docs = user_chunks # Ignore system chunks
            print(f"DEBUG: Scoped search for docs {document_ids}. Found {len(all_docs)} candidate chunks.")
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
        
        if document_ids:
            # Scoped Vector Search
            where_clause = {"doc_id": {"$in": document_ids}} if len(document_ids) > 1 else {"doc_id": document_ids[0]}
            all_vec_results = query_user_collection(user_id, subject, query_vec, initial_k, where=where_clause)
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
        if self._ensure_reranker() and rrf_results:
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
        tokenized_corpus = [self._tokenize(doc) for doc in corpus]
        tokenized_query = self._tokenize(query)
        
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
            key = self._hit_key(hit)
            if not key:
                continue
            chunk_map[key] = hit
            scores[key] = scores.get(key, 0) + (self.bm25_weight / (k + rank + 1))

        # Process Dense
        for rank, hit in enumerate(dense_hits):
            key = self._hit_key(hit)
            if not key:
                continue
            chunk_map[key] = hit
            scores[key] = scores.get(key, 0) + (self.dense_weight / (k + rank + 1))

        sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        fused_results = []
        for key in sorted_keys[:top_k]:
            hit = chunk_map[key]
            hit["score"] = scores[key]
            fused_results.append(hit)
            
        return fused_results

search_engine = HybridSearchEngine()
