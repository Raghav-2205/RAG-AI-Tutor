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

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from typing import List, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.models.evaluation import ValidationResult

router = APIRouter()


@router.get("/metrics")
async def get_evaluation_metrics(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Aggregated evaluation metrics for the dashboard."""
    try:
        match_query = {}
        if period == "24h":
            match_query["timestamp"] = {"$gte": datetime.utcnow() - timedelta(hours=24)}
        elif period == "7d":
            match_query["timestamp"] = {"$gte": datetime.utcnow() - timedelta(days=7)}

        pipeline = [
            {"$match": match_query},
            {"$group": {
                "_id": None,
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
                "total_validations": {"$sum": 1},
                "verified_count": {"$sum": {"$cond": [{"$eq": ["$validation_status", "VERIFIED"]}, 1, 0]}},
                "rejected_count": {"$sum": {"$cond": [{"$eq": ["$validation_status", "REJECTED"]}, 1, 0]}},
                "warning_count": {"$sum": {"$cond": [{"$eq": ["$validation_status", "WARNING"]}, 1, 0]}},
                "error_count": {"$sum": {"$cond": [{"$eq": ["$validation_status", "ERROR"]}, 1, 0]}},
                "insufficient_count": {"$sum": {"$cond": [{"$eq": ["$validation_status", "INSUFFICIENT_CONTEXT"]}, 1, 0]}},
            }}
        ]

        results = await db.rag_answer_validations.aggregate(pipeline).to_list(length=1)

        if not results:
            return {
                "avg_faithfulness": 0, "avg_hallucination": 0,
                "avg_bert_score": 0, "avg_cosine_similarity": 0,
                "avg_citation_alignment": 0, "avg_answer_relevance": 0,
                "avg_recall_at_5": 0, "avg_final_rag_score": 0,
                "total_validations": 0, "verified_count": 0,
                "rejected_count": 0, "warning_count": 0,
            }

        data = results[0]
        if "_id" in data:
            del data["_id"]
        return data

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
    """Get a single validation result by ID."""
    try:
        if not ObjectId.is_valid(result_id):
             raise HTTPException(status_code=400, detail="Invalid ID format")
             
        obj_id = ObjectId(result_id)
        result = await db.rag_answer_validations.find_one({"_id": obj_id})
        
        if not result:
            raise HTTPException(status_code=404, detail="Validation result not found")
            
        return ValidationResult(**result)
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
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """Recent validation logs with all metric fields."""
    try:
        cursor = db.rag_answer_validations.find().sort("timestamp", -1).skip(skip).limit(limit)
        raw_logs = await cursor.to_list(length=limit)

        validated_logs = []
        for log in raw_logs:
            try:
                validated_logs.append(ValidationResult(**log))
            except Exception as e:
                import logging
                logging.warning(f"Skipping malformed log {log.get('_id')}: {e}")
                continue

        return validated_logs

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
        validator = ValidationEngine(db)

        sessions = await db.chat_sessions.find().to_list(length=1000)
        new_validations = 0

        for session in sessions:
            user_id = session.get("user_id")
            subject = session.get("subject", "general")
            messages = session.get("messages", [])

            for i in range(1, len(messages)):
                msg = messages[i]
                prev_msg = messages[i - 1]

                if msg["role"] == "assistant" and msg.get("chunks") and prev_msg["role"] == "user":
                    exists = await db.rag_answer_validations.find_one({
                        "question": prev_msg["content"],
                        "answer": msg["content"]
                    })

                    if not exists:
                        try:
                            await validator.validate_answer(
                                question=prev_msg["content"],
                                answer=msg["content"],
                                retrieved_chunks=msg["chunks"],
                                user_id=user_id,
                                subject=subject
                            )
                            new_validations += 1
                        except Exception as e:
                            import logging
                            logging.error(f"Sync error for msg {i}: {e}")

    background_tasks.add_task(run_sync)
    return {"message": "Sync started in background"}


@router.get("/report")
async def get_evaluation_report(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Auto-debug report with root cause analysis and tuning recommendations.
    """
    from backend.core.evaluation.report_generator import generate_report

    try:
        report = await generate_report(db, period=period)
        return report
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
        r1 = await db.rag_answer_validations.delete_many({})
        r2 = await db.benchmark_runs.delete_many({})
        return {
            "message": "All evaluation data cleared",
            "validations_deleted": r1.deleted_count,
            "benchmarks_deleted": r2.deleted_count
        }
    except Exception as e:
        import logging
        logging.error(f"Clear failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
