# backend/api/auth.py
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from backend.utils.db import get_db
from backend.auth import get_password_hash, verify_password, create_access_token
from backend.models.user import UserCreate, UserPublic
from backend.config import settings
from jose import jwt, JWTError
from bson import ObjectId

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")

# Dependency to get current user
async def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise credentials_exception
    return user

# Dependency to require specific roles
def require_role(*roles: str):
    def _dep(current_user=Depends(get_current_user)):
        user_role = current_user.get("role", "Student").lower()
        if user_role not in [r.lower() for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to: {roles}",
            )
        return current_user
    return _dep

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
        "role": user_in.role,
        "created_at": datetime.utcnow()
    }
    
    # 4. Insert into DB
    try:
        result = await db.users.insert_one(user_dict)
        
        # 5. Return success
        return UserPublic(
            id=str(result.inserted_id),
            name=user_in.name,
            email=user_in.email,
            level=user_in.level,
            role=user_in.role
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
            "role": user.get("role", "Student")
        }
    }

@router.get("/me", response_model=UserPublic)
async def read_users_me(current_user = Depends(get_current_user)):
    return UserPublic(
        id=str(current_user["_id"]),
        name=current_user["name"],
        email=current_user["email"],
        level=current_user["level"],
        role=current_user.get("role", "Student")
    )

# ─── Admin Routes ─────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserPublic])
async def list_users(
    db = Depends(get_db),
    admin = Depends(require_role("Admin"))
):
    """Admin: List all users in the system"""
    users = await db.users.find().to_list(length=1000)
    return [
        UserPublic(
            id=str(u["_id"]),
            name=u.get("name", ""),
            email=u.get("email", ""),
            level=u.get("level", "undergraduate"),
            role=u.get("role", "Student")
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
    admin = Depends(require_role("Admin"))
):
    """Admin: Update a user's role"""
    if body.role not in ["Admin", "Teacher", "Student"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be Admin, Teacher, or Student.")
    
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": body.role}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {"status": "success", "message": f"Updated user role to {body.role}"}
