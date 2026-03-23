import json
import logging
import re
from typing import Optional
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Utility ──────────────────────────────────────────────────────────────────

async def register_session_file(
    db,
    session_id: str,
    user_id: int,
    file_path: str,
    file_name: str,
) -> int:
    """
    Register a file upload for a chat session.
    Returns the current total file count for that session.
    """
    doc = {
        "session_id": session_id,
        "user_id": user_id,
        "file_path": file_path,
        "file_name": file_name,
        "uploaded_at": datetime.utcnow()
    }
    await db.session_files.insert_one(doc)

    count = await db.session_files.count_documents({"session_id": session_id})
    logger.info(f"Session {session_id} now has {count} file(s).")
    return count

async def get_session_file_count(db, session_id: str) -> int:
    return await db.session_files.count_documents({"session_id": session_id})

async def get_session_files(db, session_id: str) -> list[dict]:
    cursor = db.session_files.find({"session_id": session_id})
    return await cursor.to_list(length=None)

# ─── Entity & Relationship Extraction ────────────────────────────────────────

def extract_entities_and_relations(text: str, source: str = "Unknown") -> dict:
    """
    Lightweight rule-based entity/relation extractor.
    """
    entities = []
    relations = []
    seen = set()

    # Naive NP extraction via capitalized-word sequences
    np_pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b')
    STOP_WORDS = {"the", "and", "this", "that", "with", "from", "for", "are", "was", "were"}
    
    for match in np_pattern.finditer(text):
        phrase = match.group(0).strip()
        if phrase.lower() in STOP_WORDS or len(phrase) < 3:
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        e_id = phrase.lower().replace(" ", "_")
        etype = "concept"
        if any(kw in phrase.lower() for kw in ["university", "college", "school", "institute"]):
            etype = "organization"
        elif any(kw in phrase.lower() for kw in ["chapter", "unit", "lesson", "module", "topic"]):
            etype = "topic"
        entities.append({"id": e_id, "label": phrase, "type": etype, "source": source})


    # Simple "A is B", "A has B", "A uses B" patterns for relations
    rel_pattern = re.compile(
        r'([A-Z][a-zA-Z\s]+)\s+(is|are|has|have|uses|contains|includes|defines|describes)\s+([A-Z][a-zA-Z\s]+)',
        re.MULTILINE
    )
    for m in rel_pattern.finditer(text):
        src_label = m.group(1).strip()
        rel_type  = m.group(2).strip()
        tgt_label = m.group(3).strip()
        src_id = src_label.lower().replace(" ", "_")
        tgt_id = tgt_label.lower().replace(" ", "_")
        relations.append({"source": src_id, "target": tgt_id, "relation": rel_type, "source_file": source})

    return {"entities": entities, "relations": relations}

# ─── Knowledge Graph Build / Merge ───────────────────────────────────────────

async def build_or_update_knowledge_graph(
    db,
    session_id: str,
    user_id: int,
    new_text: str,
    source: str = "Unknown",
) -> dict:
    """
    Extract entities/relations from new_text and merge into the session's KG.
    Persists the updated graph to the DB and returns it.
    """
    extracted = extract_entities_and_relations(new_text, source=source)

    kg_row = await db.knowledge_graphs.find_one({"session_id": session_id})

    if kg_row:
        graph = kg_row.get("graph_data", {"nodes": [], "edges": []})
        entity_map = kg_row.get("entity_map", {})
    else:
        graph = {"nodes": [], "edges": []}
        entity_map = {}

    existing_node_ids = {n["id"] for n in graph["nodes"]}
    for ent in extracted["entities"]:
        if ent["id"] not in existing_node_ids:
            graph["nodes"].append(ent)
            existing_node_ids.add(ent["id"])
        entity_map[ent["label"]] = ent["id"]

    existing_edges = {
        (e["source"], e["relation"], e["target"]) for e in graph["edges"]
    }
    for rel in extracted["relations"]:
        key = (rel["source"], rel["relation"], rel["target"])
        if key not in existing_edges:
            graph["edges"].append(rel)
            existing_edges.add(key)

    if kg_row:
        await db.knowledge_graphs.update_one(
            {"session_id": session_id},
            {"$set": {
                "graph_data": graph,
                "entity_map": entity_map,
                "updated_at": datetime.utcnow()
            }}
        )
    else:
        doc = {
            "session_id": session_id,
            "user_id": user_id,
            "graph_data": graph,
            "entity_map": entity_map,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await db.knowledge_graphs.insert_one(doc)

    logger.info(
        f"KG updated for session {session_id}: "
        f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges"
    )
    return graph

# ─── Graph-Based Retrieval ────────────────────────────────────────────────────

async def graph_retrieve(
    db,
    session_id: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    kg_row = await db.knowledge_graphs.find_one({"session_id": session_id})

    if not kg_row or not kg_row.get("graph_data"):
        return []

    graph = kg_row["graph_data"]
    query_tokens = set(query.lower().split())

    node_scores: dict[str, float] = defaultdict(float)
    for node in graph["nodes"]:
        label_tokens = set(node["label"].lower().split())
        overlap = len(query_tokens & label_tokens)
        if overlap:
            node_scores[node["id"]] = overlap / max(len(label_tokens), 1)

    top_nodes = sorted(node_scores, key=node_scores.get, reverse=True)[:top_k]
    neighbors = set()
    for edge in graph["edges"]:
        if edge["source"] in top_nodes:
            neighbors.add(edge["target"])
        if edge["target"] in top_nodes:
            neighbors.add(edge["source"])

    all_relevant = set(top_nodes) | neighbors
    relevant_nodes = [n for n in graph["nodes"] if n["id"] in all_relevant]
    relevant_edges = [
        e for e in graph["edges"]
        if e["source"] in all_relevant and e["target"] in all_relevant
    ]

    return [
        {
            "nodes": relevant_nodes,
            "edges": relevant_edges,
            "context_summary": _subgraph_to_text(relevant_nodes, relevant_edges),
        }
    ]

def _subgraph_to_text(nodes: list[dict], edges: list[dict]) -> str:
    lines = []
    if nodes:
        node_labels = []
        for n in nodes:
            origin = f" (from {n['source']})" if n.get('source') else ""
            node_labels.append(f"{n['label']}{origin}")
        lines.append("Key entities: " + ", ".join(node_labels))
    for e in edges:
        src = e.get("source", "").replace("_", " ").title()
        tgt = e.get("target", "").replace("_", " ").title()
        rel = e.get("relation", "relates to")
        origin = f" [Source: {e['source_file']}]" if e.get('source_file') else ""
        lines.append(f"  - {src} {rel} {tgt}{origin}")
    return "\n".join(lines)

# ─── Main Dispatcher ──────────────────────────────────────────────────────────

async def conditional_retrieve(
    db,
    session_id: str,
    user_id: int,
    query: str,
    new_file_text: Optional[str] = None,
    rag_retrieve_fn=None,
) -> dict:
    if new_file_text:
        await build_or_update_knowledge_graph(db, session_id, user_id, new_file_text)

    file_count = await get_session_file_count(db, session_id)

    if file_count < 2:
        logger.info(f"Session {session_id}: using RAG (1 file)")
        if rag_retrieve_fn:
            rag_results = await rag_retrieve_fn(query, session_id)
        else:
            rag_results = []
        return {
            "mode": "rag",
            "results": rag_results,
            "context": "\n\n".join(rag_results) if rag_results else "",
        }
    else:
        logger.info(f"Session {session_id}: using GRAG ({file_count} files)")
        graph_results = await graph_retrieve(db, session_id, query)
        context_parts = [r["context_summary"] for r in graph_results if r.get("context_summary")]

        rag_context = ""
        if rag_retrieve_fn:
            rag_results = await rag_retrieve_fn(query, session_id)
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
                "nodes": sum(len(r["nodes"]) for r in graph_results),
                "edges": sum(len(r["edges"]) for r in graph_results),
            },
        }
