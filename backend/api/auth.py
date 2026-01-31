"""
Auth API: register, login, me.
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.config import settings
from backend.models.user import UserCreate, UserLogin, UserResponse, user_doc_to_response
from backend.utils.db import get_db
from backend.utils.auth_utils import hash_password, verify_password, create_access_token, decode_access_token

router = APIRouter(tags=["auth"])
security = HTTPBearer(auto_error=False)

USERS_COLLECTION = "users"


def get_current_user_id(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> str | None:
    if not credentials:
        return None
    return decode_access_token(credentials.credentials)


@router.post("/register", response_model=dict)
def register(body: UserCreate):
    """Register a new user."""
    db = get_db()
    coll = db[USERS_COLLECTION]
    existing = coll.find_one({"email": body.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    now = datetime.utcnow()
    doc = {
        "name": body.name,
        "email": body.email,
        "password": hash_password(body.password),
        "level": body.level,
        "created_at": now,
    }
    r = coll.insert_one(doc)
    doc["_id"] = r.inserted_id
    user = user_doc_to_response({**doc, "created_at": doc["created_at"].isoformat()})
    token = create_access_token(str(r.inserted_id))
    return {"user": user.model_dump(), "token": token, "access_token": token, "jwt": token}


@router.post("/login", response_model=dict)
def login(body: UserLogin):
    """Login and return JWT."""
    db = get_db()
    coll = db[USERS_COLLECTION]
    doc = coll.find_one({"email": body.email})
    if not doc or not verify_password(body.password, doc["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user = user_doc_to_response({
        "_id": doc["_id"], "name": doc["name"], "email": doc["email"],
        "level": doc.get("level", "school"), "created_at": doc.get("created_at"),
    })
    token = create_access_token(str(doc["_id"]))
    return {"user": user.model_dump(), "token": token, "access_token": token, "jwt": token}


@router.get("/me", response_model=dict)
def me(user_id: str | None = Depends(get_current_user_id)):
    """Return current user from JWT."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db = get_db()
    coll = db[USERS_COLLECTION]
    from bson import ObjectId
    doc = coll.find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=401, detail="User not found")
    user = user_doc_to_response({
        "_id": doc["_id"], "name": doc["name"], "email": doc["email"],
        "level": doc.get("level", "school"), "created_at": doc.get("created_at"),
    })
    return {"user": user.model_dump()}
