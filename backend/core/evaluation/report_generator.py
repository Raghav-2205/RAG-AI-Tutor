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


def _average(rows: List[Dict[str, Any]], field: str) -> float | None:
    values = [_coerce_float(row.get(field)) for row in rows]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 4)


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

    if not rows:
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
        normalized["evaluation_source"] = source
        normalized["effective_final_rag_score"] = effective_score
        normalized_rows.append(normalized)
        if source == "benchmark":
            benchmark_rows.append(normalized)

    metrics = {
        "total": len(normalized_rows),
        "avg_faithfulness": _average(normalized_rows, "faithfulness_score"),
        "avg_hallucination": _average(normalized_rows, "hallucination_rate"),
        "avg_bert_score": _average(normalized_rows, "bert_score"),
        "avg_cosine_similarity": _average(normalized_rows, "cosine_similarity"),
        "avg_citation_alignment": _average(normalized_rows, "citation_alignment_score"),
        "avg_answer_relevance": _average(normalized_rows, "answer_relevance"),
        "avg_recall_at_5": _average(benchmark_rows, "recall_at_5"),
        "avg_precision_at_5": _average(benchmark_rows, "precision_at_5"),
        "avg_mrr": _average(benchmark_rows, "mrr"),
        "avg_final_rag_score": _average(normalized_rows, "effective_final_rag_score"),
        "verified": sum(1 for row in normalized_rows if str(row.get("validation_status") or "").upper() == "VERIFIED"),
        "warnings": sum(1 for row in normalized_rows if str(row.get("validation_status") or "").upper() == "WARNING"),
        "rejected": sum(1 for row in normalized_rows if str(row.get("validation_status") or "").upper() == "REJECTED"),
        "errors": sum(1 for row in normalized_rows if str(row.get("validation_status") or "").upper() == "ERROR"),
        "insufficient": sum(1 for row in normalized_rows if str(row.get("validation_status") or "").upper() == "INSUFFICIENT_CONTEXT"),
        "benchmark_available": bool(benchmark_rows),
    }

    # ── Diagnose issues ──
    issues = []
    recommendations = []

    avg_faith = metrics.get("avg_faithfulness")
    avg_halluc = metrics.get("avg_hallucination")
    avg_bert = metrics.get("avg_bert_score")
    avg_recall = metrics.get("avg_recall_at_5")
    avg_citation = metrics.get("avg_citation_alignment")
    avg_relevance = metrics.get("avg_answer_relevance")
    avg_final = metrics.get("avg_final_rag_score")

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
            "metric": "Faithfulness",
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
            "metric": "Hallucination Rate",
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
            "metric": "BERTScore",
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
            "metric": "Citation Alignment",
            "value": round(avg_citation, 3),
            "threshold": THRESHOLDS["citation_alignment"],
            "severity": "MEDIUM"
        })
        recommendations.extend([
            "📎 Citations are misaligned — LLM may be citing wrong chunks",
            "✏️ Update the prompt to enforce: 'Only cite a chunk if you directly use information from it'"
        ])

    if not metrics.get("benchmark_available"):
        recommendations.append(
            "Run the benchmark suite to populate retrieval metrics such as Recall@5, Precision@5, and MRR."
        )

    # Overall status
    critical_count = sum(1 for i in issues if i["severity"] == "CRITICAL")
    high_count = sum(1 for i in issues if i["severity"] == "HIGH")

    if critical_count > 0:
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
        "thresholds": THRESHOLDS,
        "issues": issues,
        "recommendations": unique_recs,
        "timestamp": datetime.utcnow().isoformat()
    }

    return report
