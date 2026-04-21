"""
FastAPI dependencies shared across routes.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt

from app.config import settings


def _decode(authorization: str | None) -> str | None:
    """Decode the Authorization header into a user_id, or return None if absent/invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None


async def get_current_user(authorization: str | None = Header(default=None)) -> str:
    """
    Require a valid JWT. Returns the user_id (sub claim).
    Raises 401 if the header is missing or the token is invalid/expired.
    """
    user_id = _decode(authorization)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


async def get_optional_user(authorization: str | None = Header(default=None)) -> str | None:
    """Soft auth — returns user_id when a valid JWT is present, else None. No 401."""
    return _decode(authorization)
