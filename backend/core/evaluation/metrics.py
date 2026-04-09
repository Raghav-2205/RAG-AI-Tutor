# backend/core/evaluation/metrics.py
"""
Production-grade RAG evaluation metrics.

Metric Groups:
  1. Retrieval Quality: Recall@K, Precision@K, MRR
  2. Faithfulness & Groundedness: LLM-as-Judge faithfulness, hallucination rate
  3. Semantic Accuracy: BERTScore, Cosine Similarity
  4. Citation Validation: citation alignment
  5. Answer Relevance: LLM-as-Judge relevance scoring
  6. Composite: Final RAG Score (weighted)
"""

import logging
import re
import json
from typing import List, Dict, Any, Optional
import numpy as np

try:
    from bert_score import score as bert_score_fn
except ImportError:
    bert_score_fn = None

from sentence_transformers import SentenceTransformer, util
from backend.core.llm_interface import llm_client

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Singleton embedding model (reused across calls)
# ──────────────────────────────────────────────
_embedding_model = None


def get_evaluation_chunk_id(chunk: Dict[str, Any]) -> str:
    """
    Resolve the stable chunk identity used for evaluation.

    Retrieved chunks carry the Chroma collection ID in `id`, but the original
    ingestion chunk ID is preserved in `metadata.chunk_id`. Benchmark datasets
    are written against that original chunk identity.
    """
    if not isinstance(chunk, dict):
        return ""

    metadata = chunk.get("metadata") or {}
    for candidate in (
        metadata.get("chunk_id"),
        chunk.get("chunk_id"),
        chunk.get("id"),
    ):
        if candidate:
            return str(candidate)
    return ""

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        last_error = None
        for kwargs in ({"local_files_only": True}, {}):
            try:
                _embedding_model = SentenceTransformer('all-MiniLM-L6-v2', **kwargs)
                break
            except Exception as e:
                last_error = e
        if _embedding_model is None:
            logger.error(f"Failed to load embedding model: {last_error}")
    return _embedding_model


# ═══════════════════════════════════════════════
#  GROUP 1 — RETRIEVAL QUALITY
# ═══════════════════════════════════════════════

def calculate_retrieval_metrics(
    retrieved_ids: List[str],
    gold_chunk_ids: List[str],
    k_list: List[int] = [3, 5, 10]
) -> Dict[str, float]:
    """
    Compute Recall@K, Precision@K, and MRR.
    Used primarily during benchmark evaluation when gold_chunk_ids are available.
    """
    retrieved = [str(item) for item in retrieved_ids if item]
    gold = [str(item) for item in gold_chunk_ids if item]
    metrics = {}

    # MRR — Mean Reciprocal Rank
    mrr = 0.0
    for i, rid in enumerate(retrieved):
        if rid in gold:
            mrr = 1.0 / (i + 1)
            break
    metrics["mrr"] = mrr

    # Recall & Precision @ K
    gold_set = set(gold)
    for k in k_list:
        top_k = set(retrieved[:k])
        intersection = top_k.intersection(gold_set)

        recall = len(intersection) / len(gold_set) if gold_set else 0.0
        precision = len(intersection) / k if k > 0 else 0.0

        metrics[f"recall@{k}"] = recall
        metrics[f"precision@{k}"] = precision

    return metrics


def calculate_retrieval_confidence(chunks: List[Dict], has_graph_context: bool = False) -> float:
    """
    Calculate confidence based on retrieval scores (Rerank or RRF).
    Normalize to 0.0 - 1.0 range.
    """
    if not chunks and not has_graph_context:
        return 0.0
        
    # If we have graph context, it's a strong signal of relationship discovery
    base_boost = 0.2 if has_graph_context else 0.0
        
    scores = []
    for c in chunks:
        r_score = c.get("rerank_score")
        if r_score is not None:
            # Sigmoid normalization for logits
            norm = 1 / (1 + np.exp(-r_score))
            scores.append(norm)
        else:
            # RRF or BM25 scores (usually > 0, small)
            # Rough heuristic
            s = c.get("score", 0.0)
            scores.append(min(1.0, s * 5)) # Boost RRF scores
            
    if not scores:
        return base_boost if has_graph_context else 0.0
        
    return float(min(1.0, np.mean(scores) + base_boost))



def calculate_chunk_coverage(answer: str, chunks: List[Dict]) -> Dict[str, Any]:
    """
    Calculate what % of the answer is covered by the retrieved chunks.
    Metric: token overlap
    """
    if not answer.strip() or not chunks:
        return {"covered_ratio": 0.0, "used_chunks": []}
        
    answer_tokens = set(answer.lower().split())
    if not answer_tokens:
        return {"covered_ratio": 0.0, "used_chunks": []}
        
    total_tokens = len(answer_tokens)
    covered_tokens = set()
    used_indices = []
    
    for i, c in enumerate(chunks):
        chunk_text = c.get("text", "").lower()
        chunk_tokens = set(chunk_text.split())
        
        overlap = answer_tokens.intersection(chunk_tokens)
        if overlap:
            covered_tokens.update(overlap)
            if len(overlap) > 2: # Heuristic: at least 3 common words to count as "used"
                used_indices.append(i)
                
    ratio = len(covered_tokens) / total_tokens
    
    return {
        "covered_ratio": round(ratio, 2),
        "used_chunk_indices": used_indices
    }


# ═══════════════════════════════════════════════
#  GROUP 2 — FAITHFULNESS & GROUNDEDNESS
# ═══════════════════════════════════════════════

async def calculate_faithfulness(answer: str, context: str) -> Dict[str, Any]:
    """
    LLM-as-Judge: verify if every sentence in the answer is supported by the context.
    Returns faithfulness_score (0.0–1.0), reasoning, and unsupported_sentences.
    """
    if not context.strip():
        return {
            "faithfulness_score": 0.0,
            "reasoning": "No context provided for faithfulness check.",
            "unsupported_sentences": []
        }

    prompt = f"""You are a strict fact-checking judge.
Review the following ANSWER and CONTEXT.
Determine if every sentence in the ANSWER is supported by the CONTEXT.

CONTEXT:
{context}

ANSWER:
{answer}

INSTRUCTIONS:
1. Break the answer into individual sentences.
2. For each sentence, classify it as "Supported", "Contradicted", or "Unsupported" (information not found in context).
3. Calculate score = number_of_supported_sentences / total_sentences.

OUTPUT FORMAT (JSON only, no markdown):
{{
  "score": <float 0.0-1.0>,
  "total_sentences": <int>,
  "supported_count": <int>,
  "reasoning": "<brief explanation>",
  "unsupported_sentences": ["<sentence 1>", "<sentence 2>"]
}}
JSON ONLY. NO MARKDOWN."""

    try:
        response = await llm_client.async_generate(
            prompt,
            system_prompt="You are a JSON-only evaluation bot. Return valid JSON with no markdown formatting.",
            temperature=0.0
        )
        clean_resp = re.sub(r'```json\s*|\s*```', '', response).strip()
        data = json.loads(clean_resp)

        return {
            "faithfulness_score": float(data.get("score", 0.0)),
            "reasoning": data.get("reasoning", "No reasoning provided"),
            "unsupported_sentences": data.get("unsupported_sentences", [])
        }
    except Exception as e:
        logger.error(f"Faithfulness check failed: {e}")
        return {
            "faithfulness_score": 0.5,
            "reasoning": f"Evaluation error: {str(e)}",
            "unsupported_sentences": []
        }


# ═══════════════════════════════════════════════
#  GROUP 3 — SEMANTIC ACCURACY
# ═══════════════════════════════════════════════

def calculate_bert_score(answer: str, reference: str) -> float:
    """
    Compute BERTScore F1 between generated answer and reference text.
    Uses distilbert-base-uncased for speed.
    """
    if not bert_score_fn:
        logger.warning("bert_score library not installed. Returning 0.0")
        return 0.0

    if not answer.strip() or not reference.strip():
        return 0.0

    try:
        P, R, F1 = bert_score_fn(
            [answer], [reference],
            lang="en",
            verbose=False,
            model_type="distilbert-base-uncased"
        )
        return float(F1.mean())
    except Exception as e:
        logger.error(f"BERTScore failed: {e}")
        return 0.0


def calculate_cosine_similarity(text1: str, text2: str) -> float:
    """
    Compute cosine similarity between two texts using sentence embeddings (all-MiniLM-L6-v2).
    """
    model = get_embedding_model()
    if not model:
        return 0.0

    if not text1.strip() or not text2.strip():
        return 0.0

    try:
        emb1 = model.encode(text1, convert_to_tensor=True)
        emb2 = model.encode(text2, convert_to_tensor=True)
        score = util.pytorch_cos_sim(emb1, emb2)
        return float(score.item())
    except Exception as e:
        logger.error(f"Cosine similarity failed: {e}")
        return 0.0


# ═══════════════════════════════════════════════
#  GROUP 4 — CITATION VALIDATION
# ═══════════════════════════════════════════════

def calculate_citation_alignment(
    answer: str,
    retrieved_chunks: List[Dict],
) -> float:
    """
    Validate citations in the answer:
    1. Parse [CHUNK N] references from the answer text.
    2. For each cited chunk, verify it exists in the retrieved set.
    3. Compute semantic similarity between the citing sentence and the cited chunk.

    Returns a score from 0.0 to 1.0.
    If no citations found in the answer, returns 1.0 (no citations to misalign).
    """
    # Parse all [CHUNK N] references
    citation_pattern = re.compile(r'\[CHUNK\s*(\d+)\]', re.IGNORECASE)
    citations_found = citation_pattern.findall(answer)

    if not citations_found:
        # No citations in answer — nothing to validate
        return 1.0

    if not retrieved_chunks:
        # Citations exist but no chunks available — all invalid
        return 0.0

    model = get_embedding_model()
    if not model:
        # Fallback: just check existence
        valid = sum(1 for c in citations_found if 1 <= int(c) <= len(retrieved_chunks))
        return valid / len(citations_found) if citations_found else 1.0

    # Split answer into sentences for context-aware validation
    sentences = re.split(r'(?<=[.!?])\s+', answer)

    scores = []
    for citation_num_str in citations_found:
        chunk_idx = int(citation_num_str) - 1  # Convert 1-indexed to 0-indexed

        # Check if cited chunk exists
        if chunk_idx < 0 or chunk_idx >= len(retrieved_chunks):
            scores.append(0.0)
            continue

        chunk_text = retrieved_chunks[chunk_idx].get("text", "")
        if not chunk_text.strip():
            scores.append(0.0)
            continue

        # Find the sentence containing this citation
        citing_sentence = ""
        citation_ref = f"[CHUNK {citation_num_str}]"
        for sent in sentences:
            if citation_ref.lower() in sent.lower() or f"chunk {citation_num_str}" in sent.lower():
                citing_sentence = sent
                break

        if not citing_sentence:
            # Citation exists, chunk exists — give partial credit
            scores.append(0.7)
            continue

        # Semantic similarity between citing sentence and cited chunk
        try:
            emb_sent = model.encode(citing_sentence, convert_to_tensor=True)
            emb_chunk = model.encode(chunk_text, convert_to_tensor=True)
            sim = float(util.pytorch_cos_sim(emb_sent, emb_chunk).item())
            # Normalize: sim > 0.5 is good alignment
            scores.append(min(1.0, max(0.0, sim)))
        except Exception:
            scores.append(0.5)

    return sum(scores) / len(scores) if scores else 1.0


# ═══════════════════════════════════════════════
#  GROUP 5 — ANSWER RELEVANCE (LLM-as-Judge)
# ═══════════════════════════════════════════════

async def calculate_answer_relevance(question: str, answer: str) -> float:
    """
    LLM-as-Judge: How well does the answer address the question?
    Returns a score from 0.0 to 1.0.
    """
    prompt = f"""You are a strict relevance judge.
Rate how well the ANSWER addresses the QUESTION.

QUESTION:
{question}

ANSWER:
{answer}

SCORING CRITERIA:
- 1.0: Answer fully and directly addresses the question with clear, accurate information
- 0.8: Answer mostly addresses the question with minor gaps
- 0.6: Answer partially addresses the question
- 0.4: Answer is tangentially related but misses the core question
- 0.2: Answer barely relates to the question
- 0.0: Answer is completely irrelevant or nonsensical

OUTPUT FORMAT (JSON only, no markdown):
{{
  "relevance_score": <float 0.0-1.0>,
  "reasoning": "<one sentence explanation>"
}}
JSON ONLY. NO MARKDOWN."""

    try:
        response = await llm_client.async_generate(
            prompt,
            system_prompt="You are a JSON-only evaluation bot. Return valid JSON with no markdown formatting.",
            temperature=0.0
        )
        clean_resp = re.sub(r'```json\s*|\s*```', '', response).strip()
        data = json.loads(clean_resp)
        return float(data.get("relevance_score", 0.5))
    except Exception as e:
        logger.error(f"Answer relevance check failed: {e}")
        return 0.5


# ═══════════════════════════════════════════════
#  GROUP 6 — COMPOSITE FINAL RAG SCORE
# ═══════════════════════════════════════════════

def calculate_final_rag_score(
    recall_at_5: Optional[float] = None,
    faithfulness: Optional[float] = None,
    bert_score_val: Optional[float] = None,
    citation_alignment: Optional[float] = None,
    answer_relevance: Optional[float] = None
) -> float:
    """
    Weighted final RAG score:
      0.25 * Recall@5
    + 0.25 * Faithfulness
    + 0.20 * BERTScore
    + 0.15 * Citation Alignment
    + 0.15 * Answer Relevance
    """
    weighted_components = [
        (0.25, recall_at_5),
        (0.25, faithfulness),
        (0.20, bert_score_val),
        (0.15, citation_alignment),
        (0.15, answer_relevance),
    ]

    active_components = [
        (weight, float(value))
        for weight, value in weighted_components
        if value is not None
    ]
    if not active_components:
        return 0.0

    weighted_sum = sum(weight * value for weight, value in active_components)
    total_weight = sum(weight for weight, _ in active_components)
    return round(weighted_sum / total_weight, 4)
