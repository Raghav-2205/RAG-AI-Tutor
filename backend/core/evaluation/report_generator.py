# backend/core/evaluation/report_generator.py
"""
Auto-debug report generator.

Analyzes evaluation results and produces:
  - Aggregated metrics
  - Overall health status
  - Root cause analysis for failing metrics
  - Tuning recommendations
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from backend.core.evaluation.metrics import calculate_final_rag_score
from backend.core.feedback_analyzer import FeedbackAnalyzer
from backend.core.evaluation.status_policy import normalize_validation_record, normalize_validation_status

logger = logging.getLogger(__name__)

# Thresholds
THRESHOLDS = {
    "recall_at_5": 0.7,
    "faithfulness": 0.85,
    "hallucination_rate": 0.15,  # max
    "bert_score": 0.85,
    "citation_alignment": 0.8,
    "answer_relevance": 0.8,
    "final_rag_score": 0.7,
}
GENERATION_FAILURE_PREFIXES = (
    "llm async request failed",
    "llm request failed",
    "llm api error",
    "error: no gemini api key",
)


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _infer_source(record: Dict[str, Any]) -> str:
    explicit = str(record.get("evaluation_source") or "").strip().lower()
    if explicit in {"live", "benchmark", "synced_history"}:
        return explicit
    if str(record.get("user_id") or "") == "benchmark_runner":
        return "benchmark"
    return "live"


def _is_generation_error(record: Dict[str, Any]) -> bool:
    source_mode = str(record.get("answer_source_mode") or "").strip().lower()
    if source_mode == "error":
        return True
    answer_text = str(record.get("answer") or "").strip().lower()
    if any(answer_text.startswith(prefix) for prefix in GENERATION_FAILURE_PREFIXES):
        return True
    reason = str(record.get("reason") or "").strip().lower()
    return "answer generation failed" in reason or "llm " in reason


def _quality_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    valid_rows = []
    for row in rows:
        if _is_generation_error(row):
            continue
        valid_rows.append(row)
    return valid_rows


def _average(rows: List[Dict[str, Any]], field: str) -> float | None:
    values = [_coerce_float(row.get(field)) for row in rows]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 4)


def _average_nested(rows: List[Dict[str, Any]], field: str, nested_field: str) -> float | None:
    numeric: List[float] = []
    for row in rows:
        nested = row.get(field) or {}
        if isinstance(nested, dict):
            value = _coerce_float(nested.get(nested_field))
            if value is not None:
                numeric.append(value)
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 4)


def _build_graph_quality_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    graph_rows = [
        row for row in rows
        if isinstance(row.get("graph_quality_metrics"), dict) and row.get("graph_quality_metrics")
    ]
    multi_doc_rows = [
        row for row in rows
        if isinstance(row.get("multi_document_metrics"), dict)
        and row.get("multi_document_metrics", {}).get("graph_used")
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


def _build_source_metrics_payload(rows: List[Dict[str, Any]], include_retrieval: bool = False) -> Dict[str, Any]:
    quality_rows = _quality_rows(rows)
    generation_error_rows = [row for row in rows if _is_generation_error(row)]
    payload = {
        "total_validations": len(rows),
        "answer_quality_count": len(quality_rows),
        "generation_error_count": len(generation_error_rows),
        "avg_faithfulness": _average(quality_rows, "faithfulness_score"),
        "avg_hallucination": _average(quality_rows, "hallucination_rate"),
        "avg_bert_score": _average(quality_rows, "bert_score"),
        "avg_cosine_similarity": _average(quality_rows, "cosine_similarity"),
        "avg_citation_alignment": _average(quality_rows, "citation_alignment_score"),
        "avg_answer_relevance": _average(quality_rows, "answer_relevance"),
        "avg_final_rag_score": _average(quality_rows, "effective_final_rag_score"),
        "avg_judge_parse_failure_count": _average(rows, "judge_parse_failure_count"),
        "judge_fallback_count": sum(1 for row in rows if row.get("judge_fallback_used")),
    }
    if include_retrieval:
        payload.update({
            "avg_recall_at_5": _average(rows, "recall_at_5"),
            "avg_precision_at_5": _average(rows, "precision_at_5"),
            "avg_mrr": _average(rows, "mrr"),
        })
    return payload


def _build_live_window_metrics(rows: List[Dict[str, Any]], window_size: int = 50) -> Dict[str, Any]:
    def sort_key(item: Dict[str, Any]) -> str:
        value = item.get("timestamp")
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value or "")

    ordered_live_rows = sorted(
        [row for row in rows if row.get("evaluation_source") == "live"],
        key=sort_key,
        reverse=True,
    )
    window_rows = ordered_live_rows[:window_size]
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


async def _build_feedback_loop_status(db, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    response_chunk_count = await db.response_chunks.count_documents({})
    feedback_count = await db.feedback.count_documents({})
    influence_log_count = await db.feedback_influence_log.count_documents({})
    retrieval_penalty_count = await db.feedback_influence_log.count_documents({
        "adjustment_type": "retrieval_penalty"
    })

    analyzer = FeedbackAnalyzer(db)
    live_subjects = [
        str(row.get("subject") or "").strip()
        for row in rows
        if row.get("evaluation_source") == "live" and str(row.get("subject") or "").strip()
    ]
    subject = live_subjects[0] if live_subjects else None
    try:
        penalty_signals = await analyzer.get_low_quality_chunk_signals(subject=subject)
    except Exception:
        penalty_signals = {"chunk_ids": [], "chunk_sources": []}

    return {
        "response_chunk_count": response_chunk_count,
        "feedback_count": feedback_count,
        "influence_log_count": influence_log_count,
        "retrieval_penalty_count": retrieval_penalty_count,
        "tracking_populated": response_chunk_count > 0,
        "penalties_active": retrieval_penalty_count > 0 or bool(penalty_signals.get("chunk_ids") or penalty_signals.get("chunk_sources")),
        "low_quality_chunk_ids": len(penalty_signals.get("chunk_ids", [])),
        "low_quality_chunk_sources": len(penalty_signals.get("chunk_sources", [])),
    }


def _normalize_benchmark_run(run: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not run:
        return None

    total_samples = int(run.get("total_samples") or 0)
    answer_quality_count = int(run.get("answer_quality_count") or run.get("completed") or 0)
    generation_error_count = int(run.get("generation_error_count") or 0)
    unexpected_error_count = int(run.get("unexpected_error_count") or 0)
    generation_valid = bool(run.get("generation_valid")) if "generation_valid" in run else (
        answer_quality_count > 0 and generation_error_count == 0 and unexpected_error_count == 0
    )

    return {
        "timestamp": run.get("timestamp"),
        "created_at": run.get("created_at"),
        "total_samples": total_samples,
        "completed": answer_quality_count,
        "answer_quality_count": answer_quality_count,
        "generation_error_count": generation_error_count,
        "unexpected_error_count": unexpected_error_count,
        "failure_count": int(run.get("failure_count") or generation_error_count + unexpected_error_count),
        "failure_rate": _coerce_float(run.get("failure_rate"))
        if _coerce_float(run.get("failure_rate")) is not None
        else (round((generation_error_count + unexpected_error_count) / total_samples, 4) if total_samples else 0.0),
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
    }


async def generate_report(db, period: str = "all") -> Dict[str, Any]:
    """
    Generate a comprehensive evaluation report with auto-debug analysis.
    """
    # Build time filter
    match_query = {}
    if period == "24h":
        match_query["timestamp"] = {"$gte": datetime.utcnow() - timedelta(hours=24)}
    elif period == "7d":
        match_query["timestamp"] = {"$gte": datetime.utcnow() - timedelta(days=7)}

    rows = await db.rag_answer_validations.find(match_query).to_list(length=5000)
    latest_benchmark = _normalize_benchmark_run(
        await db.benchmark_runs.find_one({}, sort=[("created_at", -1)])
    )

    if not rows and not latest_benchmark:
        return {
            "overall_status": "NO_DATA",
            "message": "No validation records found. Run a benchmark or send chat queries first.",
            "metrics": {},
            "recommendations": [],
            "timestamp": datetime.utcnow().isoformat()
        }

    normalized_rows = []
    benchmark_rows = []
    for row in rows:
        source = _infer_source(row)
        recall = _coerce_float(row.get("recall_at_5")) if source == "benchmark" else None
        effective_score = calculate_final_rag_score(
            recall_at_5=recall,
            faithfulness=_coerce_float(row.get("faithfulness_score")),
            bert_score_val=_coerce_float(row.get("bert_score")),
            citation_alignment=_coerce_float(row.get("citation_alignment_score")),
            answer_relevance=_coerce_float(row.get("answer_relevance")),
        )
        normalized = dict(row)
        normalized = normalize_validation_record(normalized)
        normalized["evaluation_source"] = source
        normalized["effective_final_rag_score"] = effective_score
        normalized_rows.append(normalized)
        if source == "benchmark":
            benchmark_rows.append(normalized)
    live_rows = [row for row in normalized_rows if row.get("evaluation_source") == "live"]
    quality_rows = _quality_rows(normalized_rows)
    generation_error_rows = [row for row in normalized_rows if _is_generation_error(row)]
    live_metrics = _build_source_metrics_payload(live_rows, include_retrieval=False)
    live_window_metrics = _build_live_window_metrics(normalized_rows)
    benchmark_history_metrics = _build_source_metrics_payload(benchmark_rows, include_retrieval=True)
    feedback_loop_status = await _build_feedback_loop_status(db, normalized_rows)
    graph_quality_metrics = _build_graph_quality_metrics(normalized_rows)

    metrics = {
        "total": len(normalized_rows),
        "answer_quality_count": len(quality_rows),
        "generation_error_count": len(generation_error_rows),
        "avg_faithfulness": _average(quality_rows, "faithfulness_score"),
        "avg_hallucination": _average(quality_rows, "hallucination_rate"),
        "avg_bert_score": _average(quality_rows, "bert_score"),
        "avg_cosine_similarity": _average(quality_rows, "cosine_similarity"),
        "avg_citation_alignment": _average(quality_rows, "citation_alignment_score"),
        "avg_answer_relevance": _average(quality_rows, "answer_relevance"),
        "avg_recall_at_5": _average(benchmark_rows, "recall_at_5"),
        "avg_precision_at_5": _average(benchmark_rows, "precision_at_5"),
        "avg_mrr": _average(benchmark_rows, "mrr"),
        "avg_final_rag_score": _average(quality_rows, "effective_final_rag_score"),
        "verified": sum(1 for row in normalized_rows if normalize_validation_status(row.get("validation_status")) == "VERIFIED"),
        "rejected": sum(1 for row in normalized_rows if normalize_validation_status(row.get("validation_status")) == "REJECTED"),
        "errors": sum(1 for row in normalized_rows if _is_generation_error(row)),
        "benchmark_available": bool(benchmark_rows),
        "latest_benchmark": latest_benchmark,
        "live_metrics": live_metrics,
        "live_window_metrics": live_window_metrics,
        "benchmark_history_metrics": benchmark_history_metrics,
        "feedback_loop_status": feedback_loop_status,
        "graph_quality_metrics": graph_quality_metrics,
        "multi_document_metrics": {
            "multi_document_answer_count": graph_quality_metrics.get("multi_document_answer_count", 0),
            "avg_document_coverage_balance": graph_quality_metrics.get("avg_document_coverage_balance"),
            "avg_covered_document_count": graph_quality_metrics.get("avg_covered_document_count"),
            "avg_uploaded_document_count": graph_quality_metrics.get("avg_uploaded_document_count"),
            "avg_unsupported_document_count": graph_quality_metrics.get("avg_unsupported_document_count"),
        },
        "judge_parse_failure_count": int(sum(int(row.get("judge_parse_failure_count") or 0) for row in normalized_rows)),
    }

    # ── Diagnose issues ──
    issues = []
    recommendations = []

    benchmark_generation_valid = bool(latest_benchmark and latest_benchmark.get("generation_valid"))
    generation_metrics = latest_benchmark if benchmark_generation_valid else live_metrics
    metric_prefix = "Benchmark" if benchmark_generation_valid else "Live answer quality"
    avg_faith = generation_metrics.get("avg_faithfulness")
    avg_halluc = generation_metrics.get("avg_hallucination_rate") if benchmark_generation_valid else generation_metrics.get("avg_hallucination")
    avg_bert = generation_metrics.get("avg_bert_score")
    avg_recall = latest_benchmark.get("avg_recall_at_5") if latest_benchmark else metrics.get("avg_recall_at_5")
    avg_citation = generation_metrics.get("avg_citation_alignment")
    avg_relevance = generation_metrics.get("avg_answer_relevance")
    avg_final = generation_metrics.get("avg_final_rag_score")
    generation_error_count = int(metrics.get("generation_error_count") or 0)
    answer_quality_count = int(metrics.get("answer_quality_count") or 0)

    if latest_benchmark and int(latest_benchmark.get("generation_error_count") or 0) > 0:
        issues.append({
            "metric": "Latest Benchmark Generation Availability",
            "value": latest_benchmark.get("generation_error_count"),
            "threshold": 0,
            "severity": "HIGH"
        })
        recommendations.append(
            "Restore LLM/API connectivity before treating the latest benchmark as a valid generation-quality baseline."
        )
    elif answer_quality_count == 0 and generation_error_count > 0:
        issues.append({
            "metric": "Generation Availability",
            "value": generation_error_count,
            "threshold": 0,
            "severity": "HIGH"
        })
        recommendations.append(
            "Restore LLM/API connectivity before using answer-quality metrics as a judgment of RAG quality."
        )

    # Recall@5 issues → Retrieval problems
    if metrics.get("benchmark_available") and avg_recall is not None and avg_recall < THRESHOLDS["recall_at_5"]:
        issues.append({
            "metric": "Recall@5",
            "value": round(avg_recall, 3),
            "threshold": THRESHOLDS["recall_at_5"],
            "severity": "HIGH"
        })
        recommendations.extend([
            "📈 Increase retrieval top_k from current value to 8–10",
            "🔧 Adjust hybrid search weights: increase dense_weight to 0.6, reduce bm25_weight to 0.4",
            "📄 Improve chunk_size (try 800) and chunk_overlap (try 150) for better coverage",
            "🔍 Strengthen the cross-encoder reranker or switch to a larger model"
        ])

    # Faithfulness issues → Grounding problems
    if avg_faith is not None and avg_faith < THRESHOLDS["faithfulness"]:
        issues.append({
            "metric": f"{metric_prefix} Faithfulness",
            "value": round(avg_faith, 3),
            "threshold": THRESHOLDS["faithfulness"],
            "severity": "CRITICAL"
        })
        recommendations.extend([
            "⚠️ CRITICAL: Tighten the system prompt to enforce strict grounding",
            "🔒 Add explicit instruction: 'ONLY use information from the provided chunks'",
            "🔀 Enable strict_mode=True for RAG generation by default",
            "📊 Review unsupported_sentences in validation logs to identify common failure patterns"
        ])

    # Hallucination rate
    if avg_halluc is not None and avg_halluc > THRESHOLDS["hallucination_rate"]:
        issues.append({
            "metric": f"{metric_prefix} Hallucination Rate",
            "value": round(avg_halluc, 3),
            "threshold": THRESHOLDS["hallucination_rate"],
            "severity": "CRITICAL"
        })
        recommendations.extend([
            "🚨 High hallucination rate detected — review LLM temperature setting (try 0.3–0.5)",
            "📝 Constrain output generation with structured output format",
            "🔄 Consider using a more grounded LLM model or adding a post-generation filter"
        ])

    # BERTScore issues → Semantic drift
    if avg_bert is not None and avg_bert < THRESHOLDS["bert_score"]:
        issues.append({
            "metric": f"{metric_prefix} BERTScore",
            "value": round(avg_bert, 3),
            "threshold": THRESHOLDS["bert_score"],
            "severity": "MEDIUM"
        })
        recommendations.extend([
            "🧠 Low semantic overlap — answers may be paraphrasing too heavily",
            "📋 Encourage the LLM to use terminology from the source material"
        ])

    # Citation alignment
    if avg_citation is not None and avg_citation < THRESHOLDS["citation_alignment"]:
        issues.append({
            "metric": f"{metric_prefix} Citation Alignment",
            "value": round(avg_citation, 3),
            "threshold": THRESHOLDS["citation_alignment"],
            "severity": "MEDIUM"
        })
        recommendations.extend([
            "📎 Citations are misaligned — LLM may be citing wrong chunks",
            "✏️ Update the prompt to enforce: 'Only cite a chunk if you directly use information from it'"
        ])

    if not latest_benchmark and not metrics.get("benchmark_available"):
        recommendations.append(
            "Run the benchmark suite to populate retrieval metrics such as Recall@5, Precision@5, and MRR."
        )
    if latest_benchmark and not benchmark_generation_valid and live_metrics.get("answer_quality_count"):
        recommendations.append(
            "Latest benchmark generation is not valid, so live answer-quality metrics are shown as secondary context only."
        )
    if not feedback_loop_status.get("tracking_populated"):
        recommendations.append(
            "Response-chunk tracking is empty, so the feedback loop cannot demote weak chunks yet."
        )
    elif not feedback_loop_status.get("penalties_active") and int(feedback_loop_status.get("feedback_count") or 0) > 0:
        recommendations.append(
            "Feedback is being captured, but retrieval penalties have not activated yet. Check response reference mapping and chunk tracking."
        )
    if live_window_metrics.get("answer_quality_count") and not live_window_metrics.get("meets_final_rag_target"):
        recommendations.append(
            "The recent live validation window is still below the 0.90 quality target. Use this rolling window to judge the post-fix pipeline rather than all-time history."
        )
    if generation_error_count > 0:
        recommendations.append(
            "Treat generation outages separately from retrieval quality. Current retrieval metrics may still be valid even when the answer text is an LLM error."
        )

    # Overall status
    critical_count = sum(1 for i in issues if i["severity"] == "CRITICAL")
    high_count = sum(1 for i in issues if i["severity"] == "HIGH")

    if latest_benchmark and not benchmark_generation_valid:
        overall_status = "DEGRADED"
    elif answer_quality_count == 0 and generation_error_count > 0:
        overall_status = "DEGRADED"
    elif critical_count > 0:
        overall_status = "FAILING"
    elif high_count > 0:
        overall_status = "DEGRADED"
    elif len(issues) > 0:
        overall_status = "NEEDS_ATTENTION"
    else:
        overall_status = "HEALTHY"

    # Deduplicate recommendations
    seen = set()
    unique_recs = []
    for r in recommendations:
        if r not in seen:
            seen.add(r)
            unique_recs.append(r)

    report = {
        "overall_status": overall_status,
        "assessment_basis": "latest_benchmark" if latest_benchmark else "historical_metrics",
        "period": period,
        "metrics": {
            "total_validations": metrics.get("total", 0),
            "avg_faithfulness": round(avg_faith or 0, 4),
            "avg_hallucination_rate": round(avg_halluc or 0, 4),
            "avg_bert_score": round(avg_bert or 0, 4),
            "avg_cosine_similarity": round(metrics.get("avg_cosine_similarity", 0) or 0, 4),
            "avg_citation_alignment": round(avg_citation or 0, 4),
            "avg_answer_relevance": round(avg_relevance or 0, 4),
            "avg_recall_at_5": round(avg_recall or 0, 4),
            "avg_precision_at_5": round(metrics.get("avg_precision_at_5", 0) or 0, 4),
            "avg_mrr": round(metrics.get("avg_mrr", 0) or 0, 4),
            "avg_final_rag_score": round(avg_final or 0, 4),
            "verified": metrics.get("verified", 0),
            "warnings": metrics.get("warnings", 0),
            "rejected": metrics.get("rejected", 0),
            "errors": metrics.get("errors", 0),
            "insufficient_context": metrics.get("insufficient", 0),
        },
        "latest_benchmark": latest_benchmark,
        "live_metrics": live_metrics,
        "live_window_metrics": live_window_metrics,
        "benchmark_history_metrics": benchmark_history_metrics,
        "feedback_loop_status": feedback_loop_status,
        "graph_quality_metrics": graph_quality_metrics,
        "multi_document_metrics": {
            "multi_document_answer_count": graph_quality_metrics.get("multi_document_answer_count", 0),
            "avg_document_coverage_balance": graph_quality_metrics.get("avg_document_coverage_balance"),
            "avg_covered_document_count": graph_quality_metrics.get("avg_covered_document_count"),
            "avg_uploaded_document_count": graph_quality_metrics.get("avg_uploaded_document_count"),
            "avg_unsupported_document_count": graph_quality_metrics.get("avg_unsupported_document_count"),
        },
        "judge_parse_failure_count": int(sum(int(row.get("judge_parse_failure_count") or 0) for row in normalized_rows)),
        "thresholds": THRESHOLDS,
        "issues": issues,
        "recommendations": unique_recs,
        "timestamp": datetime.utcnow().isoformat()
    }

    return report
