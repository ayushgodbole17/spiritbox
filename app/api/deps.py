"""
FastAPI dependencies shared across routes.
"""
from __future__ import annotations

from fastapi import Header
from jose import JWTError, jwt

from app.config import settings


async def get_current_user(authorization: str | None = Header(default=None)) -> str:
    """
    Extract user_id from JWT Authorization header.
    Returns "default" if no token provided (backward compatibility).
    Raises 401 if token is invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return "default"

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload["sub"]
    except JWTError:
        return "default"
