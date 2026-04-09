# backend/api/quiz.py
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
from bson import ObjectId
from backend.utils.db import get_db
from backend.api.auth import get_current_user
from backend.core.quiz_generator import generate_quiz_from_chunks
from backend.core.student_profile import StudentProfile
from backend.utils.helpers import doc_to_dict
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

class QuizGenerateRequest(BaseModel):
    subject: Optional[str] = "general"
    num_questions: int = 10

class QuizSubmitRequest(BaseModel):
    quiz_id: str
    answers: List[int]  # Indices of selected answers

class QuizResponse(BaseModel):
    quiz_id: str
    subject: str
    questions: List[Dict]
    total_questions: int

class QuizSubmitResponse(BaseModel):
    score: int
    total: int
    percentage: float
    level: str
    weak_topics: List[str]
    feedback: str
    correct_answers: List[int]

@router.post("/generate", response_model=QuizResponse)
async def generate_quiz_endpoint(
    request: QuizGenerateRequest,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Generate a new quiz from document chunks"""
    try:
        user_id = str(current_user["_id"])
        
        logger.info(f"[QUIZ GENERATE] User={user_id}, Subject={request.subject}, Questions={request.num_questions}")
        
        # Generate quiz using new chunk-based generator
        quiz_data = generate_quiz_from_chunks(
            user_id=user_id,
            subject=request.subject,
            num_questions=request.num_questions
        )
        
        # Add metadata
        quiz_data["user_id"] = user_id
        quiz_data["created_at"] = _utcnow()
        
        # Save to MongoDB
        result = await db.quizzes.insert_one(quiz_data.copy())
        quiz_data["_id"] = result.inserted_id
        
        logger.info(f"[QUIZ SAVED] QuizID={quiz_data['quiz_id']}")
        
        # Don't send correct answers to frontend yet
        questions_for_frontend = []
        for q in quiz_data["questions"]:
            questions_for_frontend.append({
                "question": q["question"],
                "options": q["options"],
                "chunk_source": q.get("chunk_source", "Unknown")
                # Note: correct_index is NOT included
            })
        
        return QuizResponse(
            quiz_id=quiz_data["quiz_id"],
            subject=quiz_data["subject"],
            questions=questions_for_frontend,
            total_questions=len(questions_for_frontend)
        )
        
    except ValueError as e:
        logger.error(f"[QUIZ ERROR] {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("[QUIZ ERROR]")
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {str(e)}")


@router.post("/submit", response_model=QuizSubmitResponse)
async def submit_quiz_endpoint(
    request: QuizSubmitRequest,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Submit quiz answers and get results"""
    try:
        user_id = str(current_user["_id"])
        
        logger.info(f"[QUIZ SUBMIT] User={user_id}, QuizID={request.quiz_id}")
        
        # Fetch the original quiz
        quiz = await db.quizzes.find_one({"quiz_id": request.quiz_id})
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")
        
        # Verify ownership
        if quiz.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Not your quiz")
        
        # Score the quiz
        questions = quiz["questions"]
        answers = request.answers
        
        if len(answers) != len(questions):
            raise HTTPException(status_code=400, detail="Answer count mismatch")
        
        score = 0
        correct_answers = []
        for i, (question, answer) in enumerate(zip(questions, answers)):
            correct_index = question["correct_index"]
            correct_answers.append(correct_index)
            if answer == correct_index:
                score += 1
        
        total = len(questions)
        percentage = (score / total) * 100 if total > 0 else 0
        
        # Calculate level
        if percentage >= 71:
            level = "Advanced"
        elif percentage >= 41:
            level = "Intermediate"
        else:
            level = "Beginner"
        
        # Identify weak topics
        weak_topics = []
        for i, (question, answer) in enumerate(zip(questions, answers)):
            if answer != question["correct_index"]:
                source = question.get("chunk_source", "Unknown")
                if source not in weak_topics:
                    weak_topics.append(source)
        
        # Save submission
        submission = {
            "quiz_id": request.quiz_id,
            "user_id": user_id,
            "answers": answers,
            "score": score,
            "total": total,
            "percentage": percentage,
            "level": level,
            "weak_topics": weak_topics,
            "timestamp": _utcnow()
        }
        
        await db.quiz_submissions.insert_one(submission)
        
        # Update student profile
        try:
            logger.info(f"[PROFILE UPDATE] Updating profile for user {user_id}")
            profile = StudentProfile(user_id, db)
            quiz_result = {
                "quiz_id": request.quiz_id,
                "score": score,
                "total_questions": total,
                "questions": questions,
                "answers": answers
            }
            await profile.update_from_quiz(quiz_result)
            logger.info(f"[PROFILE UPDATE] Profile updated successfully")
        except Exception as profile_error:
            logger.error(f"[PROFILE UPDATE ERROR] {profile_error}")
            logger.exception("Full traceback:")
            # Don't fail the whole request if profile update fails
            pass
        
        # Generate personalized feedback
        feedback = _generate_feedback(level, score, total, percentage)
        
        logger.info(f"[QUIZ RESULT] Score={score}/{total}, Level={level}")
        
        return QuizSubmitResponse(
            score=score,
            total=total,
            percentage=percentage,
            level=level,
            weak_topics=weak_topics,
            feedback=feedback,
            correct_answers=correct_answers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[QUIZ SUBMIT ERROR]")
        raise HTTPException(status_code=500, detail=f"Submission failed: {str(e)}")


@router.get("/history")
async def get_quiz_history(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get quiz history for current user"""
    user_id = str(current_user["_id"])
    
    submissions = await db.quiz_submissions.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(20).to_list(length=20)
    
    return [doc_to_dict(s) for s in submissions]


@router.get("/stats")
async def get_student_stats(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get student learning statistics"""
    user_id = str(current_user["_id"])
    
    profile = StudentProfile(user_id, db)
    stats = await profile.get_learning_stats()
    
    return stats


def _generate_feedback(level: str, score: int, total: int, percentage: float) -> str:
    """Generate personalized feedback based on performance"""
    
    if level == "Beginner":
        if percentage < 20:
            return f"You got {score} out of {total} correct. Don't worry—everyone starts somewhere! Let's review the basics together and build a strong foundation. I'm here to help you every step of the way. 💪"
        else:
            return f"You scored {score}/{total} ({percentage:.0f}%)! You're making progress. Let's focus on strengthening your understanding of the fundamentals. Keep going—you're doing better than you think! 🌟"
    
    elif level == "Intermediate":
        if percentage < 55:
            return f"You got {score}/{total} ({percentage:.0f}%). You have a good foundation, but there are some gaps we need to address. Let's work on the areas where you struggled and solidify your understanding. You're on the right track! 📚"
        else:
            return f"Nice work! {score}/{total} ({percentage:.0f}%). You're showing solid understanding. Now let's push deeper into these concepts and tackle the trickier aspects. You're ready for the next level! 🚀"
    
    else:  # Advanced
        if percentage < 85:
            return f"Strong performance: {score}/{total} ({percentage:.0f}%)! You've mastered the core concepts. Let's explore the nuances and edge cases that will take your understanding to expert level. Ready for a challenge? 🎯"
        else:
            return f"Excellent! {score}/{total} ({percentage:.0f}%)! You've demonstrated advanced mastery. Let's dive into complex applications and advanced topics to keep challenging you. Outstanding work! ⭐"
