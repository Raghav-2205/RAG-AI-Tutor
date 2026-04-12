"""
Quiz Generator Service

Generates MCQ questions from document chunks stored in the vector database.
Ensures questions are grounded in actual content to prevent hallucinations.
"""

import re
import uuid
from typing import Any, Dict, List

from backend.core.llm_interface import llm_client
from backend.vector_db import get_all_chunks


def generate_quiz_from_chunks(user_id: str, subject: str, num_questions: int = 10) -> Dict[str, Any]:
    """
    Generate a quiz with MCQ questions based on document chunks.

    The primary path uses the LLM to write grounded multiple-choice questions.
    If the model output is partially malformed, or the parser extracts too few
    valid questions, we backfill from retrieved chunk content instead of
    failing the whole request.
    """

    user_chunks = get_all_chunks(user_id, subject)
    global_chunks = get_all_chunks("global", "general")
    chunks = user_chunks + global_chunks

    if not chunks:
        raise ValueError("Not enough document content to generate quiz. Please upload more documents.")

    selected_chunks = _select_diverse_chunks(chunks, max(num_questions, 4))
    quiz_prompt = _build_quiz_generation_prompt(selected_chunks, num_questions, subject)

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


def _build_quiz_generation_prompt(chunks: List[Dict[str, Any]], num_questions: int, subject: str) -> str:
    """Build the LLM prompt for grounded quiz generation."""
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("metadata", {}).get("source", "Unknown")
        text = chunk.get("text", "")
        context_parts.append(f"[SOURCE {i}] ({source})\n{text}")

    context = "\n\n---\n\n".join(context_parts)
    return f"""Generate {num_questions} multiple-choice questions for a {subject} quiz based ONLY on the provided content below.

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


def _parse_quiz_response(response: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse LLM response into structured question format."""
    questions: List[Dict[str, Any]] = []
    lines = response.strip().split("\n")

    current_q = None
    options: List[str] = []
    correct_answer = None
    source_num = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("Q") and ":" in line:
            if current_q and len(options) == 4 and correct_answer is not None:
                questions.append({
                    "question": current_q,
                    "options": options,
                    "correct_index": correct_answer,
                    "chunk_source": _source_name(chunks, source_num),
                })

            current_q = line.split(":", 1)[1].strip()
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
    Create grounded MCQs directly from chunk text when LLM parsing fails.

    These are simpler than the LLM-authored questions, but they remain tied to
    retrieved material and keep the diagnostic quiz experience functional.
    """

    exclude_questions = exclude_questions or []
    seen = {q.get("question", "").strip().lower() for q in exclude_questions if q.get("question")}

    sentence_pool: List[Dict[str, str]] = []
    for chunk in chunks:
        source = chunk.get("metadata", {}).get("source", "Unknown")
        for sentence in _sentence_candidates(chunk.get("text", "")):
            sentence_pool.append({"text": sentence, "source": source})

    fallback_questions: List[Dict[str, Any]] = []
    for index, item in enumerate(sentence_pool):
        if len(fallback_questions) >= num_questions:
            break

        question = f"Which statement is directly supported by the material from {item['source']}?"
        q_key = question.strip().lower()
        if q_key in seen:
            continue

        distractors: List[str] = []
        for other in sentence_pool:
            if other["text"] == item["text"]:
                continue
            if other["source"] == item["source"] and len(sentence_pool) > 4:
                continue
            distractors.append(other["text"])
            if len(distractors) == 3:
                break

        if len(distractors) < 3:
            continue

        options = [item["text"], *distractors[:3]]
        correct_index = index % 4
        if correct_index != 0:
            correct_option = options.pop(0)
            options.insert(correct_index, correct_option)

        fallback_questions.append({
            "question": question,
            "options": options,
            "correct_index": correct_index,
            "chunk_source": item["source"],
        })
        seen.add(q_key)

    return fallback_questions


QUIZ_GENERATION_SYSTEM_PROMPT = """You are a quiz generator for an educational AI tutor.

Your role is to create high-quality multiple-choice questions that:
- Test real understanding, not just memorization
- Are clear and unambiguous
- Have plausible distractors (wrong answers that seem reasonable)
- Are grounded in the provided content

CRITICAL: You must ONLY use information from the provided sources. Do not add external knowledge."""
