import asyncio

from backend.core.evaluation.metrics import (
    _repair_nearly_valid_json,
    calculate_citation_alignment,
    calculate_chunk_coverage,
    calculate_final_rag_score,
    calculate_retrieval_metrics,
    calculate_retrieval_confidence,
    get_evaluation_chunk_id,
    _strip_inline_chunk_citations,
)
from backend.core.evaluation.run_evaluation import (
    _resolve_gold_chunk_ids,
    _should_retry_sample,
    _summarize_benchmark_results,
)
from backend.core.evaluation.status_policy import (
    normalize_validation_record,
    normalize_validation_status,
)
from backend.core.evaluation.validator import ValidationEngine
from backend.core.feedback_analyzer import FeedbackAnalyzer
from backend.api.evaluation import (
    _build_final_metrics_payload,
    _build_live_window_metrics,
    _build_query_patterns,
)
from backend.preprocessing import analyze_chunk_set, chunk_text
from backend.rag_tutor import (
    _build_document_coverage_payload,
    _build_grounded_prompt,
    _normalize_answer_citations,
    _resolve_answer_mode,
    _should_repair,
    _resolve_scope_mode,
    answer_query_with_rag,
    retrieve_chunks_for_streaming,
)
from backend.core.search_engine import HybridSearchEngine
from backend.services.grag_service import _extract_entities_and_relations, graph_retrieve, session_supports_grag


def test_get_evaluation_chunk_id_prefers_metadata_chunk_id():
    chunk = {
        "id": "chroma-id-123",
        "metadata": {"chunk_id": "doc1_p1_c0"},
    }
    assert get_evaluation_chunk_id(chunk) == "doc1_p1_c0"


def test_calculate_final_rag_score_reweights_when_recall_missing():
    score = calculate_final_rag_score(
        recall_at_5=None,
        faithfulness=0.8,
        bert_score_val=0.7,
        citation_alignment=0.9,
        answer_relevance=0.85,
    )
    expected = round(
        (
            0.25 * 0.8
            + 0.20 * 0.7
            + 0.15 * 0.9
            + 0.15 * 0.85
        ) / 0.75,
        4,
    )
    assert score == expected


def test_resolve_gold_chunk_ids_uses_source_and_text_anchor():
    sample = {
        "gold_chunk_id": "scrum_overview",
        "gold_chunk_source": "Scrum methodology_UNIT 1.pptx",
        "gold_chunk_contains": "What is Scrum? Scrum is a framework",
    }
    chunks = [
        {
            "id": "chroma-id-1",
            "text": "What is Scrum? Scrum is a framework that helps agile teams work together.",
            "metadata": {"source": "Scrum methodology_UNIT 1.pptx"},
        },
        {
            "id": "chroma-id-2",
            "text": "Kanban is a visual system for managing work.",
            "metadata": {"source": "kanban notes_UNIT 1.pptx"},
        },
    ]
    assert _resolve_gold_chunk_ids(sample, chunks) == ["chroma-id-1"]


def test_calculate_retrieval_metrics_matches_resolved_ids():
    metrics = calculate_retrieval_metrics(
        ["doc1_p1_c0", "doc1_p1_c1", "doc1_p2_c0"],
        ["doc1_p1_c1"],
        k_list=[1, 3, 5],
    )
    assert metrics["mrr"] == 0.5
    assert metrics["recall@1"] == 0.0
    assert metrics["recall@3"] == 1.0


def test_normalize_validation_status_collapses_legacy_states():
    assert normalize_validation_status("WARNING") == "VERIFIED"
    assert normalize_validation_status("INSUFFICIENT_CONTEXT") == "VERIFIED"
    assert normalize_validation_status("ERROR") == "REJECTED"
    assert normalize_validation_status("VERIFIED") == "VERIFIED"


def test_normalize_validation_record_rewrites_status_field():
    normalized = normalize_validation_record(
        {"validation_status": "WARNING", "reason": "judge fallback"}
    )

    assert normalized["validation_status"] == "VERIFIED"
    assert normalized["reason"] == "judge fallback"


def test_normalize_answer_citations_strips_leaked_metadata():
    raw = (
        "Unit-4 Key Management & Distribution.pdf explains certificates "
        "[CHUNK 1Source: Unit-4 Key Management & Distribution.pdf\n"
        "Page: 72\n"
        "Type: pdf\n"
        "Certificate Extensions..., 3, 4]."
    )

    normalized = _normalize_answer_citations(raw)

    assert normalized.endswith("[CHUNK 1][CHUNK 3][CHUNK 4].")
    assert "Source:" not in normalized
    assert "Page:" not in normalized
    assert "Type:" not in normalized


def test_normalize_answer_citations_handles_bare_chunk_metadata():
    raw = (
        "This document discusses MIME CHUNK 6Source: Unit-4 Part-2 E-Mail Security.pdf\n"
        "Page: 41\n"
        "Type: pdf\n"
        "for multimedia email."
    )

    normalized = _normalize_answer_citations(raw)

    assert "[CHUNK 6]" in normalized
    assert "Source:" not in normalized


def test_resolve_answer_mode_uses_benchmark_runner():
    assert _resolve_answer_mode("benchmark_runner") == "benchmark_mode"
    assert _resolve_answer_mode("user-1") == "live_tutor_mode"


def test_build_grounded_prompt_uses_benchmark_style_for_single_doc():
    prompt = _build_grounded_prompt(
        query="What is Scrum?",
        context_text="[CHUNK 1]\nScrum is a framework for agile teams.",
        history_text="",
        doc_context="",
        strict_mode=True,
        answer_mode="benchmark_mode",
        synthesis_mode=False,
    )

    assert "benchmark-style grounded answer" in prompt
    assert "exactly one compact sentence" in prompt
    assert "Avoid tutoring filler" in prompt


def test_should_repair_flags_weak_semantic_match_in_benchmark_mode():
    class DummyValidation:
        faithfulness_score = 0.95
        hallucination_rate = 0.05
        citation_alignment_score = 0.95
        bert_score = 0.73
        answer_relevance = 0.94
        retrieval_confidence = 0.9
        chunk_usage = {"covered_ratio": 0.8, "document_coverage_balance": 1.0}
        multi_document_metrics = {}

    should_repair, repair_reason = _should_repair(
        DummyValidation(),
        retrieval_confidence=0.9,
        answer_mode="benchmark_mode",
    )

    assert should_repair is True
    assert "semantic overlap" in repair_reason


def test_should_repair_flags_verbose_benchmark_answer():
    class DummyValidation:
        faithfulness_score = 0.95
        hallucination_rate = 0.01
        citation_alignment_score = 0.95
        bert_score = 0.88
        answer_relevance = 0.98
        retrieval_confidence = 0.95
        chunk_usage = {"covered_ratio": 0.9, "document_coverage_balance": 1.0}
        multi_document_metrics = {}

    should_repair, repair_reason = _should_repair(
        DummyValidation(),
        retrieval_confidence=0.95,
        answer_mode="benchmark_mode",
        answer_text="Answer line.\n\n- Bullet one [CHUNK 1]\n- Bullet two [CHUNK 2]",
    )

    assert should_repair is True
    assert "too verbose" in repair_reason.lower()


def test_validate_answer_can_skip_persistence(monkeypatch):
    class DummyCollection:
        def __init__(self):
            self.insert_calls = 0

        async def insert_one(self, data):
            self.insert_calls += 1

            class Result:
                inserted_id = "dummy-id"

            return Result()

        async def update_one(self, selector, update):
            return None

        async def find_one(self, query):
            return None

    class DummyDB:
        def __init__(self):
            self.rag_answer_validations = DummyCollection()
            self.chat_sessions = DummyCollection()

    async def fake_faithfulness(answer, context):
        return {
            "faithfulness_score": 1.0,
            "reasoning": "ok",
            "unsupported_sentences": [],
            "judge_available": True,
        }

    async def fake_relevance(question, answer):
        return {
            "relevance_score": 1.0,
            "reasoning": "ok",
            "judge_available": True,
        }

    monkeypatch.setattr("backend.core.evaluation.validator.calculate_faithfulness", fake_faithfulness)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_answer_relevance", fake_relevance)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_cosine_similarity", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_bert_score", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_citation_alignment", lambda *args, **kwargs: 1.0)

    db = DummyDB()
    engine = ValidationEngine(db)
    result = asyncio.run(
        engine.validate_answer(
            question="What is Scrum?",
            answer="Scrum is an agile framework. [CHUNK 1]",
            retrieved_chunks=[{"text": "Scrum is an agile framework.", "metadata": {"source": "doc.pdf"}}],
            user_id="benchmark_runner",
            subject="agile",
            evaluation_source="benchmark",
            persist_result=False,
        )
    )

    assert result.validation_status == "VERIFIED"
    assert db.rag_answer_validations.insert_calls == 0


def test_calculate_citation_alignment_uses_sentence_level_support(monkeypatch):
    class DummyModel:
        def encode(self, text, convert_to_tensor=True):
            return text

    monkeypatch.setattr("backend.core.evaluation.metrics.get_embedding_model", lambda: DummyModel())

    class DummyUtil:
        @staticmethod
        def pytorch_cos_sim(a, b):
            class Score:
                def item(self_inner):
                    return 0.92 if "instructions" in str(a).lower() and "instructions" in str(b).lower() else 0.41
            return Score()

    monkeypatch.setattr("backend.core.evaluation.metrics.util", DummyUtil)

    score = calculate_citation_alignment(
        "Software is instructions, data structures, and documentation [CHUNK 1][CHUNK 2].",
        [
            {"text": "Software is instructions, data structures, and documentation."},
            {"text": "Software does not wear out like hardware."},
        ],
    )

    assert score >= 0.9


def test_validate_with_gold_recomputes_semantic_metrics_from_gold_answer(monkeypatch):
    class DummyCollection:
        async def insert_one(self, data):
            class Result:
                inserted_id = "dummy-id"
            return Result()

        async def update_one(self, selector, update):
            self.last_update = update
            return None

        async def find_one(self, query):
            return None

    class DummyDB:
        def __init__(self):
            self.rag_answer_validations = DummyCollection()
            self.chat_sessions = DummyCollection()

    async def fake_faithfulness(answer, context):
        return {
            "faithfulness_score": 1.0,
            "reasoning": "ok",
            "unsupported_sentences": [],
            "judge_available": True,
        }

    async def fake_relevance(question, answer):
        return {
            "relevance_score": 1.0,
            "reasoning": "ok",
            "judge_available": True,
        }

    monkeypatch.setattr("backend.core.evaluation.validator.calculate_faithfulness", fake_faithfulness)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_answer_relevance", fake_relevance)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_citation_alignment", lambda *args, **kwargs: 0.9)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_cosine_similarity", lambda answer, reference: 0.97 if "gold" in reference else 0.25)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_bert_score", lambda answer, reference: 0.96 if "gold" in reference else 0.31)

    engine = ValidationEngine(DummyDB())
    result = asyncio.run(
        engine.validate_with_gold(
            question="What is Scrum?",
            answer="Scrum is an agile framework. [CHUNK 1]",
            retrieved_chunks=[{"text": "Scrum is a framework for teams.", "metadata": {"source": "doc.pdf"}}],
            gold_chunk_ids=["chunk-1"],
            gold_answer="A gold benchmark answer about Scrum.",
        )
    )

    assert result.bert_score == 0.96
    assert result.cosine_similarity == 0.97


def test_validation_uses_heuristic_when_faithfulness_judge_falls_back(monkeypatch):
    class DummyCollection:
        async def insert_one(self, data):
            class Result:
                inserted_id = "dummy-id"
            return Result()

        async def update_one(self, selector, update):
            return None

    class DummyDB:
        rag_answer_validations = DummyCollection()

    async def fake_faithfulness(answer, context):
        return {
            "faithfulness_score": 0.5,
            "reasoning": "judge unavailable",
            "unsupported_sentences": [],
            "judge_available": False,
        }

    async def fake_relevance(question, answer):
        return {
            "relevance_score": 1.0,
            "reasoning": "fully relevant",
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    monkeypatch.setattr("backend.core.evaluation.validator.calculate_faithfulness", fake_faithfulness)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_answer_relevance", fake_relevance)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_cosine_similarity", lambda a, b: 0.8)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_bert_score", lambda a, b: 0.84)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_citation_alignment", lambda a, b: 1.0)

    engine = ValidationEngine(DummyDB())
    result = asyncio.run(
        engine.validate_answer(
            question="what is scrum?",
            answer="Scrum is a framework that helps agile teams work together. [CHUNK 1]",
            retrieved_chunks=[
                {"id": "chroma-1", "text": "Scrum is a framework that helps agile teams work together."}
            ],
            user_id="user-1",
            subject="general",
        )
    )

    assert result.validation_status == "VERIFIED"
    assert result.faithfulness_score > 0.85
    assert result.judge_fallback_used is True


def test_validation_softens_single_document_overview_with_strong_grounding(monkeypatch):
    class DummyCollection:
        async def insert_one(self, data):
            class Result:
                inserted_id = "dummy-id"
            return Result()

        async def update_one(self, selector, update):
            return None

        async def find_one(self, query):
            return {
                "chat_id": "chat-1",
                "document_ids": ["doc-1"],
                "document_names": ["Unit-4 Part-2 E-Mail Security.pdf"],
                "file_count": 1,
            }

    class DummyDB:
        rag_answer_validations = DummyCollection()
        chat_sessions = DummyCollection()

    async def fake_faithfulness(answer, context):
        return {
            "faithfulness_score": 0.0,
            "reasoning": "judge was overly strict",
            "unsupported_sentences": [],
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    async def fake_relevance(question, answer):
        return {
            "relevance_score": 1.0,
            "reasoning": "fully relevant",
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    monkeypatch.setattr("backend.core.evaluation.validator.calculate_faithfulness", fake_faithfulness)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_answer_relevance", fake_relevance)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_cosine_similarity", lambda a, b: 0.74)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_bert_score", lambda a, b: 0.68)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_citation_alignment", lambda a, b: 1.0)

    engine = ValidationEngine(DummyDB())
    result = asyncio.run(
        engine.validate_answer(
            question="what is this document about?",
            answer="This document explains email security concepts such as MIME, phishing risks, and protection controls. [CHUNK 1]",
            retrieved_chunks=[
                {
                    "id": "chunk-1",
                    "text": "This unit covers MIME, phishing, and email security controls.",
                    "metadata": {"source": "Unit-4 Part-2 E-Mail Security.pdf", "doc_id": "doc-1"},
                }
            ],
            user_id="user-1",
            subject="general",
            chat_id="chat-1",
            answer_source_mode="document",
        )
    )

    assert result.validation_status == "VERIFIED"
    assert result.faithfulness_score >= 0.74
    assert result.judge_fallback_used is True
    assert "overview answer accepted" in (result.reason or "").lower()


def test_strip_inline_chunk_citations_removes_grounding_markers():
    cleaned = _strip_inline_chunk_citations(
        "Direct Answer: Both documents discuss security. [CHUNK 1][CHUNK 2]"
    )

    assert "[CHUNK" not in cleaned
    assert "Both documents discuss security." in cleaned


def test_repair_nearly_valid_json_recovers_truncated_payload():
    payload = _repair_nearly_valid_json(
        '{\n  "score": 0.75,\n  "total_sentences": 8,\n  "supported_count": 6,\n  "reasoning": "Mostly supported.",\n  "unsupported_sentences": ['
    )

    assert payload is None

    repaired = _repair_nearly_valid_json(
        '{\n  "score": 0.75,\n  "total_sentences": 8,\n  "supported_count": 6,\n  "reasoning": "Mostly supported.",\n  "unsupported_sentences": []'
    )

    assert repaired["score"] == 0.75
    assert repaired["supported_count"] == 6


def test_validation_softens_multi_document_judge_fallback_with_full_coverage(monkeypatch):
    class DummyCollection:
        async def insert_one(self, data):
            class Result:
                inserted_id = "dummy-id"
            return Result()

        async def update_one(self, selector, update):
            return None

        async def find_one(self, query):
            return {
                "chat_id": "chat-1",
                "document_ids": ["doc-1", "doc-2"],
                "document_names": ["Doc A.pdf", "Doc B.pdf"],
                "file_count": 2,
            }

    class DummyDB:
        rag_answer_validations = DummyCollection()
        chat_sessions = DummyCollection()

    async def fake_faithfulness(answer, context):
        return {
            "faithfulness_score": 0.5,
            "reasoning": "Faithfulness judge returned malformed JSON.",
            "unsupported_sentences": [],
            "judge_available": False,
            "judge_fallback_used": True,
            "parse_failure_count": 2,
        }

    async def fake_relevance(question, answer):
        return {
            "relevance_score": 1.0,
            "reasoning": "fully relevant",
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    monkeypatch.setattr("backend.core.evaluation.validator.calculate_faithfulness", fake_faithfulness)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_answer_relevance", fake_relevance)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_cosine_similarity", lambda a, b: 0.74)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_bert_score", lambda a, b: 0.75)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_citation_alignment", lambda a, b: 0.44)

    engine = ValidationEngine(DummyDB())
    result = asyncio.run(
        engine.validate_answer(
            question="what are the both documents related about?",
            answer=(
                "Direct Answer: Both documents are related to security mechanisms and protection approaches. [CHUNK 1][CHUNK 4]\n\n"
                "Document Summaries:\n"
                "- Doc A.pdf: It discusses key management and distribution concepts. [CHUNK 1][CHUNK 2]\n"
                "- Doc B.pdf: It discusses email security threats and controls. [CHUNK 3][CHUNK 4]\n\n"
                "Shared Themes:\n"
                "- Both documents focus on securing communication and information exchange. [CHUNK 2][CHUNK 4]"
            ),
            retrieved_chunks=[
                {"id": "chunk-1", "text": "Doc A covers key management and distribution methods.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}},
                {"id": "chunk-2", "text": "Doc A explains mechanisms for secure key exchange.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}},
                {"id": "chunk-3", "text": "Doc B covers email security threats such as phishing and spoofing.", "metadata": {"source": "Doc B.pdf", "doc_id": "doc-2"}},
                {"id": "chunk-4", "text": "Doc B explains email security controls and protections.", "metadata": {"source": "Doc B.pdf", "doc_id": "doc-2"}},
            ],
            user_id="user-1",
            subject="general",
            chat_id="chat-1",
            answer_source_mode="document",
            graph_context={
                "context_summary": "Doc A and Doc B both discuss security topics.",
                "document_coverage": {
                    "coverage_ratio": 1.0,
                    "matched_sources": ["Doc A.pdf", "Doc B.pdf"],
                    "total_sources": 2,
                    "covered_document_count": 2,
                    "total_documents": 2,
                },
                "document_coverage_map": [
                    {"doc_id": "doc-1", "name": "Doc A.pdf", "selected_chunk_count": 2, "graph_fact_count": 1, "supported": True},
                    {"doc_id": "doc-2", "name": "Doc B.pdf", "selected_chunk_count": 2, "graph_fact_count": 1, "supported": True},
                ],
                "uploaded_documents": [
                    {"doc_id": "doc-1", "name": "Doc A.pdf"},
                    {"doc_id": "doc-2", "name": "Doc B.pdf"},
                ],
            },
        )
    )

    assert result.validation_status == "VERIFIED"
    assert result.faithfulness_score >= 0.74
    assert result.judge_fallback_used is True
    assert "fallback metrics" in (result.reason or "").lower()


def test_chunk_text_respects_structure_and_overlap():
    text = (
        "Intro paragraph about software engineering.\n\n"
        "What is DevOps? DevOps is the practice of bringing development and operations together. "
        "It helps teams ship faster.\n\n"
        "- Track history\n"
        "- Support collaboration\n"
        "- Enable branching"
    )

    chunks = chunk_text(text, chunk_size=120, chunk_overlap=30)

    assert len(chunks) >= 2
    assert all(chunk.strip() for chunk in chunks)
    assert any("What is DevOps?" in chunk for chunk in chunks)
    assert any("Support collaboration" in chunk for chunk in chunks)


def test_analyze_chunk_set_reports_duplicates():
    stats = analyze_chunk_set([
        "Git is a distributed version control system.",
        "Git is a distributed version control system.",
        "Selenium is an open-source testing framework."
    ])

    assert stats["chunk_count"] == 3
    assert stats["duplicate_chunk_count"] == 1
    assert stats["duplicate_rate"] > 0


def test_benchmark_summary_separates_generation_failures_from_answer_quality():
    summary = _summarize_benchmark_results(
        total_samples=3,
        chunk_diagnostics={"chunk_count": 10},
        results=[
            {
                "question": "q1",
                "status": "completed",
                "validation_status": "VERIFIED",
                "answer_source_mode": "knowledge_base",
                "faithfulness_score": 0.9,
                "hallucination_rate": 0.1,
                "bert_score": 0.8,
                "cosine_similarity": 0.7,
                "citation_alignment": 1.0,
                "answer_relevance": 0.85,
                "recall_at_5": 0.6,
                "precision_at_5": 0.2,
                "mrr": 1.0,
                "final_rag_score": 0.78,
            },
            {
                "question": "q2",
                "status": "generation_error",
                "validation_status": "REJECTED",
                "answer_source_mode": "error",
                "answer": "LLM Async Request Failed: All connection attempts failed",
                "reason": "Answer generation failed before validation could complete.",
                "faithfulness_score": 0.0,
                "hallucination_rate": 1.0,
                "bert_score": 0.4,
                "cosine_similarity": 0.2,
                "citation_alignment": 1.0,
                "answer_relevance": 0.0,
                "recall_at_5": 1.0,
                "precision_at_5": 0.4,
                "mrr": 1.0,
                "final_rag_score": 0.35,
            },
            {
                "question": "q3",
                "status": "error",
            },
        ],
    )

    assert summary["completed"] == 1
    assert summary["answer_quality_count"] == 1
    assert summary["generation_error_count"] == 1
    assert summary["ungrounded_failure_count"] == 0
    assert summary["unexpected_error_count"] == 1
    assert summary["error_count"] == 2
    assert summary["failure_count"] == 2
    assert summary["failure_rate"] == 0.6667
    assert summary["generation_valid"] is False
    assert summary["avg_faithfulness"] == 0.9
    assert summary["avg_recall_at_5"] == 0.8
    assert len(summary["sample_results"]) == 3


def test_benchmark_summary_excludes_ungrounded_rows_from_answer_quality():
    summary = _summarize_benchmark_results(
        total_samples=3,
        chunk_diagnostics={"chunk_count": 12},
        results=[
            {
                "question": "q1",
                "status": "completed",
                "validation_status": "VERIFIED",
                "answer_source_mode": "knowledge_base",
                "num_chunks": 4,
                "faithfulness_score": 0.94,
                "hallucination_rate": 0.02,
                "bert_score": 0.9,
                "citation_alignment": 0.95,
                "answer_relevance": 0.93,
                "recall_at_5": 1.0,
                "precision_at_5": 0.4,
                "mrr": 1.0,
                "final_rag_score": 0.93,
            },
            {
                "question": "q2",
                "status": "ungrounded_fallback",
                "validation_status": "REJECTED",
                "answer_source_mode": "gemini_fallback",
                "num_chunks": 0,
                "recall_at_5": 0.0,
                "precision_at_5": 0.0,
                "mrr": 0.0,
                "final_rag_score": 0.0,
            },
            {
                "question": "q3",
                "status": "no_context",
                "validation_status": "REJECTED",
                "answer_source_mode": "knowledge_base",
                "num_chunks": 0,
                "recall_at_5": 0.0,
                "precision_at_5": 0.0,
                "mrr": 0.0,
                "final_rag_score": 0.0,
            },
        ],
    )

    assert summary["answer_quality_count"] == 1
    assert summary["ungrounded_failure_count"] == 2
    assert summary["failure_count"] == 2
    assert summary["generation_valid"] is False


def test_final_metrics_prefers_benchmark_primary_and_tracks_live_window_targets():
    latest_benchmark = {
        "generation_valid": True,
        "answer_quality_count": 15,
        "avg_faithfulness": 0.95,
        "avg_hallucination_rate": 0.04,
        "avg_bert_score": 0.91,
        "avg_citation_alignment": 0.93,
        "avg_answer_relevance": 0.94,
        "avg_final_rag_score": 0.92,
        "avg_recall_at_5": 0.84,
    }
    live_window = {
        "answer_quality_count": 3,
        "avg_faithfulness": 0.94,
        "avg_hallucination": 0.05,
        "avg_bert_score": 0.9,
        "avg_citation_alignment": 0.91,
        "avg_answer_relevance": 0.92,
        "avg_final_rag_score": 0.91,
        "meets_final_rag_target": True,
    }

    payload = _build_final_metrics_payload(
        records=[],
        latest_benchmark=latest_benchmark,
        live_window_metrics=live_window,
        feedback_loop_status={},
    )

    assert payload["primary_metrics_basis"] == "benchmark"
    assert payload["primary_metrics"]["avg_final_rag_score"] == 0.92
    assert payload["secondary_metrics_basis"] == "live_window"
    assert payload["quality_targets"]["benchmark_target_met"] is True
    assert payload["quality_targets"]["live_window_target_active"] is True
    assert payload["quality_targets"]["live_window_target_met"] is True


def test_should_retry_sample_identifies_transient_generation_failures():
    assert _should_retry_sample({
        "status": "generation_error",
        "validation_status": "REJECTED",
        "answer_source_mode": "error",
        "answer": "LLM Async Request Failed: timeout",
        "reason": "Answer generation failed before validation could complete.",
    }) is True
    assert _should_retry_sample({
        "status": "error",
        "error": "timeout while contacting model",
    }) is True
    assert _should_retry_sample({
        "status": "completed",
        "validation_status": "VERIFIED",
        "answer_source_mode": "knowledge_base",
    }) is False


def test_feedback_analyzer_tracks_response_chunks_with_ids_and_sources():
    class DummyCollection:
        def __init__(self):
            self.inserted = []

        async def insert_one(self, data):
            self.inserted.append(data)
            class Result:
                inserted_id = "dummy-id"
            return Result()

    class DummyDB:
        def __init__(self):
            self.response_chunks = DummyCollection()

    db = DummyDB()
    analyzer = FeedbackAnalyzer(db)
    asyncio.run(
        analyzer.track_response_quality(
            reference_id="resp-1",
            chunk_sources=["doc-a.pdf", "doc-b.pdf"],
            chunk_ids=["chunk-1", "chunk-2"],
            user_id="user-1",
            subject="general",
        )
    )

    inserted = db.response_chunks.inserted[0]
    assert inserted["reference_id"] == "resp-1"
    assert inserted["chunk_ids"] == ["chunk-1", "chunk-2"]
    assert inserted["chunk_sources"] == ["doc-a.pdf", "doc-b.pdf"]
    assert inserted["user_id"] == "user-1"
    assert inserted["subject"] == "general"


def test_live_window_metrics_reports_quality_targets():
    rows = [
        {
            "evaluation_source": "live",
            "validation_status": "VERIFIED",
            "answer_source_mode": "knowledge_base",
            "faithfulness_score": 0.95,
            "hallucination_rate": 0.05,
            "bert_score": 0.92,
            "citation_alignment_score": 0.95,
            "answer_relevance": 0.96,
            "final_rag_score": 0.93,
        },
        {
            "evaluation_source": "live",
            "validation_status": "VERIFIED",
            "answer_source_mode": "knowledge_base",
            "faithfulness_score": 0.91,
            "hallucination_rate": 0.09,
            "bert_score": 0.9,
            "citation_alignment_score": 0.91,
            "answer_relevance": 0.94,
            "final_rag_score": 0.91,
        },
    ]

    metrics = _build_live_window_metrics(rows, window_size=10)

    assert metrics["window_count"] == 2
    assert metrics["answer_quality_count"] == 2
    assert metrics["meets_final_rag_target"] is True
    assert metrics["meets_faithfulness_target"] is True
    assert metrics["meets_hallucination_target"] is True


def test_final_metrics_payload_includes_source_breakdown():
    rows = [
        {
            "evaluation_source": "benchmark",
            "validation_status": "VERIFIED",
            "answer_source_mode": "knowledge_base",
            "faithfulness_score": 0.94,
            "hallucination_rate": 0.05,
            "bert_score": 0.9,
            "citation_alignment_score": 0.91,
            "answer_relevance": 0.95,
            "final_rag_score": 0.92,
            "recall_at_5": 0.8,
        },
        {
            "evaluation_source": "live",
            "validation_status": "VERIFIED",
            "answer_source_mode": "knowledge_base",
            "faithfulness_score": 0.91,
            "hallucination_rate": 0.07,
            "bert_score": 0.89,
            "citation_alignment_score": 0.88,
            "answer_relevance": 0.9,
            "final_rag_score": 0.9,
        },
    ]

    payload = _build_final_metrics_payload(rows)

    assert payload["source_breakdown"]["benchmark"]["total_validations"] == 1
    assert payload["source_breakdown"]["live"]["total_validations"] == 1
    assert payload["source_breakdown"]["synced_history"]["total_validations"] == 0


def test_build_query_patterns_groups_repeated_attention_queries():
    patterns = _build_query_patterns(
        [
            {
                "question": "What is Scrum?",
                "evaluation_source": "live",
                "validation_status": "REJECTED",
                "final_rag_score": 0.58,
                "citation_alignment_score": 0.6,
                "hallucination_rate": 0.18,
            },
            {
                "question": "what is scrum?",
                "evaluation_source": "benchmark",
                "validation_status": "REJECTED",
                "final_rag_score": 0.62,
                "citation_alignment_score": 0.7,
                "hallucination_rate": 0.16,
            },
            {
                "question": "Explain Kanban",
                "evaluation_source": "live",
                "validation_status": "VERIFIED",
                "final_rag_score": 0.91,
                "citation_alignment_score": 0.9,
                "hallucination_rate": 0.03,
            },
        ]
    )

    assert patterns[0]["question"].lower() == "what is scrum?"
    assert patterns[0]["count"] == 2
    assert patterns[0]["top_source"] in {"live", "benchmark"}


def test_search_engine_prefers_dense_weight_in_benchmark_mode():
    engine = HybridSearchEngine()
    bm25_weight, dense_weight = engine._resolve_weight_profile("benchmark_mode")

    assert dense_weight > bm25_weight
    assert dense_weight > engine.dense_weight - 0.01


def test_chunk_coverage_accounts_for_graph_facts_and_document_balance():
    coverage = calculate_chunk_coverage(
        answer="Document A covers Scrum roles and Document B covers Scrum events.",
        chunks=[
            {
                "text": "Document A explains Scrum roles such as Product Owner and Scrum Master.",
                "metadata": {"source": "doc-a.pdf"},
            },
            {
                "text": "Document B explains Scrum events like sprint planning and retrospectives.",
                "metadata": {"source": "doc-b.pdf"},
            },
        ],
        graph_facts=[
            "Scrum roles appear in doc-a.pdf",
            "Scrum events appear in doc-b.pdf",
        ],
        expected_sources=["doc-a.pdf", "doc-b.pdf"],
    )

    assert coverage["covered_ratio"] > 0.2
    assert coverage["graph_fact_support_ratio"] > 0.2
    assert coverage["document_coverage_balance"] == 1.0


def test_retrieval_confidence_boosts_with_graph_support():
    chunks = [{"score": 0.08}, {"score": 0.07}]
    baseline = calculate_retrieval_confidence(chunks, has_graph_context=False)
    boosted = calculate_retrieval_confidence(
        chunks,
        has_graph_context=True,
        graph_support=0.8,
        document_coverage=1.0,
    )

    assert boosted > baseline


def test_graph_extraction_retains_chunk_provenance():
    extracted = _extract_entities_and_relations(
        chunks=[
            {
                "text": "Scrum Framework uses Sprint Planning and Retrospective ceremonies.",
                "metadata": {
                    "chunk_id": "chunk-1",
                    "doc_id": "doc-1",
                    "source": "doc-a.pdf",
                },
            },
            {
                "text": "Scrum Framework is supported by Product Owner and Scrum Master roles.",
                "metadata": {
                    "chunk_id": "chunk-2",
                    "doc_id": "doc-2",
                    "source": "doc-b.pdf",
                },
            },
        ],
        new_text="",
        source="doc-a.pdf",
    )

    nodes = {node["id"]: node for node in extracted["nodes"]}
    assert "scrum_framework" in nodes
    assert "chunk-1" in nodes["scrum_framework"]["support_chunk_ids"]
    assert "chunk-2" in nodes["scrum_framework"]["support_chunk_ids"]


def test_document_coverage_payload_marks_missing_documents():
    payload = _build_document_coverage_payload(
        documents=[
            {"doc_id": "doc-1", "name": "Doc A.pdf"},
            {"doc_id": "doc-2", "name": "Doc B.pdf"},
        ],
        chunks=[
            {
                "text": "Doc A covers Scrum roles.",
                "metadata": {"doc_id": "doc-1", "source": "Doc A.pdf"},
            }
        ],
        graph_payload={},
    )

    assert payload["covered_document_count"] == 1
    assert payload["unsupported_documents"] == ["Doc B.pdf"]
    assert payload["documents"][0]["supported"] is True
    assert payload["documents"][1]["unsupported_for_query"] is True


def test_validation_rejects_multi_document_answer_that_omits_uploaded_docs(monkeypatch):
    class DummyCollection:
        async def insert_one(self, data):
            class Result:
                inserted_id = "dummy-id"
            return Result()

        async def update_one(self, selector, update):
            return None

        async def find_one(self, selector):
            return {
                "chat_id": "chat-1",
                "document_ids": ["doc-1", "doc-2"],
                "document_names": ["Doc A.pdf", "Doc B.pdf"],
            }

    class DummyDB:
        def __init__(self):
            self.rag_answer_validations = DummyCollection()
            self.chat_sessions = DummyCollection()

    async def fake_faithfulness(answer, context):
        return {
            "faithfulness_score": 1.0,
            "reasoning": "fully supported",
            "unsupported_sentences": [],
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    async def fake_relevance(question, answer):
        return {
            "relevance_score": 1.0,
            "reasoning": "relevant",
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    monkeypatch.setattr("backend.core.evaluation.validator.calculate_faithfulness", fake_faithfulness)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_answer_relevance", fake_relevance)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_cosine_similarity", lambda a, b: 0.9)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_bert_score", lambda a, b: 0.88)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_citation_alignment", lambda a, b: 1.0)

    engine = ValidationEngine(DummyDB())
    result = asyncio.run(
        engine.validate_answer(
            question="what are these documents about?",
            answer="Doc A.pdf explains Scrum roles and responsibilities. [CHUNK 1]",
            retrieved_chunks=[
                {"id": "chunk-a", "text": "Doc A explains Scrum roles.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}},
                {"id": "chunk-b", "text": "Doc B explains Scrum events.", "metadata": {"source": "Doc B.pdf", "doc_id": "doc-2"}},
            ],
            user_id="user-1",
            subject="general",
            chat_id="chat-1",
            graph_context={
                "context_summary": "Doc A and Doc B are both in scope.",
                "document_coverage": {"coverage_ratio": 1.0, "matched_sources": ["Doc A.pdf", "Doc B.pdf"], "total_sources": 2},
                "document_coverage_map": [
                    {"doc_id": "doc-1", "name": "Doc A.pdf", "selected_chunk_count": 1, "graph_fact_count": 1, "supported": True},
                    {"doc_id": "doc-2", "name": "Doc B.pdf", "selected_chunk_count": 1, "graph_fact_count": 1, "supported": True},
                ],
                "uploaded_documents": [
                    {"doc_id": "doc-1", "name": "Doc A.pdf"},
                    {"doc_id": "doc-2", "name": "Doc B.pdf"},
                ],
            },
        )
    )

    assert result.validation_status == "REJECTED"
    assert result.multi_document_metrics["missing_document_names"] == ["Doc B.pdf"]
    assert result.multi_document_metrics["covered_document_count"] == 1


def test_validation_rejects_multi_document_refusal_when_docs_are_supported(monkeypatch):
    class DummyCollection:
        async def insert_one(self, data):
            class Result:
                inserted_id = "dummy-id"
            return Result()

        async def update_one(self, selector, update):
            return None

        async def find_one(self, selector):
            return {
                "chat_id": "chat-1",
                "document_ids": ["doc-1", "doc-2"],
                "document_names": ["Doc A.pdf", "Doc B.pdf"],
            }

    class DummyDB:
        def __init__(self):
            self.rag_answer_validations = DummyCollection()
            self.chat_sessions = DummyCollection()

    async def fake_faithfulness(answer, context):
        return {
            "faithfulness_score": 1.0,
            "reasoning": "fully supported",
            "unsupported_sentences": [],
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    async def fake_relevance(question, answer):
        return {
            "relevance_score": 1.0,
            "reasoning": "relevant",
            "judge_available": True,
            "judge_fallback_used": False,
            "parse_failure_count": 0,
        }

    monkeypatch.setattr("backend.core.evaluation.validator.calculate_faithfulness", fake_faithfulness)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_answer_relevance", fake_relevance)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_cosine_similarity", lambda a, b: 0.9)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_bert_score", lambda a, b: 0.88)
    monkeypatch.setattr("backend.core.evaluation.validator.calculate_citation_alignment", lambda a, b: 1.0)

    engine = ValidationEngine(DummyDB())
    result = asyncio.run(
        engine.validate_answer(
            question="what are these documents about?",
            answer=(
                "The retrieved material does not provide enough evidence to compare or summarize all of the uploaded "
                "documents in Doc A.pdf, Doc B.pdf. Based on the available context, I should not guess."
            ),
            retrieved_chunks=[
                {"id": "chunk-a", "text": "Doc A explains Scrum roles.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}},
                {"id": "chunk-b", "text": "Doc B explains Scrum events.", "metadata": {"source": "Doc B.pdf", "doc_id": "doc-2"}},
            ],
            user_id="user-1",
            subject="general",
            chat_id="chat-1",
            graph_context={
                "context_summary": "Doc A and Doc B are both in scope.",
                "document_coverage": {"coverage_ratio": 1.0, "matched_sources": ["Doc A.pdf", "Doc B.pdf"], "total_sources": 2},
                "document_coverage_map": [
                    {"doc_id": "doc-1", "name": "Doc A.pdf", "selected_chunk_count": 1, "graph_fact_count": 1, "supported": True},
                    {"doc_id": "doc-2", "name": "Doc B.pdf", "selected_chunk_count": 1, "graph_fact_count": 1, "supported": True},
                ],
                "uploaded_documents": [
                    {"doc_id": "doc-1", "name": "Doc A.pdf"},
                    {"doc_id": "doc-2", "name": "Doc B.pdf"},
                ],
            },
        )
    )

    assert result.validation_status == "REJECTED"
    assert result.multi_document_metrics["available_supported_document_count"] == 2


def test_retrieve_chunks_for_streaming_abstain_path_no_longer_raises(monkeypatch):
    async def fake_search_chunks(user_id, subject, query, top_k, document_ids, chat_id, file_count, scope_mode, answer_mode=None):
        return (
            [{"id": "chunk-1", "text": "Short grounded chunk.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}}],
            {"chunk_ids": [], "chunk_sources": []},
            {},
            False,
            False,
        )

    async def fake_load_document_context(chat_id):
        return "Currently indexed files in this session: Doc A.pdf\n\n", ["Doc A.pdf"], [{"doc_id": "doc-1", "name": "Doc A.pdf"}]

    monkeypatch.setattr("backend.rag_tutor._search_chunks", fake_search_chunks)
    monkeypatch.setattr("backend.rag_tutor._load_document_context", fake_load_document_context)
    monkeypatch.setattr("backend.rag_tutor.calculate_retrieval_confidence", lambda *args, **kwargs: 0.1)

    result = asyncio.run(
        retrieve_chunks_for_streaming(
            user_id="user-1",
            query="what does this say?",
            subject="general",
            document_ids=["doc-1"],
            file_count=1,
            chat_id="chat-1",
        )
    )

    assert result["abstain_response"]
    assert result["multi_document_mode"] is False
    assert result["source_mode"] == "document"
    assert result["graph_used"] is False


def test_retrieve_chunks_for_streaming_document_overview_does_not_abstain(monkeypatch):
    async def fake_search_chunks(user_id, subject, query, top_k, document_ids, chat_id, file_count, scope_mode, answer_mode=None):
        return (
            [{"id": "chunk-1", "text": "This unit covers MIME, phishing, and email security controls.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}}],
            {"chunk_ids": [], "chunk_sources": []},
            {},
            False,
            False,
        )

    async def fake_load_document_context(chat_id):
        return "Currently indexed files in this session: Doc A.pdf\n\n", ["Doc A.pdf"], [{"doc_id": "doc-1", "name": "Doc A.pdf"}]

    monkeypatch.setattr("backend.rag_tutor._search_chunks", fake_search_chunks)
    monkeypatch.setattr("backend.rag_tutor._load_document_context", fake_load_document_context)
    monkeypatch.setattr("backend.rag_tutor.calculate_retrieval_confidence", lambda *args, **kwargs: 0.05)

    result = asyncio.run(
        retrieve_chunks_for_streaming(
            user_id="user-1",
            query="what is this document about?",
            subject="general",
            document_ids=["doc-1"],
            file_count=1,
            chat_id="chat-1",
        )
    )

    assert result["abstain_response"] is None
    assert result["source_mode"] == "document"
    assert "document overview question" in result["prompt"].lower()


def test_retrieve_chunks_for_streaming_multi_doc_generates_best_effort(monkeypatch):
    async def fake_search_chunks(user_id, subject, query, top_k, document_ids, chat_id, file_count, scope_mode, answer_mode=None):
        return (
            [
                {"id": "chunk-1", "text": "Doc A explains Scrum roles.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}},
                {"id": "chunk-2", "text": "Doc B explains Scrum events.", "metadata": {"source": "Doc B.pdf", "doc_id": "doc-2"}},
            ],
            {"chunk_ids": [], "chunk_sources": []},
            {},
            True,
            True,
        )

    async def fake_load_document_context(chat_id):
        return (
            "Currently indexed files in this session: Doc A.pdf, Doc B.pdf\n\n",
            ["Doc A.pdf", "Doc B.pdf"],
            [{"doc_id": "doc-1", "name": "Doc A.pdf"}, {"doc_id": "doc-2", "name": "Doc B.pdf"}],
        )

    monkeypatch.setattr("backend.rag_tutor._search_chunks", fake_search_chunks)
    monkeypatch.setattr("backend.rag_tutor._load_document_context", fake_load_document_context)
    monkeypatch.setattr("backend.rag_tutor.calculate_retrieval_confidence", lambda *args, **kwargs: 0.1)

    result = asyncio.run(
        retrieve_chunks_for_streaming(
            user_id="user-1",
            query="what are the both docuemnts about?",
            subject="general",
            document_ids=["doc-1", "doc-2"],
            file_count=2,
            chat_id="chat-1",
        )
    )

    assert result["abstain_response"] is None
    assert result["multi_document_mode"] is True
    assert result["comparison_mode"] is True
    assert result["document_coverage"]["covered_document_count"] == 2
    assert "Document Summaries" in result["prompt"]
    assert "How They Are Related" in result["prompt"]


def test_retrieve_chunks_for_streaming_marks_graph_used_when_multi_doc_graph_exists(monkeypatch):
    async def fake_search_chunks(user_id, subject, query, top_k, document_ids, chat_id, file_count, scope_mode, answer_mode=None):
        return (
            [
                {"id": "chunk-1", "text": "Doc A explains Scrum roles.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}},
                {"id": "chunk-2", "text": "Doc B explains Scrum events.", "metadata": {"source": "Doc B.pdf", "doc_id": "doc-2"}},
            ],
            {"chunk_ids": [], "chunk_sources": []},
            {
                "context_summary": "Doc A and Doc B both cover Scrum.",
                "graph_facts": ["Scrum roles connect to Scrum events."],
                "support_chunk_ids": ["chunk-1", "chunk-2"],
            },
            True,
            True,
        )

    async def fake_load_document_context(chat_id):
        return (
            "Currently indexed files in this session: Doc A.pdf, Doc B.pdf\n\n",
            ["Doc A.pdf", "Doc B.pdf"],
            [{"doc_id": "doc-1", "name": "Doc A.pdf"}, {"doc_id": "doc-2", "name": "Doc B.pdf"}],
        )

    monkeypatch.setattr("backend.rag_tutor._search_chunks", fake_search_chunks)
    monkeypatch.setattr("backend.rag_tutor._load_document_context", fake_load_document_context)
    monkeypatch.setattr("backend.rag_tutor.calculate_retrieval_confidence", lambda *args, **kwargs: 0.72)

    result = asyncio.run(
        retrieve_chunks_for_streaming(
            user_id="user-1",
            query="compare both documents",
            subject="general",
            document_ids=["doc-1", "doc-2"],
            file_count=2,
            chat_id="chat-1",
        )
    )

    assert result["graph_used"] is True
    assert result["graph_context"]["context_summary"] == "Doc A and Doc B both cover Scrum."


def test_graph_retrieve_ignores_stale_graph_for_single_document_session():
    class DummyCollection:
        def __init__(self, docs):
            self.docs = docs

        async def find_one(self, query):
            for doc in self.docs:
                if all(doc.get(key) == value for key, value in query.items()):
                    return doc
            return None

    class DummyDB:
        def __init__(self):
            self.chat_sessions = DummyCollection([
                {
                    "chat_id": "chat-1",
                    "user_id": "user-1",
                    "document_ids": ["doc-1"],
                    "document_names": ["Doc A.pdf"],
                    "file_count": 1,
                }
            ])
            self.knowledge_graphs = DummyCollection([
                {
                    "session_id": "chat-1",
                    "graph_data": {
                        "nodes": [{"id": "node-1", "label": "Node 1", "sources": ["Doc A.pdf"]}],
                        "edges": [],
                        "stats": {"document_count": 1},
                    },
                }
            ])

    result = asyncio.run(graph_retrieve(DummyDB(), "chat-1", "what is this about?"))

    assert result == []


def test_session_supports_grag_requires_two_documents():
    assert session_supports_grag(file_count=1, document_ids=["doc-1"]) is False
    assert session_supports_grag(file_count=2, document_ids=["doc-1", "doc-2"]) is True


def test_answer_query_with_rag_multi_doc_generates_instead_of_refusing(monkeypatch):
    async def fake_search_chunks(user_id, subject, query, top_k, document_ids, chat_id, file_count, scope_mode, answer_mode=None):
        return (
            [
                {"id": "chunk-1", "text": "Doc A discusses Scrum roles and responsibilities.", "metadata": {"source": "Doc A.pdf", "doc_id": "doc-1"}},
                {"id": "chunk-2", "text": "Doc B discusses Scrum ceremonies and sprint flow.", "metadata": {"source": "Doc B.pdf", "doc_id": "doc-2"}},
            ],
            {"chunk_ids": [], "chunk_sources": []},
            {
                "document_coverage_map": [
                    {"doc_id": "doc-1", "name": "Doc A.pdf", "graph_fact_count": 1, "supported": True},
                    {"doc_id": "doc-2", "name": "Doc B.pdf", "graph_fact_count": 1, "supported": True},
                ],
                "document_coverage": {"covered_document_count": 2, "total_documents": 2, "coverage_ratio": 1.0},
                "per_document_facts": {
                    "Doc A.pdf": ["Scrum roles include Product Owner and Scrum Master."],
                    "Doc B.pdf": ["Scrum ceremonies include sprint planning and retrospectives."],
                },
            },
            True,
            True,
        )

    async def fake_load_document_context(chat_id):
        return (
            "Currently indexed files in this session: Doc A.pdf, Doc B.pdf\n\n",
            ["Doc A.pdf", "Doc B.pdf"],
            [{"doc_id": "doc-1", "name": "Doc A.pdf"}, {"doc_id": "doc-2", "name": "Doc B.pdf"}],
        )

    async def fake_generate(prompt, system_prompt=None, temperature=None):
        return (
            "Direct Answer: The documents both explain Scrum, with one focusing on roles and the other on ceremonies. [CHUNK 1][CHUNK 2]\n\n"
            "Document Summaries:\n"
            "- Doc A.pdf: It explains Scrum roles and responsibilities. [CHUNK 1]\n"
            "- Doc B.pdf: It explains Scrum ceremonies and sprint flow. [CHUNK 2]\n\n"
            "Shared Themes:\n"
            "- Both documents describe core Scrum concepts. [CHUNK 1][CHUNK 2]"
        )

    async def fake_validate(**kwargs):
        class DummyValidation:
            def model_dump(self):
                return {"validation_status": "VERIFIED"}
        return DummyValidation()

    monkeypatch.setattr("backend.rag_tutor._search_chunks", fake_search_chunks)
    monkeypatch.setattr("backend.rag_tutor._load_document_context", fake_load_document_context)
    monkeypatch.setattr("backend.rag_tutor.calculate_retrieval_confidence", lambda *args, **kwargs: 0.1)
    monkeypatch.setattr("backend.rag_tutor.llm_client.async_generate", fake_generate)
    monkeypatch.setattr("backend.rag_tutor._validate_generated_answer", fake_validate)

    result = asyncio.run(
        answer_query_with_rag(
            user_id="user-1",
            query="what are these documents about?",
            subject="general",
            document_ids=["doc-1", "doc-2"],
            file_count=2,
            chat_id="chat-1",
        )
    )

    assert result["abstained"] is False
    assert result["source_mode"] == "document"
    assert "Document Summaries" in result["answer"]
    assert "Doc A.pdf" in result["answer"]
    assert "Doc B.pdf" in result["answer"]


def test_answer_query_with_rag_uses_gemini_fallback_for_low_confidence_kb(monkeypatch):
    async def fake_search_chunks(user_id, subject, query, top_k, document_ids, chat_id, file_count, scope_mode, answer_mode=None):
        assert scope_mode == "system_only"
        return (
            [{"id": "chunk-1", "text": "Thin KB evidence.", "metadata": {"source": "system", "doc_id": "sys-1"}}],
            {"chunk_ids": [], "chunk_sources": []},
            {},
            False,
            False,
        )

    async def fake_load_document_context(chat_id):
        return "", [], []

    async def fake_generate_fallback(query, history):
        return {
            "answer": "Gemini fallback answer.",
            "citations": [],
            "chunks": [],
            "validation": None,
            "source_mode": "gemini_fallback",
            "retrieval_confidence": 0.0,
            "chunk_ids": [],
            "chunk_sources": [],
            "abstained": False,
            "repaired": False,
        }

    monkeypatch.setattr("backend.rag_tutor._search_chunks", fake_search_chunks)
    monkeypatch.setattr("backend.rag_tutor._load_document_context", fake_load_document_context)
    monkeypatch.setattr("backend.rag_tutor.calculate_retrieval_confidence", lambda *args, **kwargs: 0.1)
    monkeypatch.setattr("backend.rag_tutor._generate_gemini_fallback", fake_generate_fallback)

    result = asyncio.run(
        answer_query_with_rag(
            user_id="user-1",
            query="tell me something from the base kb",
            subject="general",
            document_ids=[],
            scope_mode="system_only",
        )
    )

    assert result["source_mode"] == "gemini_fallback"
    assert result["answer"] == "Gemini fallback answer."
    assert result["abstained"] is False
    assert result["document_coverage"]["covered_document_count"] == 0


def test_retrieve_chunks_for_streaming_uses_gemini_fallback_for_low_confidence_kb(monkeypatch):
    async def fake_search_chunks(user_id, subject, query, top_k, document_ids, chat_id, file_count, scope_mode, answer_mode=None):
        assert scope_mode == "system_only"
        return (
            [{"id": "chunk-1", "text": "Thin KB evidence.", "metadata": {"source": "system", "doc_id": "sys-1"}}],
            {"chunk_ids": [], "chunk_sources": []},
            {},
            False,
            False,
        )

    async def fake_load_document_context(chat_id):
        return "", [], []

    monkeypatch.setattr("backend.rag_tutor._search_chunks", fake_search_chunks)
    monkeypatch.setattr("backend.rag_tutor._load_document_context", fake_load_document_context)
    monkeypatch.setattr("backend.rag_tutor.calculate_retrieval_confidence", lambda *args, **kwargs: 0.1)

    result = asyncio.run(
        retrieve_chunks_for_streaming(
            user_id="user-1",
            query="tell me something from the base kb",
            subject="general",
            document_ids=[],
            scope_mode="system_only",
        )
    )

    assert result["source_mode"] == "gemini_fallback"
    assert result["abstain_response"] is None
    assert result["chunks"] == []
    assert result["citations"] == []


def test_resolve_scope_mode_prefers_document_scope_when_session_has_docs():
    assert _resolve_scope_mode(document_ids=["doc-1"], explicit_scope_mode="system_only") == "document_scoped"
    assert _resolve_scope_mode(document_ids=[], explicit_scope_mode="system_only") == "system_only"
    assert _resolve_scope_mode(document_ids=None, explicit_scope_mode=None) == "system_only"


def test_search_engine_system_only_scope_skips_user_chunks(monkeypatch):
    engine = HybridSearchEngine()

    def fake_get_all_chunks(user_id, subject, where=None):
        if user_id == "global":
            return [{"id": "sys-1", "text": "System base knowledge.", "metadata": {"source": "system", "doc_id": "sys"}}]
        raise AssertionError("user chunks should not be fetched in system_only mode")

    def fake_query_user_collection(user_id, subject, query_embedding, top_k=6, where=None):
        if user_id == "global":
            return [{"id": "sys-1", "text": "System base knowledge.", "metadata": {"source": "system", "doc_id": "sys"}, "score": 0.2}]
        raise AssertionError("user vector search should not run in system_only mode")

    monkeypatch.setattr("backend.core.search_engine.get_all_chunks", fake_get_all_chunks)
    monkeypatch.setattr("backend.core.search_engine.query_user_collection", fake_query_user_collection)
    monkeypatch.setattr("backend.core.search_engine.embedding_service.embed_text", lambda query: [0.1, 0.2])
    monkeypatch.setattr(engine, "_bm25_search", lambda query, docs, top_k: docs)
    monkeypatch.setattr(engine, "_rrf_fusion", lambda bm25, vec, initial_k: bm25 if bm25 else vec)
    monkeypatch.setattr(engine, "_ensure_reranker", lambda: False)

    results = engine.search(
        user_id="user-1",
        subject="general",
        query="what is in the base kb",
        top_k=3,
        document_ids=[],
        scope_mode="system_only",
    )

    assert len(results) == 1
    assert results[0]["id"] == "sys-1"
