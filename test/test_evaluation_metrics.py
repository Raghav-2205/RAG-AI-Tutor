from backend.core.evaluation.metrics import (
    calculate_final_rag_score,
    calculate_retrieval_metrics,
    get_evaluation_chunk_id,
)
from backend.core.evaluation.run_evaluation import _resolve_gold_chunk_ids


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
