from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from .auth import verify_token
from .db import get_database

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db = Depends(get_database)
) -> dict:
    """Get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Verify token and get user_id
        payload = verify_token(token)
        user_id = payload.get("user_id")
        
        if user_id is None:
            raise credentials_exception
        
        # Get user from database
        user = await db.users.find_one({"_id": user_id})
        if user is None:
            raise credentials_exception
        
        return user
    except Exception:
        raise credentials_exception