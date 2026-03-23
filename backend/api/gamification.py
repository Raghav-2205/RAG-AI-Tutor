"""
Gamification API Router — Points, Badges, Leaderboard
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from backend.utils.db import get_db
from backend.api.auth import get_current_user
import backend.services.gamification_service as gamification_service

router = APIRouter()


@router.get("/my-stats", summary="Get current user's gamification stats")
async def my_stats(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    points = await gamification_service.get_user_points(db, user_id)
    badges = await gamification_service.get_user_badges(db, user_id)
    stats = await gamification_service.get_user_stats(db, user_id)
    return {
        "user_id": user_id,
        "total_points": points,
        "badges": badges,
        "badge_count": len(badges),
        "stats": stats,
    }


@router.get("/badges", summary="Get all badges earned by current user")
async def my_badges(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    badges = await gamification_service.get_user_badges(db, user_id)
    return badges


@router.post("/badges/check", summary="Check & award any newly earned badges")
async def check_badges(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    new_badges = await gamification_service.check_and_award_badges(db, user_id)
    return {"newly_awarded": new_badges, "count": len(new_badges)}


@router.get("/points/history", summary="Get point transaction history")
async def point_history(
    limit: int = Query(30, ge=1, le=100),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    history = await gamification_service.get_point_history(db, user_id, limit)
    return history


@router.get("/leaderboard", summary="Get global or class leaderboard")
async def leaderboard(
    class_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    board = await gamification_service.get_leaderboard(db, class_id, limit)
    return board


@router.post("/award", summary="Manually award points (admin only)")
async def award_points_manual(
    user_id: str,
    action: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = current_user.get("role", "student").lower()
    if role not in ("admin", "teacher"):
        raise HTTPException(status_code=403, detail="Only admins/teachers can manually award points")
    points = await gamification_service.award_points(db, user_id, action)
    if points == 0:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    await gamification_service.check_and_award_badges(db, user_id)
    return {"message": f"Awarded {points} points for '{action}'", "points": points}
