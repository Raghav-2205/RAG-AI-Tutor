# backend/api/auth.py
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from backend.utils.db import get_db
from backend.auth import get_password_hash, verify_password, create_access_token
from backend.models.user import UserCreate, UserPublic
from backend.utils.security import format_role, get_current_user, normalize_role, require_role, validate_role_input
from bson import ObjectId

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

@router.post("/register", response_model=UserPublic, status_code=201)
async def register(user_in: UserCreate, db = Depends(get_db)):
    # 1. Check if email exists
    existing_user = await db.users.find_one({"email": user_in.email.lower()})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Hash password
    hashed_pw = get_password_hash(user_in.password)

    # 3. MANUAL DICT CREATION (Fixes the Pydantic/Mongo _id bug)
    user_dict = {
        "name": user_in.name,
        "email": user_in.email.lower(),
        "hashed_password": hashed_pw,
        "level": user_in.level,
        "role": "student",
        "created_at": _utcnow()
    }
    
    # 4. Insert into DB
    try:
        result = await db.users.insert_one(user_dict)

        invited_email = user_in.email.lower()
        pending_invites = await db.class_invitations.find(
            {
                "student_email": invited_email,
                "status": "pending",
                "expires_at": {"$gte": _utcnow()},
            }
        ).to_list(length=100)
        for invite in pending_invites:
            class_id = invite.get("class_id")
            if not class_id:
                continue

            cls = await db.classes.find_one({"id": class_id})
            if cls and str(result.inserted_id) not in (cls.get("students") or []):
                await db.classes.update_one({"id": class_id}, {"$push": {"students": str(result.inserted_id)}})

            await db.class_invitations.update_one(
                {"id": invite.get("id")},
                {
                    "$set": {
                        "status": "accepted",
                        "accepted_at": _utcnow(),
                        "accepted_user_id": str(result.inserted_id),
                    }
                },
            )
        
        # 5. Return success
        return UserPublic(
            id=str(result.inserted_id),
            name=user_in.name,
            email=user_in.email,
            level=user_in.level,
            role="student"
        )
    except Exception as e:
        print(f"DB Error: {e}")
        raise HTTPException(status_code=500, detail="Database write failed")

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db = Depends(get_db)):
    # Note: OAuth2 form uses 'username' field for email
    user = await db.users.find_one({"email": form_data.username.lower()})

    hashed_password = user.get("hashed_password") if user else None
    if not user or not hashed_password or not verify_password(form_data.password, hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user["_id"])})

    user_name = user.get("name") or user.get("email", "").split("@")[0]
    user_email = user.get("email") or form_data.username.lower()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user["_id"]),
            "name": user_name,
            "email": user_email,
            "role": normalize_role(user.get("role", "student"))
        }
    }

@router.get("/me", response_model=UserPublic)
async def read_users_me(current_user = Depends(get_current_user)):
    return UserPublic(
        id=str(current_user["_id"]),
        name=current_user["name"],
        email=current_user["email"],
        level=current_user.get("level", "undergraduate"),
        role=normalize_role(current_user.get("role", "student"))
    )

# ─── Admin Routes ─────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserPublic])
async def list_users(
    db = Depends(get_db),
    admin = Depends(require_role("admin"))
):
    """Admin: List all users in the system"""
    users = await db.users.find().to_list(length=1000)
    return [
        UserPublic(
            id=str(u["_id"]),
            name=u.get("name", ""),
            email=u.get("email", ""),
            level=u.get("level", "undergraduate"),
            role=normalize_role(u.get("role", "student"))
        ) for u in users
    ]

from pydantic import BaseModel
class UpdateRoleIn(BaseModel):
    role: str

@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    body: UpdateRoleIn,
    db = Depends(get_db),
    admin = Depends(require_role("admin"))
):
    """Admin: Update a user's role"""
    normalized_role = validate_role_input(body.role)
    
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": normalized_role}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {"status": "success", "message": f"Updated user role to {format_role(normalized_role)}"}
