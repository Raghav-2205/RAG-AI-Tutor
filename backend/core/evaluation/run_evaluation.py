# backend/core/evaluation/run_evaluation.py
"""
Benchmark evaluation runner.

Loads benchmark_dataset.json, runs the full RAG pipeline for each sample,
computes retrieval + generation metrics, and stores results.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from backend.preprocessing import analyze_chunk_set
from backend.core.evaluation.status_policy import normalize_validation_status

logger = logging.getLogger(__name__)

BENCHMARK_DATASET_PATH = Path(__file__).parent / "benchmark_dataset.json"
GENERATION_FAILURE_PREFIXES = (
    "llm async request failed",
    "llm request failed",
    "llm api error",
    "error: no gemini api key",
)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _resolve_gold_chunk_ids(sample: Dict[str, Any], chunks: List[Dict[str, Any]]) -> List[str]:
    source = str(sample.get("gold_chunk_source") or "").strip()
    contains = _normalize_text(sample.get("gold_chunk_contains") or "")
    explicit_ids = sample.get("gold_chunk_ids") or []
    if not explicit_ids and sample.get("gold_chunk_id"):
        explicit_ids = [sample["gold_chunk_id"]]

    matches: List[str] = []
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        chunk_source = str(metadata.get("source") or "")
        chunk_text = _normalize_text(chunk.get("text") or "")
        evaluation_id = str(metadata.get("chunk_id") or chunk.get("chunk_id") or chunk.get("id") or "")
        if not evaluation_id:
            continue
        if source and chunk_source != source:
            continue
        if contains and contains not in chunk_text:
            continue
        matches.append(evaluation_id)

    if matches:
        return matches
    return [str(item) for item in explicit_ids if item]


def _is_generation_error_result(result: Dict[str, Any]) -> bool:
    source_mode = str(
        result.get("answer_source_mode")
        or result.get("source_mode")
        or ""
    ).strip().lower()
    if source_mode == "error":
        return True

    if str(result.get("status") or "").strip().lower() == "generation_error":
        return True

    answer_text = str(result.get("answer") or "").strip().lower()
    if any(answer_text.startswith(prefix) for prefix in GENERATION_FAILURE_PREFIXES):
        return True

    reason = str(result.get("reason") or "").strip().lower()
    return "answer generation failed" in reason or "llm " in reason


def _should_retry_sample(result: Dict[str, Any]) -> bool:
    if _is_generation_error_result(result):
        return True
    if str(result.get("status") or "").strip().lower() == "error":
        error_text = str(result.get("error") or result.get("reason") or "").strip().lower()
        return any(prefix in error_text for prefix in GENERATION_FAILURE_PREFIXES) or "timeout" in error_text
    return False


def _is_grounded_benchmark_success(result: Dict[str, Any]) -> bool:
    status = str(result.get("status") or "").strip().lower()
    source_mode = str(result.get("answer_source_mode") or result.get("source_mode") or "").strip().lower()
    if status != "completed":
        return False
    if source_mode in {"gemini_fallback", "error"}:
        return False
    return int(result.get("num_chunks") or 0) > 0


def _trim_benchmark_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "question": result.get("question"),
        "status": result.get("status"),
        "answer_source_mode": result.get("answer_source_mode") or result.get("source_mode"),
        "validation_status": result.get("validation_status"),
        "recall_at_5": result.get("recall_at_5"),
        "final_rag_score": result.get("final_rag_score"),
        "attempts": result.get("attempts"),
        "reason": result.get("reason"),
        "error": result.get("error"),
        "num_chunks": result.get("num_chunks"),
    }


def _summarize_benchmark_results(
    total_samples: int,
    results: List[Dict[str, Any]],
    chunk_diagnostics: Dict[str, Any],
    user_id: str = "benchmark_runner",
) -> Dict[str, Any]:
    completed_rows = [row for row in results if _is_grounded_benchmark_success(row)]
    generation_error_rows = [
        row for row in results
        if _is_generation_error_result(row)
    ]
    ungrounded_rows = [
        row for row in results
        if str(row.get("status") or "").strip().lower() in {"no_context", "ungrounded_fallback"}
    ]
    pipeline_error_rows = [
        row for row in results
        if str(row.get("status") or "").strip().lower() == "error" and not _is_generation_error_result(row)
    ]
    retrieval_rows = [
        row for row in results
        if str(row.get("status") or "").strip().lower() in {"completed", "generation_error", "no_context", "ungrounded_fallback"}
    ]

    def avg(rows: List[Dict[str, Any]], key: str) -> float | None:
        values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    answer_quality_count = len(completed_rows)
    generation_error_count = len(generation_error_rows)
    ungrounded_failure_count = len(ungrounded_rows)
    unexpected_error_count = len(pipeline_error_rows)
    error_count = generation_error_count + unexpected_error_count + ungrounded_failure_count
    generation_valid = (
        total_samples > 0
        and answer_quality_count == total_samples
        and generation_error_count == 0
        and unexpected_error_count == 0
        and ungrounded_failure_count == 0
    )

    return {
        "user_id": user_id,
        "total_samples": total_samples,
        "completed": answer_quality_count,
        "answer_quality_count": answer_quality_count,
        "retrieval_metrics_count": len(retrieval_rows),
        "generation_error_count": generation_error_count,
        "ungrounded_failure_count": ungrounded_failure_count,
        "unexpected_error_count": unexpected_error_count,
        "failure_count": error_count,
        "failure_rate": round(error_count / total_samples, 4) if total_samples else 0.0,
        "error_count": error_count,
        "errors": error_count,
        "generation_valid": generation_valid,
        "generation_failure_rate": round(generation_error_count / total_samples, 4) if total_samples else 0.0,
        "avg_faithfulness": avg(completed_rows, "faithfulness_score"),
        "avg_hallucination_rate": avg(completed_rows, "hallucination_rate"),
        "avg_bert_score": avg(completed_rows, "bert_score"),
        "avg_cosine_similarity": avg(completed_rows, "cosine_similarity"),
        "avg_citation_alignment": avg(completed_rows, "citation_alignment"),
        "avg_answer_relevance": avg(completed_rows, "answer_relevance"),
        "avg_recall_at_5": avg(retrieval_rows, "recall_at_5"),
        "avg_precision_at_5": avg(retrieval_rows, "precision_at_5"),
        "avg_mrr": avg(retrieval_rows, "mrr"),
        "avg_final_rag_score": avg(completed_rows, "final_rag_score"),
        "verified_count": sum(1 for row in completed_rows if normalize_validation_status(row.get("validation_status")) == "VERIFIED"),
        "rejected_count": sum(1 for row in completed_rows if normalize_validation_status(row.get("validation_status")) == "REJECTED"),
        "fallback_count": sum(
            1
            for row in results
            if str(row.get("answer_source_mode") or row.get("source_mode") or "").strip().lower() == "gemini_fallback"
        ),
        "chunk_diagnostics": chunk_diagnostics,
        "timestamp": datetime.utcnow().isoformat(),
        "sample_results": [_trim_benchmark_result(row) for row in results],
    }


async def run_benchmark(db) -> Dict[str, Any]:
    """
    Execute full benchmark evaluation:
    1. Load benchmark samples
    2. For each: run retrieval -> generate answer -> validate with gold
    3. Aggregate results
    4. Return summary
    """
    from backend.core.evaluation.validator import ValidationEngine
    from backend.rag_tutor import answer_query_with_rag
    from backend.vector_db import get_all_chunks

    logger.info("Starting benchmark evaluation run...")

    try:
        with open(BENCHMARK_DATASET_PATH, "r", encoding="utf-8") as f:
            samples = json.load(f)
    except FileNotFoundError:
        logger.error("Benchmark dataset not found at %s", BENCHMARK_DATASET_PATH)
        return {"error": "Benchmark dataset not found", "results": []}

    validator = ValidationEngine(db)
    results: List[Dict[str, Any]] = []
    user_id = "benchmark_runner"
    benchmark_chunks = get_all_chunks("global", "general")
    benchmark_chunk_diagnostics = analyze_chunk_set([chunk.get("text", "") for chunk in benchmark_chunks])

    for index, sample in enumerate(samples):
        question = sample["question"]
        gold_answer = sample.get("gold_answer", "")
        subject = sample.get("subject", "general")

        logger.info("[%s/%s] Evaluating benchmark question: %s", index + 1, len(samples), question)

        final_result: Dict[str, Any] | None = None
        last_exception: Exception | None = None
        for attempt in range(2):
            try:
                rag_result = await answer_query_with_rag(
                    user_id=user_id,
                    query=question,
                    subject=subject,
                    history=[],
                    feedback_context="",
                    strict_mode=True,
                    answer_mode="benchmark_mode",
                    persist_validation=False,
                )

                answer = rag_result.get("answer", "")
                chunks = rag_result.get("chunks", [])
                source_mode = rag_result.get("source_mode", "knowledge_base")
                gold_ids = _resolve_gold_chunk_ids(sample, benchmark_chunks)

                validation = await validator.validate_with_gold(
                    question=question,
                    answer=answer,
                    retrieved_chunks=chunks,
                    gold_chunk_ids=gold_ids,
                    gold_answer=gold_answer,
                    user_id=user_id,
                    subject=subject,
                    answer_source_mode=source_mode,
                )

                effective_source_mode = str(validation.answer_source_mode or source_mode).strip().lower()
                result_status = "completed"
                if effective_source_mode == "error":
                    result_status = "generation_error"
                elif effective_source_mode == "gemini_fallback":
                    result_status = "ungrounded_fallback"
                elif not chunks:
                    result_status = "no_context"

                final_result = {
                    "question": question,
                    "answer": answer[:200],
                    "gold_answer": gold_answer[:200],
                    "num_chunks": len(chunks),
                    "source_mode": source_mode,
                    "answer_source_mode": effective_source_mode,
                    "faithfulness_score": validation.faithfulness_score,
                    "hallucination_rate": validation.hallucination_rate,
                    "bert_score": validation.bert_score,
                    "cosine_similarity": validation.cosine_similarity,
                    "citation_alignment": validation.citation_alignment_score,
                    "answer_relevance": validation.answer_relevance,
                    "recall_at_5": validation.recall_at_5,
                    "precision_at_5": validation.precision_at_5,
                    "mrr": validation.mrr,
                    "final_rag_score": validation.final_rag_score,
                    "validation_status": validation.validation_status,
                    "reason": validation.reason,
                    "status": result_status,
                    "attempts": attempt + 1,
                }

                if attempt == 0 and _should_retry_sample(final_result):
                    logger.warning("Retrying benchmark sample after transient failure: %s", question)
                    continue
                break
            except Exception as exc:
                last_exception = exc
                logger.error("Benchmark error for '%s' on attempt %s: %s", question, attempt + 1, exc)
                final_result = {
                    "question": question,
                    "status": "error",
                    "error": str(exc),
                    "attempts": attempt + 1,
                }
                if attempt == 0 and _should_retry_sample(final_result):
                    logger.warning("Retrying benchmark sample after runtime error: %s", question)
                    continue
                break

        if final_result is None and last_exception is not None:
            final_result = {
                "question": question,
                "status": "error",
                "error": str(last_exception),
                "attempts": 2,
            }

        results.append(final_result or {
            "question": question,
            "status": "error",
            "error": "Unknown benchmark failure",
            "attempts": 2,
        })

    summary = _summarize_benchmark_results(
        total_samples=len(samples),
        results=results,
        chunk_diagnostics=benchmark_chunk_diagnostics,
        user_id=user_id,
    )

    logger.info(
        "Benchmark complete: %s/%s answer-quality samples, generation_errors=%s, avg_recall@5=%.2f, avg_final_score=%.2f",
        summary["completed"],
        summary["total_samples"],
        summary["generation_error_count"],
        summary["avg_recall_at_5"] or 0.0,
        summary["avg_final_rag_score"] or 0.0,
    )

    try:
        await db.benchmark_runs.insert_one({
            **summary,
            "created_at": datetime.utcnow(),
        })
    except Exception as exc:
        logger.error("Failed to save benchmark summary: %s", exc)

    return summary
