# backend/api/evaluation.py
"""
Evaluation API endpoints for the RAG Evaluation Dashboard.

Endpoints:
  GET  /api/evaluation/metrics       — Aggregated evaluation metrics
  GET  /api/evaluation/logs          — Recent validation log entries
  POST /api/evaluation/run_benchmark — Trigger benchmark run (background)
  POST /api/evaluation/sync_history  — Sync historical chat messages into evaluation
  GET  /api/evaluation/report        — Auto-debug report with recommendations
"""

from collections import Counter
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.core.feedback_analyzer import FeedbackAnalyzer
from backend.models.evaluation import ValidationResult
from backend.core.evaluation.status_policy import normalize_validation_record, normalize_validation_status
from backend.utils.security import normalize_role
from backend.core.evaluation.metrics import calculate_final_rag_score

router = APIRouter()

FINAL_RETRIEVAL_FIELDS = ("recall_at_5", "precision_at_5", "mrr")
FINAL_ANSWER_FIELDS = (
    "faithfulness_score",
    "hallucination_rate",
    "bert_score",
    "citation_alignment_score",
    "answer_relevance",
    "final_rag_score",
    "retrieval_confidence",
)
GENERATION_FAILURE_PREFIXES = (
    "llm async request failed",
    "llm request failed",
    "llm api error",
    "error: no gemini api key",
)
LOG_SORT_OPTIONS = {"NEWEST", "OLDEST", "RAG_ASC", "RAG_DESC", "HALLUC_DESC"}
LOG_SOURCE_OPTIONS = {"ALL", "BENCHMARK", "LIVE", "SYNCED_HISTORY"}
LOG_STATUS_OPTIONS = {"ALL", "VERIFIED", "REJECTED"}


def _final_time_filter(period: str) -> Dict[str, Any]:
    if period == "24h":
        return {"timestamp": {"$gte": datetime.utcnow() - timedelta(hours=24)}}
    if period == "7d":
        return {"timestamp": {"$gte": datetime.utcnow() - timedelta(days=7)}}
    return {}


def _is_admin_user(current_user: Dict[str, Any]) -> bool:
    return normalize_role(current_user.get("role")) == "admin"


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _average(records: List[Dict[str, Any]], field: str) -> Optional[float]:
    values = [_coerce_float(record.get(field)) for record in records]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 4)


def _average_nested(records: List[Dict[str, Any]], field: str, nested_field: str) -> Optional[float]:
    numeric: List[float] = []
    for record in records:
        nested = record.get(field) or {}
        if isinstance(nested, dict):
            value = _coerce_float(nested.get(nested_field))
            if value is not None:
                numeric.append(value)
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 4)


def _build_graph_quality_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    graph_rows = [
        record for record in records
        if isinstance(record.get("graph_quality_metrics"), dict) and record.get("graph_quality_metrics")
    ]
    multi_doc_rows = [
        record for record in records
        if isinstance(record.get("multi_document_metrics"), dict)
        and record.get("multi_document_metrics", {}).get("graph_used")
    ]
    return {
        "graph_answer_count": len(graph_rows),
        "multi_document_answer_count": len(multi_doc_rows),
        "avg_graph_score": _average_nested(graph_rows, "graph_quality_metrics", "graph_score"),
        "avg_graph_fact_support_ratio": _average_nested(graph_rows, "graph_quality_metrics", "graph_fact_support_ratio"),
        "avg_document_coverage_balance": _average_nested(multi_doc_rows, "multi_document_metrics", "document_coverage_balance"),
        "avg_covered_document_count": _average_nested(multi_doc_rows, "multi_document_metrics", "covered_document_count"),
        "avg_uploaded_document_count": _average_nested(multi_doc_rows, "multi_document_metrics", "uploaded_document_count"),
        "avg_unsupported_document_count": _average_nested(multi_doc_rows, "multi_document_metrics", "unsupported_document_count"),
    }


def _infer_evaluation_source(record: Dict[str, Any]) -> str:
    explicit = str(record.get("evaluation_source") or "").strip().lower()
    if explicit in {"live", "benchmark", "synced_history"}:
        return explicit
    if str(record.get("user_id") or "") == "benchmark_runner":
        return "benchmark"
    return "live"


def _normalize_final_record(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_validation_record(record)
    normalized["_id"] = str(normalized.get("_id"))
    normalized["evaluation_source"] = _infer_evaluation_source(normalized)
    normalized["answer_source_mode"] = str(
        normalized.get("answer_source_mode")
        or normalized.get("source_mode")
        or ("knowledge_base" if normalized["evaluation_source"] == "benchmark" else "unknown")
    ).strip().lower()
    benchmark_metrics_available = normalized["evaluation_source"] == "benchmark"
    recall_value = _coerce_float(normalized.get("recall_at_5")) if benchmark_metrics_available else None
    normalized["benchmark_metrics_available"] = benchmark_metrics_available
    normalized["final_rag_score"] = calculate_final_rag_score(
        recall_at_5=recall_value,
        faithfulness=_coerce_float(normalized.get("faithfulness_score")),
        bert_score_val=_coerce_float(normalized.get("bert_score")),
        citation_alignment=_coerce_float(normalized.get("citation_alignment_score")),
        answer_relevance=_coerce_float(normalized.get("answer_relevance")),
    )
    return normalized


def _is_generation_error(record: Dict[str, Any]) -> bool:
    source_mode = str(record.get("answer_source_mode") or "").strip().lower()
    if source_mode == "error":
        return True
    answer_text = str(record.get("answer") or "").strip().lower()
    if any(answer_text.startswith(prefix) for prefix in GENERATION_FAILURE_PREFIXES):
        return True
    reason = str(record.get("reason") or "").strip().lower()
    return "answer generation failed" in reason or "llm " in reason


def _quality_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for record in records:
        if _is_generation_error(record):
            continue
        filtered.append(record)
    return filtered


def _build_status_counts(records: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "verified_count": 0,
        "rejected_count": 0,
        "error_count": 0,
    }
    for record in records:
        status = normalize_validation_status(record.get("validation_status"))
        if status == "VERIFIED":
            counts["verified_count"] += 1
        elif status == "REJECTED":
            counts["rejected_count"] += 1
        if _is_generation_error(record):
            counts["error_count"] += 1
    return counts


def _normalize_log_source(value: Optional[str]) -> str:
    normalized = str(value or "ALL").strip().upper()
    return normalized if normalized in LOG_SOURCE_OPTIONS else "ALL"


def _normalize_log_status(value: Optional[str]) -> str:
    normalized = str(value or "ALL").strip().upper()
    return normalized if normalized in LOG_STATUS_OPTIONS else "ALL"


def _normalize_log_sort(value: Optional[str]) -> str:
    normalized = str(value or "NEWEST").strip().upper()
    return normalized if normalized in LOG_SORT_OPTIONS else "NEWEST"


def _build_log_match_query(
    period: str,
    current_user: Dict[str, Any],
    *,
    source_filter: str = "ALL",
    status_filter: str = "ALL",
) -> Dict[str, Any]:
    match_query = _final_time_filter(period)
    if not _is_admin_user(current_user):
        match_query["user_id"] = str(current_user["_id"])

    normalized_source = _normalize_log_source(source_filter)
    if normalized_source == "BENCHMARK":
        match_query["$or"] = [
            {"evaluation_source": "benchmark"},
            {"user_id": "benchmark_runner"},
        ]
    elif normalized_source == "LIVE":
        match_query["evaluation_source"] = "live"
    elif normalized_source == "SYNCED_HISTORY":
        match_query["evaluation_source"] = "synced_history"

    normalized_status = _normalize_log_status(status_filter)
    if normalized_status != "ALL":
        match_query["validation_status"] = normalized_status

    return match_query


def _resolve_log_sort(sort_name: str):
    normalized = _normalize_log_sort(sort_name)
    if normalized == "OLDEST":
        return [("timestamp", 1)]
    if normalized == "RAG_ASC":
        return [("final_rag_score", 1), ("timestamp", -1)]
    if normalized == "RAG_DESC":
        return [("final_rag_score", -1), ("timestamp", -1)]
    if normalized == "HALLUC_DESC":
        return [("hallucination_rate", -1), ("timestamp", -1)]
    return [("timestamp", -1)]


def _extract_question_preview(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(record.get("_id") or ""),
        "question": str(record.get("question") or "").strip(),
        "timestamp": record.get("timestamp"),
        "source": record.get("evaluation_source"),
        "validation_status": normalize_validation_status(record.get("validation_status")),
        "final_rag_score": _coerce_float(record.get("final_rag_score")),
    }


def _build_recent_questions(records: List[Dict[str, Any]], source: str, limit: int = 5) -> List[Dict[str, Any]]:
    items = [record for record in records if record.get("evaluation_source") == source]
    return [_extract_question_preview(record) for record in items[:limit] if str(record.get("question") or "").strip()]


def _build_daily_counts(records: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    counts: Counter[str] = Counter()
    for record in records:
        timestamp = record.get("timestamp")
        if not timestamp:
            continue
        try:
            dt = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        counts[dt.strftime("%Y-%m-%d")] += 1
    return [
        {"date": date_key, "count": counts[date_key]}
        for date_key in sorted(counts.keys(), reverse=True)[:limit]
    ]


def _is_attention_record(record: Dict[str, Any]) -> bool:
    if normalize_validation_status(record.get("validation_status")) == "REJECTED":
        return True
    if _is_generation_error(record):
        return True
    hallucination = _coerce_float(record.get("hallucination_rate")) or 0.0
    final_rag = _coerce_float(record.get("final_rag_score")) or 0.0
    citation = _coerce_float(record.get("citation_alignment_score")) or 0.0
    return hallucination >= 0.15 or final_rag < 0.75 or citation < 0.75


def _build_attention_summary(records: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    items = []
    for record in records:
        if not _is_attention_record(record):
            continue
        items.append({
            "id": str(record.get("_id") or ""),
            "question": str(record.get("question") or "").strip(),
            "source": record.get("evaluation_source"),
            "timestamp": record.get("timestamp"),
            "validation_status": normalize_validation_status(record.get("validation_status")),
            "final_rag_score": _coerce_float(record.get("final_rag_score")),
            "hallucination_rate": _coerce_float(record.get("hallucination_rate")),
            "citation_alignment_score": _coerce_float(record.get("citation_alignment_score")),
            "reason": str(record.get("reason") or "").strip(),
        })
    return items[:limit]


def _normalize_query_key(question: str) -> str:
    return " ".join(str(question or "").strip().lower().split())


def _build_query_patterns(records: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if not _is_attention_record(record):
            continue
        question = str(record.get("question") or "").strip()
        key = _normalize_query_key(question)
        if not key:
            continue
        bucket = grouped.setdefault(key, {
            "question": question,
            "count": 0,
            "latest_timestamp": record.get("timestamp"),
            "avg_final_rag_score": 0.0,
            "sources": Counter(),
        })
        bucket["count"] += 1
        bucket["avg_final_rag_score"] += _coerce_float(record.get("final_rag_score")) or 0.0
        bucket["sources"][str(record.get("evaluation_source") or "live")] += 1

    ranked = sorted(grouped.values(), key=lambda item: (-item["count"], item["avg_final_rag_score"]))
    results = []
    for item in ranked[:limit]:
        count = int(item["count"] or 0)
        results.append({
            "question": item["question"],
            "count": count,
            "avg_final_rag_score": round((item["avg_final_rag_score"] / count), 4) if count else None,
            "top_source": item["sources"].most_common(1)[0][0] if item["sources"] else "live",
        })
    return results


def _build_log_source_counts(records: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"benchmark": 0, "live": 0, "synced_history": 0}
    for record in records:
        source = str(record.get("evaluation_source") or "live")
        if source in counts:
            counts[source] += 1
    return counts


def _build_source_metrics_payload(records: List[Dict[str, Any]], include_retrieval: bool = False) -> Dict[str, Any]:
    quality_rows = _quality_rows(records)
    generation_error_rows = [record for record in records if _is_generation_error(record)]
    fallback_rows = [
        record for record in records
        if str(record.get("answer_source_mode") or "").lower() in {"gemini_fallback", "error"}
    ]

    payload = {
        "total_validations": len(records),
        "answer_quality_count": len(quality_rows),
        "generation_error_count": len(generation_error_rows),
        "fallback_answer_count": len(fallback_rows),
        "avg_faithfulness": _average(quality_rows, "faithfulness_score"),
        "avg_hallucination": _average(quality_rows, "hallucination_rate"),
        "avg_bert_score": _average(quality_rows, "bert_score"),
        "avg_cosine_similarity": _average(quality_rows, "cosine_similarity"),
        "avg_citation_alignment": _average(quality_rows, "citation_alignment_score"),
        "avg_answer_relevance": _average(quality_rows, "answer_relevance"),
        "avg_final_rag_score": _average(quality_rows, "final_rag_score"),
        "avg_retrieval_confidence": _average(quality_rows, "retrieval_confidence"),
        "avg_judge_parse_failure_count": _average(records, "judge_parse_failure_count"),
        "judge_fallback_count": sum(1 for record in records if record.get("judge_fallback_used")),
    }
    if include_retrieval:
        payload.update({
            "avg_recall_at_5": _average(records, "recall_at_5"),
            "avg_precision_at_5": _average(records, "precision_at_5"),
            "avg_mrr": _average(records, "mrr"),
        })
    payload.update(_build_status_counts(records))
    return payload


def _normalize_benchmark_run(run: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not run:
        return None

    total_samples = int(run.get("total_samples") or 0)
    answer_quality_count = int(run.get("answer_quality_count") or run.get("completed") or 0)
    generation_error_count = int(run.get("generation_error_count") or 0)
    unexpected_error_count = int(run.get("unexpected_error_count") or 0)
    inferred_error_count = generation_error_count + unexpected_error_count
    error_count = int(run.get("error_count") or run.get("errors") or inferred_error_count)
    generation_valid = bool(run.get("generation_valid")) if "generation_valid" in run else (
        answer_quality_count > 0 and generation_error_count == 0 and unexpected_error_count == 0
    )

    return {
        "timestamp": run.get("timestamp"),
        "created_at": run.get("created_at"),
        "total_samples": total_samples,
        "completed": answer_quality_count,
        "answer_quality_count": answer_quality_count,
        "retrieval_metrics_count": int(run.get("retrieval_metrics_count") or answer_quality_count + generation_error_count),
        "generation_error_count": generation_error_count,
        "ungrounded_failure_count": int(run.get("ungrounded_failure_count") or 0),
        "unexpected_error_count": unexpected_error_count,
        "failure_count": int(run.get("failure_count") or error_count),
        "failure_rate": _coerce_float(run.get("failure_rate"))
        if _coerce_float(run.get("failure_rate")) is not None
        else (round(error_count / total_samples, 4) if total_samples else 0.0),
        "error_count": error_count,
        "errors": error_count,
        "generation_valid": generation_valid,
        "generation_failure_rate": run.get("generation_failure_rate")
        if isinstance(run.get("generation_failure_rate"), (int, float))
        else (round(generation_error_count / total_samples, 4) if total_samples else 0.0),
        "avg_faithfulness": _coerce_float(run.get("avg_faithfulness")),
        "avg_hallucination_rate": _coerce_float(run.get("avg_hallucination_rate")),
        "avg_bert_score": _coerce_float(run.get("avg_bert_score")),
        "avg_cosine_similarity": _coerce_float(run.get("avg_cosine_similarity")),
        "avg_citation_alignment": _coerce_float(run.get("avg_citation_alignment")),
        "avg_answer_relevance": _coerce_float(run.get("avg_answer_relevance")),
        "avg_recall_at_5": _coerce_float(run.get("avg_recall_at_5")),
        "avg_precision_at_5": _coerce_float(run.get("avg_precision_at_5")),
        "avg_mrr": _coerce_float(run.get("avg_mrr")),
        "avg_final_rag_score": _coerce_float(run.get("avg_final_rag_score")),
        "verified_count": int(run.get("verified_count") or 0) + int(run.get("warning_count") or 0),
        "rejected_count": int(run.get("rejected_count") or 0),
        "fallback_count": int(run.get("fallback_count") or 0),
        "chunk_diagnostics": run.get("chunk_diagnostics") or {},
        "sample_results": list(run.get("sample_results") or run.get("results") or []),
    }


def _build_metric_summary(
    source: Optional[Dict[str, Any]],
    *,
    benchmark: bool = False,
) -> Dict[str, Optional[float]]:
    source = source or {}
    return {
        "avg_faithfulness": _coerce_float(source.get("avg_faithfulness")),
        "avg_hallucination": _coerce_float(
            source.get("avg_hallucination_rate") if benchmark else source.get("avg_hallucination")
        ),
        "avg_bert_score": _coerce_float(source.get("avg_bert_score")),
        "avg_citation_alignment": _coerce_float(source.get("avg_citation_alignment")),
        "avg_answer_relevance": _coerce_float(source.get("avg_answer_relevance")),
        "avg_final_rag_score": _coerce_float(source.get("avg_final_rag_score")),
        "avg_recall_at_5": _coerce_float(source.get("avg_recall_at_5")),
    }


def _resolve_primary_metrics(
    *,
    latest_benchmark: Optional[Dict[str, Any]],
    live_window_metrics: Optional[Dict[str, Any]],
    historical_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    benchmark_ready = bool(latest_benchmark and latest_benchmark.get("generation_valid"))
    live_window_active = bool((live_window_metrics or {}).get("answer_quality_count"))

    if benchmark_ready:
        primary_basis = "benchmark"
        primary_metrics = _build_metric_summary(latest_benchmark, benchmark=True)
    elif live_window_active:
        primary_basis = "live_window"
        primary_metrics = _build_metric_summary(live_window_metrics)
    else:
        primary_basis = "historical"
        primary_metrics = _build_metric_summary(historical_metrics)

    secondary_basis = "live_window" if benchmark_ready and live_window_active else None
    secondary_metrics = _build_metric_summary(live_window_metrics) if secondary_basis else None
    benchmark_target_met = bool(
        benchmark_ready and (_coerce_float((latest_benchmark or {}).get("avg_final_rag_score")) or 0.0) >= 0.9
    )
    live_window_target_met = bool(
        live_window_active and (_coerce_float((live_window_metrics or {}).get("avg_final_rag_score")) or 0.0) >= 0.9
    )

    return {
        "primary_metrics_basis": primary_basis,
        "primary_metrics": primary_metrics,
        "secondary_metrics_basis": secondary_basis,
        "secondary_metrics": secondary_metrics,
        "quality_targets": {
            "benchmark_target_active": benchmark_ready,
            "benchmark_target_met": benchmark_target_met,
            "live_window_target_active": live_window_active,
            "live_window_target_met": live_window_target_met,
            "all_active_targets_met": benchmark_target_met and (not live_window_active or live_window_target_met),
        },
    }


async def _load_latest_benchmark_run(
    db,
    current_user: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    match_query: Dict[str, Any] = {}
    if not _is_admin_user(current_user):
        match_query["user_id"] = str(current_user["_id"])

    run = await db.benchmark_runs.find_one(match_query, sort=[("created_at", -1)])
    return _normalize_benchmark_run(run)


def _build_final_metrics_payload(
    records: List[Dict[str, Any]],
    latest_benchmark: Optional[Dict[str, Any]] = None,
    live_window_metrics: Optional[Dict[str, Any]] = None,
    feedback_loop_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    benchmark_rows = [record for record in records if record.get("evaluation_source") == "benchmark"]
    live_rows = [record for record in records if record.get("evaluation_source") == "live"]
    synced_rows = [record for record in records if record.get("evaluation_source") == "synced_history"]
    quality_rows = _quality_rows(records)
    generation_error_rows = [record for record in records if _is_generation_error(record)]
    fallback_rows = [
        record for record in records
        if str(record.get("answer_source_mode") or "").lower() in {"gemini_fallback", "error"}
    ]
    live_metrics = _build_source_metrics_payload(live_rows, include_retrieval=False)
    benchmark_history_metrics = _build_source_metrics_payload(benchmark_rows, include_retrieval=True)
    synced_history_metrics = _build_source_metrics_payload(synced_rows, include_retrieval=False)
    graph_quality_metrics = _build_graph_quality_metrics(records)

    payload = {
        "total_validations": len(records),
        "benchmark_count": len(benchmark_rows),
        "live_count": len(live_rows),
        "synced_history_count": len(synced_rows),
        "answer_quality_count": len(quality_rows),
        "generation_error_count": len(generation_error_rows),
        "fallback_answer_count": len(fallback_rows),
        "benchmark_available": bool(benchmark_rows),
        "avg_faithfulness": _average(quality_rows, "faithfulness_score"),
        "avg_hallucination": _average(quality_rows, "hallucination_rate"),
        "avg_bert_score": _average(quality_rows, "bert_score"),
        "avg_cosine_similarity": _average(quality_rows, "cosine_similarity"),
        "avg_citation_alignment": _average(quality_rows, "citation_alignment_score"),
        "avg_answer_relevance": _average(quality_rows, "answer_relevance"),
        "avg_final_rag_score": _average(quality_rows, "final_rag_score"),
        "avg_retrieval_confidence": _average(quality_rows, "retrieval_confidence"),
        "avg_recall_at_5": _average(benchmark_rows, "recall_at_5"),
        "avg_precision_at_5": _average(benchmark_rows, "precision_at_5"),
        "avg_mrr": _average(benchmark_rows, "mrr"),
        "live_metrics": live_metrics,
        "live_window_metrics": live_window_metrics or {},
        "benchmark_history_metrics": benchmark_history_metrics,
        "synced_history_metrics": synced_history_metrics,
        "source_breakdown": {
            "benchmark": benchmark_history_metrics,
            "live": live_metrics,
            "synced_history": synced_history_metrics,
        },
        "latest_benchmark": latest_benchmark,
        "feedback_loop_status": feedback_loop_status or {},
        "graph_quality_metrics": graph_quality_metrics,
        "multi_document_metrics": {
            "multi_document_answer_count": graph_quality_metrics.get("multi_document_answer_count", 0),
            "avg_document_coverage_balance": graph_quality_metrics.get("avg_document_coverage_balance"),
            "avg_covered_document_count": graph_quality_metrics.get("avg_covered_document_count"),
            "avg_uploaded_document_count": graph_quality_metrics.get("avg_uploaded_document_count"),
            "avg_unsupported_document_count": graph_quality_metrics.get("avg_unsupported_document_count"),
        },
        "judge_parse_failure_count": int(sum(int(record.get("judge_parse_failure_count") or 0) for record in records)),
    }
    payload.update(
        _resolve_primary_metrics(
            latest_benchmark=latest_benchmark,
            live_window_metrics=live_window_metrics or {},
            historical_metrics=payload,
        )
    )
    payload.update(_build_status_counts(records))
    return payload


def _build_live_window_metrics(records: List[Dict[str, Any]], window_size: int = 50) -> Dict[str, Any]:
    live_rows = [record for record in records if record.get("evaluation_source") == "live"]
    window_rows = live_rows[:window_size]
    payload = _build_source_metrics_payload(window_rows, include_retrieval=False)
    payload.update({
        "window_size": window_size,
        "window_count": len(window_rows),
        "meets_final_rag_target": (
            (payload.get("avg_final_rag_score") or 0.0) >= 0.9
            if payload.get("answer_quality_count")
            else False
        ),
        "meets_faithfulness_target": (
            (payload.get("avg_faithfulness") or 0.0) >= 0.9
            if payload.get("answer_quality_count")
            else False
        ),
        "meets_hallucination_target": (
            (payload.get("avg_hallucination") or 1.0) <= 0.1
            if payload.get("answer_quality_count")
            else False
        ),
    })
    return payload


async def _build_feedback_loop_status(
    db,
    current_user: Dict[str, Any],
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    base_query: Dict[str, Any] = {}
    if not _is_admin_user(current_user):
        base_query["user_id"] = str(current_user["_id"])

    response_chunk_count = await db.response_chunks.count_documents(base_query)
    feedback_count = await db.feedback.count_documents(base_query)
    influence_log_count = await db.feedback_influence_log.count_documents(base_query)
    retrieval_penalty_count = await db.feedback_influence_log.count_documents({
        **base_query,
        "adjustment_type": "retrieval_penalty",
    })

    analyzer = FeedbackAnalyzer(db)
    subject = None
    live_subjects = [
        str(record.get("subject") or "").strip()
        for record in records
        if record.get("evaluation_source") == "live" and str(record.get("subject") or "").strip()
    ]
    if live_subjects:
        subject = live_subjects[0]

    try:
        penalty_signals = await analyzer.get_low_quality_chunk_signals(subject=subject)
    except Exception:
        penalty_signals = {"chunk_ids": [], "chunk_sources": []}

    live_rows = [record for record in records if record.get("evaluation_source") == "live"]
    tracked_live_references = {
        str(record.get("chat_id") or "")
        for record in live_rows
        if str(record.get("chat_id") or "")
    }

    return {
        "response_chunk_count": response_chunk_count,
        "feedback_count": feedback_count,
        "influence_log_count": influence_log_count,
        "retrieval_penalty_count": retrieval_penalty_count,
        "tracked_response_count": response_chunk_count,
        "tracking_populated": response_chunk_count > 0,
        "penalties_active": retrieval_penalty_count > 0 or bool(penalty_signals.get("chunk_ids") or penalty_signals.get("chunk_sources")),
        "low_quality_chunk_ids": len(penalty_signals.get("chunk_ids", [])),
        "low_quality_chunk_sources": len(penalty_signals.get("chunk_sources", [])),
        "live_validation_count": len(live_rows),
        "tracked_live_reference_count": len(tracked_live_references),
    }


async def _load_final_rows(
    db,
    current_user: Dict[str, Any],
    period: str = "all",
    source_filter: str = "ALL",
    status_filter: str = "ALL",
    sort_name: str = "NEWEST",
    limit: Optional[int] = None,
    skip: int = 0,
) -> List[Dict[str, Any]]:
    match_query = _build_log_match_query(
        period,
        current_user,
        source_filter=source_filter,
        status_filter=status_filter,
    )
    sort_spec = _resolve_log_sort(sort_name)
    cursor = db.rag_answer_validations.find(match_query).sort(sort_spec)
    if skip:
        cursor = cursor.skip(skip)
    if limit is not None:
        cursor = cursor.limit(limit)

    rows = await cursor.to_list(length=limit or 5000)
    return [_normalize_final_record(row) for row in rows]


def _build_final_report(
    records: List[Dict[str, Any]],
    latest_benchmark: Optional[Dict[str, Any]] = None,
    live_window_metrics: Optional[Dict[str, Any]] = None,
    feedback_loop_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metrics = _build_final_metrics_payload(
        records,
        latest_benchmark=latest_benchmark,
        live_window_metrics=live_window_metrics,
        feedback_loop_status=feedback_loop_status,
    )
    if not records and not latest_benchmark:
        return {
            "overall_status": "NO_DATA",
            "message": "No evaluation data yet. Send chat messages or run a benchmark first.",
            "metrics": metrics,
            "issues": [],
            "recommendations": [
                "Generate at least one live answer or run the benchmark to populate the dashboard."
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

    issues: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    live_metrics = metrics.get("live_metrics") or {}
    live_window_metrics = metrics.get("live_window_metrics") or {}
    benchmark_history_metrics = metrics.get("benchmark_history_metrics") or {}
    feedback_loop_status = metrics.get("feedback_loop_status") or {}
    assessment_basis = "latest_benchmark" if latest_benchmark else "historical_metrics"

    def add_issue(metric: str, value: Optional[float], threshold: str, severity: str, recommendation: str) -> None:
        issues.append({
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "severity": severity,
        })
        recommendations.append(recommendation)

    recall = (
        latest_benchmark.get("avg_recall_at_5")
        if latest_benchmark is not None
        else metrics.get("avg_recall_at_5")
    )
    benchmark_generation_valid = bool(latest_benchmark and latest_benchmark.get("generation_valid"))
    fallback_count = int(metrics.get("fallback_answer_count") or 0)
    generation_error_count = int(metrics.get("generation_error_count") or 0)
    quality_count = int(metrics.get("answer_quality_count") or 0)

    if latest_benchmark and int(latest_benchmark.get("generation_error_count") or 0) > 0:
        add_issue(
            "Latest Benchmark Generation Availability",
            latest_benchmark.get("generation_error_count"),
            "0 generation errors",
            "HIGH",
            "The latest benchmark preserved retrieval metrics, but answer generation failed for one or more samples. Restore LLM/API connectivity before treating benchmark generation scores as current quality.",
        )
    elif quality_count == 0 and generation_error_count > 0:
        add_issue(
            "Generation Availability",
            generation_error_count,
            "0 generation errors",
            "HIGH",
            "Retriever evidence is available, but answer generation is failing. Restore LLM/API connectivity before judging answer quality.",
        )

    if recall is not None and recall < 0.5:
        add_issue("Benchmark Recall@5", recall, ">= 0.50", "MEDIUM", "Tune retrieval weights or chunking strategy for better benchmark recall.")
    elif latest_benchmark is None and not metrics.get("benchmark_available"):
        recommendations.append("Run benchmark evaluation to populate retrieval metrics such as Recall@5, Precision@5, and MRR.")

    generation_metrics = latest_benchmark if benchmark_generation_valid else live_metrics
    generation_label = "Benchmark" if benchmark_generation_valid else "Live answer quality"
    faith = generation_metrics.get("avg_faithfulness")
    halluc = generation_metrics.get("avg_hallucination_rate") if benchmark_generation_valid else generation_metrics.get("avg_hallucination")
    bert = generation_metrics.get("avg_bert_score")
    citation = generation_metrics.get("avg_citation_alignment")
    relevance = generation_metrics.get("avg_answer_relevance")
    rag = generation_metrics.get("avg_final_rag_score")

    if faith is not None and faith < 0.9:
        add_issue(f"{generation_label} Faithfulness", faith, ">= 0.90", "HIGH", "Tighten grounding prompts and review unsupported sentences in low-scoring rows.")
    if halluc is not None and halluc > 0.1:
        add_issue(f"{generation_label} Hallucination Rate", halluc, "<= 0.10", "HIGH", "Reduce temperature or strengthen context-only answering rules.")
    if bert is not None and bert < 0.85:
        add_issue(f"{generation_label} BERTScore", bert, ">= 0.85", "MEDIUM", "Review semantic drift and encourage source terminology in generated answers.")
    if citation is not None and citation < 0.85:
        add_issue(f"{generation_label} Citation Alignment", citation, ">= 0.85", "MEDIUM", "Review citation prompting so only directly used chunks are cited.")
    if relevance is not None and relevance < 0.85:
        add_issue(f"{generation_label} Answer Relevance", relevance, ">= 0.85", "MEDIUM", "Refine prompt instructions to answer the question more directly.")
    if rag is not None and rag < 0.9:
        add_issue(f"{generation_label} Final RAG Score", rag, ">= 0.90", "HIGH", "Improve grounding and semantic match before expanding generation style.")

    if latest_benchmark and not benchmark_generation_valid and live_metrics.get("answer_quality_count"):
        recommendations.append(
            "Latest benchmark generation is not valid, so live answer-quality metrics are shown as secondary context only."
        )
    if live_window_metrics.get("answer_quality_count") and not live_window_metrics.get("meets_final_rag_target"):
        add_issue(
            "Live Window Final RAG Score",
            live_window_metrics.get("avg_final_rag_score"),
            ">= 0.90",
            "MEDIUM",
            "Recent live answers are below the 0.90 target. Fix live grounding quality before treating the dashboard as healthy.",
        )
    if not feedback_loop_status.get("tracking_populated"):
        recommendations.append(
            "Response-to-chunk tracking is not populated yet, so feedback cannot reliably demote weak chunks during retrieval."
        )
    elif not feedback_loop_status.get("penalties_active") and int(feedback_loop_status.get("feedback_count") or 0) > 0:
        recommendations.append(
            "Feedback is being collected, but retrieval penalties have not been triggered yet. Review whether new response feedback is reaching response_chunks correctly."
        )
    if live_window_metrics.get("answer_quality_count") and not live_window_metrics.get("meets_final_rag_target"):
        recommendations.append(
            "Recent live-window answer quality is below the 0.90 target. Use the live window as the freshness check after each fix."
        )
    if fallback_count > 0:
        recommendations.append("Review Gemini fallback answers separately from grounded RAG answers so retrieval quality is not blamed for no-context responses.")
    if generation_error_count > 0:
        recommendations.append("Generation outages are being tracked separately from true RAG-quality failures. Re-run benchmark after LLM connectivity is restored.")

    if not issues:
        overall_status = "STRONG" if (rag or 0) >= 0.7 else "STABLE"
        if not recommendations:
            recommendations.append("Continue monitoring fresh benchmark and live evaluation runs to track quality trends.")
    else:
        severities = {issue["severity"] for issue in issues}
        if latest_benchmark and not benchmark_generation_valid:
            overall_status = "DEGRADED"
        elif quality_count == 0 and generation_error_count > 0:
            overall_status = "DEGRADED"
        elif "HIGH" in severities:
            overall_status = "NEEDS_IMPROVEMENT"
        else:
            overall_status = "STABLE"

    deduped_recommendations: List[str] = []
    for item in recommendations:
        if item not in deduped_recommendations:
            deduped_recommendations.append(item)

    return {
        "overall_status": overall_status,
        "assessment_basis": assessment_basis,
        "metrics": metrics,
        "latest_benchmark": latest_benchmark,
        "live_metrics": live_metrics,
        "live_window_metrics": live_window_metrics,
        "benchmark_history_metrics": benchmark_history_metrics,
        "feedback_loop_status": feedback_loop_status,
        "issues": issues,
        "recommendations": deduped_recommendations,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/metrics")
async def get_evaluation_metrics(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Canonical aggregated evaluation metrics for the dashboard."""
    try:
        rows = await _load_final_rows(db, current_user, period=period)
        latest_benchmark = await _load_latest_benchmark_run(db, current_user)
        live_window_metrics = _build_live_window_metrics(rows)
        feedback_loop_status = await _build_feedback_loop_status(db, current_user, rows)
        return _build_final_metrics_payload(
            rows,
            latest_benchmark=latest_benchmark,
            live_window_metrics=live_window_metrics,
            feedback_loop_status=feedback_loop_status,
        )
    except Exception as e:
        import logging
        logging.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results/{result_id}", response_model=ValidationResult)
async def get_validation_result(
    result_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Get a single source-aware validation result by ID."""
    try:
        if not ObjectId.is_valid(result_id):
             raise HTTPException(status_code=400, detail="Invalid ID format")
             
        obj_id = ObjectId(result_id)
        result = await db.rag_answer_validations.find_one({"_id": obj_id})
        
        if not result:
            raise HTTPException(status_code=404, detail="Validation result not found")

        normalized = _normalize_final_record(result)
        if not _is_admin_user(current_user) and str(normalized.get("user_id") or "") != str(current_user["_id"]):
            raise HTTPException(status_code=403, detail="Not authorized to view this evaluation result")

        return ValidationResult(**normalized)
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Error fetching validation result {result_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs", response_model=List[ValidationResult])
async def get_validation_logs(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Recent source-aware validation logs."""
    try:
        rows = await _load_final_rows(db, current_user, period=period, limit=limit, skip=skip)
        return [ValidationResult(**row) for row in rows]
    except Exception as e:
        import logging
        logging.error(f"Error fetching logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run_benchmark")
async def trigger_benchmark_run(
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Trigger a benchmark evaluation run in the background."""
    from backend.core.evaluation.run_evaluation import run_benchmark

    async def _run():
        try:
            await run_benchmark(db)
        except Exception as e:
            import logging
            logging.error(f"Benchmark run failed: {e}")

    background_tasks.add_task(_run)
    return {"message": "Benchmark evaluation started in background. Results will appear in the dashboard within a few minutes."}


@router.post("/sync_history")
async def sync_chat_history(
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Analyze historical chat messages and add them to the evaluation system."""
    async def run_sync():
        from backend.core.evaluation.validator import ValidationEngine
        import logging
        validator = ValidationEngine(db)

        owner_id = str(current_user["_id"])
        sessions = await db.chat_sessions.find({"user_id": owner_id}).to_list(length=1000)
        new_validations = 0
        backfilled_by_id = 0
        backfilled_by_match = 0

        def _missing_chat_filter() -> Dict[str, Any]:
            return {
                "$or": [
                    {"chat_id": {"$exists": False}},
                    {"chat_id": None},
                    {"chat_id": ""}
                ]
            }

        def _parse_dt(value: Any) -> Any:
            def _normalize(dt: datetime) -> datetime:
                if dt.tzinfo is not None:
                    return dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt

            if isinstance(value, datetime):
                return _normalize(value)
            if isinstance(value, str):
                try:
                    return _normalize(datetime.fromisoformat(value.replace("Z", "+00:00")))
                except ValueError:
                    return None
            return None

        async def backfill_by_validation_id(validation_payload: Any, chat_id: str, user_id: str) -> bool:
            nonlocal backfilled_by_id
            if not isinstance(validation_payload, dict) or not chat_id or not user_id:
                return False

            for key in ("_id", "id"):
                raw_id = validation_payload.get(key)
                if not raw_id:
                    continue
                raw_id = str(raw_id)
                if not ObjectId.is_valid(raw_id):
                    continue

                oid = ObjectId(raw_id)
                result = await db.rag_answer_validations.update_one(
                    {"_id": oid, "user_id": user_id, **_missing_chat_filter()},
                    {"$set": {"chat_id": chat_id}}
                )
                if result.modified_count:
                    backfilled_by_id += 1
                    return True

                existing = await db.rag_answer_validations.find_one(
                    {"_id": oid, "user_id": user_id},
                    {"chat_id": 1}
                )
                if existing and existing.get("chat_id") == chat_id:
                    return True

            return False

        async def backfill_by_content_match(
            question: str,
            answer: str,
            chat_id: str,
            assistant_ts: Any,
            user_id: str
        ) -> bool:
            nonlocal backfilled_by_match

            if not question or not answer or not chat_id or not user_id:
                return False

            candidates = await db.rag_answer_validations.find({
                "user_id": user_id,
                "question": question,
                "answer": answer
            }).to_list(length=50)

            if not candidates:
                return False

            unresolved = []
            for candidate in candidates:
                candidate_chat = candidate.get("chat_id")
                if candidate_chat == chat_id:
                    return True
                if candidate_chat:
                    continue
                unresolved.append(candidate)

            if not unresolved:
                return False

            if len(unresolved) == 1:
                result = await db.rag_answer_validations.update_one(
                    {"_id": unresolved[0]["_id"], **_missing_chat_filter()},
                    {"$set": {"chat_id": chat_id}}
                )
                if result.modified_count:
                    backfilled_by_match += 1
                    return True
                return False

            msg_ts = _parse_dt(assistant_ts)
            if not msg_ts:
                return False

            scored = []
            for candidate in unresolved:
                candidate_ts = _parse_dt(candidate.get("timestamp"))
                if not candidate_ts:
                    continue
                scored.append((abs((candidate_ts - msg_ts).total_seconds()), candidate))

            if not scored:
                return False

            scored.sort(key=lambda item: item[0])
            if len(scored) > 1 and scored[0][0] == scored[1][0]:
                return False

            # Correctness-first: only accept a uniquely nearest timestamp within a tight window.
            if scored[0][0] > 300:
                return False

            result = await db.rag_answer_validations.update_one(
                {"_id": scored[0][1]["_id"], **_missing_chat_filter()},
                {"$set": {"chat_id": chat_id}}
            )
            if result.modified_count:
                backfilled_by_match += 1
                return True

            return False

        for session in sessions:
            user_id = session.get("user_id")
            subject = session.get("subject", "general")
            chat_id = session.get("chat_id")
            messages = session.get("messages", [])

            for i in range(1, len(messages)):
                msg = messages[i]
                prev_msg = messages[i - 1]

                if msg.get("role") != "assistant" or prev_msg.get("role") != "user":
                    continue

                question = prev_msg.get("content", "")
                answer = msg.get("content", "")

                matched_by_id = await backfill_by_validation_id(
                    msg.get("validation_result"),
                    chat_id,
                    user_id
                )
                matched_by_content = await backfill_by_content_match(
                    question,
                    answer,
                    chat_id,
                    msg.get("timestamp"),
                    user_id
                )

                existing_for_session = await db.rag_answer_validations.find_one({
                    "user_id": user_id,
                    "question": question,
                    "answer": answer,
                    "chat_id": chat_id
                })

                if existing_for_session or matched_by_id or matched_by_content:
                    continue

                # Keep correctness-first behavior for historical duplicates:
                # if an unlinked or conflicting duplicate exists, do not guess-create another row.
                existing_any = await db.rag_answer_validations.find_one({
                    "user_id": user_id,
                    "question": question,
                    "answer": answer
                })
                if existing_any:
                    continue

                if not msg.get("chunks"):
                    continue

                try:
                    await validator.validate_answer(
                        question=question,
                        answer=answer,
                        retrieved_chunks=msg["chunks"],
                        user_id=user_id,
                        subject=subject,
                        document_id=session.get("document_id"),
                        chat_id=chat_id,
                        evaluation_source="synced_history"
                    )
                    new_validations += 1
                except Exception as e:
                    logging.error(f"Sync error for msg {i}: {e}")

        logging.info(
            "[EVAL SYNC] complete: new=%s, backfilled_by_id=%s, backfilled_by_match=%s",
            new_validations,
            backfilled_by_id,
            backfilled_by_match
        )

    background_tasks.add_task(run_sync)
    return {"message": "Sync started in background"}


@router.post("/normalize_statuses")
async def normalize_validation_statuses(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    validations = await db.rag_answer_validations.find({}).to_list(length=100000)
    validation_updates = 0
    for row in validations:
        normalized_status = normalize_validation_status(row.get("validation_status"))
        if str(row.get("validation_status") or "").strip().upper() == normalized_status:
            continue
        result = await db.rag_answer_validations.update_one(
            {"_id": row["_id"]},
            {"$set": {"validation_status": normalized_status}},
        )
        validation_updates += int(result.modified_count or 0)

    benchmark_runs = await db.benchmark_runs.find({}).to_list(length=10000)
    benchmark_updates = 0
    for run in benchmark_runs:
        verified_count = int(run.get("verified_count") or 0) + int(run.get("warning_count") or 0)
        rejected_count = int(run.get("rejected_count") or 0)
        update_payload = {
            "verified_count": verified_count,
            "rejected_count": rejected_count,
        }
        if "warning_count" in run:
            update_payload["warning_count"] = 0
        result = await db.benchmark_runs.update_one(
            {"_id": run["_id"]},
            {"$set": update_payload},
        )
        benchmark_updates += int(result.modified_count or 0)

    return {
        "message": "Validation statuses normalized",
        "validation_rows_updated": validation_updates,
        "benchmark_runs_updated": benchmark_updates,
    }


@router.get("/final/metrics")
async def get_final_evaluation_metrics(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        rows = await _load_final_rows(db, current_user, period=period)
        latest_benchmark = await _load_latest_benchmark_run(db, current_user)
        live_window_metrics = _build_live_window_metrics(rows)
        feedback_loop_status = await _build_feedback_loop_status(db, current_user, rows)
        return _build_final_metrics_payload(
            rows,
            latest_benchmark=latest_benchmark,
            live_window_metrics=live_window_metrics,
            feedback_loop_status=feedback_loop_status,
        )
    except Exception as e:
        import logging
        logging.error(f"Error fetching final metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/final/logs")
async def get_final_evaluation_logs(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    source: str = Query("ALL", description="Source filter: ALL, BENCHMARK, LIVE, SYNCED_HISTORY"),
    status: str = Query("ALL", description="Status filter: ALL, VERIFIED, REJECTED"),
    sort: str = Query("NEWEST", description="Sort: NEWEST, OLDEST, RAG_ASC, RAG_DESC, HALLUC_DESC"),
    attention_only: bool = Query(False, description="Only include rejected or low-quality rows."),
    include_summary: bool = Query(False, description="Return pagination and query insights alongside rows."),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        normalized_source = _normalize_log_source(source)
        normalized_status = _normalize_log_status(status)
        normalized_sort = _normalize_log_sort(sort)

        if include_summary or attention_only:
            all_rows = await _load_final_rows(
                db,
                current_user,
                period=period,
                source_filter=normalized_source,
                status_filter=normalized_status,
                sort_name=normalized_sort,
            )
            filtered_rows = [row for row in all_rows if _is_attention_record(row)] if attention_only else all_rows
            rows = filtered_rows[skip: skip + limit]
            for row in rows:
                row["benchmark_metrics_available"] = row.get("evaluation_source") == "benchmark"
            return {
                "rows": rows,
                "pagination": {
                    "total_count": len(filtered_rows),
                    "skip": skip,
                    "limit": limit,
                    "returned_count": len(rows),
                    "has_more": (skip + len(rows)) < len(filtered_rows),
                    "page": (skip // limit) + 1,
                },
                "active_filters": {
                    "period": period,
                    "source": normalized_source,
                    "status": normalized_status,
                    "sort": normalized_sort,
                    "attention_only": attention_only,
                },
                "source_counts": _build_log_source_counts(filtered_rows),
                "status_counts": _build_status_counts(filtered_rows),
                "daily_counts": _build_daily_counts(filtered_rows),
                "recent_questions": {
                    "benchmark": _build_recent_questions(filtered_rows, "benchmark"),
                    "live": _build_recent_questions(filtered_rows, "live"),
                    "synced_history": _build_recent_questions(filtered_rows, "synced_history"),
                },
                "trend_rows": filtered_rows[:120],
                "query_patterns": _build_query_patterns(filtered_rows),
                "needs_attention": _build_attention_summary(filtered_rows),
            }

        rows = await _load_final_rows(
            db,
            current_user,
            period=period,
            source_filter=normalized_source,
            status_filter=normalized_status,
            sort_name=normalized_sort,
            limit=limit,
            skip=skip,
        )
        for row in rows:
            row["benchmark_metrics_available"] = row.get("evaluation_source") == "benchmark"
        return rows
    except Exception as e:
        import logging
        logging.error(f"Error fetching final logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/final/results/{result_id}")
async def get_final_validation_result(
    result_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        if not ObjectId.is_valid(result_id):
            raise HTTPException(status_code=400, detail="Invalid ID format")

        obj_id = ObjectId(result_id)
        result = await db.rag_answer_validations.find_one({"_id": obj_id})
        if not result:
            raise HTTPException(status_code=404, detail="Validation result not found")

        normalized = _normalize_final_record(result)
        if not _is_admin_user(current_user) and str(normalized.get("user_id") or "") != str(current_user["_id"]):
            raise HTTPException(status_code=403, detail="Not authorized to view this evaluation result")

        normalized["benchmark_metrics_available"] = normalized.get("evaluation_source") == "benchmark"
        return normalized
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Error fetching final validation result {result_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/final/report")
async def get_final_evaluation_report(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        rows = await _load_final_rows(db, current_user, period=period)
        latest_benchmark = await _load_latest_benchmark_run(db, current_user)
        live_window_metrics = _build_live_window_metrics(rows)
        feedback_loop_status = await _build_feedback_loop_status(db, current_user, rows)
        return _build_final_report(
            rows,
            latest_benchmark=latest_benchmark,
            live_window_metrics=live_window_metrics,
            feedback_loop_status=feedback_loop_status,
        )
    except Exception as e:
        import logging
        logging.error(f"Error fetching final report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/report")
async def get_evaluation_report(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Auto-debug report with root cause analysis and tuning recommendations.
    """
    try:
        rows = await _load_final_rows(db, current_user, period=period)
        latest_benchmark = await _load_latest_benchmark_run(db, current_user)
        live_window_metrics = _build_live_window_metrics(rows)
        feedback_loop_status = await _build_feedback_loop_status(db, current_user, rows)
        return _build_final_report(
            rows,
            latest_benchmark=latest_benchmark,
            live_window_metrics=live_window_metrics,
            feedback_loop_status=feedback_loop_status,
        )
    except Exception as e:
        import logging
        logging.error(f"Report generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clear")
async def clear_evaluation_data(
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Clear all evaluation data for a fresh start."""
    try:
        if _is_admin_user(current_user):
            validation_query = {}
            benchmark_query = {}
        else:
            validation_query = {"user_id": str(current_user["_id"])}
            benchmark_query = {"user_id": str(current_user["_id"])}

        r1 = await db.rag_answer_validations.delete_many(validation_query)
        r2 = await db.benchmark_runs.delete_many(benchmark_query)
        return {
            "message": "All evaluation data cleared",
            "validations_deleted": r1.deleted_count,
            "benchmarks_deleted": r2.deleted_count
        }
    except Exception as e:
        import logging
        logging.error(f"Clear failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
