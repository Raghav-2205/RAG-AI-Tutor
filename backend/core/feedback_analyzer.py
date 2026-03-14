# backend/core/feedback_analyzer.py
"""
Feedback Analysis Module

Analyzes user feedback to inform RAG system behavior.
Provides insights on user satisfaction, problem areas, and response quality.
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class FeedbackAnalyzer:
    """Analyzes feedback to drive AI tutor improvements"""
    
    def __init__(self, db):
        self.db = db
    
    async def get_user_feedback_stats(self, user_id: str, hours: int = 24) -> Dict:
        """
        Get recent feedback statistics for a user.
        
        Returns:
            {
                "total_feedback": 10,
                "negative_count": 3,
                "positive_count": 7,
                "negative_percentage": 30.0,
                "recent_subjects": ["Math", "CS"],
                "struggling": true/false
            }
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        # Get recent feedback
        recent_feedback = await self.db.feedback.find({
            "user_id": user_id,
            "timestamp": {"$gte": cutoff_time}
        }).to_list(length=100)
        
        total = len(recent_feedback)
        if total == 0:
            return {
                "total_feedback": 0,
                "negative_count": 0,
                "positive_count": 0,
                "negative_percentage": 0.0,
                "recent_subjects": [],
                "struggling": False
            }
        
        # Count negative feedback (chat: "negative", quiz: "1" or "2")
        negative = sum(
            1 for f in recent_feedback 
            if f["rating"] in ["negative", "1", "2"]
        )
        
        positive = sum(
            1 for f in recent_feedback 
            if f["rating"] in ["positive", "4", "5"]
        )
        
        # Extract subjects
        subjects = list(set(f.get("subject", "general") for f in recent_feedback))
        
        negative_pct = (negative / total) * 100 if total > 0 else 0
        
        # User is "struggling" if >40% negative feedback or 3+ negative in last 24h
        struggling = negative_pct > 40 or negative >= 3
        
        return {
            "total_feedback": total,
            "negative_count": negative,
            "positive_count": positive,
            "negative_percentage": round(negative_pct, 1),
            "recent_subjects": subjects,
            "struggling": struggling
        }
    
    async def should_adjust_prompt(self, user_id: str) -> tuple[bool, str]:
        """
        Determine if system prompt should be adjusted for this user.
        
        Returns:
            (should_adjust: bool, reason: str)
        """
        stats = await self.get_user_feedback_stats(user_id, hours=24)
        
        # No feedback yet - use default
        if stats["total_feedback"] == 0:
            return False, "no_feedback"
        
        # High negative feedback - adjust
        if stats["struggling"]:
            return True, "high_negative_feedback"
        
        # Mostly positive - no adjustment needed
        if stats["negative_percentage"] < 20:
            return False, "positive_feedback"
        
        # Moderate issues - slight adjustment
        if stats["negative_percentage"] >= 20:
            return True, "moderate_negative_feedback"
        
        return False, "default"
    
    async def get_adaptive_context(self, user_id: str) -> str:
        """
        Generate context string to append to system prompt based on feedback.
        
        Returns text to add to system prompt for better responses.
        """
        stats = await self.get_user_feedback_stats(user_id, hours=24)
        
        if not stats["struggling"]:
            return ""
        
        # Generate adaptive instructions
        context = "\n\n--- ADAPTIVE INSTRUCTIONS (Based on User Feedback) ---\n"
        
        if stats["negative_count"] >= 3:
            context += """
IMPORTANT: This user has given negative feedback recently. Adjust your approach:
- Be MORE detailed and thorough in explanations
- Break down complex concepts into smaller steps
- Ask clarifying questions before assuming understanding
- Provide concrete examples for every concept
- Double-check your responses for clarity and accuracy
- If explaining code, add extensive comments
"""
        
        if stats["negative_percentage"] > 60:
            context += """
- This user is struggling significantly
- Use simpler language and avoid jargon
- Start from absolute basics
- Be extremely patient and encouraging
- Celebrate small wins
"""
        
        return context.strip()
    
    async def track_response_quality(
        self,
        reference_id: str,
        chunk_sources: List[str]
    ):
        """
        Track which document chunks were used for a response.
        This allows future correlation with feedback.
        
        Stores: response_id -> [chunk1, chunk2, ...]
        """
        if self.db is None:
            return
        
        await self.db.response_chunks.insert_one({
            "reference_id": reference_id,
            "chunk_sources": chunk_sources,
            "timestamp": datetime.utcnow()
        })
    
    async def get_low_quality_chunks(
        self,
        subject: Optional[str] = None,
        threshold: float = 0.3
    ) -> List[str]:
        """
        Get chunk sources that consistently lead to negative feedback.
        
        Args:
            subject: Optional subject filter
            threshold: If >30% of responses using this chunk get negative feedback, mark it
        
        Returns:
            List of chunk source identifiers
        """
        # Aggregate: Find chunks used in responses with negative feedback
        pipeline = [
            # Stage 1: Get all negative feedback with reference_ids
            {
                "$match": {
                    "rating": {"$in": ["negative", "1", "2"]},
                    **({"subject": subject} if subject else {})
                }
            },
            # Stage 2: Lookup the chunks used in those responses
            {
                "$lookup": {
                    "from": "response_chunks",
                    "localField": "reference_id",
                    "foreignField": "reference_id",
                    "as": "chunks"
                }
            },
            # Stage 3: Unwind chunk arrays
            {"$unwind": "$chunks"},
            {"$unwind": "$chunks.chunk_sources"},
            # Stage 4: Group by chunk source and count
            {
                "$group": {
                    "_id": "$chunks.chunk_sources",
                    "negative_count": {"$sum": 1}
                }
            }
        ]
        
        negative_chunks = await self.db.feedback.aggregate(pipeline).to_list(length=1000)
        
        # Now get total usage for each chunk to calculate percentage
        low_quality = []
        for chunk_data in negative_chunks:
            chunk_id = chunk_data["_id"]
            negative_count = chunk_data["negative_count"]
            
            # Get total times this chunk was used
            total_uses = await self.db.response_chunks.count_documents({
                "chunk_sources": chunk_id
            })
            
            if total_uses > 0:
                negative_rate = negative_count / total_uses
                if negative_rate >= threshold:
                    low_quality.append(chunk_id)
                    logger.info(f"Low quality chunk detected: {chunk_id} ({negative_rate:.1%} negative)")
        
        return low_quality
    
    async def log_feedback_influence(
        self,
        user_id: str,
        reference_id: str,
        adjustment_type: str,
        details: Dict
    ):
        """
        Log when feedback influenced a response.
        Useful for monitoring and analyzing effectiveness.
        """
        if self.db is None:
            return
        
        await self.db.feedback_influence_log.insert_one({
            "user_id": user_id,
            "reference_id": reference_id,
            "adjustment_type": adjustment_type,
            "details": details,
            "timestamp": datetime.utcnow()
        })


async def get_feedback_analyzer(db):
    """Factory function to get FeedbackAnalyzer instance"""
    return FeedbackAnalyzer(db)
