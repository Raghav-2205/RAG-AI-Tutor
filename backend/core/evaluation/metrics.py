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

JUDGE_FAILURE_PREFIXES = (
    "llm async request failed",
    "llm request failed",
    "llm api error",
    "error: no gemini api key",
)
JUDGE_JSON_SYSTEM_PROMPT = (
    "You are a deterministic evaluation bot. Return only one valid JSON object and no markdown."
)

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


def _strip_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _strip_inline_chunk_citations(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\[CHUNK\s*\d+\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned.strip()


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    cleaned = _strip_code_fences(text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        start = match.start()
        try:
            payload, _ = decoder.raw_decode(cleaned[start:])
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            continue
    return None


def _repair_nearly_valid_json(text: str) -> Optional[Dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    if not cleaned:
        return None
    truncated = cleaned.strip()
    if truncated.count("{") > truncated.count("}"):
        truncated += "}" * (truncated.count("{") - truncated.count("}"))
    payload = _extract_first_json_object(truncated)
    if payload is not None:
        return payload
    for end_token in ('"]', '"]}', '"}', "]}", "}"):
        idx = truncated.rfind(end_token)
        if idx == -1:
            continue
        candidate = truncated[: idx + len(end_token)]
        if candidate.count("{") > candidate.count("}"):
            candidate += "}" * (candidate.count("{") - candidate.count("}"))
        payload = _extract_first_json_object(candidate)
        if payload is not None:
            return payload
    return None


async def _run_json_judge(prompt: str) -> tuple[Optional[Dict[str, Any]], int]:
    parse_failure_count = 0
    for attempt in range(2):
        response = await llm_client.async_generate(
            prompt,
            system_prompt=JUDGE_JSON_SYSTEM_PROMPT,
            temperature=0.0,
        )
        payload = _extract_first_json_object(response)
        if payload is not None:
            return payload, parse_failure_count
        repaired_payload = _repair_nearly_valid_json(response)
        if repaired_payload is not None:
            logger.warning(
                "Judge returned truncated or noisy JSON on attempt %s; repaired payload successfully.",
                attempt + 1,
            )
            return repaired_payload, parse_failure_count + 1
        parse_failure_count += 1
        logger.warning(
            "Judge returned malformed JSON on attempt %s: %s",
            attempt + 1,
            _strip_code_fences(response)[:400],
        )
    return None, parse_failure_count


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


def calculate_retrieval_confidence(
    chunks: List[Dict],
    has_graph_context: bool = False,
    graph_support: float = 0.0,
    document_coverage: float = 0.0,
) -> float:
    """
    Calculate confidence based on retrieval scores (Rerank or RRF).
    Normalize to 0.0 - 1.0 range.
    """
    if not chunks and not has_graph_context:
        return 0.0
        
    # If we have graph context, it's a strong signal of relationship discovery
    base_boost = 0.1 if has_graph_context else 0.0
    graph_bonus = min(0.2, max(0.0, graph_support) * 0.2)
    document_bonus = min(0.15, max(0.0, document_coverage) * 0.15)
        
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
        return min(1.0, base_boost + graph_bonus + document_bonus) if has_graph_context else 0.0
        
    return float(min(1.0, np.mean(scores) + base_boost + graph_bonus + document_bonus))



def calculate_chunk_coverage(
    answer: str,
    chunks: List[Dict],
    graph_facts: Optional[List[str]] = None,
    expected_sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Calculate what % of the answer is covered by the retrieved chunks.
    Metric: token overlap
    """
    if not answer.strip() or (not chunks and not graph_facts):
        return {
            "covered_ratio": 0.0,
            "used_chunk_indices": [],
            "graph_fact_support_ratio": 0.0,
            "document_coverage_balance": 0.0,
        }
        
    answer_tokens = set(re.findall(r"[a-z0-9_]+", answer.lower()))
    if not answer_tokens:
        return {
            "covered_ratio": 0.0,
            "used_chunk_indices": [],
            "graph_fact_support_ratio": 0.0,
            "document_coverage_balance": 0.0,
        }
        
    total_tokens = len(answer_tokens)
    covered_tokens = set()
    used_indices = []
    used_sources = set()
    graph_tokens = set()
    
    for i, c in enumerate(chunks):
        chunk_text = c.get("text", "").lower()
        chunk_tokens = set(re.findall(r"[a-z0-9_]+", chunk_text))
        
        overlap = answer_tokens.intersection(chunk_tokens)
        if overlap:
            covered_tokens.update(overlap)
            if len(overlap) > 2:
                used_indices.append(i)
                source_name = str((c.get("metadata") or {}).get("source") or "")
                if source_name:
                    used_sources.add(source_name)

    for fact in graph_facts or []:
        graph_tokens.update(set(re.findall(r"[a-z0-9_]+", str(fact).lower())))

    graph_overlap = answer_tokens.intersection(graph_tokens)
    expected_source_list = [source for source in (expected_sources or []) if source]
    if expected_source_list:
        source_balance = len(used_sources.intersection(expected_source_list)) / len(set(expected_source_list))
    elif used_sources:
        source_balance = 1.0
    else:
        source_balance = 0.0
                
    ratio = len(covered_tokens) / total_tokens
    graph_fact_support_ratio = len(graph_overlap) / total_tokens if total_tokens else 0.0
    
    return {
        "covered_ratio": round(ratio, 2),
        "used_chunk_indices": used_indices,
        "graph_fact_support_ratio": round(graph_fact_support_ratio, 2),
        "document_coverage_balance": round(source_balance, 2),
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
            "unsupported_sentences": [],
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    answer_text = str(answer or "").strip().lower()
    if any(answer_text.startswith(prefix) for prefix in JUDGE_FAILURE_PREFIXES):
        return {
            "faithfulness_score": 0.0,
            "reasoning": "Answer generation failed before faithfulness judgment could be computed.",
            "unsupported_sentences": [],
            "judge_available": False,
            "judge_fallback_used": True,
            "parse_failure_count": 0,
        }

    answer_without_citations = _strip_inline_chunk_citations(answer)

    prompt = f"""You are a strict grounded-answer judge.
Review the ANSWER against the CONTEXT and grade only the support provided by the context.
Ignore inline citation markers such as [CHUNK 1] and judge only the substantive claims.

CONTEXT:
{context}

ANSWER:
{answer_without_citations}

Return JSON only:
{{
  "score": <float 0.0-1.0>,
  "total_sentences": <int>,
  "supported_count": <int>,
  "reasoning": "<brief explanation, one sentence max>",
  "unsupported_sentences": ["<sentence 1>", "<sentence 2>"]
}}
The score is supported_count / total_sentences."""

    try:
        data, parse_failures = await _run_json_judge(prompt)
        if data is None:
            return {
                "faithfulness_score": 0.5,
                "reasoning": "Faithfulness judge returned malformed JSON.",
                "unsupported_sentences": [],
                "judge_available": False,
                "judge_fallback_used": True,
                "parse_failure_count": parse_failures,
            }

        return {
            "faithfulness_score": float(data.get("score", 0.0)),
            "reasoning": data.get("reasoning", "No reasoning provided"),
            "unsupported_sentences": data.get("unsupported_sentences", []),
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": parse_failures,
        }
    except Exception as e:
        logger.error(f"Faithfulness check failed: {e}")
        return {
            "faithfulness_score": 0.5,
            "reasoning": f"Evaluation error: {str(e)}",
            "unsupported_sentences": [],
            "judge_available": False,
            "judge_fallback_used": True,
            "parse_failure_count": 0,
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
    citation_pattern = re.compile(r'\[CHUNK\s*(\d+)\]', re.IGNORECASE)
    citations_found = citation_pattern.findall(answer)

    if not citations_found:
        return 1.0

    if not retrieved_chunks:
        return 0.0

    model = get_embedding_model()
    if not model:
        valid = sum(1 for c in citations_found if 1 <= int(c) <= len(retrieved_chunks))
        return valid / len(citations_found) if citations_found else 1.0

    sentences = re.split(r'(?<=[.!?])\s+', answer)

    scores = []
    for sentence in sentences:
        sentence_citations = citation_pattern.findall(sentence)
        if not sentence_citations:
            continue

        valid_chunk_texts: List[str] = []
        valid_citation_count = 0
        for citation_num_str in sentence_citations:
            chunk_idx = int(citation_num_str) - 1
            if 0 <= chunk_idx < len(retrieved_chunks):
                chunk_text = str(retrieved_chunks[chunk_idx].get("text", "") or "").strip()
                if chunk_text:
                    valid_citation_count += 1
                    valid_chunk_texts.append(chunk_text)

        if not valid_chunk_texts:
            scores.append(0.0)
            continue

        substantive_sentence = _strip_inline_chunk_citations(sentence)
        if not substantive_sentence:
            scores.append(valid_citation_count / len(sentence_citations))
            continue

        try:
            emb_sent = model.encode(substantive_sentence, convert_to_tensor=True)
            similarities = []
            for chunk_text in valid_chunk_texts:
                emb_chunk = model.encode(chunk_text, convert_to_tensor=True)
                similarities.append(float(util.pytorch_cos_sim(emb_sent, emb_chunk).item()))
            support_score = max(similarities) if similarities else 0.0
            validity_ratio = valid_citation_count / len(sentence_citations)
            scores.append(min(1.0, max(0.0, support_score)) * validity_ratio)
        except Exception:
            scores.append(0.5)

    return sum(scores) / len(scores) if scores else 1.0


# ═══════════════════════════════════════════════
#  GROUP 5 — ANSWER RELEVANCE (LLM-as-Judge)
# ═══════════════════════════════════════════════

async def calculate_answer_relevance(question: str, answer: str) -> Dict[str, Any]:
    """
    LLM-as-Judge: How well does the answer address the question?
    Returns a score from 0.0 to 1.0.
    """
    answer_text = str(answer or "").strip().lower()
    if any(answer_text.startswith(prefix) for prefix in JUDGE_FAILURE_PREFIXES):
        return {
            "relevance_score": 0.0,
            "reasoning": "Answer generation failed before relevance evaluation.",
            "judge_available": False,
            "judge_fallback_used": True,
            "parse_failure_count": 0,
        }

    answer_without_citations = _strip_inline_chunk_citations(answer)

    prompt = f"""You are a strict relevance judge.
Rate how well the ANSWER addresses the QUESTION.
Ignore inline citation markers such as [CHUNK 1] and judge only the substantive answer.

QUESTION:
{question}

ANSWER:
{answer_without_citations}

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
        data, parse_failures = await _run_json_judge(prompt)
        if data is None:
            return {
                "relevance_score": 0.5,
                "reasoning": "Relevance judge returned malformed JSON.",
                "judge_available": False,
                "judge_fallback_used": True,
                "parse_failure_count": parse_failures,
            }
        return {
            "relevance_score": float(data.get("relevance_score", 0.5)),
            "reasoning": data.get("reasoning", "No reasoning provided"),
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": parse_failures,
        }
    except Exception as e:
        logger.error(f"Answer relevance check failed: {e}")
        return {
            "relevance_score": 0.5,
            "reasoning": f"Evaluation error: {str(e)}",
            "judge_available": False,
            "judge_fallback_used": True,
            "parse_failure_count": 0,
        }


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
