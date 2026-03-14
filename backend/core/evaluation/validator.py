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
  7. Decision logic (VERIFIED / WARNING / REJECTED / INSUFFICIENT_CONTEXT)
"""

import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any

from backend.models.evaluation import ValidationResult
from backend.core.evaluation.metrics import (
    calculate_faithfulness,
    calculate_bert_score,
    calculate_cosine_similarity,
    calculate_citation_alignment,
    calculate_answer_relevance,
    calculate_answer_relevance,
    calculate_final_rag_score,
    calculate_retrieval_confidence,
    calculate_chunk_coverage,
)

logger = logging.getLogger(__name__)


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
        document_id: str = None  # NEW
    ) -> ValidationResult:
        """
        Full validation pipeline — runs automatically after RAG generation.
        """
        logger.info(f"🧪 Validating answer for Q: {question[:60]}... Doc: {document_id}")

        # ── Handle empty context ──
        if not retrieved_chunks:
            result = ValidationResult(
                question=question,
                answer=answer,
                subject=subject,
                user_id=user_id,
                document_id=document_id, # NEW
                validation_status="INSUFFICIENT_CONTEXT",
                reason="No chunks retrieved. Cannot validate groundedness."
            )
            await self._save_result(result)
            return result

        # ── Prepare context ──
        context_text = "\n\n".join([c.get("text", "") for c in retrieved_chunks])
        chunk_ids = [c.get("id", "") for c in retrieved_chunks if c.get("id")]
        chunks_text = [c.get("text", "") for c in retrieved_chunks]

        try:
            # ── A. Faithfulness & Hallucination (ASYNC — calls LLM) ──
            faith_task = calculate_faithfulness(answer, context_text)

            # ── B. Answer Relevance (ASYNC — calls LLM) ──
            relevance_task = calculate_answer_relevance(question, answer)

            # Run both LLM calls concurrently
            faith_result, answer_relevance = await asyncio.gather(
                faith_task, relevance_task
            )

            faith_score = faith_result.get("faithfulness_score", 0.0)
            unsupported = faith_result.get("unsupported_sentences", [])
            hallucination_rate = round(1.0 - faith_score, 4)

            # ── C. CPU-bound metrics (run in executor to avoid blocking) ──
            loop = asyncio.get_event_loop()

            cosine_future = loop.run_in_executor(
                None, calculate_cosine_similarity, answer, context_text
            )
            bert_future = loop.run_in_executor(
                None, calculate_bert_score, answer, context_text
            )
            citation_future = loop.run_in_executor(
                None, calculate_citation_alignment, answer, retrieved_chunks
            )

            cosine_sim, bert_score_val, citation_score = await asyncio.gather(
                cosine_future, bert_future, citation_future
            )

            # ── D. Lightweight Metrics (Sync) ──
            retrieval_conf = calculate_retrieval_confidence(retrieved_chunks)
            chunk_usage_stats = calculate_chunk_coverage(answer, retrieved_chunks)

            # ── D. Final RAG Score ──
            # For live validation without gold labels, recall@5 defaults to 0
            # (retrieval metrics need gold_chunk_ids from benchmark dataset)
            final_score = calculate_final_rag_score(
                recall_at_5=0.0,  # Not available in live mode
                faithfulness=faith_score,
                bert_score_val=bert_score_val,
                citation_alignment=citation_score,
                answer_relevance=answer_relevance
            )

            # ── E. Decision Logic ──
            status = "VERIFIED"
            reason = "Answer is grounded and accurate."

            if faith_score < 0.85:
                status = "REJECTED"
                reason = f"Low faithfulness ({faith_score:.2f}). Potential hallucination detected."
            elif hallucination_rate > 0.2:
                status = "WARNING"
                reason = f"Elevated hallucination risk ({hallucination_rate:.2f})."
            elif citation_score < 0.8:
                status = "WARNING"
                reason = f"Citation alignment below threshold ({citation_score:.2f})."

            # ── F. Construct Result ──
            result = ValidationResult(
                question=question,
                answer=answer,
                subject=subject,
                user_id=user_id,
                # Retrieval metrics (populated during benchmark only)
                recall_at_5=0.0,
                precision_at_5=0.0,
                mrr=0.0,
                # Generation metrics
                faithfulness_score=faith_score,
                hallucination_rate=hallucination_rate,
                citation_alignment_score=citation_score,
                bert_score=bert_score_val,
                cosine_similarity=cosine_sim,
                answer_relevance=answer_relevance,
                # New Metrics
                retrieval_confidence=retrieval_conf,
                chunk_usage=chunk_usage_stats,
                # Composite
                final_rag_score=final_score,
                # Status
                validation_status=status,
                reason=reason,
                # Metadata
                retrieved_chunk_ids=chunk_ids,
                retrieved_chunks_text=chunks_text,
                unsupported_sentences=unsupported,
                document_id=document_id  # NEW
            )

            # ── G. Persist to MongoDB ──
            await self._save_result(result)

            logger.info(
                f"✅ Validation complete: status={status}, faith={faith_score:.2f}, "
                f"bert={bert_score_val:.2f}, cite={citation_score:.2f}, "
                f"relevance={answer_relevance:.2f}, conf={retrieval_conf:.2f}, cov={chunk_usage_stats.get('covered_ratio', 0.0):.2f}"
            )
            return result

        except Exception as e:
            logger.error(f"Validation pipeline failed: {e}", exc_info=True)
            error_result = ValidationResult(
                question=question,
                answer=answer,
                subject=subject,
                user_id=user_id,
                validation_status="ERROR",
                reason=f"Validation error: {str(e)}"
            )
            await self._save_result(error_result)
            return error_result

    async def validate_with_gold(
        self,
        question: str,
        answer: str,
        retrieved_chunks: List[Dict],
        gold_chunk_ids: List[str],
        user_id: str = "benchmark_runner",
        subject: str = "general"
    ) -> ValidationResult:
        """
        Extended validation for benchmark mode — includes retrieval metrics
        against gold labels.
        """
        from backend.core.evaluation.metrics import calculate_retrieval_metrics

        # Run standard validation first
        result = await self.validate_answer(
            question=question,
            answer=answer,
            retrieved_chunks=retrieved_chunks,
            user_id=user_id,
            subject=subject
        )

        # Add retrieval metrics
        retrieved_ids = [c.get("id", "") for c in retrieved_chunks]
        retrieval_metrics = calculate_retrieval_metrics(retrieved_ids, gold_chunk_ids)

        result.recall_at_5 = retrieval_metrics.get("recall@5", 0.0)
        result.precision_at_5 = retrieval_metrics.get("precision@5", 0.0)
        result.mrr = retrieval_metrics.get("mrr", 0.0)

        # Recompute final score WITH retrieval metrics
        result.final_rag_score = calculate_final_rag_score(
            recall_at_5=result.recall_at_5,
            faithfulness=result.faithfulness_score,
            bert_score_val=result.bert_score,
            citation_alignment=result.citation_alignment_score,
            answer_relevance=result.answer_relevance
        )

        # Update in DB
        await self._update_result(result)

        return result

    async def _save_result(self, result: ValidationResult):
        """Persist validation result to MongoDB."""
        try:
            data = result.dict(by_alias=True)
            if "_id" in data and not data["_id"]:
                del data["_id"]
            insert_result = await self.db.rag_answer_validations.insert_one(data)
            # Update the result object with the new ID
            result.id = str(insert_result.inserted_id)
            logger.info(f"💾 Saved validation for: {result.question[:30]}... ID: {result.id}")
        except Exception as e:
            logger.error(f"Failed to save validation result: {e}")

    async def _update_result(self, result: ValidationResult):
        """Update an existing validation result in MongoDB."""
        try:
            await self.db.rag_answer_validations.update_one(
                {"question": result.question, "answer": result.answer},
                {"$set": {
                    "recall_at_5": result.recall_at_5,
                    "precision_at_5": result.precision_at_5,
                    "mrr": result.mrr,
                    "final_rag_score": result.final_rag_score,
                }}
            )
        except Exception as e:
            logger.error(f"Failed to update validation result: {e}")
