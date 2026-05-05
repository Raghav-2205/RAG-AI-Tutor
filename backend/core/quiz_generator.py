"""
Quiz Generator Service

Generates MCQ questions from document chunks stored in the vector database.
Ensures questions are grounded in actual content to prevent hallucinations.
"""

import re
import uuid
from typing import Any, Dict, List, Optional

from backend.core.llm_interface import llm_client
from backend.vector_db import get_all_chunks


def generate_quiz_from_chunks(
    user_id: str,
    subject: str,
    num_questions: int = 10,
    level: str | None = None,
    document_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generate a quiz with MCQ questions based on document chunks.

    The primary path uses the LLM to write grounded multiple-choice questions.
    If the model output is partially malformed, or the parser extracts too few
    valid questions, we backfill from retrieved chunk content instead of
    failing the whole request.

    Args:
        document_ids: If provided, restrict chunks to these document IDs
            (scopes the quiz to a specific chat session's uploaded files).
    """

    # Build where-filter for ChromaDB if document_ids are supplied
    where_filter: Optional[Dict] = None
    if document_ids:
        if len(document_ids) == 1:
            where_filter = {"doc_id": {"$eq": document_ids[0]}}
        else:
            where_filter = {"doc_id": {"$in": document_ids}}

    user_chunks = get_all_chunks(user_id, subject, where=where_filter)

    # If document-scoped filter returned nothing, fall back to all user chunks
    # (handles metadata mismatch between session doc_ids and stored chunk metadata)
    if document_ids and not user_chunks:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"[QUIZ] Session doc filter returned 0 chunks (ids={document_ids}). "
            "Falling back to all user chunks."
        )
        user_chunks = get_all_chunks(user_id, subject)

    # Only pull global chunks when NOT scoped to specific docs
    if not document_ids:
        global_chunks = get_all_chunks("global", "general")
        global_chunks = global_chunks[:100]  # Cap fallback
        user_chunks = user_chunks[:200]      # Cap fallback
    else:
        global_chunks = []

    import logging as _logging
    _logging.getLogger(__name__).info(
        f"[QUIZ GENERATOR] Retrieved {len(user_chunks)} user chunks, {len(global_chunks)} global chunks"
    )

    chunks = user_chunks + global_chunks

    if not chunks:
        raise ValueError("Not enough document content to generate quiz. Please upload more documents.")


    # Dynamically adjust number of questions based on available material if document scoped
    if document_ids:
        chunk_count = len(chunks)
        if chunk_count <= 20:
            num_questions = 10
        elif chunk_count <= 50:
            num_questions = 15
        else:
            num_questions = 20

    # Pull 2x chunks to give LLM enough diverse material to write all questions
    selected_chunks = _select_diverse_chunks(chunks, max(num_questions * 2, 10))
    quiz_prompt = _build_quiz_generation_prompt(selected_chunks, num_questions, subject, level=level or "Intermediate")

    print(f"[QUIZ] Generating {num_questions} question(s) from {len(selected_chunks)} chunk(s)")

    try:
        response = llm_client.generate(quiz_prompt, system_prompt=QUIZ_GENERATION_SYSTEM_PROMPT)
        questions = _parse_quiz_response(response, selected_chunks)

        if len(questions) < num_questions:
            fallback_questions = _build_fallback_questions(
                selected_chunks,
                num_questions,
                exclude_questions=questions,
            )
            questions.extend(fallback_questions[: max(num_questions - len(questions), 0)])

        if not questions:
            raise ValueError("No grounded quiz questions could be generated from the available material.")

        questions = questions[:num_questions]
        quiz_id = str(uuid.uuid4())
        print(f"[QUIZ] Generated quiz {quiz_id} with {len(questions)} question(s)")
        return {
            "quiz_id": quiz_id,
            "subject": subject,
            "questions": questions,
            "total_questions": len(questions),
        }

    except Exception as exc:
        print(f"[QUIZ] Primary generation failed: {exc}")
        fallback_questions = _build_fallback_questions(selected_chunks, num_questions)
        if fallback_questions:
            quiz_id = str(uuid.uuid4())
            print(f"[QUIZ] Fallback quiz {quiz_id} generated with {len(fallback_questions[:num_questions])} question(s)")
            return {
                "quiz_id": quiz_id,
                "subject": subject,
                "questions": fallback_questions[:num_questions],
                "total_questions": min(len(fallback_questions), num_questions),
            }
        raise ValueError("Not enough structured content to generate a quiz. Please upload more relevant documents.")


def _select_diverse_chunks(chunks: List[Dict[str, Any]], num_needed: int) -> List[Dict[str, Any]]:
    """Select chunks from different sources in a round-robin pattern."""
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in chunks:
        source = chunk.get("metadata", {}).get("source", "unknown")
        by_source.setdefault(source, []).append(chunk)

    selected: List[Dict[str, Any]] = []
    sources = list(by_source.keys())
    source_idx = 0

    while len(selected) < num_needed and sources:
        source = sources[source_idx % len(sources)]
        if by_source[source]:
            selected.append(by_source[source].pop(0))
            source_idx += 1
        else:
            sources.remove(source)

    if len(selected) < num_needed:
        for source_chunks in by_source.values():
            selected.extend(source_chunks)
            if len(selected) >= num_needed:
                break

    return selected[:num_needed]


def _build_quiz_generation_prompt(chunks: List[Dict[str, Any]], num_questions: int, subject: str, level: str = "Intermediate") -> str:
    """Build the LLM prompt for grounded quiz generation."""
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("metadata", {}).get("source", "Unknown")
        text = chunk.get("text", "")
        context_parts.append(f"[SOURCE {i}] ({source})\n{text}")

    context = "\n\n---\n\n".join(context_parts)

    level_upper = (level or "Intermediate").strip().capitalize()
    level_instructions = {
        "Beginner": (
            "Use simple vocabulary. Focus on basic definitions, core concepts, and direct recall. "
            "Avoid jargon or multi-step reasoning. Questions should be solvable with minimal prior knowledge."
        ),
        "Intermediate": (
            "Balance recall with application. Include questions that require understanding relationships "
            "between concepts. Some inference is fine but avoid overly complex scenarios."
        ),
        "Advanced": (
            "Prioritise application, analysis, and synthesis. Questions should require multi-step reasoning, "
            "comparing concepts, or applying knowledge to novel scenarios. Distractors must be plausible."
        ),
    }
    difficulty_note = level_instructions.get(level_upper, level_instructions["Intermediate"])

    return f"""Generate {num_questions} multiple-choice questions for a {subject} quiz based ONLY on the provided content below.
Student level: {level_upper}. {difficulty_note}

STRICT RULES:
0. CRITICAL: You MUST generate EXACTLY {num_questions} questions. Do not stop early.
1. ALL questions must be directly answerable from the provided sources
2. Do NOT use external knowledge or make assumptions
3. Each question must have exactly 4 options (A, B, C, D)
4. Exactly ONE option must be correct
5. All distractors (incorrect options) MUST be highly plausible, logical, and challenging. Do not use obvious throwaway options.
6. Questions should test understanding, not just memorization
7. Vary difficulty from basic recall to application

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



def _parse_quiz_response(response: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse LLM response into structured question format."""
    questions: List[Dict[str, Any]] = []
    lines = response.strip().split("\n")

    current_q = None
    options: List[str] = []
    correct_answer = None
    source_num = None

    import re
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Match Q1:, Q1., 1., 1:, etc.
        is_question_start = bool(re.match(r"^(?:Q\d+|\d+)[:.]", line))
        if is_question_start:
            if current_q and len(options) == 4 and correct_answer is not None:
                questions.append({
                    "question": current_q,
                    "options": options,
                    "correct_index": correct_answer,
                    "chunk_source": _source_name(chunks, source_num),
                })

            current_q = re.split(r"[:.]", line, maxsplit=1)[1].strip()
            options = []
            correct_answer = None
            source_num = None
        elif line.startswith(("A)", "B)", "C)", "D)")):
            options.append(line[2:].strip())
        elif line.startswith("ANSWER:"):
            answer_letter = line.split(":", 1)[1].strip().upper()[:1]
            if answer_letter in {"A", "B", "C", "D"}:
                correct_answer = ord(answer_letter) - ord("A")
        elif line.startswith("SOURCE:"):
            try:
                source_text = line.split(":", 1)[1].strip()
                source_num = int(source_text.replace("SOURCE", "").strip())
            except Exception:
                source_num = 1

    if current_q and len(options) == 4 and correct_answer is not None:
        questions.append({
            "question": current_q,
            "options": options,
            "correct_index": correct_answer,
            "chunk_source": _source_name(chunks, source_num),
        })

    return questions


def _source_name(chunks: List[Dict[str, Any]], source_num: int | None) -> str:
    if source_num and 0 < source_num <= len(chunks):
        return chunks[source_num - 1].get("metadata", {}).get("source", "Unknown")
    return "Unknown"


def _sentence_candidates(text: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []

    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    candidates: List[str] = []
    for part in parts:
        sentence = part.strip(" -•\t")
        if 35 <= len(sentence) <= 220 and len(sentence.split()) >= 6:
            candidates.append(sentence)
    return candidates


def _build_fallback_questions(
    chunks: List[Dict[str, Any]],
    num_questions: int,
    exclude_questions: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """
    Create grounded MCQs directly from chunk text using multi-pattern generation.
    """
    import random
    import re
    exclude_questions = exclude_questions or []
    seen = {q.get("question", "").strip().lower() for q in exclude_questions if q.get("question")}

    sentence_pool: List[Dict[str, str]] = []
    for chunk in chunks:
        source = chunk.get("metadata", {}).get("source", "Unknown")
        for sentence in _sentence_candidates(chunk.get("text", "")):
            sentence_pool.append({"text": sentence, "source": source})

    fallback_questions: List[Dict[str, Any]] = []
    random.shuffle(sentence_pool)
    
    for index, item in enumerate(sentence_pool):
        if len(fallback_questions) >= num_questions:
            break

        text = item["text"]
        words = text.split()
        if len(words) < 6:
            continue
            
        pattern_type = random.choice(["keyword", "cloze", "fact"])
        
        if pattern_type == "keyword":
            candidates = [w for w in words if len(re.sub(r'[^a-zA-Z]', '', w)) > 7]
            if not candidates:
                pattern_type = "cloze"
            else:
                target = random.choice(candidates)
                clean_target = re.sub(r'[^a-zA-Z]', '', target)
                question_text = f"Fill in the missing key term: '{text.replace(target, '________')}'"
                correct_ans = clean_target
                
                distractors = []
                for other in sentence_pool:
                    if other["text"] == text: continue
                    other_words = [re.sub(r'[^a-zA-Z]', '', w) for w in other["text"].split() if len(re.sub(r'[^a-zA-Z]', '', w)) > 7]
                    distractors.extend([w for w in other_words if w.lower() != clean_target.lower()])
                
                distractors = list(set(distractors))
                random.shuffle(distractors)
                
        if pattern_type in ["cloze", "fact"]:
            mid = len(words) // 2
            first_half = " ".join(words[:mid])
            second_half = " ".join(words[mid:])
            
            if pattern_type == "cloze":
                question_text = f"Complete the sentence from the text: '{first_half}...'"
            else:
                question_text = f"Regarding the premise '{first_half}...', which conclusion is supported by the text?"
                
            correct_ans = second_half
            
            distractors = []
            for other in sentence_pool:
                if other["text"] == text: continue
                other_words = other["text"].split()
                if len(other_words) >= 6:
                    other_mid = len(other_words) // 2
                    distractors.append(" ".join(other_words[other_mid:]))
            
            distractors = list(set(distractors))
            random.shuffle(distractors)

        if len(distractors) < 3:
            continue
            
        q_key = question_text.strip().lower()
        if q_key in seen:
            continue
        seen.add(q_key)
        
        options = [correct_ans, *distractors[:3]]
        correct_index = random.randint(0, 3)
        if correct_index != 0:
            correct_option = options.pop(0)
            options.insert(correct_index, correct_option)

        fallback_questions.append({
            "question": question_text,
            "options": options,
            "correct_index": correct_index,
            "chunk_source": item["source"],
        })

    return fallback_questions


QUIZ_GENERATION_SYSTEM_PROMPT = """You are a quiz generator for an educational AI tutor.

Your role is to create high-quality multiple-choice questions that:
- Test real understanding, not just memorization
- Are clear and unambiguous
- Have plausible distractors (wrong answers that seem reasonable)
- Are grounded in the provided content

CRITICAL: You must ONLY use information from the provided sources. Do not add external knowledge."""
