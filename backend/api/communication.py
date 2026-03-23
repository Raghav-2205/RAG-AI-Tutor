# backend/api/communication.py
"""
Communication Module — Notice Board, College Updates, Forum.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.utils.db import get_db
from backend.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ===================== Helpers =====================

def require_role(user, roles):
    role = user.get("role", "Student")
    if role not in roles:
        raise HTTPException(403, f"Access denied. Required role: {roles}")


# ===================== Pydantic Models =====================

class NoticeCreate(BaseModel):
    title: str
    content: str
    priority: str = "normal"  # low, normal, high, urgent
    target_roles: List[str] = ["Student", "Teacher", "Admin"]

class UpdateCreate(BaseModel):
    title: str
    content: str
    category: str = "general"  # general, event, academic, sports

class ForumPostCreate(BaseModel):
    title: str
    content: str
    tags: List[str] = []

class ForumReplyCreate(BaseModel):
    post_id: str
    content: str


# ===================== NOTICE BOARD =====================

@router.post("/notices")
async def create_notice(data: NoticeCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    require_role(current_user, ["Teacher", "Admin"])
    notice_id = str(uuid.uuid4())
    record = {
        "notice_id": notice_id,
        "title": data.title,
        "content": data.content,
        "priority": data.priority,
        "target_roles": data.target_roles,
        "author_id": str(current_user["_id"]),
        "author_name": current_user.get("name", ""),
        "author_role": current_user.get("role", "Teacher"),
        "created_at": datetime.utcnow()
    }
    await db.notices.insert_one(record)
    return {"status": "posted", "notice_id": notice_id}


@router.get("/notices")
async def list_notices(current_user=Depends(get_current_user), db=Depends(get_db)):
    role = current_user.get("role", "Student")
    notices = await db.notices.find({"target_roles": role}).sort("created_at", -1).to_list(50)
    for n in notices:
        n["_id"] = str(n["_id"])
    return notices


@router.delete("/notices/{notice_id}")
async def delete_notice(notice_id: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    require_role(current_user, ["Admin"])
    await db.notices.delete_one({"notice_id": notice_id})
    return {"status": "deleted"}


# ===================== COLLEGE UPDATES =====================

@router.post("/updates")
async def create_update(data: UpdateCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    require_role(current_user, ["Teacher", "Admin"])
    update_id = str(uuid.uuid4())
    record = {
        "update_id": update_id,
        "title": data.title,
        "content": data.content,
        "category": data.category,
        "author_id": str(current_user["_id"]),
        "author_name": current_user.get("name", ""),
        "created_at": datetime.utcnow()
    }
    await db.college_updates.insert_one(record)
    return {"status": "posted", "update_id": update_id}


@router.get("/updates")
async def list_updates(category: Optional[str] = None, current_user=Depends(get_current_user), db=Depends(get_db)):
    query = {}
    if category:
        query["category"] = category
    updates = await db.college_updates.find(query).sort("created_at", -1).to_list(50)
    for u in updates:
        u["_id"] = str(u["_id"])
    return updates


# ===================== FORUM =====================

@router.post("/forum/posts")
async def create_forum_post(data: ForumPostCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    post_id = str(uuid.uuid4())
    record = {
        "post_id": post_id,
        "title": data.title,
        "content": data.content,
        "tags": data.tags,
        "author_id": str(current_user["_id"]),
        "author_name": current_user.get("name", ""),
        "author_role": current_user.get("role", "Student"),
        "replies": [],
        "likes": 0,
        "liked_by": [],
        "created_at": datetime.utcnow()
    }
    await db.forum_posts.insert_one(record)
    return {"status": "posted", "post_id": post_id}


@router.get("/forum/posts")
async def list_forum_posts(tag: Optional[str] = None, current_user=Depends(get_current_user), db=Depends(get_db)):
    query = {}
    if tag:
        query["tags"] = tag
    posts = await db.forum_posts.find(query).sort("created_at", -1).to_list(50)
    for p in posts:
        p["_id"] = str(p["_id"])
    return posts


@router.get("/forum/posts/{post_id}")
async def get_forum_post(post_id: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    post = await db.forum_posts.find_one({"post_id": post_id})
    if not post:
        raise HTTPException(404, "Post not found")
    post["_id"] = str(post["_id"])
    return post


@router.post("/forum/reply")
async def reply_to_post(data: ForumReplyCreate, current_user=Depends(get_current_user), db=Depends(get_db)):
    reply = {
        "reply_id": str(uuid.uuid4()),
        "content": data.content,
        "author_id": str(current_user["_id"]),
        "author_name": current_user.get("name", ""),
        "author_role": current_user.get("role", "Student"),
        "created_at": datetime.utcnow().isoformat()
    }
    result = await db.forum_posts.update_one(
        {"post_id": data.post_id},
        {"$push": {"replies": reply}}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Post not found")
    return {"status": "replied", "reply_id": reply["reply_id"]}


@router.post("/forum/posts/{post_id}/like")
async def like_post(post_id: str, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])
    post = await db.forum_posts.find_one({"post_id": post_id})
    if not post:
        raise HTTPException(404, "Post not found")

    if user_id in post.get("liked_by", []):
        # Unlike
        await db.forum_posts.update_one(
            {"post_id": post_id},
            {"$pull": {"liked_by": user_id}, "$inc": {"likes": -1}}
        )
        return {"status": "unliked"}
    else:
        await db.forum_posts.update_one(
            {"post_id": post_id},
            {"$push": {"liked_by": user_id}, "$inc": {"likes": 1}}
        )
        return {"status": "liked"}
