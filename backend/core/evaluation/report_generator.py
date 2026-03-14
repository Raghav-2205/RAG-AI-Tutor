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

    # Aggregate metrics from rag_answer_validations
    pipeline = [
        {"$match": match_query},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "avg_faithfulness": {"$avg": "$faithfulness_score"},
            "avg_hallucination": {"$avg": "$hallucination_rate"},
            "avg_bert_score": {"$avg": "$bert_score"},
            "avg_cosine_similarity": {"$avg": "$cosine_similarity"},
            "avg_citation_alignment": {"$avg": "$citation_alignment_score"},
            "avg_answer_relevance": {"$avg": "$answer_relevance"},
            "avg_recall_at_5": {"$avg": "$recall_at_5"},
            "avg_precision_at_5": {"$avg": "$precision_at_5"},
            "avg_mrr": {"$avg": "$mrr"},
            "avg_final_rag_score": {"$avg": "$final_rag_score"},
            "verified": {"$sum": {"$cond": [{"$eq": ["$validation_status", "VERIFIED"]}, 1, 0]}},
            "warnings": {"$sum": {"$cond": [{"$eq": ["$validation_status", "WARNING"]}, 1, 0]}},
            "rejected": {"$sum": {"$cond": [{"$eq": ["$validation_status", "REJECTED"]}, 1, 0]}},
            "errors": {"$sum": {"$cond": [{"$eq": ["$validation_status", "ERROR"]}, 1, 0]}},
            "insufficient": {"$sum": {"$cond": [{"$eq": ["$validation_status", "INSUFFICIENT_CONTEXT"]}, 1, 0]}},
        }}
    ]

    agg_results = await db.rag_answer_validations.aggregate(pipeline).to_list(length=1)

    if not agg_results:
        return {
            "overall_status": "NO_DATA",
            "message": "No validation records found. Run a benchmark or send chat queries first.",
            "metrics": {},
            "recommendations": [],
            "timestamp": datetime.utcnow().isoformat()
        }

    metrics = agg_results[0]
    del metrics["_id"]

    # ── Diagnose issues ──
    issues = []
    recommendations = []

    avg_faith = metrics.get("avg_faithfulness", 0) or 0
    avg_halluc = metrics.get("avg_hallucination", 0) or 0
    avg_bert = metrics.get("avg_bert_score", 0) or 0
    avg_recall = metrics.get("avg_recall_at_5", 0) or 0
    avg_citation = metrics.get("avg_citation_alignment", 0) or 0
    avg_relevance = metrics.get("avg_answer_relevance", 0) or 0
    avg_final = metrics.get("avg_final_rag_score", 0) or 0

    # Recall@5 issues → Retrieval problems
    if avg_recall < THRESHOLDS["recall_at_5"] and avg_recall > 0:
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
    if avg_faith < THRESHOLDS["faithfulness"]:
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
    if avg_halluc > THRESHOLDS["hallucination_rate"]:
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
    if avg_bert < THRESHOLDS["bert_score"] and avg_bert > 0:
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
    if avg_citation < THRESHOLDS["citation_alignment"]:
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
            "avg_faithfulness": round(avg_faith, 4),
            "avg_hallucination_rate": round(avg_halluc, 4),
            "avg_bert_score": round(avg_bert, 4),
            "avg_cosine_similarity": round(metrics.get("avg_cosine_similarity", 0) or 0, 4),
            "avg_citation_alignment": round(avg_citation, 4),
            "avg_answer_relevance": round(avg_relevance, 4),
            "avg_recall_at_5": round(avg_recall, 4),
            "avg_precision_at_5": round(metrics.get("avg_precision_at_5", 0) or 0, 4),
            "avg_mrr": round(metrics.get("avg_mrr", 0) or 0, 4),
            "avg_final_rag_score": round(avg_final, 4),
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
