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
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.models.evaluation import ValidationResult
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


def _infer_evaluation_source(record: Dict[str, Any]) -> str:
    explicit = str(record.get("evaluation_source") or "").strip().lower()
    if explicit in {"live", "benchmark", "synced_history"}:
        return explicit
    if str(record.get("user_id") or "") == "benchmark_runner":
        return "benchmark"
    return "live"


def _normalize_final_record(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(record)
    normalized["_id"] = str(normalized.get("_id"))
    normalized["evaluation_source"] = _infer_evaluation_source(normalized)
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


def _build_status_counts(records: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "verified_count": 0,
        "warning_count": 0,
        "rejected_count": 0,
        "error_count": 0,
        "insufficient_count": 0,
    }
    for record in records:
        status = str(record.get("validation_status") or "").upper()
        if status == "VERIFIED":
            counts["verified_count"] += 1
        elif status == "WARNING":
            counts["warning_count"] += 1
        elif status == "REJECTED":
            counts["rejected_count"] += 1
        elif status == "ERROR":
            counts["error_count"] += 1
        elif status == "INSUFFICIENT_CONTEXT":
            counts["insufficient_count"] += 1
    return counts


def _build_final_metrics_payload(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    benchmark_rows = [record for record in records if record.get("evaluation_source") == "benchmark"]
    live_rows = [record for record in records if record.get("evaluation_source") == "live"]
    synced_rows = [record for record in records if record.get("evaluation_source") == "synced_history"]

    payload = {
        "total_validations": len(records),
        "benchmark_count": len(benchmark_rows),
        "live_count": len(live_rows),
        "synced_history_count": len(synced_rows),
        "benchmark_available": bool(benchmark_rows),
        "avg_faithfulness": _average(records, "faithfulness_score"),
        "avg_hallucination": _average(records, "hallucination_rate"),
        "avg_bert_score": _average(records, "bert_score"),
        "avg_cosine_similarity": _average(records, "cosine_similarity"),
        "avg_citation_alignment": _average(records, "citation_alignment_score"),
        "avg_answer_relevance": _average(records, "answer_relevance"),
        "avg_final_rag_score": _average(records, "final_rag_score"),
        "avg_retrieval_confidence": _average(records, "retrieval_confidence"),
        "avg_recall_at_5": _average(benchmark_rows, "recall_at_5"),
        "avg_precision_at_5": _average(benchmark_rows, "precision_at_5"),
        "avg_mrr": _average(benchmark_rows, "mrr"),
    }
    payload.update(_build_status_counts(records))
    return payload


async def _load_final_rows(
    db,
    current_user: Dict[str, Any],
    period: str = "all",
    limit: Optional[int] = None,
    skip: int = 0,
) -> List[Dict[str, Any]]:
    match_query = _final_time_filter(period)
    if not _is_admin_user(current_user):
        match_query["user_id"] = str(current_user["_id"])

    cursor = db.rag_answer_validations.find(match_query).sort("timestamp", -1)
    if skip:
        cursor = cursor.skip(skip)
    if limit is not None:
        cursor = cursor.limit(limit)

    rows = await cursor.to_list(length=limit or 5000)
    return [_normalize_final_record(row) for row in rows]


def _build_final_report(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = _build_final_metrics_payload(records)
    if not records:
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

    def add_issue(metric: str, value: Optional[float], threshold: str, severity: str, recommendation: str) -> None:
        issues.append({
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "severity": severity,
        })
        recommendations.append(recommendation)

    faith = metrics.get("avg_faithfulness")
    halluc = metrics.get("avg_hallucination")
    bert = metrics.get("avg_bert_score")
    citation = metrics.get("avg_citation_alignment")
    relevance = metrics.get("avg_answer_relevance")
    rag = metrics.get("avg_final_rag_score")
    recall = metrics.get("avg_recall_at_5")

    if faith is not None and faith < 0.7:
        add_issue("Faithfulness", faith, ">= 0.70", "HIGH", "Tighten grounding prompts and review unsupported sentences in low-scoring rows.")
    if halluc is not None and halluc > 0.3:
        add_issue("Hallucination Rate", halluc, "<= 0.30", "HIGH", "Reduce temperature or strengthen context-only answering rules.")
    if bert is not None and bert < 0.7:
        add_issue("BERTScore", bert, ">= 0.70", "MEDIUM", "Review semantic drift and encourage source terminology in generated answers.")
    if citation is not None and citation < 0.85:
        add_issue("Citation Alignment", citation, ">= 0.85", "MEDIUM", "Review citation prompting so only directly used chunks are cited.")
    if relevance is not None and relevance < 0.75:
        add_issue("Answer Relevance", relevance, ">= 0.75", "MEDIUM", "Refine prompt instructions to answer the question more directly.")
    if rag is not None and rag < 0.55:
        add_issue("Final RAG Score", rag, ">= 0.55", "HIGH", "Improve grounding and semantic match before expanding generation style.")
    if metrics.get("benchmark_available"):
        if recall is not None and recall < 0.5:
            add_issue("Benchmark Recall@5", recall, ">= 0.50", "MEDIUM", "Tune retrieval weights or chunking strategy for better benchmark recall.")
    else:
        recommendations.append("Run benchmark evaluation to populate retrieval metrics such as Recall@5, Precision@5, and MRR.")

    if not issues:
        overall_status = "STRONG" if (rag or 0) >= 0.7 else "STABLE"
        if not recommendations:
            recommendations.append("Continue monitoring fresh benchmark and live evaluation runs to track quality trends.")
    else:
        severities = {issue["severity"] for issue in issues}
        if "HIGH" in severities:
            overall_status = "NEEDS_IMPROVEMENT"
        else:
            overall_status = "STABLE"

    deduped_recommendations: List[str] = []
    for item in recommendations:
        if item not in deduped_recommendations:
            deduped_recommendations.append(item)

    return {
        "overall_status": overall_status,
        "metrics": metrics,
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


@router.get("/final/metrics")
async def get_final_evaluation_metrics(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        rows = await _load_final_rows(db, current_user, period=period)
        return _build_final_metrics_payload(rows)
    except Exception as e:
        import logging
        logging.error(f"Error fetching final metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/final/logs")
async def get_final_evaluation_logs(
    period: str = Query("all", description="Filter period: all, 24h, 7d"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    db=Depends(get_db),
    current_user=Depends(get_current_user)
):
    try:
        rows = await _load_final_rows(db, current_user, period=period, limit=limit, skip=skip)
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
        return _build_final_report(rows)
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
