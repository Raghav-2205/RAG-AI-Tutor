# backend/api/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import timedelta
from typing import Optional

from backend.utils import get_db, create_access_token, verify_token
from backend.models.user import UserCreate, UserLogin, UserPublic


router = APIRouter(tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


class Token(BaseModel):
    access_token: str
    token_type: str


@router.post("/register", response_model=UserPublic, status_code=201)
async def register(user: UserCreate, db=Depends(get_db)):
    """Register new user"""
    # Check if user exists
    existing = db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Hash password and save (handled by UserCreate)
    user_doc = user.dict()
    result = db.users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    
    return UserPublic.from_mongo(user_doc)


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    """Login and return JWT token"""
    user = db.users.find_one({"email": form_data.username})
    if not user or not verify_token(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": str(user["_id"])})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserPublic)
async def read_users_me(token: str = Depends(oauth2_scheme), db=Depends(get_db)):
    """Get current user info"""
    payload = verify_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.users.find_one({"_id": user_id})
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic.from_mongo(user)
