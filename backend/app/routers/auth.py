"""
Auth router: OIDC flow, dev-bypass, /me, /logout.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.auth import create_jwt
from app.config import settings
from app.db import DatabaseNotConfigured, db_upsert_user, db_get_user, db_update_user_theme, db_is_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "jwt"
COOKIE_MAX_AGE = 60 * 60 * 24  # 24h


def _set_jwt_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


# ── /me ───────────────────────────────────────────────────────────────────────

@router.get("/me")
async def me(request: Request):
    """Return current user info from JWT cookie, or 401."""
    jwt_cookie = request.cookies.get("jwt")
    if not jwt_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    from app.auth import decode_jwt
    payload = decode_jwt(jwt_cookie)
    sid = payload["sub"]

    # Try to fetch theme + super admin from DB; fall back to JWT data if DB unavailable
    theme = "dark"
    is_sa = False
    try:
        user_row = await db_get_user(sid)
        if user_row:
            theme = user_row.get("theme") or "dark"
        is_sa = await db_is_super_admin(sid)
    except DatabaseNotConfigured:
        pass

    return {
        "sid": sid,
        "display_name": payload.get("display_name", ""),
        "email": payload.get("email", ""),
        "theme": theme,
        "is_super_admin": is_sa,
    }


class PreferencesBody(BaseModel):
    theme: str


@router.patch("/preferences")
async def update_preferences(body: PreferencesBody, request: Request):
    """Update user preferences (theme). Requires auth."""
    jwt_cookie = request.cookies.get("jwt")
    if not jwt_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    from app.auth import decode_jwt
    payload = decode_jwt(jwt_cookie)
    sid = payload["sub"]

    if body.theme not in ("dark", "light"):
        raise HTTPException(status_code=400, detail="theme must be 'dark' or 'light'")

    try:
        await db_update_user_theme(sid, body.theme)
    except DatabaseNotConfigured:
        pass  # Silently ignore if DB not configured

    return {"ok": True}


# ── Dev bypass ────────────────────────────────────────────────────────────────

class DevLoginBody(BaseModel):
    sid: str
    display_name: str
    email: str = ""


@router.post("/dev-login")
async def dev_login(body: DevLoginBody):
    """Dev-only: set JWT cookie without SSO. Only works if DEV_AUTH_BYPASS=true."""
    if not settings.dev_auth_bypass:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dev auth bypass is disabled")

    try:
        await db_upsert_user(body.sid, body.display_name, body.email)
    except DatabaseNotConfigured:
        pass  # OK to continue without DB in dev mode

    token = create_jwt(body.sid, body.display_name, body.email)
    response = Response(content='{"ok": true}', media_type="application/json")
    _set_jwt_cookie(response, token)
    return response


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout():
    response = Response(content='{"ok": true}', media_type="application/json")
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


# ── OIDC login ────────────────────────────────────────────────────────────────

@router.get("/login")
async def oidc_login(request: Request):
    """Redirect to OIDC provider. Returns 501 if OIDC_ISSUER not configured."""
    if not settings.oidc_issuer:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OIDC not configured")

    try:
        from authlib.integrations.starlette_client import OAuth
        from itsdangerous import URLSafeTimedSerializer
        import secrets

        oauth = OAuth()
        oauth.register(
            name="oidc",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=f"{settings.oidc_issuer}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email"},
        )

        state = secrets.token_urlsafe(16)
        s = URLSafeTimedSerializer(settings.jwt_secret)
        signed_state = s.dumps(state)

        redirect_uri = f"{settings.app_base_url}/api/auth/callback"
        auth_url, _ = await oauth.oidc.create_authorization_url(redirect_uri, state=state)

        response = RedirectResponse(auth_url)
        response.set_cookie("oidc_state", signed_state, httponly=True, samesite="lax", max_age=600)
        return response
    except Exception:
        logger.exception("OIDC login failed")
        raise HTTPException(status_code=500, detail="OIDC login failed")


# ── OIDC callback ─────────────────────────────────────────────────────────────

@router.get("/callback")
async def oidc_callback(request: Request, code: str, state: str):
    """Exchange OIDC code for token, upsert user, set JWT cookie."""
    if not settings.oidc_issuer:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OIDC not configured")

    try:
        from authlib.integrations.starlette_client import OAuth
        from itsdangerous import URLSafeTimedSerializer, BadSignature

        # Verify state
        signed_state = request.cookies.get("oidc_state", "")
        s = URLSafeTimedSerializer(settings.jwt_secret)
        try:
            expected_state = s.loads(signed_state, max_age=600)
        except (BadSignature, Exception):
            raise HTTPException(status_code=400, detail="Invalid state")

        if expected_state != state:
            raise HTTPException(status_code=400, detail="State mismatch")

        oauth = OAuth()
        oauth.register(
            name="oidc",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=f"{settings.oidc_issuer}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email"},
        )

        redirect_uri = f"{settings.app_base_url}/api/auth/callback"
        token = await oauth.oidc.authorize_access_token(request)
        userinfo = token.get("userinfo") or await oauth.oidc.userinfo(token=token)

        sid = userinfo.get("sub", "")
        display_name = userinfo.get("name", userinfo.get("preferred_username", sid))
        email = userinfo.get("email", "")

        try:
            await db_upsert_user(sid, display_name, email)
        except DatabaseNotConfigured:
            pass

        jwt_token = create_jwt(sid, display_name, email)
        response = RedirectResponse(url="/")
        _set_jwt_cookie(response, jwt_token)
        response.delete_cookie("oidc_state", path="/")
        return response

    except HTTPException:
        raise
    except Exception:
        logger.exception("OIDC callback failed")
        raise HTTPException(status_code=500, detail="OIDC callback failed")
