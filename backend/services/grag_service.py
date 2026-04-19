import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

GENERIC_ENTITY_TERMS = {
    "chapter",
    "document",
    "documents",
    "introduction",
    "section",
    "student",
    "students",
    "topic",
    "topics",
    "unit",
    "lesson",
    "module",
    "unknown",
}

ENTITY_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,4})\b")
RELATION_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\s+"
    r"(is|are|has|have|uses|use|contains|includes|defines|describes|supports|requires|improves|enables|connects to)\s+"
    r"([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\b"
)
DEFINITION_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\s+"
    r"(is|are|refers to|means|describes|defines)\s+([^.!?\n]{12,220})"
)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_]+", str(text or "").lower())


def _canonical_entity_id(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s_-]", "", str(label or "").lower())
    normalized = re.sub(r"[\s-]+", "_", normalized).strip("_")
    return normalized


def _should_skip_entity(label: str) -> bool:
    cleaned = _normalize_whitespace(label)
    if len(cleaned) < 3:
        return True
    lowered = cleaned.lower()
    if lowered in GENERIC_ENTITY_TERMS:
        return True
    if lowered.startswith("the "):
        lowered = lowered[4:]
    return lowered in GENERIC_ENTITY_TERMS


def _safe_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if value is None:
        return []
    stringified = str(value).strip()
    return [stringified] if stringified else []


def _chunk_records_from_text(new_text: str, source: str) -> List[Dict[str, Any]]:
    text = str(new_text or "")
    if not text.strip():
        return []

    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", text) if segment.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    records: List[Dict[str, Any]] = []
    for index, paragraph in enumerate(paragraphs[:80]):
        snippet = _normalize_whitespace(paragraph)
        if len(snippet) < 20:
            continue
        records.append({
            "text": snippet,
            "metadata": {
                "chunk_id": f"{_canonical_entity_id(source or 'unknown')}_pseudo_{index}",
                "doc_id": _canonical_entity_id(source or "unknown"),
                "source": source,
            },
        })
    return records


def _iter_chunk_records(chunks: Optional[List[Dict[str, Any]]], new_text: str, source: str) -> Iterable[Dict[str, Any]]:
    provided = chunks or []
    if provided:
        for chunk in provided:
            text = _normalize_whitespace(chunk.get("text", ""))
            if not text:
                continue
            metadata = dict(chunk.get("metadata") or {})
            if "chunk_id" not in metadata:
                metadata["chunk_id"] = str(chunk.get("id") or "")
            if "source" not in metadata:
                metadata["source"] = source
            yield {"text": text, "metadata": metadata}
        return

    for record in _chunk_records_from_text(new_text, source):
        yield record


def _merge_unique(existing: List[str], values: Iterable[str], limit: int = 6) -> List[str]:
    merged = list(existing or [])
    seen = {item for item in merged if item}
    for value in values:
        if not value:
            continue
        item = str(value).strip()
        if not item or item in seen:
            continue
        merged.append(item)
        seen.add(item)
        if len(merged) >= limit:
            break
    return merged


def _build_node(
    label: str,
    source: str,
    doc_id: str,
    chunk_id: str,
    snippet: str,
) -> Dict[str, Any]:
    canonical_id = _canonical_entity_id(label)
    entity_type = "concept"
    lowered = label.lower()
    if any(keyword in lowered for keyword in ("university", "college", "school", "institute")):
        entity_type = "organization"
    elif any(keyword in lowered for keyword in ("chapter", "unit", "lesson", "module", "topic")):
        entity_type = "topic"

    return {
        "id": canonical_id,
        "label": _normalize_whitespace(label),
        "canonical_label": canonical_id,
        "type": entity_type,
        "sources": [source] if source else [],
        "doc_ids": [doc_id] if doc_id else [],
        "support_chunk_ids": [chunk_id] if chunk_id else [],
        "support_snippets": [snippet] if snippet else [],
        "mention_count": 1,
    }


def _merge_node(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    existing["sources"] = _merge_unique(existing.get("sources", []), incoming.get("sources", []))
    existing["doc_ids"] = _merge_unique(existing.get("doc_ids", []), incoming.get("doc_ids", []), limit=8)
    existing["support_chunk_ids"] = _merge_unique(
        existing.get("support_chunk_ids", []),
        incoming.get("support_chunk_ids", []),
        limit=12,
    )
    existing["support_snippets"] = _merge_unique(
        existing.get("support_snippets", []),
        incoming.get("support_snippets", []),
        limit=6,
    )
    existing["mention_count"] = int(existing.get("mention_count", 0) or 0) + int(incoming.get("mention_count", 0) or 0)
    if len(incoming.get("label", "")) > len(existing.get("label", "")):
        existing["label"] = incoming["label"]
    return existing


def _build_edge(
    source_id: str,
    target_id: str,
    relation: str,
    source_file: str,
    doc_id: str,
    chunk_id: str,
    snippet: str,
) -> Dict[str, Any]:
    return {
        "source": source_id,
        "target": target_id,
        "relation": relation,
        "source_files": [source_file] if source_file else [],
        "doc_ids": [doc_id] if doc_id else [],
        "support_chunk_ids": [chunk_id] if chunk_id else [],
        "support_snippets": [snippet] if snippet else [],
        "mention_count": 1,
    }


def _merge_edge(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    existing["source_files"] = _merge_unique(existing.get("source_files", []), incoming.get("source_files", []))
    existing["doc_ids"] = _merge_unique(existing.get("doc_ids", []), incoming.get("doc_ids", []), limit=8)
    existing["support_chunk_ids"] = _merge_unique(
        existing.get("support_chunk_ids", []),
        incoming.get("support_chunk_ids", []),
        limit=12,
    )
    existing["support_snippets"] = _merge_unique(
        existing.get("support_snippets", []),
        incoming.get("support_snippets", []),
        limit=6,
    )
    existing["mention_count"] = int(existing.get("mention_count", 0) or 0) + int(incoming.get("mention_count", 0) or 0)
    return existing


def _extract_entities_and_relations(chunks: Optional[List[Dict[str, Any]]], new_text: str, source: str) -> Dict[str, Any]:
    node_map: Dict[str, Dict[str, Any]] = {}
    edge_map: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    for record in _iter_chunk_records(chunks, new_text, source):
        text = record["text"]
        metadata = record.get("metadata") or {}
        chunk_id = str(metadata.get("chunk_id") or "")
        doc_id = str(metadata.get("doc_id") or "")
        source_name = str(metadata.get("source") or source or "Unknown")
        snippet = text[:220]

        chunk_entities: List[str] = []
        seen_labels = set()
        for match in ENTITY_PATTERN.finditer(text):
            label = _normalize_whitespace(match.group(1))
            if _should_skip_entity(label):
                continue
            canonical_id = _canonical_entity_id(label)
            if not canonical_id or canonical_id in seen_labels:
                continue
            seen_labels.add(canonical_id)
            chunk_entities.append(canonical_id)
            node = _build_node(label, source_name, doc_id, chunk_id, snippet)
            if canonical_id in node_map:
                node_map[canonical_id] = _merge_node(node_map[canonical_id], node)
            else:
                node_map[canonical_id] = node

        for match in RELATION_PATTERN.finditer(text):
            src_label = _normalize_whitespace(match.group(1))
            relation = _normalize_whitespace(match.group(2)).lower()
            tgt_label = _normalize_whitespace(match.group(3))
            if _should_skip_entity(src_label) or _should_skip_entity(tgt_label):
                continue
            src_id = _canonical_entity_id(src_label)
            tgt_id = _canonical_entity_id(tgt_label)
            if not src_id or not tgt_id or src_id == tgt_id:
                continue
            if src_id not in node_map:
                node_map[src_id] = _build_node(src_label, source_name, doc_id, chunk_id, snippet)
            if tgt_id not in node_map:
                node_map[tgt_id] = _build_node(tgt_label, source_name, doc_id, chunk_id, snippet)
            edge_key = (src_id, relation, tgt_id)
            edge = _build_edge(src_id, tgt_id, relation, source_name, doc_id, chunk_id, snippet)
            if edge_key in edge_map:
                edge_map[edge_key] = _merge_edge(edge_map[edge_key], edge)
            else:
                edge_map[edge_key] = edge

        for match in DEFINITION_PATTERN.finditer(text):
            entity_label = _normalize_whitespace(match.group(1))
            descriptor = _normalize_whitespace(match.group(3))
            if _should_skip_entity(entity_label):
                continue
            entity_id = _canonical_entity_id(entity_label)
            if entity_id not in node_map:
                node_map[entity_id] = _build_node(entity_label, source_name, doc_id, chunk_id, snippet)
            node_map[entity_id]["support_snippets"] = _merge_unique(
                node_map[entity_id].get("support_snippets", []),
                [f"{entity_label}: {descriptor}"],
                limit=6,
            )

        if len(chunk_entities) >= 2:
            anchor = chunk_entities[0]
            for other in chunk_entities[1:3]:
                edge_key = (anchor, "co_occurs_with", other)
                edge = _build_edge(anchor, other, "co_occurs_with", source_name, doc_id, chunk_id, snippet)
                if edge_key in edge_map:
                    edge_map[edge_key] = _merge_edge(edge_map[edge_key], edge)
                else:
                    edge_map[edge_key] = edge

    return {
        "nodes": list(node_map.values()),
        "edges": list(edge_map.values()),
    }


def _normalize_existing_graph(graph: Dict[str, Any]) -> Dict[str, Any]:
    normalized_nodes = []
    for node in graph.get("nodes", []):
        normalized_nodes.append({
            "id": str(node.get("id") or ""),
            "label": str(node.get("label") or node.get("id") or ""),
            "canonical_label": str(node.get("canonical_label") or node.get("id") or ""),
            "type": str(node.get("type") or "concept"),
            "sources": _safe_list(node.get("sources") or node.get("source")),
            "doc_ids": _safe_list(node.get("doc_ids")),
            "support_chunk_ids": _safe_list(node.get("support_chunk_ids")),
            "support_snippets": _safe_list(node.get("support_snippets")),
            "mention_count": int(node.get("mention_count", 1) or 1),
        })

    normalized_edges = []
    for edge in graph.get("edges", []):
        normalized_edges.append({
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            "relation": str(edge.get("relation") or "related_to"),
            "source_files": _safe_list(edge.get("source_files") or edge.get("source_file")),
            "doc_ids": _safe_list(edge.get("doc_ids")),
            "support_chunk_ids": _safe_list(edge.get("support_chunk_ids")),
            "support_snippets": _safe_list(edge.get("support_snippets")),
            "mention_count": int(edge.get("mention_count", 1) or 1),
        })

    return {"nodes": normalized_nodes, "edges": normalized_edges}


async def register_session_file(
    db,
    session_id: str,
    user_id: int,
    file_path: str,
    file_name: str,
) -> int:
    doc = {
        "session_id": session_id,
        "user_id": user_id,
        "file_path": file_path,
        "file_name": file_name,
        "uploaded_at": _utcnow(),
    }
    await db.session_files.insert_one(doc)

    count = await db.session_files.count_documents({"session_id": session_id})
    logger.info("Session %s now has %s file(s).", session_id, count)
    return count


async def get_session_file_count(db, session_id: str) -> int:
    return await db.session_files.count_documents({"session_id": session_id})


async def get_session_files(db, session_id: str) -> list[dict]:
    cursor = db.session_files.find({"session_id": session_id})
    return await cursor.to_list(length=None)


def _normalize_session_documents(
    document_ids: Optional[List[str]] = None,
    document_names: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    ids = [str(item or "").strip() for item in (document_ids or []) if str(item or "").strip()]
    names = [str(item or "").strip() for item in (document_names or []) if str(item or "").strip()]
    total = max(len(ids), len(names))
    documents: List[Dict[str, str]] = []
    for index in range(total):
        doc_id = ids[index] if index < len(ids) else ""
        name = names[index] if index < len(names) else (doc_id or f"Document {index + 1}")
        documents.append({"doc_id": doc_id, "name": name})
    return documents


def session_supports_grag(file_count: int = 0, document_ids: Optional[List[str]] = None) -> bool:
    normalized_ids = [str(item or "").strip() for item in (document_ids or []) if str(item or "").strip()]
    return int(file_count or 0) >= 2 or len(normalized_ids) >= 2


async def get_grag_session_state(db, session_id: str) -> Dict[str, Any]:
    session_row = await db.chat_sessions.find_one({"chat_id": session_id}) or {}
    document_ids = [str(item or "").strip() for item in (session_row.get("document_ids") or []) if str(item or "").strip()]
    document_names = [str(item or "").strip() for item in (session_row.get("document_names") or []) if str(item or "").strip()]

    legacy_doc_id = str(session_row.get("document_id") or "").strip()
    legacy_doc_name = str(session_row.get("document_name") or "").strip()
    if legacy_doc_id and legacy_doc_id not in document_ids:
        document_ids.append(legacy_doc_id)
        document_names.append(legacy_doc_name or legacy_doc_id)

    file_count = int(session_row.get("file_count") or 0)
    if file_count < len(document_ids):
        file_count = len(document_ids)

    return {
        "session": session_row,
        "user_id": session_row.get("user_id"),
        "document_ids": document_ids,
        "document_names": document_names,
        "uploaded_documents": _normalize_session_documents(document_ids, document_names),
        "file_count": file_count,
        "grag_enabled": session_supports_grag(file_count=file_count, document_ids=document_ids),
    }


def _graph_document_count(graph_data: Optional[Dict[str, Any]]) -> int:
    graph_data = graph_data or {}
    stats = graph_data.get("stats") or {}
    count = int(stats.get("document_count") or 0)
    if count > 0:
        return count

    sources = {
        source_name
        for node in (graph_data.get("nodes") or [])
        for source_name in _safe_list(node.get("sources") or node.get("source"))
        if str(source_name or "").strip()
    }
    return len(sources)


async def rebuild_knowledge_graph_for_session(
    db,
    session_id: str,
    user_id: Any,
) -> Dict[str, Any]:
    state = await get_grag_session_state(db, session_id)
    if not state["grag_enabled"]:
        logger.info("Session %s: skipping KG rebuild because only one document is in scope", session_id)
        return {}

    document_ids = list(state.get("document_ids") or [])
    if not document_ids:
        return {}

    from backend.file_handler import extract_text_from_file
    from backend.preprocessing import create_chunks

    documents = await db.documents.find({"doc_id": {"$in": document_ids}}).to_list(length=len(document_ids))
    docs_by_id = {
        str(doc.get("doc_id") or "").strip(): doc
        for doc in documents
        if str(doc.get("doc_id") or "").strip()
    }

    await db.knowledge_graphs.delete_many({"session_id": session_id})

    rebuilt_graph: Dict[str, Any] = {}
    for index, doc_id in enumerate(document_ids):
        document = docs_by_id.get(doc_id)
        if not document:
            logger.warning("Session %s: missing document metadata for %s during KG rebuild", session_id, doc_id)
            continue

        file_path = str(document.get("file_path") or "").strip()
        filename = str(document.get("filename") or "").strip() or (
            state["document_names"][index] if index < len(state.get("document_names") or []) else doc_id
        )
        if not file_path:
            logger.warning("Session %s: document %s has no file_path, skipping KG rebuild input", session_id, doc_id)
            continue

        try:
            pages = extract_text_from_file(file_path)
        except Exception as exc:
            logger.warning("Session %s: failed to extract %s during KG rebuild: %s", session_id, filename, exc)
            continue

        if not pages:
            logger.warning("Session %s: no pages extracted from %s during KG rebuild", session_id, filename)
            continue

        full_text = "\n".join(
            page.get("text", "") if isinstance(page, dict) else str(page)
            for page in pages
        )
        chunks = create_chunks(pages, filename, doc_id) or None
        rebuilt_graph = await build_or_update_knowledge_graph(
            db,
            session_id,
            user_id,
            full_text,
            source=filename,
            chunks=chunks,
        )

    return rebuilt_graph


async def ensure_grag_for_session(
    db,
    session_id: str,
    user_id: Any,
    new_text: Optional[str] = None,
    source: str = "Unknown",
    chunks: Optional[List[Dict[str, Any]]] = None,
    force_rebuild: bool = False,
) -> Dict[str, Any]:
    state = await get_grag_session_state(db, session_id)
    if not state["grag_enabled"]:
        logger.info("Session %s: GRAG disabled because the session has fewer than two documents", session_id)
        return {}

    kg_row = await db.knowledge_graphs.find_one({"session_id": session_id})
    graph_data = (kg_row or {}).get("graph_data") or {}
    expected_count = max(int(state.get("file_count") or 0), len(state.get("document_ids") or []))
    existing_count = _graph_document_count(graph_data)

    if force_rebuild or not graph_data or existing_count < expected_count:
        logger.info(
            "Session %s: rebuilding KG (force=%s existing_docs=%s expected_docs=%s)",
            session_id,
            force_rebuild,
            existing_count,
            expected_count,
        )
        return await rebuild_knowledge_graph_for_session(db, session_id, user_id)

    if new_text and str(new_text).strip():
        return await build_or_update_knowledge_graph(
            db,
            session_id,
            user_id,
            new_text,
            source=source,
            chunks=chunks,
        )

    return graph_data


async def build_or_update_knowledge_graph(
    db,
    session_id: str,
    user_id: int,
    new_text: str,
    source: str = "Unknown",
    chunks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    extracted = _extract_entities_and_relations(chunks, new_text, source=source)

    kg_row = await db.knowledge_graphs.find_one({"session_id": session_id})
    if kg_row:
        graph = _normalize_existing_graph(kg_row.get("graph_data", {"nodes": [], "edges": []}))
        entity_map = kg_row.get("entity_map", {}) or {}
    else:
        graph = {"nodes": [], "edges": []}
        entity_map = {}

    node_map = {node["id"]: node for node in graph["nodes"] if node.get("id")}
    for node in extracted["nodes"]:
        node_id = node["id"]
        if node_id in node_map:
            node_map[node_id] = _merge_node(node_map[node_id], node)
        else:
            node_map[node_id] = node
        entity_map[node.get("label", node_id)] = node_id

    edge_map = {
        (edge["source"], edge["relation"], edge["target"]): edge
        for edge in graph["edges"]
        if edge.get("source") and edge.get("target")
    }
    for edge in extracted["edges"]:
        edge_key = (edge["source"], edge["relation"], edge["target"])
        if edge_key in edge_map:
            edge_map[edge_key] = _merge_edge(edge_map[edge_key], edge)
        else:
            edge_map[edge_key] = edge

    merged_graph = {
        "nodes": list(node_map.values()),
        "edges": list(edge_map.values()),
        "stats": {
            "node_count": len(node_map),
            "edge_count": len(edge_map),
            "document_count": len({source_name for node in node_map.values() for source_name in node.get("sources", [])}),
        },
    }

    update_payload = {
        "graph_data": merged_graph,
        "entity_map": entity_map,
        "updated_at": _utcnow(),
    }
    if kg_row:
        await db.knowledge_graphs.update_one(
            {"session_id": session_id},
            {"$set": update_payload},
        )
    else:
        await db.knowledge_graphs.insert_one({
            "session_id": session_id,
            "user_id": user_id,
            **update_payload,
            "created_at": _utcnow(),
        })

    logger.info(
        "KG updated for session %s: %s nodes, %s edges",
        session_id,
        merged_graph["stats"]["node_count"],
        merged_graph["stats"]["edge_count"],
    )
    return merged_graph


def _score_overlap(query_tokens: set[str], candidate_text: str) -> float:
    candidate_tokens = set(_tokenize(candidate_text))
    if not query_tokens or not candidate_tokens:
        return 0.0
    overlap = len(query_tokens.intersection(candidate_tokens))
    if not overlap:
        return 0.0
    return overlap / max(len(candidate_tokens), 1)


def _edge_to_fact(edge: Dict[str, Any], node_lookup: Dict[str, Dict[str, Any]]) -> str:
    source_label = node_lookup.get(edge.get("source", ""), {}).get("label", edge.get("source", "").replace("_", " ").title())
    target_label = node_lookup.get(edge.get("target", ""), {}).get("label", edge.get("target", "").replace("_", " ").title())
    relation = edge.get("relation", "relates to")
    evidence = ""
    if edge.get("source_files"):
        evidence = f" [Sources: {', '.join(edge['source_files'][:2])}]"
    return f"{source_label} {relation} {target_label}{evidence}"


def _subgraph_to_text(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    graph_facts: List[str],
    document_coverage: Dict[str, Any],
) -> str:
    lines: List[str] = []
    if nodes:
        grouped = defaultdict(list)
        for node in nodes:
            for source in node.get("sources", []) or ["Unknown"]:
                grouped[source].append(node.get("label", node.get("id", "")))
        for source, labels in grouped.items():
            unique_labels = []
            for label in labels:
                if label and label not in unique_labels:
                    unique_labels.append(label)
            lines.append(f"{source}: {', '.join(unique_labels[:5])}")

    if graph_facts:
        lines.append("Cross-document evidence:")
        for fact in graph_facts[:6]:
            lines.append(f"- {fact}")

    matched_sources = document_coverage.get("matched_sources", [])
    if matched_sources:
        lines.append(
            "Document coverage: "
            f"{len(matched_sources)}/{document_coverage.get('total_sources', len(matched_sources))} "
            f"documents represented"
        )
    return "\n".join(lines)


async def graph_retrieve(
    db,
    session_id: str,
    query: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    session_state = await get_grag_session_state(db, session_id)
    if not session_state["grag_enabled"]:
        logger.info("Session %s: skipping graph retrieval because the session has fewer than two documents", session_id)
        return []

    kg_row = await db.knowledge_graphs.find_one({"session_id": session_id})
    graph_data = (kg_row or {}).get("graph_data") or {}
    expected_count = max(int(session_state.get("file_count") or 0), len(session_state.get("document_ids") or []))
    if not graph_data or _graph_document_count(graph_data) < expected_count:
        rebuilt_graph = await rebuild_knowledge_graph_for_session(db, session_id, session_state.get("user_id"))
        if rebuilt_graph:
            kg_row = await db.knowledge_graphs.find_one({"session_id": session_id})
            graph_data = (kg_row or {}).get("graph_data") or rebuilt_graph
        else:
            return []

    if not graph_data:
        return []

    uploaded_documents = list(session_state.get("uploaded_documents") or [])

    graph = _normalize_existing_graph(graph_data)
    query_tokens = {
        token
        for token in _tokenize(query)
        if token not in {"the", "and", "with", "what", "about", "these", "those", "both", "compare"}
    }
    if not query_tokens:
        query_tokens = set(_tokenize(query))

    node_lookup = {node["id"]: node for node in graph["nodes"] if node.get("id")}
    node_scores: Dict[str, float] = defaultdict(float)
    for node in graph["nodes"]:
        score = _score_overlap(query_tokens, node.get("label", ""))
        for snippet in node.get("support_snippets", []):
            score = max(score, _score_overlap(query_tokens, snippet) * 0.7)
        if len(node.get("sources", [])) > 1:
            score += 0.15
        if score > 0:
            node_scores[node["id"]] = score

    edge_scores: Dict[tuple[str, str, str], float] = {}
    for edge in graph["edges"]:
        key = (edge["source"], edge["relation"], edge["target"])
        edge_text = f"{edge.get('relation', '')} {' '.join(edge.get('source_files', []))}"
        score = (
            node_scores.get(edge["source"], 0.0) * 0.9
            + node_scores.get(edge["target"], 0.0) * 0.9
            + _score_overlap(query_tokens, edge_text)
        )
        if len(set(edge.get("source_files", []))) > 1 or len(set(edge.get("doc_ids", []))) > 1:
            score += 0.2
        if score > 0:
            edge_scores[key] = score

    ranked_nodes = sorted(node_scores, key=node_scores.get, reverse=True)[: max(top_k, 3)]
    ranked_edges = sorted(edge_scores, key=edge_scores.get, reverse=True)[: max(top_k, 4)]

    if not ranked_nodes and graph["nodes"]:
        ranked_nodes = [node["id"] for node in graph["nodes"][: min(len(graph["nodes"]), top_k)]]

    if uploaded_documents:
        selected_node_ids = set(ranked_nodes)
        for document in uploaded_documents:
            doc_id = str(document.get("doc_id") or "").strip()
            name = str(document.get("name") or "").strip()
            fallback_node = None
            for node in graph["nodes"]:
                node_doc_ids = {str(item).strip() for item in _safe_list(node.get("doc_ids")) if str(item).strip()}
                node_sources = {str(item).strip() for item in _safe_list(node.get("sources")) if str(item).strip()}
                if (doc_id and doc_id in node_doc_ids) or (name and name in node_sources):
                    fallback_node = node.get("id")
                    if fallback_node in selected_node_ids:
                        break
                    ranked_nodes.append(fallback_node)
                    selected_node_ids.add(fallback_node)
                    break

    relevant_node_ids = set(ranked_nodes)
    for source_id, _, target_id in ranked_edges:
        relevant_node_ids.add(source_id)
        relevant_node_ids.add(target_id)

    relevant_nodes = [node_lookup[node_id] for node_id in relevant_node_ids if node_id in node_lookup]
    relevant_edges = [
        edge
        for edge in graph["edges"]
        if (edge["source"], edge["relation"], edge["target"]) in ranked_edges
    ]

    support_chunk_ids = []
    for node in relevant_nodes:
        support_chunk_ids.extend(node.get("support_chunk_ids", []))
    for edge in relevant_edges:
        support_chunk_ids.extend(edge.get("support_chunk_ids", []))
    support_chunk_ids = list(dict.fromkeys([chunk_id for chunk_id in support_chunk_ids if chunk_id]))

    matched_sources = []
    for node in relevant_nodes:
        for source_name in node.get("sources", []):
            if source_name and source_name not in matched_sources:
                matched_sources.append(source_name)
    total_sources = sorted({
        source_name
        for node in graph["nodes"]
        for source_name in node.get("sources", [])
        if source_name
    })

    graph_facts = [_edge_to_fact(edge, node_lookup) for edge in relevant_edges]
    if not graph_facts:
        for node in relevant_nodes[:top_k]:
            for snippet in node.get("support_snippets", [])[:1]:
                graph_facts.append(f"{node.get('label', '')}: {snippet}")

    cross_document_connections = [
        fact
        for fact, edge in zip(graph_facts, relevant_edges)
        if len(set(edge.get("source_files", []))) > 1 or len(set(edge.get("doc_ids", []))) > 1
    ]
    per_document_facts: Dict[str, List[str]] = defaultdict(list)
    document_fact_counts: Dict[str, int] = defaultdict(int)
    for node in relevant_nodes:
        source_names = _safe_list(node.get("sources"))
        if not source_names:
            continue
        snippets = _safe_list(node.get("support_snippets"))[:1]
        fact_text = snippets[0] if snippets else node.get("label", "")
        for source_name in source_names:
            if fact_text and fact_text not in per_document_facts[source_name]:
                per_document_facts[source_name].append(fact_text)
                document_fact_counts[source_name] += 1
    for edge, fact in zip(relevant_edges, graph_facts):
        for source_name in _safe_list(edge.get("source_files")):
            if fact and fact not in per_document_facts[source_name]:
                per_document_facts[source_name].append(fact)
                document_fact_counts[source_name] += 1
    if uploaded_documents:
        for document in uploaded_documents:
            doc_id = str(document.get("doc_id") or "").strip()
            name = str(document.get("name") or "").strip()
            if not name or per_document_facts.get(name):
                continue
            fallback_facts: List[str] = []
            for node in graph["nodes"]:
                node_doc_ids = {str(item).strip() for item in _safe_list(node.get("doc_ids")) if str(item).strip()}
                node_sources = {str(item).strip() for item in _safe_list(node.get("sources")) if str(item).strip()}
                if (doc_id and doc_id in node_doc_ids) or (name and name in node_sources):
                    snippets = _safe_list(node.get("support_snippets"))[:1]
                    fallback_facts.append(snippets[0] if snippets else node.get("label", ""))
                if len(fallback_facts) >= 2:
                    break
            if fallback_facts:
                per_document_facts[name] = [fact for fact in fallback_facts if fact][:2]
                document_fact_counts[name] = max(int(document_fact_counts.get(name, 0) or 0), len(per_document_facts[name]))

    document_coverage_map: List[Dict[str, Any]] = []
    covered_names: List[str] = []
    unsupported_documents: List[str] = []
    if uploaded_documents:
        support_doc_ids = {
            str(doc_id).strip()
            for node in relevant_nodes
            for doc_id in _safe_list(node.get("doc_ids"))
            if str(doc_id).strip()
        }
        support_doc_ids.update(
            str(doc_id).strip()
            for edge in relevant_edges
            for doc_id in _safe_list(edge.get("doc_ids"))
            if str(doc_id).strip()
        )
        for document in uploaded_documents:
            doc_id = str(document.get("doc_id") or "").strip()
            name = str(document.get("name") or "").strip()
            graph_fact_count = int(document_fact_counts.get(name, 0))
            supported = bool(graph_fact_count or (doc_id and doc_id in support_doc_ids))
            entry = {
                "doc_id": doc_id,
                "name": name,
                "graph_fact_count": graph_fact_count,
                "supported": supported,
                "unsupported_for_query": not supported,
            }
            document_coverage_map.append(entry)
            if supported:
                covered_names.append(name)
            else:
                unsupported_documents.append(name)
    else:
        for source_name in matched_sources:
            document_coverage_map.append({
                "doc_id": "",
                "name": source_name,
                "graph_fact_count": int(document_fact_counts.get(source_name, 0)),
                "supported": True,
                "unsupported_for_query": False,
            })
        covered_names = matched_sources[:]

    document_coverage = {
        "matched_sources": covered_names or matched_sources,
        "total_sources": len(document_coverage_map) if document_coverage_map else len(total_sources),
        "total_documents": len(document_coverage_map) if document_coverage_map else len(total_sources),
        "covered_document_count": len(covered_names or matched_sources),
        "unsupported_documents": unsupported_documents,
        "coverage_ratio": round(
            (len(covered_names or matched_sources) / (len(document_coverage_map) if document_coverage_map else len(total_sources))),
            4,
        ) if (document_coverage_map or total_sources) else 0.0,
    }
    graph_score = round(
        min(
            1.0,
            (sum(node_scores.get(node_id, 0.0) for node_id in ranked_nodes) / max(len(ranked_nodes), 1))
            + (0.15 if document_coverage["coverage_ratio"] >= 0.75 else 0.0)
            + (0.1 if cross_document_connections else 0.0),
        ),
        4,
    )
    context_summary = _subgraph_to_text(relevant_nodes, relevant_edges, graph_facts, document_coverage)

    return [{
        "nodes": relevant_nodes,
        "edges": relevant_edges,
        "graph_facts": graph_facts[: max(top_k + 1, 4)],
        "per_document_facts": {
            name: facts[:4]
            for name, facts in per_document_facts.items()
            if facts
        },
        "cross_document_facts": cross_document_connections[:4],
        "support_chunk_ids": support_chunk_ids[: max(top_k * 2, 6)],
        "cross_document_connections": cross_document_connections,
        "document_coverage": document_coverage,
        "document_coverage_map": document_coverage_map,
        "unsupported_documents": unsupported_documents,
        "uploaded_documents": uploaded_documents,
        "graph_score": graph_score,
        "context_summary": context_summary,
    }]


async def conditional_retrieve(
    db,
    session_id: str,
    user_id: int,
    query: str,
    new_file_text: Optional[str] = None,
    rag_retrieve_fn=None,
) -> dict:
    if new_file_text:
        await ensure_grag_for_session(db, session_id, user_id, new_text=new_file_text)

    session_state = await get_grag_session_state(db, session_id)
    file_count = int(session_state.get("file_count") or 0)

    if not session_state.get("grag_enabled"):
        logger.info("Session %s: using RAG (1 file)", session_id)
        rag_results = await rag_retrieve_fn(query, session_id) if rag_retrieve_fn else []
        return {
            "mode": "rag",
            "results": rag_results,
            "context": "\n\n".join(rag_results) if rag_results else "",
        }

    logger.info("Session %s: using GRAG (%s files)", session_id, file_count)
    graph_results = await graph_retrieve(db, session_id, query)
    context_parts = [result["context_summary"] for result in graph_results if result.get("context_summary")]

    rag_context = ""
    rag_results = await rag_retrieve_fn(query, session_id) if rag_retrieve_fn else []
    if rag_results:
        rag_context = "\n\n".join(rag_results)

    combined_context = "\n\n---\n\n".join(filter(None, [
        "### Knowledge Graph Context\n" + "\n".join(context_parts) if context_parts else "",
        "### Document Chunks\n" + rag_context if rag_context else "",
    ]))

    return {
        "mode": "grag",
        "results": graph_results,
        "context": combined_context,
        "graph_summary": {
            "nodes": sum(len(result["nodes"]) for result in graph_results),
            "edges": sum(len(result["edges"]) for result in graph_results),
        },
    }
