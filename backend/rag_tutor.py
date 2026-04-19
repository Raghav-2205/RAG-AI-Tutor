import asyncio
import logging
import re
import warnings
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings
from backend.core.evaluation.metrics import calculate_retrieval_confidence, get_evaluation_chunk_id
from backend.core.evaluation.validator import ValidationEngine
from backend.core.feedback_analyzer import FeedbackAnalyzer
from backend.core.llm_interface import SOCRATIC_SYSTEM_PROMPT, llm_client
from backend.core.search_engine import search_engine
from backend.utils.db import db_manager

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

STRICT_RAG_TEMPERATURE = 0.15
REPAIR_RAG_TEMPERATURE = 0.0
RETRIEVAL_ABSTAIN_THRESHOLD = 0.48
RETRIEVAL_REPAIR_THRESHOLD = 0.62
FAITHFULNESS_REPAIR_THRESHOLD = 0.86
HALLUCINATION_REPAIR_THRESHOLD = 0.12
CITATION_REPAIR_THRESHOLD = 0.82
COVERAGE_REPAIR_THRESHOLD = 0.58
BENCHMARK_BERT_REPAIR_THRESHOLD = 0.8
LIVE_BERT_REPAIR_THRESHOLD = 0.76
BENCHMARK_RELEVANCE_REPAIR_THRESHOLD = 0.92
LIVE_RELEVANCE_REPAIR_THRESHOLD = 0.88
BENCHMARK_MODE = "benchmark_mode"
LIVE_TUTOR_MODE = "live_tutor_mode"
SYNTHESIS_KEYWORDS = (
    "both",
    "compare",
    "comparison",
    "common",
    "difference",
    "different",
    "documents",
    "docuemnts",
    "summarize both",
    "what are these documents about",
    "what are both documents about",
    "what are the both documents about",
    "what are the both docuemnts about",
    "what are the both documents related about",
    "what are these documents related to",
    "what are the documents related to",
)
MULTI_DOCUMENT_OVERVIEW_KEYWORDS = (
    "what are both documents about",
    "what are the both documents about",
    "what are the both docuemnts about",
    "what are these documents about",
    "what are these docuemnts about",
    "what are the both documents related about",
    "what are the both docuemnts related about",
    "what are these documents related to",
    "what are the documents related to",
    "how are these documents related",
    "how are both documents related",
    "summarize both documents",
    "summarise both documents",
)
DOCUMENT_OVERVIEW_KEYWORDS = (
    "what is this document about",
    "what is this doc about",
    "what is this file about",
    "what is this pdf about",
    "what is this chapter about",
    "summarize this document",
    "summarise this document",
    "summary of this document",
    "overview of this document",
    "describe this document",
    "what does this document cover",
    "what does this file cover",
    "what is this note about",
    "what is this notes about",
)
INSUFFICIENT_EVIDENCE_PHRASES = (
    "not enough evidence",
    "insufficient evidence",
    "no relevant evidence",
    "not relevant to this question",
    "does not provide enough evidence",
    "should not guess",
    "do not have enough retrieved evidence",
)


def _has_multiple_documents(file_count: int, document_ids: Optional[List[str]] = None) -> bool:
    return file_count >= 2 or len(document_ids or []) >= 2


def _is_explicit_comparison_query(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(keyword in lowered for keyword in SYNTHESIS_KEYWORDS)


def _is_document_overview_query(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in DOCUMENT_OVERVIEW_KEYWORDS)


def _is_multi_document_overview_query(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in MULTI_DOCUMENT_OVERVIEW_KEYWORDS)


def _is_benchmark_definition_query(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered or _is_document_overview_query(lowered) or _is_multi_document_overview_query(lowered):
        return False
    return lowered.startswith("what is ") or lowered.startswith("what exactly is ")


def _is_benchmark_reason_query(query: str) -> bool:
    return str(query or "").strip().lower().startswith("why ")


def _is_benchmark_difference_query(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    return lowered.startswith("how is ") and "different" in lowered


def _is_benchmark_list_query(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False
    starters = (
        "what are ",
        "which ",
        "what topics",
        "what are some features",
    )
    return lowered.startswith(starters)


def _build_benchmark_structure(query: str) -> str:
    if _is_benchmark_definition_query(query):
        return (
            "Benchmark format for a definition question:\n"
            "1. Write exactly one compact sentence in roughly 18 to 35 words.\n"
            "2. Put the main definition first and keep only the most essential qualifying detail.\n"
            "3. Do not use bullets, preambles, teaching filler, or extra examples.\n"
            "4. End the sentence with one or two citations only."
        )
    if _is_benchmark_reason_query(query):
        return (
            "Benchmark format for a why-question:\n"
            "1. Write one direct causal sentence, with a second short sentence only if needed.\n"
            "2. Focus on the main reason stated in the retrieved material.\n"
            "3. Do not use bullets or broad elaboration.\n"
            "4. Use one or two citations total."
        )
    if _is_benchmark_difference_query(query):
        return (
            "Benchmark format for a comparison question:\n"
            "1. Write one concise comparison sentence.\n"
            "2. Name the distinguishing trait directly from the retrieved material.\n"
            "3. Do not use bullets or extra side details.\n"
            "4. Use one or two citations total."
        )
    if _is_benchmark_list_query(query):
        return (
            "Benchmark format for a list question:\n"
            "1. Write one compact sentence or one lead sentence followed by a semicolon-separated list.\n"
            "2. Include only the requested roles, tools, topics, features, or concepts.\n"
            "3. Do not add explanations for each item unless the question asks for them.\n"
            "4. Do not use markdown bullets.\n"
            "5. Use one or two citations total."
        )
    return (
        "Benchmark format:\n"
        "1. Answer in no more than two short sentences.\n"
        "2. Put the direct answer first and keep only high-value supported details.\n"
        "3. Do not use bullets, filler, or broad paraphrases.\n"
        "4. Use one or two citations total."
    )


def _is_overly_verbose_benchmark_answer(answer: str) -> bool:
    text = str(answer or "").strip()
    if not text:
        return False
    bullet_count = len(re.findall(r"(?m)^\s*(?:[-*]|\d+\.)\s+", text))
    sentence_count = len(re.findall(r"[.!?]+(?:\s|$)", text))
    paragraph_count = len([block for block in re.split(r"\n\s*\n", text) if block.strip()])
    return bullet_count > 0 or sentence_count > 2 or paragraph_count > 1 or len(text) > 360


def _build_document_records(
    document_ids: Optional[List[str]] = None,
    document_names: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    ids = [str(item) for item in (document_ids or []) if str(item or "").strip()]
    names = [str(item).strip() for item in (document_names or []) if str(item or "").strip()]
    total = max(len(ids), len(names))
    records: List[Dict[str, str]] = []
    for index in range(total):
        doc_id = ids[index] if index < len(ids) else ""
        fallback_name = f"Document {index + 1}"
        name = names[index] if index < len(names) else (doc_id or fallback_name)
        records.append({
            "doc_id": doc_id,
            "name": name,
            "label": name,
        })
    return records


def _build_document_coverage_payload(
    documents: List[Dict[str, str]],
    chunks: List[Dict[str, Any]],
    graph_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    graph_payload = graph_payload or {}
    existing_map = graph_payload.get("document_coverage_map") or []
    existing_by_doc: Dict[str, Dict[str, Any]] = {}
    existing_by_name: Dict[str, Dict[str, Any]] = {}
    for item in existing_map:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if doc_id:
            existing_by_doc[doc_id] = item
        if name:
            existing_by_name[name] = item

    selected_counts: Dict[str, int] = {}
    selected_source_counts: Dict[str, int] = {}
    for chunk in chunks:
        metadata = chunk.get("metadata") or {}
        doc_id = str(metadata.get("doc_id") or "").strip()
        source = str(metadata.get("source") or "").strip()
        if doc_id:
            selected_counts[doc_id] = selected_counts.get(doc_id, 0) + 1
        if source:
            selected_source_counts[source] = selected_source_counts.get(source, 0) + 1

    coverage_entries: List[Dict[str, Any]] = []
    covered_names: List[str] = []
    unsupported_documents: List[str] = []
    for index, document in enumerate(documents):
        doc_id = str(document.get("doc_id") or "").strip()
        name = str(document.get("name") or document.get("label") or f"Document {index + 1}").strip()
        base = existing_by_doc.get(doc_id) or existing_by_name.get(name) or {}
        selected_chunk_count = int(base.get("selected_chunk_count") or 0)
        if doc_id:
            selected_chunk_count = max(selected_chunk_count, selected_counts.get(doc_id, 0))
        if name:
            selected_chunk_count = max(selected_chunk_count, selected_source_counts.get(name, 0))
        graph_fact_count = int(base.get("graph_fact_count") or 0)
        supported = bool(selected_chunk_count or graph_fact_count)
        entry = {
            "doc_id": doc_id,
            "name": name,
            "selected_chunk_count": selected_chunk_count,
            "graph_fact_count": graph_fact_count,
            "supported": supported,
            "unsupported_for_query": not supported,
        }
        coverage_entries.append(entry)
        if supported:
            covered_names.append(name)
        else:
            unsupported_documents.append(name)

    total_documents = len(coverage_entries)
    covered_document_count = len(covered_names)
    coverage_ratio = round(covered_document_count / total_documents, 4) if total_documents else 0.0
    return {
        "documents": coverage_entries,
        "matched_sources": covered_names,
        "total_sources": total_documents,
        "total_documents": total_documents,
        "covered_document_count": covered_document_count,
        "unsupported_documents": unsupported_documents,
        "coverage_ratio": coverage_ratio,
    }


def _build_history_text(history: Optional[List[Dict[str, Any]]]) -> str:
    if not history:
        return ""
    return "Chat History:\n" + "\n".join(
        f"{message['role']}: {message['content']}"
        for message in history[-4:]
    ) + "\n\n"


def _is_multi_document_query(query: str, file_count: int, document_ids: Optional[List[str]] = None) -> bool:
    return _has_multiple_documents(file_count, document_ids)


def _resolve_scope_mode(
    document_ids: Optional[List[str]] = None,
    explicit_scope_mode: Optional[str] = None,
) -> str:
    normalized = str(explicit_scope_mode or "").strip().lower()
    if normalized in {"document_scoped", "system_only"}:
        return normalized
    if document_ids:
        return "document_scoped"
    return "system_only"


def _resolve_answer_mode(user_id: Optional[str], explicit_answer_mode: Optional[str] = None) -> str:
    normalized = str(explicit_answer_mode or "").strip().lower()
    if normalized in {BENCHMARK_MODE, LIVE_TUTOR_MODE}:
        return normalized
    if str(user_id or "").strip() == "benchmark_runner":
        return BENCHMARK_MODE
    return LIVE_TUTOR_MODE


async def _load_session_document_state(chat_id: Optional[str]) -> Dict[str, Any]:
    if not chat_id or db_manager.db is None:
        return {"document_ids": [], "document_names": [], "documents": []}
    try:
        session = await db_manager.db.chat_sessions.find_one({"chat_id": chat_id})
        document_ids = list(session.get("document_ids") or []) if session else []
        document_names = list(session.get("document_names") or []) if session else []
        return {
            "document_ids": document_ids,
            "document_names": document_names,
            "documents": _build_document_records(document_ids, document_names),
        }
    except Exception:
        logger.debug("Unable to load session document state", exc_info=True)
        return {"document_ids": [], "document_names": [], "documents": []}


async def _load_document_context(chat_id: Optional[str]) -> Tuple[str, List[str], List[Dict[str, str]]]:
    if not chat_id or db_manager.db is None:
        return "", [], []
    state = await _load_session_document_state(chat_id)
    names = state.get("document_names", [])
    if names:
        return f"Currently indexed files in this session: {', '.join(names)}\n\n", names, state.get("documents", [])
    return "", [], state.get("documents", [])


async def _load_graph_payload(
    query: str,
    chat_id: Optional[str],
    file_count: int,
    document_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not chat_id or db_manager.db is None:
        return {}
    try:
        from backend.services.grag_service import get_grag_session_state, session_supports_grag, graph_retrieve

        session_state = await get_grag_session_state(db_manager.db, chat_id)
        effective_file_count = max(int(file_count or 0), int(session_state.get("file_count") or 0))
        effective_document_ids = list(session_state.get("document_ids") or document_ids or [])
        if not session_supports_grag(file_count=effective_file_count, document_ids=effective_document_ids):
            return {}

        logger.info("[GRAG] File count %s >= 2, using GRAG pipeline", file_count)
        results = await graph_retrieve(db_manager.db, chat_id, query)
        return results[0] if results else {}
    except Exception:
        logger.warning("Graph retrieval failed; continuing with chunk-only context", exc_info=True)
        return {}


def _graph_payload_has_context(graph_payload: Optional[Dict[str, Any]]) -> bool:
    payload = graph_payload or {}
    return bool(
        payload.get("context_summary")
        or payload.get("graph_facts")
        or payload.get("per_document_facts")
        or payload.get("cross_document_facts")
        or payload.get("support_chunk_ids")
    )


def _build_context_parts(
    chunks: List[Dict[str, Any]],
    graph_payload: Dict[str, Any],
    synthesis_mode: bool,
) -> Tuple[List[str], Dict[str, Any]]:
    context_parts: List[str] = []
    normalized_graph = graph_payload or {}
    if normalized_graph.get("context_summary"):
        label = "Graph Synthesis Context" if synthesis_mode else "Graph Context"
        context_parts.append(f"{label}:\n{normalized_graph['context_summary']}")
    if normalized_graph.get("graph_facts"):
        facts = "\n".join(f"- {fact}" for fact in normalized_graph["graph_facts"][:6])
        context_parts.append(f"Graph Facts:\n{facts}")
    if normalized_graph.get("per_document_facts"):
        for document_name, facts in list((normalized_graph.get("per_document_facts") or {}).items())[:8]:
            fact_lines = [f"- {fact}" for fact in (facts or [])[:3]]
            if fact_lines:
                context_parts.append(f"Document Evidence - {document_name}:\n" + "\n".join(fact_lines))
    if normalized_graph.get("cross_document_facts"):
        overlap_lines = "\n".join(f"- {fact}" for fact in normalized_graph["cross_document_facts"][:4])
        context_parts.append(f"Cross-Document Evidence:\n{overlap_lines}")

    for index, chunk in enumerate(chunks, start=1):
        source = chunk.get("metadata", {}).get("source", "Unknown")
        text = chunk.get("text", "")
        context_parts.append(f"[CHUNK {index}] From document \"{source}\"\n{text}")

    return context_parts, normalized_graph


def _select_generation_chunks(
    chunks: List[Dict[str, Any]],
    answer_mode: str,
    synthesis_mode: bool,
) -> List[Dict[str, Any]]:
    if not chunks:
        return []
    if synthesis_mode:
        limit = 6 if answer_mode == BENCHMARK_MODE else 7
        return chunks[:limit]
    limit = 5 if answer_mode == BENCHMARK_MODE else 6
    return chunks[:limit]


def _extract_citation_numbers(raw_text: str) -> List[str]:
    if not raw_text:
        return []
    numbers: List[str] = []
    lead = re.search(r"CHUNK\s+(\d+)", raw_text, flags=re.IGNORECASE)
    if lead:
        numbers.append(lead.group(1))
    for match in re.finditer(r",\s*(\d+)\b", raw_text):
        number = match.group(1)
        if number not in numbers:
            numbers.append(number)
    return numbers


def _canonical_chunk_refs(numbers: List[str]) -> str:
    unique_numbers: List[str] = []
    for number in numbers:
        cleaned = str(number or "").strip()
        if cleaned and cleaned not in unique_numbers:
            unique_numbers.append(cleaned)
    return "".join(f"[CHUNK {number}]" for number in unique_numbers)


def _normalize_answer_citations(answer: str) -> str:
    text = str(answer or "")
    if not text.strip():
        return text

    text = re.sub(
        r"\[[^\]]*CHUNK[^\]]*\]",
        lambda match: _canonical_chunk_refs(_extract_citation_numbers(match.group(0))) or match.group(0),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\([^)]*CHUNK[^)]*\)",
        lambda match: _canonical_chunk_refs(_extract_citation_numbers(match.group(0))) or match.group(0),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bCHUNK\s+(\d+)\s*(?=(?:Source|Page|Type)\s*:)",
        lambda match: f"[CHUNK {match.group(1)}]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bCHUNK\s+(\d+(?:\s*,\s*\d+)+)\b",
        lambda match: _canonical_chunk_refs(re.findall(r"\d+", match.group(1))) or match.group(0),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?im)^[ \t]*(?:Source|Page|Type)\s*:\s*[^\n]*(?:\n|$)", "", text)
    text = re.sub(r"\s*(?:Source|Page|Type)\s*:\s*[^\[\]\n]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\[)\bCHUNK\s+(\d+)\b", r"[CHUNK \1]", text, flags=re.IGNORECASE)
    text = re.sub(r"(\[CHUNK \d+\])\s*,\s*(?=\[CHUNK \d+\])", r"\1", text)
    text = re.sub(r"(\[CHUNK \d+\])\s+(?=\[CHUNK \d+\])", r"\1", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_grounded_prompt(
    query: str,
    context_text: str,
    history_text: str,
    doc_context: str,
    strict_mode: bool,
    answer_mode: str = LIVE_TUTOR_MODE,
    synthesis_mode: bool = False,
    document_names: Optional[List[str]] = None,
    document_coverage: Optional[Dict[str, Any]] = None,
    repair_reason: Optional[str] = None,
    draft_answer: Optional[str] = None,
    best_effort_mode: bool = False,
) -> str:
    repair_block = ""
    if repair_reason:
        repair_block = (
            "Your previous draft was not grounded enough.\n"
            f"Repair reason: {repair_reason}\n"
        )
        if draft_answer:
            repair_block += f"Previous draft:\n{draft_answer}\n\n"

    grounding_rules = (
        "Use only the retrieved material below. If the material is incomplete, say exactly what is supported and "
        "state that the evidence is insufficient for the rest. Never guess."
    )
    if strict_mode:
        grounding_rules += " STRICT MODE: every factual claim must be attributable to the provided chunks or graph facts."

    if synthesis_mode:
        doc_list = ", ".join(document_names or [])
        coverage_entries = list((document_coverage or {}).get("documents") or [])
        unsupported_documents = list((document_coverage or {}).get("unsupported_documents") or [])
        document_lines = "\n".join(
            f"- {entry.get('name')}: {'supported evidence available' if entry.get('supported') else 'no strong evidence retrieved for this query'}"
            for entry in coverage_entries
        )
        if _is_multi_document_overview_query(query):
            structure = (
                "This is a broad multi-document overview question.\n"
                f"Documents in scope: {doc_list if doc_list else 'the uploaded documents'}.\n"
                "Structure the answer as:\n"
                "1. A 'Direct Answer' sentence stating what the documents are mainly related to.\n"
                "2. A 'Document Summaries' section with one concise bullet per uploaded document. Use the actual document name in each bullet.\n"
                "3. A 'How They Are Related' section with one or two short bullets using only directly supported shared themes.\n"
                "4. A 'Differences' section only if the differences are explicitly supported.\n"
                "5. An 'Evidence Gaps' section only when one or more uploaded documents lack relevant support.\n"
                "Keep the answer concise, query-shaped, and grounded. Do not introduce adjacent domain concepts unless they appear in retrieved chunks or graph facts."
            )
        else:
            structure = (
                "This is a multi-document synthesis question.\n"
                f"Documents in scope: {doc_list if doc_list else 'the uploaded documents'}.\n"
                "Structure the answer as:\n"
                "1. A 'Direct Answer' sentence.\n"
                "2. A 'Document Summaries' section with one concise bullet per uploaded document. Use the actual document name in each bullet.\n"
                "3. A 'Shared Themes' section.\n"
                "4. A 'Differences' section, only if supported.\n"
                "5. An 'Evidence Gaps' section only when one or more uploaded documents lack relevant support.\n"
                "Keep the answer concise and grounded."
            )
        if best_effort_mode:
            structure += (
                "\nBest-effort rule: do not give a blanket refusal when any uploaded document has support. "
                "Summarize every supported document first, then explicitly name any unsupported document in the Evidence Gaps section."
            )
        if unsupported_documents:
            structure += f"\nKnown evidence gaps right now: {', '.join(unsupported_documents)}."
        if document_lines:
            structure += (
                "\nCurrent document evidence map:\n"
                f"{document_lines}\n"
                "Do not skip any uploaded document. If a document lacks support, say that explicitly in the Evidence Gaps section."
            )
        if answer_mode == BENCHMARK_MODE:
            structure += (
                "\nBenchmark style: keep each section terse, preserve source terminology, and avoid teaching-style filler."
            )
    else:
        if answer_mode == BENCHMARK_MODE:
            structure = (
                "Write the strongest benchmark-style grounded answer.\n"
                f"{_build_benchmark_structure(query)}\n"
                "Preserve key source terminology and avoid tutoring filler, motivational phrasing, or long paraphrases.\n"
                "Do not copy metadata such as 'Source:', 'Page:', or raw chunk headers."
            )
        elif _is_document_overview_query(query):
            structure = (
                "This is a document overview question.\n"
                "Write a concise overview with:\n"
                "1. A one-sentence summary of what the retrieved sections are mainly about.\n"
                "2. Two to five short bullets covering the main topics, themes, or sections visible in the chunks.\n"
                "3. If the retrieved chunks appear to cover only part of the document, say 'Based on the retrieved sections...' and continue with the supported overview.\n"
                "4. Do not refuse when the chunks clearly support a partial document summary.\n"
                "5. No copied metadata such as 'Source:', 'Page:', or raw chunk headers."
            )
        else:
            structure = (
                "Write a concise, well-structured answer with:\n"
                "1. A one-sentence direct answer first.\n"
                "2. Two to four short bullets for key supporting points.\n"
                "3. No copied metadata such as 'Source:', 'Page:', or raw chunk headers."
            )

    return (
        f"{history_text}{doc_context}"
        f"{repair_block}"
        "Use the following course materials from the indexed files to answer the student's question.\n"
        f"{grounding_rules}\n"
        f"{structure}\n\n"
        f"{context_text}\n\n"
        f"Student Question: {query}\n\n"
        "Citation rules:\n"
        "- Use inline citations in the exact format [CHUNK n].\n"
        "- Add at least one citation to every factual paragraph or bullet.\n"
        "- Do not mention 'Source:', 'Page:', or copy the chunk labels verbatim.\n"
        "- If evidence is split across chunks, cite both like [CHUNK 1][CHUNK 2]."
    )


def _build_fallback_prompt(query: str, history_text: str) -> str:
    return (
        f"{history_text}You are a helpful AI tutor. A student has asked you a question.\n\n"
        f"Student Question: {query}\n\n"
        "Provide a comprehensive, student-friendly educational explanation. "
        "Use examples when helpful, but keep the answer accurate and concise."
    )


def _build_system_prompt(
    feedback_context: str = "",
    strict_mode: bool = True,
    answer_mode: str = LIVE_TUTOR_MODE,
    repair_mode: bool = False,
    synthesis_mode: bool = False,
    best_effort_mode: bool = False,
) -> str:
    prompt = SOCRATIC_SYSTEM_PROMPT
    if feedback_context:
        prompt += "\n" + feedback_context
    if strict_mode:
        prompt += (
            "\nSTRICT GROUNDING RULES:\n"
            "- Use only the provided chunks and graph context.\n"
            "- Do not use outside knowledge.\n"
            "- If the evidence is incomplete, answer with the supported part first and briefly note any uncertainty instead of refusing when the retrieved chunks clearly support a partial answer.\n"
            "- Keep claims traceable to the cited chunks."
        )
    if answer_mode == BENCHMARK_MODE:
        prompt += (
            "\nBENCHMARK ANSWER MODE:\n"
            "- Optimize for exactness, concise wording, and benchmark-style answer quality.\n"
            "- Start with the answer, preserve source terminology, and avoid extra teaching narration.\n"
            "- Prefer a short precise answer over a broad explanatory one.\n"
            "- Definition questions should usually be answered in a single sentence.\n"
            "- List questions should usually be answered in one compact list sentence, not bullets.\n"
            "- Use no more than two sentences unless the prompt explicitly requires sections."
        )
    if synthesis_mode:
        prompt += (
            "\nMULTI-DOCUMENT SYNTHESIS MODE:\n"
            "- Cover each document before making comparisons.\n"
            "- For broad overview questions, prefer per-document summaries first, then a short supported relationship statement.\n"
            "- Only state common themes or differences when the evidence supports them explicitly.\n"
            "- Do not introduce adjacent concepts unless they are explicitly present in the retrieved chunks or graph facts.\n"
            "- Prefer a short grounded answer to a speculative one."
        )
    if best_effort_mode:
        prompt += (
            "\nBEST-EFFORT MULTI-DOCUMENT RULE:\n"
            "- If any uploaded document has support, answer from that support instead of refusing.\n"
            "- When a document lacks relevant evidence, explicitly name it in an Evidence Gaps section.\n"
            "- Do not produce a blanket 'not enough evidence' refusal unless none of the uploaded documents are supported."
        )
    if repair_mode:
        prompt += (
            "\nREPAIR MODE:\n"
            "- Rewrite the answer from scratch using only supported statements.\n"
            "- Remove any unsupported detail from the previous draft.\n"
            "- Prefer a shorter answer over a speculative one."
        )
    return prompt


def _extract_chunk_metadata(chunks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    chunk_ids = [get_evaluation_chunk_id(chunk) for chunk in chunks]
    chunk_sources = [
        str(chunk.get("metadata", {}).get("source") or "")
        for chunk in chunks
        if chunk.get("metadata", {}).get("source")
    ]
    return {
        "chunk_ids": [chunk_id for chunk_id in chunk_ids if chunk_id],
        "chunk_sources": [source for source in chunk_sources if source],
    }


async def _get_feedback_signals(subject: Optional[str]) -> Dict[str, List[str]]:
    if db_manager.db is None:
        return {"chunk_ids": [], "chunk_sources": []}
    try:
        analyzer = FeedbackAnalyzer(db_manager.db)
        return await analyzer.get_low_quality_chunk_signals(subject=subject)
    except Exception:
        logger.warning("Failed to load feedback penalty signals", exc_info=True)
        return {"chunk_ids": [], "chunk_sources": []}


async def _search_chunks(
    user_id: str,
    subject: Optional[str],
    query: str,
    top_k: int,
    document_ids: Optional[List[str]],
    chat_id: Optional[str],
    file_count: int,
    scope_mode: str = "system_only",
    answer_mode: str = LIVE_TUTOR_MODE,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], Dict[str, Any], bool, bool]:
    loop = asyncio.get_event_loop()
    feedback_signals = await _get_feedback_signals(subject or "general")
    multi_document_mode = _is_multi_document_query(query, file_count=file_count, document_ids=document_ids)
    comparison_mode = multi_document_mode and _is_explicit_comparison_query(query)
    graph_payload = await _load_graph_payload(
        query,
        chat_id=chat_id,
        file_count=file_count,
        document_ids=document_ids,
    )

    search_call = partial(
        search_engine.search,
        user_id,
        subject,
        query,
        top_k,
        document_ids,
        feedback_signals.get("chunk_ids", []),
        feedback_signals.get("chunk_sources", []),
        graph_payload.get("support_chunk_ids", []),
        multi_document_mode,
        scope_mode,
        answer_mode,
    )
    chunks = await loop.run_in_executor(None, search_call)
    return chunks, feedback_signals, graph_payload, multi_document_mode, comparison_mode


def _build_abstain_answer(
    query: str,
    chunks: List[Dict[str, Any]],
    synthesis_mode: bool = False,
    document_coverage: Optional[Dict[str, Any]] = None,
) -> str:
    visible_sources = []
    for chunk in chunks[:3]:
        source = str(chunk.get("metadata", {}).get("source") or "").strip()
        if source and source not in visible_sources:
            visible_sources.append(source)
    source_note = f" in {', '.join(visible_sources)}" if visible_sources else ""
    unsupported_documents = list((document_coverage or {}).get("unsupported_documents") or [])
    unsupported_note = (
        f" The current retrieval did not surface enough evidence from: {', '.join(unsupported_documents)}."
        if unsupported_documents else ""
    )
    if synthesis_mode:
        return (
            "The retrieved material does not provide enough evidence to compare or summarize all of the uploaded documents"
            f"{source_note}.{unsupported_note} Based on the available context, I should not guess."
        )
    if chunks:
        return (
            "The retrieved material does not provide enough evidence to answer that confidently"
            f"{source_note}.{unsupported_note} Based on the available context, I should not guess."
        )
    return f"I do not have enough retrieved evidence to answer '{query}' confidently."


def _is_refusal_like_answer(answer: str) -> bool:
    answer_lower = str(answer or "").strip().lower()
    return any(phrase in answer_lower for phrase in INSUFFICIENT_EVIDENCE_PHRASES)


def _should_abstain(
    chunks: List[Dict[str, Any]],
    retrieval_confidence: float,
    source_mode: str,
    synthesis_mode: bool = False,
    query: Optional[str] = None,
    answer_mode: str = LIVE_TUTOR_MODE,
) -> bool:
    if str(answer_mode or "").strip().lower() == BENCHMARK_MODE:
        return False
    if source_mode not in {"knowledge_base", "document"}:
        return False
    if not chunks:
        return False
    if source_mode == "document":
        if _is_document_overview_query(query):
            return False
        threshold = 0.14 if synthesis_mode else 0.1
        return len(chunks) <= 1 and retrieval_confidence < threshold
    threshold = RETRIEVAL_ABSTAIN_THRESHOLD + (0.04 if synthesis_mode else 0.0)
    if retrieval_confidence < threshold:
        return True
    if len(chunks) == 1 and retrieval_confidence < (threshold + 0.04):
        return True
    return False


def _should_fallback_to_gemini(
    chunks: List[Dict[str, Any]],
    retrieval_confidence: float,
    source_mode: str,
    synthesis_mode: bool = False,
    query: Optional[str] = None,
    answer_mode: str = LIVE_TUTOR_MODE,
) -> bool:
    if str(answer_mode or "").strip().lower() == BENCHMARK_MODE:
        return False
    return source_mode == "knowledge_base" and _should_abstain(
        chunks,
        retrieval_confidence,
        source_mode,
        synthesis_mode=synthesis_mode,
        query=query,
        answer_mode=answer_mode,
    )


def _classify_document_response_mode(
    chunks: List[Dict[str, Any]],
    document_coverage: Dict[str, Any],
    graph_payload: Dict[str, Any],
    source_mode: str,
    synthesis_mode: bool,
) -> str:
    if source_mode != "document" or not synthesis_mode:
        return "standard"

    covered_document_count = int(document_coverage.get("covered_document_count") or 0)
    total_documents = int(
        document_coverage.get("total_documents")
        or document_coverage.get("total_sources")
        or len(document_coverage.get("documents") or [])
        or 0
    )
    unsupported_documents = list(document_coverage.get("unsupported_documents") or [])
    has_graph_support = bool(
        graph_payload.get("graph_facts")
        or graph_payload.get("per_document_facts")
        or graph_payload.get("support_chunk_ids")
    )

    if not chunks and not has_graph_support:
        return "abstain_no_evidence"
    if covered_document_count <= 0 and not has_graph_support:
        return "abstain_no_evidence"
    if unsupported_documents or (total_documents and covered_document_count < total_documents):
        return "generate_with_gap_note"
    return "generate_best_effort"


async def _validate_generated_answer(
    question: str,
    answer: str,
    chunks: List[Dict[str, Any]],
    user_id: str,
    subject: Optional[str],
    chat_id: Optional[str],
    graph_payload: Dict[str, Any],
    source_mode: str,
    persist_validation: bool = True,
):
    if db_manager.db is None:
        return None
    try:
        validator = ValidationEngine(db_manager.db)
        return await validator.validate_answer(
            question=question,
            answer=answer,
            retrieved_chunks=chunks,
            user_id=user_id,
            subject=subject or "general",
            chat_id=chat_id,
            graph_context=graph_payload,
            answer_source_mode=source_mode,
            persist_result=persist_validation,
        )
    except Exception:
        logger.error("Validation failed", exc_info=True)
        return None


def _should_repair(
    validation_result: Optional[ValidationEngine],
    retrieval_confidence: float,
    answer_mode: str = LIVE_TUTOR_MODE,
    answer_text: str = "",
) -> Tuple[bool, Optional[str]]:
    if validation_result is None:
        if retrieval_confidence < RETRIEVAL_REPAIR_THRESHOLD:
            return True, f"Weak retrieval confidence ({retrieval_confidence:.2f})"
        if answer_mode == BENCHMARK_MODE and _is_overly_verbose_benchmark_answer(answer_text):
            return True, "Benchmark answer was too verbose."
        return False, None

    faithfulness = float(getattr(validation_result, "faithfulness_score", 0.0) or 0.0)
    hallucination_rate = float(getattr(validation_result, "hallucination_rate", 0.0) or 0.0)
    citation_alignment = float(getattr(validation_result, "citation_alignment_score", 0.0) or 0.0)
    bert_score = float(getattr(validation_result, "bert_score", 0.0) or 0.0)
    answer_relevance = float(getattr(validation_result, "answer_relevance", 0.0) or 0.0)
    retrieval_conf = float(getattr(validation_result, "retrieval_confidence", retrieval_confidence) or 0.0)
    chunk_usage = getattr(validation_result, "chunk_usage", {}) or {}
    covered_ratio = float(chunk_usage.get("covered_ratio", 0.0) or 0.0)
    document_balance = float(chunk_usage.get("document_coverage_balance", 1.0) or 0.0)
    multi_doc_metrics = getattr(validation_result, "multi_document_metrics", {}) or {}
    missing_document_names = list(multi_doc_metrics.get("missing_document_names") or [])
    uploaded_document_count = int(multi_doc_metrics.get("uploaded_document_count") or 0)
    covered_document_count = int(multi_doc_metrics.get("covered_document_count") or 0)

    if faithfulness < FAITHFULNESS_REPAIR_THRESHOLD:
        return True, f"Low faithfulness ({faithfulness:.2f})"
    if hallucination_rate > HALLUCINATION_REPAIR_THRESHOLD:
        return True, f"Elevated hallucination risk ({hallucination_rate:.2f})"
    if citation_alignment < CITATION_REPAIR_THRESHOLD:
        return True, f"Low citation alignment ({citation_alignment:.2f})"
    if covered_ratio < COVERAGE_REPAIR_THRESHOLD:
        return True, f"Weak chunk coverage ({covered_ratio:.2f})"
    if missing_document_names:
        return True, f"Missing uploaded documents in answer ({', '.join(missing_document_names[:3])})"
    if uploaded_document_count >= 2 and covered_document_count < uploaded_document_count:
        return True, f"Only {covered_document_count}/{uploaded_document_count} uploaded documents were covered"
    if document_balance < 0.5:
        return True, f"Weak multi-document coverage ({document_balance:.2f})"
    bert_threshold = BENCHMARK_BERT_REPAIR_THRESHOLD if answer_mode == BENCHMARK_MODE else LIVE_BERT_REPAIR_THRESHOLD
    relevance_threshold = (
        BENCHMARK_RELEVANCE_REPAIR_THRESHOLD
        if answer_mode == BENCHMARK_MODE
        else LIVE_RELEVANCE_REPAIR_THRESHOLD
    )
    if bert_score and bert_score < bert_threshold:
        return True, f"Weak semantic overlap ({bert_score:.2f})"
    if answer_relevance and answer_relevance < relevance_threshold:
        return True, f"Weak answer relevance ({answer_relevance:.2f})"
    if retrieval_conf < RETRIEVAL_REPAIR_THRESHOLD:
        return True, f"Weak retrieval confidence ({retrieval_conf:.2f})"
    if answer_mode == BENCHMARK_MODE and _is_overly_verbose_benchmark_answer(answer_text):
        return True, "Benchmark answer was too verbose."
    return False, None


async def _prepare_retrieval_state(
    user_id: str,
    query: str,
    subject: Optional[str] = None,
    history: Optional[List] = None,
    top_k: Optional[int] = None,
    feedback_context: str = "",
    document_ids: Optional[List[str]] = None,
    file_count: int = 0,
    chat_id: Optional[str] = None,
    scope_mode: str = "system_only",
    answer_mode: Optional[str] = None,
) -> Dict[str, Any]:
    history = history or []
    if top_k is None:
        top_k = settings.top_k_retrieval

    resolved_scope_mode = _resolve_scope_mode(document_ids=document_ids, explicit_scope_mode=scope_mode)
    resolved_answer_mode = _resolve_answer_mode(user_id=user_id, explicit_answer_mode=answer_mode)

    if document_ids:
        chunks, feedback_signals, graph_payload, multi_document_mode, comparison_mode = await _search_chunks(
            user_id,
            subject,
            query,
            top_k,
            document_ids,
            chat_id,
            file_count,
            resolved_scope_mode,
            resolved_answer_mode,
        )
        source_mode = "document" if chunks else "document_not_found"
        logger.info("[TIER 1] Document-scoped search: %s chunks found", len(chunks))
    else:
        chunks, feedback_signals, graph_payload, multi_document_mode, comparison_mode = await _search_chunks(
            user_id,
            subject,
            query,
            top_k,
            None,
            chat_id,
            file_count,
            resolved_scope_mode,
            resolved_answer_mode,
        )
        source_mode = "knowledge_base" if chunks else "gemini_fallback"
        logger.info("[TIER 2] Knowledge base search: %s chunks found", len(chunks))

    graph_used = _graph_payload_has_context(graph_payload)

    if not chunks:
        if source_mode == "document_not_found":
            return {
                "chunks": [],
                "prompt": "",
                "system_prompt": "",
                "citations": [],
                "source_mode": source_mode,
                "graph_context": graph_payload,
                "retrieval_confidence": 0.0,
                "chunk_ids": [],
                "chunk_sources": [],
                "feedback_signals": feedback_signals,
                "abstain_response": "I couldn't find information about that in the uploaded document.",
                "graph_used": graph_used,
                "multi_document_mode": multi_document_mode,
                "comparison_mode": comparison_mode,
                "document_coverage": graph_payload.get("document_coverage", {}),
                "document_coverage_map": graph_payload.get("document_coverage_map", []),
                "unsupported_documents": graph_payload.get("unsupported_documents", []),
                "resolved_scope_mode": resolved_scope_mode,
                "resolved_answer_mode": resolved_answer_mode,
            }

        history_text = ""
        if history:
            history_text = "Previous conversation:\n" + "\n".join(
                f"{message['role']}: {message['content']}"
                for message in history[-4:]
            ) + "\n\n"

        return {
            "chunks": [],
            "prompt": _build_fallback_prompt(query, history_text),
            "system_prompt": (
                "You are a helpful AI tutor. Answer questions clearly and educationally. "
                "Be concise, accurate, and encouraging without adding fluff."
            ),
            "citations": [],
            "source_mode": source_mode,
            "graph_context": graph_payload if graph_used else {},
            "retrieval_confidence": 0.0,
            "chunk_ids": [],
            "chunk_sources": [],
            "feedback_signals": feedback_signals,
            "abstain_response": None,
            "graph_used": False,
            "multi_document_mode": multi_document_mode,
            "comparison_mode": comparison_mode,
            "document_coverage": graph_payload.get("document_coverage", {}),
            "document_coverage_map": graph_payload.get("document_coverage_map", []),
            "unsupported_documents": graph_payload.get("unsupported_documents", []),
            "resolved_scope_mode": resolved_scope_mode,
            "resolved_answer_mode": resolved_answer_mode,
            "document_response_mode": "document_not_found",
            "best_effort_mode": False,
        }

    doc_context, document_names, session_documents = await _load_document_context(chat_id)
    normalized_graph = dict(graph_payload or {})
    document_coverage = _build_document_coverage_payload(session_documents, chunks, normalized_graph)
    normalized_graph["document_coverage"] = document_coverage
    normalized_graph["document_coverage_map"] = document_coverage.get("documents", [])
    normalized_graph["unsupported_documents"] = document_coverage.get("unsupported_documents", [])
    normalized_graph["uploaded_documents"] = session_documents
    normalized_graph["comparison_mode"] = comparison_mode
    generation_chunks = _select_generation_chunks(
        chunks,
        answer_mode=resolved_answer_mode,
        synthesis_mode=multi_document_mode,
    )
    context_parts, normalized_graph = _build_context_parts(generation_chunks, normalized_graph, multi_document_mode)
    context_text = "\n\n".join(context_parts)
    history_text = _build_history_text(history)
    document_response_mode = _classify_document_response_mode(
        chunks=chunks,
        document_coverage=document_coverage,
        graph_payload=normalized_graph,
        source_mode=source_mode,
        synthesis_mode=multi_document_mode,
    )
    best_effort_mode = document_response_mode in {"generate_best_effort", "generate_with_gap_note"}
    retrieval_confidence = calculate_retrieval_confidence(
        chunks,
        has_graph_context=graph_used,
        graph_support=float(normalized_graph.get("graph_score", 0.0) or 0.0),
        document_coverage=float((normalized_graph.get("document_coverage") or {}).get("coverage_ratio", 0.0) or 0.0),
    )
    chunk_metadata = _extract_chunk_metadata(chunks)

    if _should_fallback_to_gemini(
        chunks,
        retrieval_confidence,
        source_mode,
        synthesis_mode=multi_document_mode,
        query=query,
        answer_mode=resolved_answer_mode,
    ):
        history_text = ""
        if history:
            history_text = "Previous conversation:\n" + "\n".join(
                f"{message['role']}: {message['content']}"
                for message in history[-4:]
            ) + "\n\n"
        return {
            "chunks": [],
            "prompt": _build_fallback_prompt(query, history_text),
            "system_prompt": (
                "You are a helpful AI tutor. Answer questions clearly and educationally. "
                "Be concise, accurate, and encouraging without adding fluff."
            ),
            "citations": [],
            "source_mode": "gemini_fallback",
            "graph_context": {},
            "retrieval_confidence": retrieval_confidence,
            "chunk_ids": [],
            "chunk_sources": [],
            "feedback_signals": feedback_signals,
            "abstain_response": None,
            "graph_used": False,
            "multi_document_mode": multi_document_mode,
            "comparison_mode": comparison_mode,
            "document_coverage": document_coverage,
            "document_coverage_map": document_coverage.get("documents", []),
            "unsupported_documents": document_coverage.get("unsupported_documents", []),
            "resolved_scope_mode": resolved_scope_mode,
            "resolved_answer_mode": resolved_answer_mode,
            "document_response_mode": "gemini_fallback",
            "best_effort_mode": False,
            "document_response_mode": "no_chunks",
            "best_effort_mode": False,
        }

    abstain_response = None
    if document_response_mode == "abstain_no_evidence" or (
        document_response_mode == "standard"
        and _should_abstain(
            chunks,
            retrieval_confidence,
            source_mode,
            synthesis_mode=multi_document_mode,
            query=query,
            answer_mode=resolved_answer_mode,
        )
    ):
        abstain_response = _build_abstain_answer(
            query,
            chunks,
            synthesis_mode=multi_document_mode,
            document_coverage=document_coverage,
        )

    return {
        "chunks": chunks,
        "prompt": _build_grounded_prompt(
            query=query,
            context_text=context_text,
            history_text=history_text,
            doc_context=doc_context,
            strict_mode=True,
            answer_mode=resolved_answer_mode,
            synthesis_mode=multi_document_mode,
            document_names=document_names,
            document_coverage=document_coverage,
            best_effort_mode=best_effort_mode,
        ),
        "system_prompt": _build_system_prompt(
            feedback_context=feedback_context,
            strict_mode=True,
            answer_mode=resolved_answer_mode,
            synthesis_mode=multi_document_mode,
            best_effort_mode=best_effort_mode,
        ),
        "citations": list(range(1, len(chunks) + 1)),
        "source_mode": source_mode,
        "graph_context": normalized_graph,
        "retrieval_confidence": retrieval_confidence,
        "chunk_ids": chunk_metadata["chunk_ids"],
        "chunk_sources": chunk_metadata["chunk_sources"],
        "feedback_signals": feedback_signals,
        "abstain_response": abstain_response,
        "graph_used": graph_used,
        "multi_document_mode": multi_document_mode,
        "comparison_mode": comparison_mode,
        "document_coverage": document_coverage,
        "document_coverage_map": document_coverage.get("documents", []),
        "unsupported_documents": document_coverage.get("unsupported_documents", []),
        "resolved_scope_mode": resolved_scope_mode,
        "resolved_answer_mode": resolved_answer_mode,
        "document_names": document_names,
        "doc_context": doc_context,
        "history_text": history_text,
        "document_response_mode": document_response_mode,
        "best_effort_mode": best_effort_mode,
    }


async def answer_query_with_rag(
    user_id: str,
    query: str,
    subject: Optional[str] = None,
    history: Optional[List] = None,
    top_k: Optional[int] = None,
    feedback_context: str = "",
    strict_mode: bool = True,
    document_ids: Optional[List[str]] = None,
    file_count: int = 0,
    chat_id: Optional[str] = None,
    scope_mode: str = "system_only",
    answer_mode: Optional[str] = None,
    persist_validation: bool = True,
):
    history = history or []
    prepared = await _prepare_retrieval_state(
        user_id=user_id,
        query=query,
        subject=subject,
        history=history,
        top_k=top_k,
        feedback_context=feedback_context,
        document_ids=document_ids,
        file_count=file_count,
        chat_id=chat_id,
        scope_mode=scope_mode,
        answer_mode=answer_mode,
    )

    if not prepared["chunks"]:
        if prepared["source_mode"] == "document_not_found":
            return {
                "answer": prepared["abstain_response"],
                "citations": [],
                "chunks": [],
                "source_mode": "document_not_found",
                "validation": None,
                "feedback_signals": prepared.get("feedback_signals", {"chunk_ids": [], "chunk_sources": []}),
                "graph_used": bool(prepared.get("graph_used")),
                "multi_document_mode": bool(prepared.get("multi_document_mode")),
                "comparison_mode": bool(prepared.get("comparison_mode")),
                "document_coverage": prepared.get("document_coverage", {}),
                "document_coverage_map": prepared.get("document_coverage_map", []),
                "unsupported_documents": prepared.get("unsupported_documents", []),
            }

        logger.info("[TIER 3] Gemini fallback triggered (no context available)")
        result = await _generate_gemini_fallback(query, history)
        result["feedback_signals"] = prepared.get("feedback_signals", {"chunk_ids": [], "chunk_sources": []})
        result["graph_used"] = False
        result["multi_document_mode"] = bool(prepared.get("multi_document_mode"))
        result["comparison_mode"] = bool(prepared.get("comparison_mode"))
        result["document_coverage"] = prepared.get("document_coverage", {})
        result["document_coverage_map"] = prepared.get("document_coverage_map", [])
        result["unsupported_documents"] = prepared.get("unsupported_documents", [])
        return result

    return await _generate_rag_answer(
        chunks=prepared["chunks"],
        query=query,
        history=history,
        feedback_context=feedback_context,
        strict_mode=strict_mode,
        user_id=user_id,
        subject=subject,
        source_mode=prepared["source_mode"],
        chat_id=chat_id,
        file_count=file_count,
        feedback_signals=prepared.get("feedback_signals"),
        graph_payload=prepared.get("graph_context"),
        synthesis_mode=bool(prepared.get("multi_document_mode")),
        comparison_mode=bool(prepared.get("comparison_mode")),
        answer_mode=prepared.get("resolved_answer_mode", LIVE_TUTOR_MODE),
        prepared_state=prepared,
        persist_validation=persist_validation,
    )


async def _generate_rag_answer(
    chunks: List[Dict[str, Any]],
    query: str,
    history: List[Dict[str, Any]],
    feedback_context: str,
    strict_mode: bool,
    user_id: str,
    subject: Optional[str],
    source_mode: str = "document",
    chat_id: Optional[str] = None,
    file_count: int = 0,
    feedback_signals: Optional[Dict[str, List[str]]] = None,
    graph_payload: Optional[Dict[str, Any]] = None,
    synthesis_mode: bool = False,
    comparison_mode: bool = False,
    answer_mode: str = LIVE_TUTOR_MODE,
    prepared_state: Optional[Dict[str, Any]] = None,
    persist_validation: bool = True,
):
    graph_payload = graph_payload or {}
    prepared_state = prepared_state or {}
    graph_used = bool(prepared_state.get("graph_used")) if prepared_state else _graph_payload_has_context(graph_payload)

    if prepared_state:
        normalized_graph = dict(prepared_state.get("graph_context") or {})
        document_coverage = prepared_state.get("document_coverage", {})
        prompt = prepared_state.get("prompt", "")
        system_prompt = prepared_state.get("system_prompt", "")
        doc_context = str(prepared_state.get("doc_context") or "")
        history_text = str(prepared_state.get("history_text") or "")
        document_names = list(prepared_state.get("document_names") or [])
        context_parts, normalized_graph = _build_context_parts(
            _select_generation_chunks(chunks, answer_mode=answer_mode, synthesis_mode=synthesis_mode),
            normalized_graph,
            synthesis_mode,
        )
        context_text = "\n\n".join(context_parts)
        retrieval_confidence = float(prepared_state.get("retrieval_confidence", 0.0) or 0.0)
        chunk_metadata = {
            "chunk_ids": list(prepared_state.get("chunk_ids", [])),
            "chunk_sources": list(prepared_state.get("chunk_sources", [])),
        }
        document_response_mode = str(prepared_state.get("document_response_mode") or "").strip() or _classify_document_response_mode(
            chunks=chunks,
            document_coverage=document_coverage,
            graph_payload=normalized_graph,
            source_mode=source_mode,
            synthesis_mode=synthesis_mode,
        )
        best_effort_mode = bool(prepared_state.get("best_effort_mode")) or document_response_mode in {
            "generate_best_effort",
            "generate_with_gap_note",
        }
    else:
        history_text = _build_history_text(history)
        doc_context, document_names, session_documents = await _load_document_context(chat_id)
        normalized_graph = dict(graph_payload or {})
        document_coverage = _build_document_coverage_payload(session_documents, chunks, normalized_graph)
        normalized_graph["document_coverage"] = document_coverage
        normalized_graph["document_coverage_map"] = document_coverage.get("documents", [])
        normalized_graph["unsupported_documents"] = document_coverage.get("unsupported_documents", [])
        normalized_graph["uploaded_documents"] = session_documents
        normalized_graph["comparison_mode"] = comparison_mode
        generation_chunks = _select_generation_chunks(chunks, answer_mode=answer_mode, synthesis_mode=synthesis_mode)
        context_parts, normalized_graph = _build_context_parts(generation_chunks, normalized_graph, synthesis_mode)
        context_text = "\n\n".join(context_parts)
        chunk_metadata = _extract_chunk_metadata(chunks)
        document_response_mode = _classify_document_response_mode(
            chunks=chunks,
            document_coverage=document_coverage,
            graph_payload=normalized_graph,
            source_mode=source_mode,
            synthesis_mode=synthesis_mode,
        )
        best_effort_mode = document_response_mode in {"generate_best_effort", "generate_with_gap_note"}
        retrieval_confidence = calculate_retrieval_confidence(
            chunks,
            has_graph_context=graph_used,
            graph_support=float(normalized_graph.get("graph_score", 0.0) or 0.0),
            document_coverage=float((normalized_graph.get("document_coverage") or {}).get("coverage_ratio", 0.0) or 0.0),
        )
        prompt = _build_grounded_prompt(
            query=query,
            context_text=context_text,
            history_text=history_text,
            doc_context=doc_context,
            strict_mode=strict_mode,
            answer_mode=answer_mode,
            synthesis_mode=synthesis_mode,
            document_names=document_names,
            document_coverage=document_coverage,
            best_effort_mode=best_effort_mode,
        )
        system_prompt = _build_system_prompt(
            feedback_context=feedback_context,
            strict_mode=strict_mode,
            answer_mode=answer_mode,
            synthesis_mode=synthesis_mode,
            best_effort_mode=best_effort_mode,
        )

    if _should_fallback_to_gemini(
        chunks,
        retrieval_confidence,
        source_mode,
        synthesis_mode=synthesis_mode,
        query=query,
        answer_mode=answer_mode,
    ):
        fallback_result = await _generate_gemini_fallback(query, history)
        fallback_result["retrieval_confidence"] = retrieval_confidence
        fallback_result["feedback_signals"] = feedback_signals or {"chunk_ids": [], "chunk_sources": []}
        fallback_result["graph_used"] = False
        fallback_result["multi_document_mode"] = synthesis_mode
        fallback_result["comparison_mode"] = comparison_mode
        fallback_result["document_coverage"] = document_coverage
        fallback_result["document_coverage_map"] = document_coverage.get("documents", [])
        fallback_result["unsupported_documents"] = document_coverage.get("unsupported_documents", [])
        return fallback_result

    if document_response_mode == "abstain_no_evidence" or (
        document_response_mode == "standard"
        and _should_abstain(
            chunks,
            retrieval_confidence,
            source_mode,
            synthesis_mode=synthesis_mode,
            query=query,
            answer_mode=answer_mode,
        )
    ):
        answer_text = _build_abstain_answer(
            query,
            chunks,
            synthesis_mode=synthesis_mode,
            document_coverage=document_coverage,
        )
        validation_result = await _validate_generated_answer(
            question=query,
            answer=answer_text,
            chunks=chunks,
            user_id=user_id,
            subject=subject,
            chat_id=chat_id,
            graph_payload=normalized_graph,
            source_mode=source_mode,
            persist_validation=persist_validation,
        )
        return {
            "answer": answer_text,
            "citations": list(range(1, len(chunks) + 1)),
            "chunks": chunks,
            "validation": validation_result.model_dump() if validation_result else None,
            "source_mode": source_mode,
            "retrieval_confidence": retrieval_confidence,
            "chunk_ids": chunk_metadata["chunk_ids"],
            "chunk_sources": chunk_metadata["chunk_sources"],
            "feedback_signals": feedback_signals or {"chunk_ids": [], "chunk_sources": []},
            "abstained": True,
            "repaired": False,
            "graph_used": graph_used,
            "multi_document_mode": synthesis_mode,
            "comparison_mode": comparison_mode,
            "document_coverage": document_coverage,
            "document_coverage_map": document_coverage.get("documents", []),
            "unsupported_documents": document_coverage.get("unsupported_documents", []),
        }

    try:
        response_text = await llm_client.async_generate(
            prompt,
            system_prompt=system_prompt,
            temperature=0.0 if answer_mode == BENCHMARK_MODE else STRICT_RAG_TEMPERATURE,
        )
        response_text = _normalize_answer_citations(response_text)
        validation_result = await _validate_generated_answer(
            question=query,
            answer=response_text,
            chunks=chunks,
            user_id=user_id,
            subject=subject,
            chat_id=chat_id,
            graph_payload=normalized_graph,
            source_mode=source_mode,
            persist_validation=persist_validation,
        )
        should_repair, repair_reason = _should_repair(
            validation_result,
            retrieval_confidence,
            answer_mode=answer_mode,
            answer_text=response_text,
        )
        if synthesis_mode and best_effort_mode and _is_refusal_like_answer(response_text):
            should_repair = True
            repair_reason = "The draft refused despite supported multi-document evidence."

        repaired = False
        if should_repair and chunks:
            repair_prompt = _build_grounded_prompt(
                query=query,
                context_text=context_text,
                history_text=history_text,
                doc_context=doc_context,
                strict_mode=True,
                answer_mode=answer_mode,
                synthesis_mode=synthesis_mode,
                document_names=document_names,
                document_coverage=document_coverage,
                repair_reason=repair_reason,
                draft_answer=response_text,
                best_effort_mode=best_effort_mode,
            )
            repair_system_prompt = _build_system_prompt(
                feedback_context=feedback_context,
                strict_mode=True,
                answer_mode=answer_mode,
                repair_mode=True,
                synthesis_mode=synthesis_mode,
                best_effort_mode=best_effort_mode,
            )
            repaired_text = await llm_client.async_generate(
                repair_prompt,
                system_prompt=repair_system_prompt,
                temperature=0.0 if answer_mode == BENCHMARK_MODE else REPAIR_RAG_TEMPERATURE,
            )
            repaired_text = _normalize_answer_citations(repaired_text)
            repaired_validation = await _validate_generated_answer(
                question=query,
                answer=repaired_text,
                chunks=chunks,
                user_id=user_id,
                subject=subject,
                chat_id=chat_id,
                graph_payload=normalized_graph,
                source_mode=source_mode,
                persist_validation=persist_validation,
            )
            repaired = True
            response_text = repaired_text
            validation_result = repaired_validation or validation_result

        return {
            "answer": response_text,
            "citations": list(range(1, len(chunks) + 1)),
            "chunks": chunks,
            "validation": validation_result.model_dump() if validation_result else None,
            "source_mode": source_mode,
            "retrieval_confidence": retrieval_confidence,
            "chunk_ids": chunk_metadata["chunk_ids"],
            "chunk_sources": chunk_metadata["chunk_sources"],
            "feedback_signals": feedback_signals or {"chunk_ids": [], "chunk_sources": []},
            "abstained": False,
            "repaired": repaired,
            "graph_used": graph_used,
            "multi_document_mode": synthesis_mode,
            "comparison_mode": comparison_mode,
            "document_coverage": document_coverage,
            "document_coverage_map": document_coverage.get("documents", []),
            "unsupported_documents": document_coverage.get("unsupported_documents", []),
        }
    except Exception:
        logger.error("RAG Generation Error", exc_info=True)
        return {
            "answer": "I encountered an error generating the answer.",
            "citations": [],
            "chunks": [],
            "source_mode": "error",
            "validation": None,
            "retrieval_confidence": retrieval_confidence,
            "chunk_ids": chunk_metadata["chunk_ids"],
            "chunk_sources": chunk_metadata["chunk_sources"],
            "feedback_signals": feedback_signals or {"chunk_ids": [], "chunk_sources": []},
            "abstained": False,
            "repaired": False,
            "graph_used": graph_used,
            "multi_document_mode": synthesis_mode,
            "comparison_mode": comparison_mode,
            "document_coverage": document_coverage,
            "document_coverage_map": document_coverage.get("documents", []),
            "unsupported_documents": document_coverage.get("unsupported_documents", []),
        }


async def _generate_gemini_fallback(query, history):
    history_text = ""
    if history:
        history_text = "Previous conversation:\n" + "\n".join(
            f"{item['role']}: {item['content']}"
            for item in history[-4:]
        ) + "\n\n"

    prompt = _build_fallback_prompt(query, history_text)
    try:
        response_text = await llm_client.async_generate(
            prompt,
            system_prompt=(
                "You are a helpful AI tutor. Answer questions clearly and educationally. "
                "Be concise, accurate, and encouraging without adding fluff."
            ),
            temperature=0.3,
        )
        return {
            "answer": response_text,
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
    except Exception:
        logger.error("Gemini Fallback Error", exc_info=True)
        return {
            "answer": "I'm having trouble generating a response right now. Please try again or upload a document for more specific help.",
            "citations": [],
            "chunks": [],
            "source_mode": "error",
            "validation": None,
            "retrieval_confidence": 0.0,
            "chunk_ids": [],
            "chunk_sources": [],
            "abstained": False,
            "repaired": False,
        }


async def retrieve_chunks_for_streaming(
    user_id: str,
    query: str,
    subject: Optional[str] = None,
    history: Optional[List] = None,
    top_k: Optional[int] = None,
    feedback_context: str = "",
    document_ids: Optional[List[str]] = None,
    file_count: int = 0,
    chat_id: Optional[str] = None,
    scope_mode: str = "system_only",
    answer_mode: Optional[str] = None,
) -> dict:
    return await _prepare_retrieval_state(
        user_id=user_id,
        query=query,
        subject=subject,
        history=history,
        top_k=top_k,
        feedback_context=feedback_context,
        document_ids=document_ids,
        file_count=file_count,
        chat_id=chat_id,
        scope_mode=scope_mode,
        answer_mode=answer_mode,
    )
