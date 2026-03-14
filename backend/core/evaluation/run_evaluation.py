# backend/core/evaluation/run_evaluation.py
"""
Benchmark evaluation runner.

Loads benchmark_dataset.json, runs the full RAG pipeline for each sample,
computes retrieval + generation metrics, and stores results.
"""

import json
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

BENCHMARK_DATASET_PATH = Path(__file__).parent / "benchmark_dataset.json"


async def run_benchmark(db) -> Dict[str, Any]:
    """
    Execute full benchmark evaluation:
    1. Load benchmark samples
    2. For each: run retrieval → generate answer → validate with gold
    3. Aggregate results
    4. Return summary
    """
    from backend.rag_tutor import answer_query_with_rag
    from backend.core.evaluation.validator import ValidationEngine

    logger.info("🚀 Starting benchmark evaluation run...")

    # Load benchmark dataset
    try:
        with open(BENCHMARK_DATASET_PATH, "r", encoding="utf-8") as f:
            samples = json.load(f)
    except FileNotFoundError:
        logger.error(f"Benchmark dataset not found at {BENCHMARK_DATASET_PATH}")
        return {"error": "Benchmark dataset not found", "results": []}

    validator = ValidationEngine(db)
    results = []
    user_id = "benchmark_runner"

    for i, sample in enumerate(samples):
        question = sample["question"]
        gold_answer = sample.get("gold_answer", "")
        gold_chunk_id = sample.get("gold_chunk_id", "")
        subject = sample.get("subject", "general")

        logger.info(f"📝 [{i+1}/{len(samples)}] Evaluating: {question}")

        try:
            # Step 1: Run RAG pipeline
            rag_result = await answer_query_with_rag(
                user_id=user_id,
                query=question,
                subject=subject,
                history=[],
                feedback_context="",
                strict_mode=False
            )

            answer = rag_result.get("answer", "")
            chunks = rag_result.get("chunks", [])

            # Step 2: Validate with gold labels
            gold_ids = [gold_chunk_id] if gold_chunk_id else []

            validation = await validator.validate_with_gold(
                question=question,
                answer=answer,
                retrieved_chunks=chunks,
                gold_chunk_ids=gold_ids,
                user_id=user_id,
                subject=subject
            )

            results.append({
                "question": question,
                "answer": answer[:200],
                "gold_answer": gold_answer[:200],
                "num_chunks": len(chunks),
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
                "status": "completed"
            })

        except Exception as e:
            logger.error(f"Benchmark error for '{question}': {e}")
            results.append({
                "question": question,
                "status": "error",
                "error": str(e)
            })

    # Aggregate summary
    completed = [r for r in results if r.get("status") == "completed"]

    if not completed:
        summary = {
            "total_samples": len(samples),
            "completed": 0,
            "errors": len(results),
            "timestamp": datetime.utcnow().isoformat(),
            "results": results
        }
        return summary

    def avg(key):
        vals = [r[key] for r in completed if key in r]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {
        "total_samples": len(samples),
        "completed": len(completed),
        "errors": len(samples) - len(completed),
        "avg_faithfulness": avg("faithfulness_score"),
        "avg_hallucination_rate": avg("hallucination_rate"),
        "avg_bert_score": avg("bert_score"),
        "avg_cosine_similarity": avg("cosine_similarity"),
        "avg_citation_alignment": avg("citation_alignment"),
        "avg_answer_relevance": avg("answer_relevance"),
        "avg_recall_at_5": avg("recall_at_5"),
        "avg_final_rag_score": avg("final_rag_score"),
        "verified_count": sum(1 for r in completed if r.get("validation_status") == "VERIFIED"),
        "warning_count": sum(1 for r in completed if r.get("validation_status") == "WARNING"),
        "rejected_count": sum(1 for r in completed if r.get("validation_status") == "REJECTED"),
        "timestamp": datetime.utcnow().isoformat(),
        "results": results
    }

    logger.info(
        f"✅ Benchmark complete: {summary['completed']}/{summary['total_samples']} samples, "
        f"avg_faithfulness={summary['avg_faithfulness']:.2f}, "
        f"avg_final_score={summary['avg_final_rag_score']:.2f}"
    )

    # Save summary to DB for dashboard
    try:
        await db.benchmark_runs.insert_one({
            **{k: v for k, v in summary.items() if k != "results"},
            "created_at": datetime.utcnow()
        })
    except Exception as e:
        logger.error(f"Failed to save benchmark summary: {e}")

    return summary
