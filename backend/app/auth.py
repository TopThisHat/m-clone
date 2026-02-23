"""
JWT-based auth helpers.
- create_jwt / decode_jwt use python-jose.
- get_current_user is a FastAPI dependency that reads the 'jwt' httpOnly cookie.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import Cookie, HTTPException, status
from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


def create_jwt(sid: str, display_name: str, email: str = "") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sid,
        "display_name": display_name,
        "email": email,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_jwt(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_current_user(jwt: str | None = Cookie(default=None, alias="jwt")) -> dict[str, Any]:
    """FastAPI dependency: reads 'jwt' cookie and returns decoded payload."""
    if not jwt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return decode_jwt(jwt)


async def get_optional_user(jwt: str | None = Cookie(default=None, alias="jwt")) -> dict[str, Any] | None:
    """Like get_current_user but returns None instead of raising 401."""
    if not jwt:
        return None
    try:
        return decode_jwt(jwt)
    except HTTPException:
        return None
