# backend/core/search_engine.py
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from backend.config import settings
from backend.core.embedding_service import embedding_service
from backend.vector_db import query_user_collection, get_all_chunks

class HybridSearchEngine:
    def __init__(self):
        self.bm25_weight = settings.bm25_weight
        self.dense_weight = settings.dense_weight
        self.system_id = "global"  # Matches scripts/index_data_folder.py GLOBAL_USER_ID
        self.cross_encoder = None
        self.use_reranker = None
        self.stopwords = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "how", "in", "is", "it", "of", "on", "or", "that", "the", "to",
            "what", "when", "where", "which", "who", "why", "with",
        }

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        tokens = re.findall(r"[a-z0-9_]+", str(text).lower())
        return [token for token in tokens if len(token) > 1]

    @staticmethod
    def _hit_key(hit: Dict[str, Any]) -> str:
        metadata = hit.get("metadata") or {}
        return str(
            metadata.get("chunk_id")
            or hit.get("id")
            or hit.get("text")
            or ""
        )

    @staticmethod
    def _dense_similarity(distance: Any) -> float:
        try:
            numeric = float(distance)
        except (TypeError, ValueError):
            return 0.0

        if numeric < 0:
            return 0.0
        if numeric <= 1.0:
            return max(0.0, 1.0 - numeric)
        return 1.0 / (1.0 + numeric)

    def _query_keywords(self, query: str) -> List[str]:
        tokens = self._tokenize(query)
        keywords = [token for token in tokens if token not in self.stopwords]
        return keywords or tokens

    def _is_synthesis_query(self, query: str) -> bool:
        lowered = str(query or "").lower()
        triggers = (
            "both",
            "compare",
            "comparison",
            "common",
            "difference",
            "different",
            "documents",
            "summarize both",
            "what are these documents about",
        )
        return any(trigger in lowered for trigger in triggers)

    @staticmethod
    def _source_key(hit: Dict[str, Any]) -> str:
        metadata = hit.get("metadata") or {}
        return str(metadata.get("doc_id") or metadata.get("source") or "")

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

    def _quality_penalty_factor(
        self,
        hit: Dict[str, Any],
        low_quality_chunk_ids: Optional[Set[str]],
        low_quality_sources: Optional[Set[str]],
        preferred_chunk_ids: Optional[Set[str]] = None,
    ) -> float:
        metadata = hit.get("metadata") or {}
        chunk_id = str(metadata.get("chunk_id") or hit.get("id") or "")
        source = str(metadata.get("source") or "")
        if preferred_chunk_ids and chunk_id in preferred_chunk_ids:
            return 1.12
        if low_quality_chunk_ids and chunk_id in low_quality_chunk_ids:
            return 0.82
        if low_quality_sources and source in low_quality_sources:
            return 0.88
        return 1.0

    def _dedupe_hits(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for hit in hits:
            text = re.sub(r"\s+", " ", str(hit.get("text") or "")).strip().lower()
            if not text:
                continue
            metadata = hit.get("metadata") or {}
            fingerprint = str(metadata.get("chunk_id") or hit.get("id") or text[:220])
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            deduped.append(hit)
        return deduped

    def _apply_quality_penalties(
        self,
        hits: List[Dict[str, Any]],
        low_quality_chunk_ids: Optional[Set[str]],
        low_quality_sources: Optional[Set[str]],
        preferred_chunk_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        adjusted_hits: List[Dict[str, Any]] = []
        for hit in hits:
            cloned = dict(hit)
            penalty_factor = self._quality_penalty_factor(
                cloned,
                low_quality_chunk_ids,
                low_quality_sources,
                preferred_chunk_ids,
            )
            cloned["quality_penalty_factor"] = penalty_factor
            cloned["adjusted_score"] = float(cloned.get("score", 0.0)) * penalty_factor
            adjusted_hits.append(cloned)
        adjusted_hits.sort(key=lambda item: item.get("adjusted_score", item.get("score", 0.0)), reverse=True)
        return adjusted_hits

    def _prune_candidates(self, hits: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        pruned = self._dedupe_hits(hits)
        if not pruned:
            return []

        filtered: List[Dict[str, Any]] = []
        for index, hit in enumerate(pruned):
            adjusted_score = float(hit.get("adjusted_score", hit.get("score", 0.0)) or 0.0)
            if index < max(limit, 3) or adjusted_score >= 0.01:
                filtered.append(hit)
        return filtered[:limit]

    def _resolve_weight_profile(self, answer_mode: str) -> tuple[float, float]:
        normalized = str(answer_mode or "").strip().lower()
        if normalized == "benchmark_mode":
            bm25_weight = max(0.25, self.bm25_weight - 0.05)
            dense_weight = min(0.75, self.dense_weight + 0.05)
            return bm25_weight, dense_weight
        return self.bm25_weight, self.dense_weight

    def _rebalance_for_document_coverage(
        self,
        hits: List[Dict[str, Any]],
        top_k: int,
        document_ids: Optional[List[str]],
        synthesis_mode: bool,
    ) -> List[Dict[str, Any]]:
        if not hits:
            return []
        if not synthesis_mode or not document_ids or len(document_ids) < 2:
            return hits[:top_k]

        by_doc: Dict[str, List[Dict[str, Any]]] = {}
        ordered_docs: List[str] = []
        for hit in hits:
            source_key = self._source_key(hit)
            if source_key not in by_doc:
                by_doc[source_key] = []
                ordered_docs.append(source_key)
            by_doc[source_key].append(hit)

        selected: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for doc_id in document_ids:
            for candidate in by_doc.get(doc_id, []):
                hit_key = self._hit_key(candidate)
                if hit_key in seen:
                    continue
                selected.append(candidate)
                seen.add(hit_key)
                break

        for source_key in ordered_docs:
            if len(selected) >= top_k:
                break
            if source_key in document_ids:
                continue
            for candidate in by_doc.get(source_key, []):
                hit_key = self._hit_key(candidate)
                if hit_key in seen:
                    continue
                selected.append(candidate)
                seen.add(hit_key)
                break

        for candidate in hits:
            if len(selected) >= top_k:
                break
            hit_key = self._hit_key(candidate)
            if hit_key in seen:
                continue
            selected.append(candidate)
            seen.add(hit_key)

        return selected[:top_k]

    def search(
        self,
        user_id: str,
        subject: str,
        query: str,
        top_k: int = 6,
        document_ids: List[str] = None,
        low_quality_chunk_ids: Optional[List[str]] = None,
        low_quality_sources: Optional[List[str]] = None,
        preferred_chunk_ids: Optional[List[str]] = None,
        synthesis_mode: bool = False,
        scope_mode: str = "auto",
        answer_mode: str = "live_tutor_mode",
    ) -> List[Dict]:
        """
        Performs Hybrid Search. 
        If document_ids is provided, strictly scopes search to those documents.
        """
        normalized_scope = str(scope_mode or "auto").strip().lower()
        if normalized_scope not in {"auto", "document_scoped", "system_only"}:
            normalized_scope = "auto"

        # 1. FETCH CHUNKS (User + System)
        if document_ids or normalized_scope == "document_scoped":
            # STRICT MODE: Only search the specific documents
            scoped_doc_ids = list(document_ids or [])
            if not scoped_doc_ids:
                print("DEBUG: Document-scoped search requested without document_ids.")
                return []
            where_clause = {"doc_id": {"$in": scoped_doc_ids}} if len(scoped_doc_ids) > 1 else {"doc_id": scoped_doc_ids[0]}
            user_chunks = get_all_chunks(user_id, subject, where=where_clause)
            all_docs = user_chunks # Ignore system chunks
            print(f"DEBUG: Scoped search for docs {scoped_doc_ids}. Found {len(all_docs)} candidate chunks.")
        elif normalized_scope == "system_only":
            all_docs = get_all_chunks(self.system_id, "general")
            print(f"DEBUG: System-only search. Found {len(all_docs)} candidate chunks.")
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
        benchmark_mode = str(answer_mode or "").strip().lower() == "benchmark_mode"
        initial_k = max(top_k * 8, top_k + 12)
        if benchmark_mode:
            initial_k = max(top_k * 10, top_k + 16)

        # 2. BM25 SEARCH (Keyword)
        bm25_results = self._bm25_search(query, all_docs, initial_k)

        # 3. VECTOR SEARCH (Semantic)
        query_vec = embedding_service.embed_text(query)
        
        if document_ids or normalized_scope == "document_scoped":
            # Scoped Vector Search
            scoped_doc_ids = list(document_ids or [])
            if not scoped_doc_ids:
                return []
            where_clause = {"doc_id": {"$in": scoped_doc_ids}} if len(scoped_doc_ids) > 1 else {"doc_id": scoped_doc_ids[0]}
            all_vec_results = query_user_collection(user_id, subject, query_vec, initial_k, where=where_clause)
        elif normalized_scope == "system_only":
            all_vec_results = query_user_collection(self.system_id, "general", query_vec, initial_k)
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
        bm25_weight, dense_weight = self._resolve_weight_profile(answer_mode)
        rrf_results = self._rrf_fusion(
            bm25_results,
            all_vec_results,
            initial_k,
            bm25_weight=bm25_weight,
            dense_weight=dense_weight,
        )
        penalized_results = self._apply_quality_penalties(
            rrf_results,
            low_quality_chunk_ids=set(low_quality_chunk_ids or []),
            low_quality_sources=set(low_quality_sources or []),
            preferred_chunk_ids=set(preferred_chunk_ids or []),
        )
        candidate_results = self._prune_candidates(
            penalized_results,
            max(top_k * 4, top_k + (4 if benchmark_mode else 6)),
        )
        if synthesis_mode or self._is_synthesis_query(query):
            synthesis_pool = max(top_k * 6, top_k + 10, max(len(document_ids or []), 1) * 4)
            if benchmark_mode:
                synthesis_pool = max(synthesis_pool, top_k * 7, top_k + 12)
            candidate_results = self._prune_candidates(penalized_results, synthesis_pool)

        # 5. RERANKING
        if self._ensure_reranker() and candidate_results:
            rerank_limit = (
                max(top_k * 3, top_k + 6, max(len(document_ids or []), 1) * 3)
                if synthesis_mode or self._is_synthesis_query(query)
                else top_k
            )
            if benchmark_mode:
                rerank_limit = max(rerank_limit, top_k + 2)
            final_results = self._rerank_results(query, candidate_results, rerank_limit)
        else:
            fallback_limit = (
                max(top_k * 3, top_k + 6, max(len(document_ids or []), 1) * 3)
                if synthesis_mode or self._is_synthesis_query(query)
                else top_k
            )
            if benchmark_mode:
                fallback_limit = max(fallback_limit, top_k + 2)
            final_results = candidate_results[:fallback_limit]

        final_results = self._rebalance_for_document_coverage(
            final_results,
            top_k=top_k,
            document_ids=document_ids,
            synthesis_mode=synthesis_mode or self._is_synthesis_query(query),
        )

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
            rerank_confidence = 1 / (1 + pow(2.718281828, -doc["rerank_score"]))
            support_score = min(1.0, float(doc.get("adjusted_score", doc.get("score", 0.0)) or 0.0) * 25)
            penalty_factor = float(doc.get("quality_penalty_factor", 1.0) or 1.0)
            doc["final_rank_score"] = (rerank_confidence * penalty_factor) + (support_score * 0.12)
            
        # Sort by final rank score descending
        reranked = sorted(documents, key=lambda x: x.get("final_rank_score", x["rerank_score"]), reverse=True)
        
        return self._dedupe_hits(reranked)[:top_k]

    def _bm25_search(self, query: str, documents: List[Dict], top_k: int) -> List[Dict]:
        if not documents: return []
        
        corpus = [d["text"] for d in documents]
        tokenized_corpus = [self._tokenize(doc) for doc in corpus]
        tokenized_query = self._query_keywords(query)
        
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(tokenized_query)
        
        results = []
        positive_scores = [score for score in scores if score > 0]
        min_score = 0.0
        if positive_scores:
            ranked_scores = sorted(positive_scores, reverse=True)
            pivot_index = min(len(ranked_scores) - 1, max(top_k * 2, 3) - 1)
            min_score = max(0.05, ranked_scores[pivot_index] * 0.15)

        for i, score in enumerate(scores):
            if score >= min_score:
                results.append({
                    "id": documents[i].get("id"),
                    "text": documents[i]["text"],
                    "metadata": documents[i]["metadata"],
                    "score": score,
                    "type": "bm25"
                })
        
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    def _rrf_fusion(
        self,
        bm25_hits: List[Dict],
        dense_hits: List[Dict],
        top_k: int,
        bm25_weight: Optional[float] = None,
        dense_weight: Optional[float] = None,
    ) -> List[Dict]:
        k = 60
        scores = {}
        chunk_map = {}
        source_counter = Counter()
        resolved_bm25_weight = self.bm25_weight if bm25_weight is None else bm25_weight
        resolved_dense_weight = self.dense_weight if dense_weight is None else dense_weight

        # Process BM25
        for rank, hit in enumerate(bm25_hits):
            key = self._hit_key(hit)
            if not key:
                continue
            chunk_map[key] = hit
            scores[key] = scores.get(key, 0) + (resolved_bm25_weight / (k + rank + 1))
            source_counter[str((hit.get("metadata") or {}).get("source") or "")] += 1

        # Process Dense
        for rank, hit in enumerate(dense_hits):
            key = self._hit_key(hit)
            if not key:
                continue
            chunk_map[key] = hit
            scores[key] = scores.get(key, 0) + (resolved_dense_weight / (k + rank + 1))
            source_counter[str((hit.get("metadata") or {}).get("source") or "")] += 1

        sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        
        fused_results = []
        for key in sorted_keys[:top_k]:
            hit = chunk_map[key]
            hit["score"] = scores[key]
            source_name = str((hit.get("metadata") or {}).get("source") or "")
            hit["source_frequency"] = source_counter.get(source_name, 0)
            fused_results.append(hit)
            
        return fused_results

search_engine = HybridSearchEngine()
