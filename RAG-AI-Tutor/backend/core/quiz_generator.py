"""
Quiz Generator Service

Generates MCQ questions from document chunks stored in the vector database.
Ensures questions are grounded in actual content to prevent hallucinations.
"""

from typing import List, Dict, Any
import uuid
from backend.core.search_engine import search_engine
from backend.core.llm_interface import llm_client
from backend.vector_db import get_all_chunks


def generate_quiz_from_chunks(user_id: str, subject: str, num_questions: int = 10) -> Dict[str, Any]:
    """
    Generate a quiz with MCQ questions based on document chunks.
    
    Args:
        user_id: User ID for retrieving their documents
        subject: Subject area for the quiz
        num_questions: Number of questions to generate (default: 10)
    
    Returns:
        Dictionary with quiz_id, questions, and metadata
    """
    
    # 1. Retrieve relevant chunks from vector store
    # Use global user for pre-indexed documents
    chunks = get_all_chunks("global", "general")
    
    if not chunks:
        # Fallback to user's own documents
        chunks = get_all_chunks(user_id, subject)
    
    if not chunks or len(chunks) < 3:
        raise ValueError("Not enough document content to generate quiz. Please upload more documents.")
    
    # 2. Select diverse chunks (don't use all from same document)
    selected_chunks = _select_diverse_chunks(chunks, num_questions)
    
    # 3. Build prompt for quiz generation
    quiz_prompt = _build_quiz_generation_prompt(selected_chunks, num_questions, subject)
    
    # 4. Generate questions via LLM
    print(f"🎯 Generating {num_questions} quiz questions from {len(selected_chunks)} chunks...")
    
    try:
        response = llm_client.generate(quiz_prompt, system_prompt=QUIZ_GENERATION_SYSTEM_PROMPT)
        
        # 5. Parse and validate questions
        questions = _parse_quiz_response(response, selected_chunks)
        
        if not questions:
            print("❌ Parsing failed. No questions extracted.")
            raise ValueError("Failed to parse quiz questions from AI response.")
            
        if len(questions) < num_questions:
            print(f"⚠️ Only generated {len(questions)}/{num_questions} questions")
        
        # 6. Create quiz object
        quiz_id = str(uuid.uuid4())
        quiz = {
            "quiz_id": quiz_id,
            "subject": subject,
            "questions": questions,
            "total_questions": len(questions)
        }
        
        print(f"✅ Quiz generated: {quiz_id} with {len(questions)} questions")
        return quiz
        
    except Exception as e:
        print(f"❌ Quiz generation failed: {e}")
        raise ValueError(f"Failed to generate quiz: {str(e)}")


def _select_diverse_chunks(chunks: List[Dict], num_needed: int) -> List[Dict]:
    """Select diverse chunks from different sources"""
    # Group chunks by source
    by_source = {}
    for chunk in chunks:
        source = chunk.get('metadata', {}).get('source', 'unknown')
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(chunk)
    
    # Take chunks from different sources in round-robin fashion
    selected = []
    sources = list(by_source.keys())
    source_idx = 0
    
    while len(selected) < num_needed and sources:
        source = sources[source_idx % len(sources)]
        if by_source[source]:
            selected.append(by_source[source].pop(0))
            source_idx += 1
        else:
            sources.remove(source)
    
    # If still need more, add any remaining
    if len(selected) < num_needed:
        for source_chunks in by_source.values():
            selected.extend(source_chunks)
            if len(selected) >= num_needed:
                break
    
    return selected[:num_needed]


def _build_quiz_generation_prompt(chunks: List[Dict], num_questions: int, subject: str) -> str:
    """Build prompt for quiz generation"""
    
    # Format chunks with labels
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get('metadata', {}).get('source', 'Unknown')
        text = chunk.get('text', '')
        context_parts.append(f"[SOURCE {i}] ({source})\n{text}")
    
    context = "\n\n---\n\n".join(context_parts)
    
    prompt = f"""Generate {num_questions} multiple-choice questions for a {subject} quiz based ONLY on the provided content below.

STRICT RULES:
1. ALL questions must be directly answerable from the provided sources
2. Do NOT use external knowledge or make assumptions
3. Each question must have exactly 4 options (A, B, C, D)
4. Exactly ONE option must be correct
5. Questions should test understanding, not just memorization
6. Vary difficulty from basic recall to application

CONTENT:
{context}

FORMAT YOUR RESPONSE EXACTLY AS:
Q1: [Question text]
A) [Option A]
B) [Option B]
C) [Option C]
D) [Option D]
ANSWER: [A/B/C/D]
SOURCE: [SOURCE number]

Q2: [Question text]
...

Generate all {num_questions} questions now:"""
    
    return prompt


def _parse_quiz_response(response: str, chunks: List[Dict]) -> List[Dict]:
    """Parse LLM response into structured question format"""
    questions = []
    lines = response.strip().split('\n')
    
    current_q = None
    options = []
    correct_answer = None
    source_num = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # New question
        if line.startswith('Q') and ':' in line:
            # Save previous question if exists
            if current_q and options and correct_answer is not None:
                questions.append({
                    "question": current_q,
                    "options": options,
                    "correct_index": correct_answer,
                    "chunk_source": chunks[source_num - 1].get('metadata', {}).get('source', 'Unknown') if source_num and source_num <= len(chunks) else 'Unknown'
                })
            
            # Start new question
            current_q = line.split(':', 1)[1].strip()
            options = []
            correct_answer = None
            source_num = None
        
        # Options
        elif line.startswith(('A)', 'B)', 'C)', 'D)')):
            option_text = line[2:].strip()
            options.append(option_text)
        
        # Answer line
        elif line.startswith('ANSWER:'):
            answer_letter = line.split(':', 1)[1].strip().upper()[0]
            correct_answer = ord(answer_letter) - ord('A')
        
        # Source line
        elif line.startswith('SOURCE:'):
            try:
                source_text = line.split(':', 1)[1].strip()
                source_num = int(source_text.replace('SOURCE', '').strip())
            except:
                source_num = 1
    
    # Don't forget the last question
    if current_q and options and correct_answer is not None:
        questions.append({
            "question": current_q,
            "options": options,
            "correct_index": correct_answer,
            "chunk_source": chunks[source_num - 1].get('metadata', {}).get('source', 'Unknown') if source_num and source_num <= len(chunks) else 'Unknown'
        })
    
    return questions


QUIZ_GENERATION_SYSTEM_PROMPT = """You are a quiz generator for an educational AI tutor.

Your role is to create high-quality multiple-choice questions that:
- Test real understanding, not just memorization
- Are clear and unambiguous
- Have plausible distractors (wrong answers that seem reasonable)
- Are grounded in the provided content

CRITICAL: You must ONLY use information from the provided sources. Do not add external knowledge."""
