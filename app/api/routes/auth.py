"""
Google OAuth2 authentication routes.

Flow:
  1. GET /auth/google           — redirect user to Google consent screen
  2. GET /auth/google/callback  — exchange code, upsert user, redirect to
                                   frontend with JWT as ?token= query param
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from jose import jwt

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

REDIRECT_URI = f"{settings.GOOGLE_CLIENT_ID and 'https://spiritbox-api-1002281700659.asia-south1.run.app'}/auth/google/callback"


def _redirect_uri() -> str:
    # Use production URL if client ID is set, otherwise localhost
    base = (
        "https://spiritbox-api-1002281700659.asia-south1.run.app"
        if settings.GOOGLE_CLIENT_ID
        else "http://localhost:8080"
    )
    return f"{base}/auth/google/callback"


def _make_jwt(user_id: str, email: str, name: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@router.get("/google", summary="Redirect to Google OAuth2 consent screen")
async def login_google():
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/google/callback", summary="Handle Google OAuth2 callback")
async def google_callback(code: str, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            logger.error(f"Token exchange failed: {token_resp.text}")
            raise HTTPException(status_code=400, detail="Token exchange failed")

        tokens = token_resp.json()
        access_token = tokens["access_token"]

        # Fetch user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")

        userinfo = userinfo_resp.json()

    google_sub = userinfo["sub"]
    email = userinfo.get("email", "")
    name = userinfo.get("name", "")
    picture = userinfo.get("picture", "")

    # Upsert user in PostgreSQL
    user_id = await _upsert_user(google_sub, email, name, picture)

    # Issue JWT and redirect to frontend
    token = _make_jwt(user_id, email, name)
    frontend_url = settings.FRONTEND_URL
    return RedirectResponse(f"{frontend_url}?token={token}")


async def _upsert_user(google_sub: str, email: str, name: str, picture: str) -> str:
    """Insert or update user, return UUID string."""
    from sqlalchemy import select
    from app.db.models import User
    from app.db.session import get_session

    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.google_sub == google_sub)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                google_sub=google_sub,
                email=email,
                name=name,
                picture=picture,
            )
            session.add(user)
        else:
            user.email = email
            user.name = name
            user.picture = picture
        await session.commit()
        return str(user.id)
