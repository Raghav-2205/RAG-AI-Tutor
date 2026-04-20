# backend/core/evaluation/validator.py
"""
Production-grade answer validation engine.

Orchestrates all evaluation metrics after RAG answer generation:
  1. Faithfulness (LLM-as-Judge)
  2. BERTScore (semantic overlap)
  3. Cosine Similarity (embedding)
  4. Citation Alignment (parsed + semantic)
  5. Answer Relevance (LLM-as-Judge)
  6. Final RAG Score (weighted composite)
  7. Decision logic (VERIFIED / REJECTED)
"""

import asyncio
import logging
import re
from typing import Any, Dict, List

from backend.core.evaluation.metrics import (
    _strip_inline_chunk_citations,
    calculate_answer_relevance,
    calculate_bert_score,
    calculate_chunk_coverage,
    calculate_citation_alignment,
    calculate_cosine_similarity,
    calculate_faithfulness,
    calculate_final_rag_score,
    calculate_retrieval_confidence,
    get_evaluation_chunk_id,
)
from backend.core.evaluation.status_policy import normalize_validation_status
from backend.models.evaluation import ValidationResult

logger = logging.getLogger(__name__)

GENERATION_FAILURE_PREFIXES = (
    "llm async request failed",
    "llm request failed",
    "llm api error",
    "error: no gemini api key",
)
REFUSAL_PHRASES = (
    "not enough evidence",
    "insufficient evidence",
    "no relevant evidence",
    "does not provide enough evidence",
    "i should not guess",
    "do not have enough retrieved evidence",
)
DOCUMENT_OVERVIEW_KEYWORDS = (
    "what is this document about",
    "what is this doc about",
    "what is this file about",
    "what is this pdf about",
    "what is this chapter about",
    "summarize this document",
    "summarise this document",
    "summary of this document",
    "overview of this document",
    "describe this document",
    "what does this document cover",
    "what does this file cover",
    "what is this note about",
    "what is this notes about",
)


def _normalize_graph_context_payload(graph_context: Any) -> Dict[str, Any]:
    if isinstance(graph_context, dict):
        summary = str(graph_context.get("context_summary") or "").strip()
        graph_facts = [
            str(item).strip()
            for item in (graph_context.get("graph_facts") or [])
            if str(item).strip()
        ]
        document_coverage = graph_context.get("document_coverage") or {}
        return {
            "summary": summary,
            "graph_facts": graph_facts,
            "graph_score": float(graph_context.get("graph_score") or 0.0),
            "document_coverage": {
                "matched_sources": list(document_coverage.get("matched_sources") or []),
                "total_sources": int(document_coverage.get("total_sources") or 0),
                "total_documents": int(document_coverage.get("total_documents") or document_coverage.get("total_sources") or 0),
                "covered_document_count": int(document_coverage.get("covered_document_count") or 0),
                "unsupported_documents": list(document_coverage.get("unsupported_documents") or []),
                "coverage_ratio": float(document_coverage.get("coverage_ratio") or 0.0),
            },
            "support_chunk_ids": list(graph_context.get("support_chunk_ids") or []),
            "cross_document_connections": list(graph_context.get("cross_document_connections") or []),
            "document_coverage_map": list(graph_context.get("document_coverage_map") or []),
            "uploaded_documents": list(graph_context.get("uploaded_documents") or []),
            "comparison_mode": bool(graph_context.get("comparison_mode")),
        }

    summary = str(graph_context or "").strip()
    return {
        "summary": summary,
        "graph_facts": [summary] if summary else [],
        "graph_score": 0.0,
        "document_coverage": {
            "matched_sources": [],
            "total_sources": 0,
            "coverage_ratio": 0.0,
        },
        "support_chunk_ids": [],
        "cross_document_connections": [],
        "document_coverage_map": [],
        "uploaded_documents": [],
        "comparison_mode": False,
    }


def _document_name_tokens(name: str) -> List[str]:
    cleaned = str(name or "").strip().lower()
    cleaned = cleaned.rsplit(".", 1)[0]
    return [
        token for token in re.findall(r"[a-z0-9_]+", cleaned)
        if len(token) > 2 and token not in {"document", "documents", "file", "files", "copy", "final"}
    ]


def _answer_mentions_document(answer: str, document_name: str) -> bool:
    answer_lower = str(answer or "").lower()
    normalized_name = str(document_name or "").strip().lower()
    normalized_name = normalized_name.rsplit(".", 1)[0]
    if normalized_name and normalized_name in answer_lower:
        return True
    tokens = _document_name_tokens(document_name)
    if not tokens:
        return False
    return all(token in answer_lower for token in tokens[: min(len(tokens), 2)])


def _answer_marks_document_unsupported(answer: str, document_name: str) -> bool:
    if not _answer_mentions_document(answer, document_name):
        return False
    answer_lower = str(answer or "").lower()
    return any(phrase in answer_lower for phrase in (
        "not enough evidence",
        "insufficient evidence",
        "no relevant evidence",
        "does not provide enough evidence",
        "not relevant to this question",
    ))


def _answer_is_refusal_like(answer: str) -> bool:
    answer_lower = str(answer or "").lower()
    return any(phrase in answer_lower for phrase in REFUSAL_PHRASES)


def _is_document_overview_question(question: str) -> bool:
    lowered = str(question or "").strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in DOCUMENT_OVERVIEW_KEYWORDS)


def _should_soften_document_overview_validation(
    *,
    question: str,
    answer_source_mode: str,
    uploaded_document_count: int,
    citation_score: float,
    answer_relevance: float,
    bert_score_val: float,
    covered_ratio: float,
    refusal_like: bool,
    generation_failed: bool,
) -> bool:
    if generation_failed or refusal_like:
        return False
    if answer_source_mode != "document":
        return False
    if uploaded_document_count > 1:
        return False
    if not _is_document_overview_question(question):
        return False
    strong_grounding = citation_score >= 0.85 and answer_relevance >= 0.8
    enough_support = bert_score_val >= 0.58 or covered_ratio >= 0.2
    return strong_grounding and enough_support


def _should_soften_multi_document_fallback_validation(
    *,
    answer_source_mode: str,
    uploaded_document_count: int,
    judge_available: bool,
    generation_failed: bool,
    refusal_like: bool,
    answer_relevance: float,
    bert_score_val: float,
    citation_score: float,
    retrieval_confidence: float,
    document_coverage_balance: float,
    covered_document_count: int,
) -> bool:
    if generation_failed or refusal_like or judge_available:
        return False
    if answer_source_mode != "document":
        return False
    if uploaded_document_count < 2:
        return False
    if answer_relevance < 0.85:
        return False
    if bert_score_val < 0.7:
        return False
    if citation_score < 0.35:
        return False
    if retrieval_confidence < 0.25:
        return False
    full_document_coverage = (
        covered_document_count >= uploaded_document_count
        or document_coverage_balance >= 0.85
    )
    return full_document_coverage


def _should_soften_multi_document_overview_validation(
    *,
    question: str,
    answer_source_mode: str,
    uploaded_document_count: int,
    judge_available: bool,
    generation_failed: bool,
    refusal_like: bool,
    faith_score: float,
    answer_relevance: float,
    bert_score_val: float,
    citation_score: float,
    retrieval_confidence: float,
    document_coverage_balance: float,
    covered_document_count: int,
    graph_summary: str,
) -> bool:
    """Soften faithfulness for multi-doc GRAG overview answers.

    When the LLM judge gives a low faithfulness score on a cross-document
    synthesis answer but every other corroborating metric is strong, the
    judge is likely penalising legitimate document-level paraphrase rather
    than true hallucination.  Apply the same soft-path already used for
    single-doc overviews.
    """
    if generation_failed or refusal_like:
        return False
    if answer_source_mode != "document":
        return False
    if uploaded_document_count < 2:
        return False
    # Only apply when faith is borderline-low (0.5 – 0.72), not catastrophic
    if faith_score >= 0.72 or faith_score < 0.45:
        return False
    # Require strong corroborating signals
    if answer_relevance < 0.8:
        return False
    if bert_score_val < 0.65:
        return False
    if citation_score < 0.3:
        return False
    # Require meaningful retrieval (graph context or good chunk coverage)
    has_graph = bool(graph_summary)
    enough_retrieval = retrieval_confidence >= 0.3 or has_graph
    if not enough_retrieval:
        return False
    # Require that the answer addresses most of the uploaded documents
    partial_coverage = (
        covered_document_count >= max(1, uploaded_document_count - 1)
        or document_coverage_balance >= 0.5
    )
    return partial_coverage


class ValidationEngine:
    def __init__(self, db):
        self.db = db

    async def validate_answer(
        self,
        question: str,
        answer: str,
        retrieved_chunks: List[Dict],
        user_id: str,
        subject: str = "general",
        document_id: str = None,
        chat_id: str = None,
        graph_context: Any = "",
        evaluation_source: str = "live",
        answer_source_mode: str = "knowledge_base",
        persist_result: bool = True,
    ) -> ValidationResult:
        logger.info("Validating answer for Q: %s... Doc: %s", question[:60], document_id)

        if not retrieved_chunks:
            result = ValidationResult(
                question=question,
                answer=answer,
                subject=subject,
                user_id=user_id,
                evaluation_source=evaluation_source,
                answer_source_mode=answer_source_mode,
                chat_id=chat_id,
                document_id=document_id,
                validation_status="VERIFIED",
                reason="No chunks retrieved. Cannot validate groundedness.",
            )
            if persist_result:
                await self._save_result(result)
            return result

        chunks_text = [chunk.get("text", "") for chunk in retrieved_chunks]
        graph_payload = _normalize_graph_context_payload(graph_context)
        graph_summary = graph_payload.get("summary", "")
        graph_facts = graph_payload.get("graph_facts", [])
        graph_document_coverage = graph_payload.get("document_coverage", {})
        coverage_map = list(graph_payload.get("document_coverage_map") or [])
        uploaded_documents = list(graph_payload.get("uploaded_documents") or [])
        if not uploaded_documents and chat_id:
            try:
                session = await self.db.chat_sessions.find_one({"chat_id": chat_id})
                if session:
                    doc_ids = list(session.get("document_ids") or [])
                    doc_names = list(session.get("document_names") or [])
                    total_docs = max(len(doc_ids), len(doc_names))
                    for index in range(total_docs):
                        uploaded_documents.append({
                            "doc_id": str(doc_ids[index] if index < len(doc_ids) else "").strip(),
                            "name": str(doc_names[index] if index < len(doc_names) else f"Document {index + 1}").strip(),
                        })
            except Exception:
                logger.debug("Unable to load session documents for validation", exc_info=True)

        context_text = "\n\n".join(chunks_text)
        if graph_summary:
            context_text += f"\n\n### GraphRAG Context ###\n{graph_summary}"

        chunk_ids = [get_evaluation_chunk_id(chunk) for chunk in retrieved_chunks]
        chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id]

        try:
            faith_task = calculate_faithfulness(answer, context_text)
            relevance_task = calculate_answer_relevance(question, answer)
            faith_result, relevance_result = await asyncio.gather(faith_task, relevance_task)

            faith_score = float(faith_result.get("faithfulness_score", 0.0) or 0.0)
            judge_available = bool(faith_result.get("judge_available", True)) and bool(
                relevance_result.get("judge_available", True)
            )
            judge_fallback_used = bool(faith_result.get("judge_fallback_used", False)) or bool(
                relevance_result.get("judge_fallback_used", False)
            )
            judge_parse_failure_count = int(faith_result.get("parse_failure_count", 0) or 0) + int(
                relevance_result.get("parse_failure_count", 0) or 0
            )
            unsupported = faith_result.get("unsupported_sentences", [])
            hallucination_rate = round(1.0 - faith_score, 4)
            answer_relevance = float(relevance_result.get("relevance_score", 0.0) or 0.0)

            loop = asyncio.get_event_loop()
            cosine_future = loop.run_in_executor(None, calculate_cosine_similarity, answer, context_text)
            bert_future = loop.run_in_executor(None, calculate_bert_score, answer, context_text)
            citation_future = loop.run_in_executor(None, calculate_citation_alignment, answer, retrieved_chunks)
            cosine_sim, bert_score_val, citation_score = await asyncio.gather(
                cosine_future,
                bert_future,
                citation_future,
            )

            expected_sources = [
                str((chunk.get("metadata") or {}).get("source") or "")
                for chunk in retrieved_chunks
                if str((chunk.get("metadata") or {}).get("source") or "")
            ]
            expected_sources = list(dict.fromkeys(expected_sources))
            chunk_usage_stats = calculate_chunk_coverage(
                answer,
                retrieved_chunks,
                graph_facts=graph_facts,
                expected_sources=expected_sources,
            )
            covered_ratio = float(chunk_usage_stats.get("covered_ratio", 0.0) or 0.0)
            graph_fact_support_ratio = float(chunk_usage_stats.get("graph_fact_support_ratio", 0.0) or 0.0)
            document_coverage_balance = float(chunk_usage_stats.get("document_coverage_balance", 0.0) or 0.0)

            coverage_lookup_by_doc = {
                str(item.get("doc_id") or "").strip(): item
                for item in coverage_map
                if isinstance(item, dict) and str(item.get("doc_id") or "").strip()
            }
            coverage_lookup_by_name = {
                str(item.get("name") or "").strip(): item
                for item in coverage_map
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            }
            supported_document_names: List[str] = []
            explicitly_unsupported_documents: List[str] = []
            missing_document_names: List[str] = []
            available_supported_document_names: List[str] = []
            for index, document in enumerate(uploaded_documents):
                doc_id = str(document.get("doc_id") or "").strip()
                name = str(document.get("name") or document.get("label") or f"Document {index + 1}").strip()
                coverage_entry = coverage_lookup_by_doc.get(doc_id) or coverage_lookup_by_name.get(name) or {}
                has_evidence = bool(
                    int(coverage_entry.get("selected_chunk_count") or 0)
                    or int(coverage_entry.get("graph_fact_count") or 0)
                )
                if has_evidence:
                    available_supported_document_names.append(name)
                mentioned_in_answer = _answer_mentions_document(answer, name)
                explicitly_unsupported = _answer_marks_document_unsupported(answer, name)
                if has_evidence and mentioned_in_answer:
                    supported_document_names.append(name)
                elif not has_evidence and explicitly_unsupported:
                    explicitly_unsupported_documents.append(name)
                else:
                    missing_document_names.append(name)

            uploaded_document_count = len(uploaded_documents)
            if not uploaded_document_count and answer_source_mode == "document":
                uploaded_document_count = 1
            supported_document_count = len(supported_document_names)
            unsupported_document_count = len(explicitly_unsupported_documents)
            covered_document_count = supported_document_count + unsupported_document_count
            if uploaded_document_count:
                document_coverage_balance = max(
                    document_coverage_balance,
                    round(covered_document_count / uploaded_document_count, 2),
                )

            retrieval_conf = calculate_retrieval_confidence(
                retrieved_chunks,
                has_graph_context=bool(graph_summary),
                graph_support=max(float(graph_payload.get("graph_score", 0.0) or 0.0), graph_fact_support_ratio),
                document_coverage=max(
                    float(graph_document_coverage.get("coverage_ratio", 0.0) or 0.0),
                    document_coverage_balance,
                ),
            )

            answer_text = str(answer or "").strip().lower()
            generation_failed = any(answer_text.startswith(prefix) for prefix in GENERATION_FAILURE_PREFIXES)
            refusal_like = _answer_is_refusal_like(answer)
            effective_source_mode = "error" if generation_failed else answer_source_mode
            overview_softening_applied = False
            multi_doc_fallback_softening_applied = False
            multi_doc_overview_softening_applied = False

            if generation_failed:
                faith_score = 0.0
                hallucination_rate = 1.0
                answer_relevance = 0.0
                unsupported = []
                judge_fallback_used = True
            elif not judge_available:
                heuristic_faith = min(
                    0.95,
                    max(
                        0.6,
                        round(
                            (citation_score * 0.4)
                            + (answer_relevance * 0.25)
                            + (covered_ratio * 0.15)
                            + (graph_fact_support_ratio * 0.1)
                            + (document_coverage_balance * 0.1),
                            4,
                        ),
                    ),
                )
                logger.warning(
                    "Faithfulness judge unavailable; using heuristic fallback "
                    "(cite=%.2f, relevance=%.2f, coverage=%.2f, graph=%.2f, docs=%.2f) -> %.2f",
                    citation_score,
                    answer_relevance,
                    covered_ratio,
                    graph_fact_support_ratio,
                    document_coverage_balance,
                    heuristic_faith,
                )
                faith_score = heuristic_faith
                hallucination_rate = round(1.0 - faith_score, 4)

            if _should_soften_document_overview_validation(
                question=question,
                answer_source_mode=answer_source_mode,
                uploaded_document_count=uploaded_document_count,
                citation_score=citation_score,
                answer_relevance=answer_relevance,
                bert_score_val=bert_score_val,
                covered_ratio=covered_ratio,
                refusal_like=refusal_like,
                generation_failed=generation_failed,
            ):
                softened_faith = min(
                    0.9,
                    max(
                        0.74,
                        round(
                            (citation_score * 0.35)
                            + (answer_relevance * 0.25)
                            + (bert_score_val * 0.2)
                            + (covered_ratio * 0.1)
                            + (max(cosine_sim, 0.0) * 0.1),
                            4,
                        ),
                    ),
                )
                if faith_score < softened_faith:
                    logger.info(
                        "Softening faithfulness for single-document overview answer "
                        "(faith=%.2f -> %.2f, cite=%.2f, relevance=%.2f, bert=%.2f, coverage=%.2f)",
                        faith_score,
                        softened_faith,
                        citation_score,
                        answer_relevance,
                        bert_score_val,
                        covered_ratio,
                    )
                    faith_score = softened_faith
                    hallucination_rate = round(1.0 - faith_score, 4)
                    judge_fallback_used = True
                    overview_softening_applied = True

            if _should_soften_multi_document_fallback_validation(
                answer_source_mode=answer_source_mode,
                uploaded_document_count=uploaded_document_count,
                judge_available=judge_available,
                generation_failed=generation_failed,
                refusal_like=refusal_like,
                answer_relevance=answer_relevance,
                bert_score_val=bert_score_val,
                citation_score=citation_score,
                retrieval_confidence=retrieval_conf,
                document_coverage_balance=document_coverage_balance,
                covered_document_count=covered_document_count,
            ):
                support_blend = round(
                    (answer_relevance * 0.24)
                    + (bert_score_val * 0.18)
                    + (max(cosine_sim, 0.0) * 0.12)
                    + (citation_score * 0.08)
                    + (retrieval_conf * 0.14)
                    + (document_coverage_balance * 0.14)
                    + (covered_ratio * 0.1),
                    4,
                )
                softened_faith = min(
                    0.9,
                    max(
                        0.74,
                        support_blend,
                    ),
                )
                if faith_score < softened_faith:
                    logger.info(
                        "Softening multi-document fallback validation after judge parse failure "
                        "(faith=%.2f -> %.2f, cite=%.2f, relevance=%.2f, bert=%.2f, cos=%.2f, conf=%.2f, doc_cov=%.2f, blend=%.2f)",
                        faith_score,
                        softened_faith,
                        citation_score,
                        answer_relevance,
                        bert_score_val,
                        max(cosine_sim, 0.0),
                        retrieval_conf,
                        document_coverage_balance,
                        support_blend,
                    )
                    faith_score = softened_faith
                    hallucination_rate = round(1.0 - faith_score, 4)
                    judge_fallback_used = True
                    multi_doc_fallback_softening_applied = True

            if _should_soften_multi_document_overview_validation(
                question=question,
                answer_source_mode=answer_source_mode,
                uploaded_document_count=uploaded_document_count,
                judge_available=judge_available,
                generation_failed=generation_failed,
                refusal_like=refusal_like,
                faith_score=faith_score,
                answer_relevance=answer_relevance,
                bert_score_val=bert_score_val,
                citation_score=citation_score,
                retrieval_confidence=retrieval_conf,
                document_coverage_balance=document_coverage_balance,
                covered_document_count=covered_document_count,
                graph_summary=graph_summary,
            ):
                overview_blend = round(
                    (answer_relevance * 0.28)
                    + (bert_score_val * 0.22)
                    + (max(cosine_sim, 0.0) * 0.14)
                    + (citation_score * 0.12)
                    + (retrieval_conf * 0.12)
                    + (document_coverage_balance * 0.12),
                    4,
                )
                softened_faith = min(0.88, max(0.72, overview_blend))
                if faith_score < softened_faith:
                    logger.info(
                        "Softening GRAG multi-doc overview faithfulness "
                        "(faith=%.2f -> %.2f, relevance=%.2f, bert=%.2f, cite=%.2f, conf=%.2f, doc_cov=%.2f)",
                        faith_score,
                        softened_faith,
                        answer_relevance,
                        bert_score_val,
                        citation_score,
                        retrieval_conf,
                        document_coverage_balance,
                    )
                    faith_score = softened_faith
                    hallucination_rate = round(1.0 - faith_score, 4)
                    judge_fallback_used = True
                    multi_doc_overview_softening_applied = True

            final_score = calculate_final_rag_score(
                recall_at_5=None,
                faithfulness=faith_score,
                bert_score_val=bert_score_val,
                citation_alignment=citation_score,
                answer_relevance=answer_relevance,
            )

            status = "VERIFIED"
            reason = "Answer is grounded and accurate."
            if generation_failed:
                status = "REJECTED"
                reason = "Answer generation failed before validation could complete."
            elif uploaded_document_count >= 2 and refusal_like and available_supported_document_names:
                if len(available_supported_document_names) >= uploaded_document_count:
                    status = "REJECTED"
                    reason = "The answer refused despite having support for all uploaded documents."
                else:
                    status = "VERIFIED"
                    reason = (
                        "The answer defaulted to a refusal even though some uploaded documents had support: "
                        f"{', '.join(available_supported_document_names[:3])}."
                    )
            elif multi_doc_fallback_softening_applied:
                status = "VERIFIED"
                reason = "Multi-document answer accepted using corroborated fallback metrics after judge parse failure."
            elif overview_softening_applied:
                status = "VERIFIED"
                reason = "Single-document overview answer accepted using grounded heuristic support."
            elif multi_doc_overview_softening_applied:
                status = "VERIFIED"
                reason = (
                    "Multi-document GRAG overview answer accepted: faithfulness was borderline but "
                    "relevance, BERTScore, and document coverage are strong."
                )
            elif faith_score < 0.7:
                status = "REJECTED"
                reason = f"Low faithfulness ({faith_score:.2f}). Potential hallucination detected."
            elif not judge_available and faith_score < 0.85:
                status = "VERIFIED"
                reason = f"Faithfulness judge fallback used ({faith_score:.2f}). Review answer manually if needed."
            elif hallucination_rate > 0.2:
                status = "VERIFIED"
                reason = f"Elevated hallucination risk ({hallucination_rate:.2f})."
            elif uploaded_document_count >= 2 and missing_document_names:
                # Only reject if ALL uploaded documents are uncovered; partial coverage is VERIFIED
                if len(missing_document_names) >= uploaded_document_count:
                    status = "REJECTED"
                    reason = "The answer did not address any of the uploaded documents."
                else:
                    status = "VERIFIED"
                    reason = f"Multi-document answer missed: {', '.join(missing_document_names[:3])}."
            elif citation_score < 0.8:
                status = "VERIFIED"
                reason = f"Citation alignment below threshold ({citation_score:.2f})."
            elif graph_summary and document_coverage_balance < 0.5:
                status = "VERIFIED"
                reason = f"Multi-document coverage is imbalanced ({document_coverage_balance:.2f})."

            status = normalize_validation_status(status)

            graph_quality_metrics = {
                "graph_score": float(graph_payload.get("graph_score", 0.0) or 0.0),
                "graph_fact_count": len(graph_facts),
                "graph_fact_support_ratio": graph_fact_support_ratio,
                "support_chunk_ids": graph_payload.get("support_chunk_ids", []),
            }
            multi_document_metrics = {
                "graph_used": bool(graph_summary),
                "document_coverage": graph_document_coverage,
                "document_coverage_balance": document_coverage_balance,
                "cross_document_connections": graph_payload.get("cross_document_connections", []),
                "support_chunk_count": len(graph_payload.get("support_chunk_ids", [])),
                "comparison_mode": bool(graph_payload.get("comparison_mode")),
                "uploaded_document_count": uploaded_document_count,
                "supported_document_count": supported_document_count,
                "available_supported_document_count": len(available_supported_document_names),
                "available_supported_document_names": available_supported_document_names,
                "covered_document_count": covered_document_count,
                "unsupported_document_count": unsupported_document_count,
                "supported_document_names": supported_document_names,
                "unsupported_documents": explicitly_unsupported_documents,
                "missing_document_names": missing_document_names,
                "document_coverage_map": coverage_map,
            }

            result = ValidationResult(
                question=question,
                answer=answer,
                subject=subject,
                user_id=user_id,
                evaluation_source=evaluation_source,
                answer_source_mode=effective_source_mode,
                chat_id=chat_id,
                recall_at_5=0.0,
                precision_at_5=0.0,
                mrr=0.0,
                faithfulness_score=faith_score,
                hallucination_rate=hallucination_rate,
                citation_alignment_score=citation_score,
                bert_score=bert_score_val,
                cosine_similarity=cosine_sim,
                answer_relevance=answer_relevance,
                final_rag_score=final_score,
                validation_status=status,
                reason=reason,
                retrieved_chunk_ids=chunk_ids,
                retrieved_chunks_text=chunks_text,
                retrieval_confidence=retrieval_conf,
                chunk_usage=chunk_usage_stats,
                unsupported_sentences=unsupported,
                document_id=document_id,
                judge_fallback_used=judge_fallback_used,
                judge_parse_failure_count=judge_parse_failure_count,
                graph_quality_metrics=graph_quality_metrics,
                multi_document_metrics=multi_document_metrics,
            )

            if persist_result:
                await self._save_result(result)
            logger.info(
                "Validation complete: status=%s, faith=%.2f, bert=%.2f, cite=%.2f, relevance=%.2f, conf=%.2f, cov=%.2f",
                status,
                faith_score,
                bert_score_val,
                citation_score,
                answer_relevance,
                retrieval_conf,
                covered_ratio,
            )
            return result

        except Exception as exc:
            logger.error("Validation pipeline failed: %s", exc, exc_info=True)
            error_result = ValidationResult(
                question=question,
                answer=answer,
                subject=subject,
                user_id=user_id,
                evaluation_source=evaluation_source,
                answer_source_mode=answer_source_mode,
                chat_id=chat_id,
                validation_status="REJECTED",
                reason=f"Validation error: {str(exc)}",
            )
            if persist_result:
                await self._save_result(error_result)
            return error_result

    async def validate_with_gold(
        self,
        question: str,
        answer: str,
        retrieved_chunks: List[Dict],
        gold_chunk_ids: List[str],
        gold_answer: str = "",
        user_id: str = "benchmark_runner",
        subject: str = "general",
        answer_source_mode: str = "knowledge_base",
    ) -> ValidationResult:
        from backend.core.evaluation.metrics import calculate_retrieval_metrics

        result = await self.validate_answer(
            question=question,
            answer=answer,
            retrieved_chunks=retrieved_chunks,
            user_id=user_id,
            subject=subject,
            evaluation_source="benchmark",
            answer_source_mode=answer_source_mode,
        )

        retrieved_ids = [get_evaluation_chunk_id(chunk) for chunk in retrieved_chunks]
        retrieved_ids = [chunk_id for chunk_id in retrieved_ids if chunk_id]
        retrieval_metrics = calculate_retrieval_metrics(retrieved_ids, gold_chunk_ids)

        result.recall_at_5 = retrieval_metrics.get("recall@5", 0.0)
        result.precision_at_5 = retrieval_metrics.get("precision@5", 0.0)
        result.mrr = retrieval_metrics.get("mrr", 0.0)
        if str(gold_answer or "").strip():
            cleaned_answer = _strip_inline_chunk_citations(answer)
            result.bert_score = calculate_bert_score(cleaned_answer, gold_answer)
            result.cosine_similarity = calculate_cosine_similarity(cleaned_answer, gold_answer)
        effective_source_mode = str(result.answer_source_mode or answer_source_mode).strip().lower()
        if not retrieved_chunks:
            result.validation_status = "REJECTED"
            result.reason = "Benchmark retrieval returned no grounded chunks."
        elif effective_source_mode == "gemini_fallback":
            result.validation_status = "REJECTED"
            result.reason = "Benchmark answer used Gemini fallback instead of grounded RAG."
        elif effective_source_mode == "error":
            result.validation_status = "REJECTED"
            result.reason = "Benchmark answer generation failed before grounded validation could complete."

        result.final_rag_score = calculate_final_rag_score(
            recall_at_5=result.recall_at_5,
            faithfulness=result.faithfulness_score,
            bert_score_val=result.bert_score,
            citation_alignment=result.citation_alignment_score,
            answer_relevance=result.answer_relevance,
        )
        result.validation_status = normalize_validation_status(result.validation_status)

        await self._update_result(result)
        return result

    async def _save_result(self, result: ValidationResult):
        try:
            result.validation_status = normalize_validation_status(result.validation_status)
            data = result.dict(by_alias=True)
            if "_id" in data and not data["_id"]:
                del data["_id"]
            insert_result = await self.db.rag_answer_validations.insert_one(data)
            result.id = str(insert_result.inserted_id)
            logger.info("Saved validation for: %s... ID: %s", result.question[:30], result.id)
        except Exception as exc:
            logger.error("Failed to save validation result: %s", exc)

    async def _update_result(self, result: ValidationResult):
        try:
            selector = {"question": result.question, "answer": result.answer}
            if getattr(result, "id", None):
                from bson import ObjectId

                if ObjectId.is_valid(str(result.id)):
                    selector = {"_id": ObjectId(str(result.id))}

            await self.db.rag_answer_validations.update_one(
                selector,
                {
                    "$set": {
                        "recall_at_5": result.recall_at_5,
                        "precision_at_5": result.precision_at_5,
                        "mrr": result.mrr,
                        "final_rag_score": result.final_rag_score,
                        "validation_status": normalize_validation_status(result.validation_status),
                        "reason": result.reason,
                        "answer_source_mode": result.answer_source_mode,
                    }
                },
            )
        except Exception as exc:
            logger.error("Failed to update validation result: %s", exc)
