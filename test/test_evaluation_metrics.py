import asyncio

from backend.core.evaluation.metrics import (
    calculate_final_rag_score,
    calculate_retrieval_metrics,
    get_evaluation_chunk_id,
)
from backend.core.evaluation.run_evaluation import _resolve_gold_chunk_ids
from backend.core.evaluation.validator import ValidationEngine
from backend.preprocessing import analyze_chunk_set, chunk_text


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
        return 1.0

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
