import logging
from typing import List, Dict, Any
from backend.core.llm_interface import llm_client
import json

logger = logging.getLogger(__name__)

class GRAGPipeline:
    def __init__(self):
        self.graph = {"nodes": [], "edges": []}
        
    async def build_graph(self, chunks: List[Dict[str, Any]]):
        """
        1. Perform entity extraction
        2. Identify relationships
        3. Construct a knowledge graph
        4. Store graph in-memory
        """
        logger.info(f"[GRAG] Building Knowledge Graph from {len(chunks)} chunks")
        combined_text = "\n\n".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in chunks])
        if len(combined_text) > 15000:
            combined_text = combined_text[:15000] # Safety limit
            
        prompt = f"""
        Extract a knowledge graph from the following text.
        Identify key entities and relationships across the documents.
        Return ONLY a JSON object with this exact structure (no markdown, no backticks, just raw json):
        {{
            "nodes": [{{"id": "entity name", "type": "entity type"}}],
            "edges": [{{"source": "entity1", "target": "entity2", "relation": "relationship description"}}]
        }}
        
        Text:
        {combined_text}
        """
        
        try:
            response = await llm_client.async_generate(prompt)
            # Robust JSON extraction
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                graph_data = json.loads(response[start:end+1])
                self.graph = graph_data
                logger.info(f"[GRAG] Built graph with {len(self.graph.get('nodes', []))} nodes and {len(self.graph.get('edges', []))} edges")
            else:
                logger.warning("[GRAG] Could not parse JSON from LLM response")
        except Exception as e:
            logger.error(f"[GRAG] Failed to build graph: {e}")
            
        return self.graph
            
    def traverse_graph(self, query: str) -> str:
        """
        5. Replace vector retrieval with Context aggregation from connected nodes
        """
        logger.info("[GRAG] Traversing graph for context aggregation")
        edges = self.graph.get("edges", [])
        if not edges:
            return "No graph context available."
            
        context_parts = []
        for edge in edges:
            src = edge.get("source", "Unknown")
            tgt = edge.get("target", "Unknown")
            rel = edge.get("relation", "related to")
            context_parts.append(f"{src} --[{rel}]--> {tgt}")
            
        return "\n".join(context_parts)
