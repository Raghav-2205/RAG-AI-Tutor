from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from .auth import verify_token
from .db import get_database
from bson import ObjectId

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
        print(f"[DEBUG dependencies.py] verify_token returned: {payload}", flush=True)
        
        if user_id is None:
            print("[DEBUG dependencies.py] user_id is None", flush=True)
            raise credentials_exception
        
        # Get user from database
        try:
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            print(f"[DEBUG dependencies.py] user found in DB: {user is not None}", flush=True)
        except Exception as e:
            print(f"[DEBUG dependencies.py] Exception querying MongoDB: {type(e).__name__}: {str(e)}", flush=True)
            raise credentials_exception
            
        if user is None:
            print("[DEBUG dependencies.py] user is None after looking up DB", flush=True)
            raise credentials_exception
        
        return user
    except Exception as e:
        if not isinstance(e, HTTPException):
            print(f"[DEBUG dependencies.py] Catch-all Exception: {type(e).__name__}: {str(e)}", flush=True)
        raise credentials_exception