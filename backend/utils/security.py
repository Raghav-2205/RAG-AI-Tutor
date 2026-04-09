from __future__ import annotations

from typing import Iterable

from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from backend.config import settings
from backend.utils.db import get_db

ALLOWED_ROLES = {"student", "teacher", "admin"}
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")


def normalize_role(role: str | None, default: str = "student") -> str:
    normalized = str(role or default).strip().lower()
    return normalized or default


def format_role(role: str | None) -> str:
    return normalize_role(role).capitalize()


def normalize_user_document(user: dict | None) -> dict | None:
    if not user:
        return user
    normalized = dict(user)
    normalized["role"] = normalize_role(user.get("role"))
    return normalized


def validate_role_input(role: str | None) -> str:
    normalized = normalize_role(role)
    if normalized not in ALLOWED_ROLES:
        allowed = ", ".join(sorted(ALLOWED_ROLES))
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {allowed}.")
    return normalized


def normalize_roles(roles: Iterable[str]) -> set[str]:
    return {validate_role_input(role) for role in roles}


async def get_current_user(token: str = Depends(oauth2_scheme), db=Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.algorithm])
        user_id: str | None = payload.get("sub")
        if not user_id or not ObjectId.is_valid(user_id):
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise credentials_exception
    return normalize_user_document(user)


def require_role(*roles: str):
    allowed_roles = normalize_roles(roles)

    def _dep(current_user=Depends(get_current_user)):
        user_role = normalize_role(current_user.get("role"))
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to: {tuple(sorted(allowed_roles))}",
            )
        return normalize_user_document(current_user)

    return _dep
