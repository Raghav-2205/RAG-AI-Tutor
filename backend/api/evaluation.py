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
from datetime import datetime, timedelta, timezone
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
                        chat_id=chat_id
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
