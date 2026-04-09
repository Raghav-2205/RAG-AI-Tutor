# backend/auth.py
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from backend.config import settings
import bcrypt

# Password Hashing with raw bcrypt (No passlib)
def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        # bcrypt.checkpw expects bytes
        return bcrypt.checkpw(
            plain_password.encode('utf-8'), 
            hashed_password.encode('utf-8')
        )
    except Exception as e:
        print(f"Auth Verify Error: {e}")
        return False

def get_password_hash(password: str) -> str:
    # bcrypt.hashpw returns bytes, we save as string
    # rounds=10 is ~3-4x faster than default 12, balancing speed/security
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=10))
    return hashed.decode('utf-8')

# Token Generation
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.jwt_secret_key, 
        algorithm=settings.algorithm
    )
    return encoded_jwt
