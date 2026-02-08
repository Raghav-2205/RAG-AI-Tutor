import warnings
from typing import List, Dict, Any
from backend.config import settings
from backend.core.search_engine import search_engine
from backend.core.llm_interface import llm_client, SOCRATIC_SYSTEM_PROMPT

warnings.filterwarnings("ignore")

def answer_query_with_rag(
    user_id: str, 
    query: str, 
    subject: str = None, 
    history: List = [], 
    top_k: int = 3,
    feedback_context: str = ""  # NEW: Adaptive context from feedback
):
    # 1. Search DB
    chunks = search_engine.search(user_id, subject, query, top_k)
    print(f"DEBUG: Retrieved {len(chunks)} chunks.")
    if chunks:
        print(f"DEBUG: Chunk 0 text: {chunks[0].get('text', '')[:50]}...")
    
    # If no documents found, respond without RAG context
    if not chunks:
        no_docs_prompt = f"""The user hasn't uploaded any documents yet. 
        
Please respond as a helpful AI tutor. Answer the user's question directly without referencing any documents:

Question: {query}

Provide a helpful, educational response. If the question would benefit from course materials, suggest they upload relevant documents."""
        
        try:
            response_text = llm_client.generate(no_docs_prompt, system_prompt="You are a helpful AI tutor. Answer questions clearly and educationally.")
            return {
                "answer": response_text,
                "citations": [],
                "chunks": []
            }
        except Exception as e:
            return {
                "answer": f"I'm your AI tutor! Upload a document using the 📄 button in the sidebar, and I'll help you understand it. Error: {str(e)}",
                "citations": [],
                "chunks": []
            }
    
    # 2. Build Prompt (only if we have chunks)
    # Format each chunk with its number and source for proper citation
    context_parts = []
    for i, c in enumerate(chunks, 1):
        source = c.get('metadata', {}).get('source', 'Unknown')
        text = c.get('text', '')
        context_parts.append(f"[CHUNK {i}] (Source: {source})\n{text}")
    context_text = "\n\n".join(context_parts)
    
    # Simple prompt construction
    # We could use the SOCRATIC_SYSTEM_PROMPT here or in llm_interface. 
    # llm_interface supports system_prompt arg.
    
    # Format history?
    # The history list contains {"role": "user"/"model", "content": ...}
    # For a simple turn, we might just append history to prompt or use chat mode.
    # For now, let's keep it simple: Context + Question. 
    # (Advanced: use history in context)
    
    history_text = ""
    if history:
         history_text = "Chat History:\n" + "\n".join([f"{h['role']}: {h['content']}" for h in history[-4:]]) + "\n\n"

    prompt = f"""{history_text}Use the following course materials to answer the question. Cite specific chunks when referencing information.

{context_text}

Student Question: {query}

Provide a helpful, educational answer based on the materials above:"""

    # 3. Generate with adaptive system prompt
    try:
        print(f"🤖 Generating response...")
        
        # Build adaptive system prompt from base + feedback context
        adaptive_prompt = SOCRATIC_SYSTEM_PROMPT
        if feedback_context:
            adaptive_prompt = SOCRATIC_SYSTEM_PROMPT + feedback_context
            print(f"📊 Using feedback-adjusted prompt (user has recent negative feedback)")
        
        response_text = llm_client.generate(prompt, system_prompt=adaptive_prompt)
        
        return {
            "answer": response_text,
            "citations": list(range(1, len(chunks)+1)),
            "chunks": chunks
        }
    except Exception as e:
        return {
            "answer": f"API Error: {str(e)}.",
            "citations": [],
            "chunks": []
        }