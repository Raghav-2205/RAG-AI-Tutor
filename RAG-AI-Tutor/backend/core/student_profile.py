"""
Student Profile Management

Tracks quiz performance, calculates student level, and manages learning profile.
"""

from typing import Dict, List, Optional
from datetime import datetime
import os


class StudentProfile:
    """Manages student learning profile and performance tracking"""
    
    def __init__(self, user_id: str, db=None):
        self.user_id = user_id
        self.db = db
        self.prompt_dir = os.path.join(os.path.dirname(__file__), '..', 'prompts')
    
    async def get_or_create_profile(self) -> Dict:
        """Get existing profile or create new one"""
        if self.db is None:
            return self._default_profile()
        
        profile = await self.db.student_profiles.find_one({"user_id": self.user_id})
        
        if not profile:
            profile = self._default_profile()
            await self.db.student_profiles.insert_one(profile)
        
        return profile
    
    def _default_profile(self) -> Dict:
        """Create default profile for new student"""
        return {
            "user_id": self.user_id,
            "current_level": "Beginner",  # Default to beginner until first quiz
            "quiz_history": [],
            "weak_topics": [],
            "total_quizzes": 0,
            "average_score": 0.0,
            "last_updated": datetime.utcnow()
        }
    
    async def update_from_quiz(self, quiz_result: Dict):
        """Update profile based on quiz results"""
        score = quiz_result['score']
        total = quiz_result['total_questions']
        percentage = (score / total) * 100 if total > 0 else 0
        
        # Calculate level
        level = self.calculate_level(percentage)
        
        # Extract weak topics from wrong answers
        weak_topics = self._identify_weak_topics(quiz_result)
        
        # Update history
        quiz_entry = {
            "quiz_id": quiz_result['quiz_id'],
            "score": score,
            "total": total,
            "percentage": percentage,
            "level": level,
            "date": datetime.utcnow()
        }
        
        if self.db is not None:
            await self.db.student_profiles.update_one(
                {"user_id": self.user_id},
                {
                    "$set": {
                        "current_level": level,
                        "weak_topics": weak_topics,
                        "last_updated": datetime.utcnow()
                    },
                    "$push": {"quiz_history": quiz_entry},
                    "$inc": {"total_quizzes": 1}
                },
                upsert=True
            )
            
            # Update average score
            await self._update_average_score()
        
        return {
            "level": level,
            "weak_topics": weak_topics,
            "percentage": percentage
        }
    
    @staticmethod
    def calculate_level(percentage: float) -> str:
        """Calculate student level based on quiz percentage"""
        if percentage >= 71:
            return "Advanced"
        elif percentage >= 41:
            return "Intermediate"
        else:
            return "Beginner"
    
    def _identify_weak_topics(self, quiz_result: Dict) -> List[str]:
        """Identify topics where student answered incorrectly"""
        weak_topics = []
        
        questions = quiz_result.get('questions', [])
        answers = quiz_result.get('answers', [])
        
        for i, (question, answer) in enumerate(zip(questions, answers)):
            correct_index = question.get('correct_index')
            if answer != correct_index:
                # Extract topic from question or source
                source = question.get('chunk_source', '')
                if source and source not in weak_topics:
                    weak_topics.append(source)
        
        return weak_topics[:5]  # Limit to top 5 weak areas
    
    async def _update_average_score(self):
        """Recalculate average score from quiz history"""
        if self.db is None:
            return
        
        profile = await self.db.student_profiles.find_one({"user_id": self.user_id})
        if profile and profile.get('quiz_history'):
            total_percentage = sum(q['percentage'] for q in profile['quiz_history'])
            avg = total_percentage / len(profile['quiz_history'])
            
            await self.db.student_profiles.update_one(
                {"user_id": self.user_id},
                {"$set": {"average_score": avg}}
            )
    
    async def get_adaptive_prompt(self) -> str:
        """Get appropriate system prompt based on student level"""
        profile = await self.get_or_create_profile()
        level = profile.get('current_level', 'Beginner')
        weak_topics = profile.get('weak_topics', [])
        
        # Load appropriate prompt template
        prompt_file = f"{level.lower()}_prompt.txt"
        prompt_path = os.path.join(self.prompt_dir, prompt_file)
        
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            # Replace placeholders
            weak_topics_str = ', '.join(weak_topics) if weak_topics else 'None identified yet'
            prompt = prompt_template.replace('{weak_topics}', weak_topics_str)
            
            return prompt
            
        except FileNotFoundError:
            print(f"⚠️ Prompt file not found: {prompt_path}, using default")
            return "You are a helpful AI tutor. Adapt your responses to the student's level."
    
    async def get_learning_stats(self) -> Dict:
        """Get student learning statistics"""
        profile = await self.get_or_create_profile()
        
        return {
            "current_level": profile.get('current_level', 'Beginner'),
            "total_quizzes": profile.get('total_quizzes', 0),
            "average_score": profile.get('average_score', 0.0),
            "weak_topics": profile.get('weak_topics', []),
            "recent_quizzes": profile.get('quiz_history', [])[-5:]  # Last 5
        }


async def get_student_level(user_id: str, db) -> str:
    """Quick helper to get student's current level"""
    profile = StudentProfile(user_id, db)
    data = await profile.get_or_create_profile()
    return data.get('current_level', 'Beginner')
