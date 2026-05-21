"""Auth API — admin_token cookie management (S1 P0-22 fix).

Session 57+1 (2026-05-19) — XSS-safe admin token storage via HttpOnly cookie.

Flow:
    1. User enters admin_token in AdminTokenModal
    2. Frontend POST /api/auth/admin-token with X-Admin-Token header (one-time, verify against settings.ADMIN_TOKEN)
    3. Backend validates + sets HttpOnly cookie `admin_token` (90 day TTL)
    4. Subsequent admin ops: cookie 自动随 request 走, verify_admin_token reads cookie
    5. Logout: POST /api/auth/admin-token/clear → Set-Cookie with Max-Age=0

Reasoning:
    - localStorage.setItem("admin_token") was XSS-vulnerable — any JS XSS could read it
    - HttpOnly cookie not accessible to JS → XSS attacker can't exfiltrate token
    - Secure + SameSite=Strict additional defense (HTTPS-only + cross-site CSRF block)
    - Header path retained for back-compat (legacy frontend, curl, tests)

关联:
    - ISSUES_PENDING_REGISTRY §1 S1 P0-22 closure
    - audit/V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md P0-22 security finding
    - backend/app/core/auth.py verify_admin_token (本 PR 同步增 cookie source)
"""

from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response

from app.config import settings
from app.core.auth import verify_admin_token

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Cookie config — sustained reasonable security defaults
_COOKIE_NAME = "admin_token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 90  # 90 days
_COOKIE_PATH = "/"
_COOKIE_SAMESITE: str = "strict"
# Secure flag toggled via settings.COOKIE_SECURE_FLAG (SSOT, 铁律 34).
# Dev HTTP localhost: false. Production HTTPS: true via .env override.
# Startup guard (config.py): EXECUTION_MODE=live && !COOKIE_SECURE_FLAG → RuntimeError.


def _cookie_secure_enabled() -> bool:
    """Read COOKIE_SECURE_FLAG from settings (铁律 34 SSOT, code-reviewer P1.2).
    Dev HTTP localhost: false. Production HTTPS: true via .env override.
    """
    return settings.COOKIE_SECURE_FLAG


@router.post("/admin-token", summary="Set admin_token HttpOnly cookie (S1 P0-22)")
async def set_admin_token_cookie(
    response: Response,
    x_admin_token: str = Header(alias="X-Admin-Token", default=""),
) -> dict[str, str]:
    """Validate X-Admin-Token header + set HttpOnly cookie for subsequent requests.

    Frontend flow (post-S1):
        1. User enters token in AdminTokenModal
        2. Frontend axios POST /api/auth/admin-token with X-Admin-Token header
        3. Backend verifies + Set-Cookie: admin_token=<token>; HttpOnly; Secure (prod); SameSite=Strict
        4. Browser stores cookie, sends automatically with future requests
        5. Frontend never stores token in localStorage/sessionStorage (XSS-safe)

    Args:
        response: FastAPI Response to set Set-Cookie header
        x_admin_token: token to validate against settings.ADMIN_TOKEN

    Returns:
        {"status": "ok", "cookie_set": "admin_token"}
    """
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN未配置")
    if not x_admin_token:
        raise HTTPException(status_code=400, detail="缺少 X-Admin-Token header")
    if not secrets.compare_digest(x_admin_token, settings.ADMIN_TOKEN):
        # Same wording as verify_admin_token for consistent client error parsing
        raise HTTPException(status_code=401, detail="无效的Admin Token (header)")

    response.set_cookie(
        key=_COOKIE_NAME,
        value=x_admin_token,
        max_age=_COOKIE_MAX_AGE,
        path=_COOKIE_PATH,
        httponly=True,
        secure=_cookie_secure_enabled(),
        samesite=_COOKIE_SAMESITE,
    )
    logger.info(
        "admin_token cookie set",
        ttl_seconds=_COOKIE_MAX_AGE,
        secure=_cookie_secure_enabled(),
    )
    return {"status": "ok", "cookie_set": _COOKIE_NAME}


@router.post("/admin-token/clear", summary="Clear admin_token cookie (logout)")
async def clear_admin_token_cookie(
    response: Response,
    _: None = Depends(verify_admin_token),
) -> dict[str, str]:
    """Delete admin_token cookie (logout / token rotate).

    P1-3 fix (security-reviewer, Session 57+1 2026-05-19): require valid cookie/header
    before clearing — prevents CSRF forced-logout DoS from cross-site navigation
    POST (SameSite=Strict blocks cross-site cookies but not all cross-origin POSTs).

    Returns:
        {"status": "ok", "cookie_cleared": "admin_token"}
    """
    response.delete_cookie(
        key=_COOKIE_NAME,
        path=_COOKIE_PATH,
        httponly=True,
        secure=_cookie_secure_enabled(),
        samesite=_COOKIE_SAMESITE,
    )
    logger.info("admin_token cookie cleared")
    return {"status": "ok", "cookie_cleared": _COOKIE_NAME}


@router.get("/admin-token/status", summary="Check admin_token cookie presence (no value leak)")
async def get_admin_token_status(
    admin_token_cookie: str = Cookie(alias=_COOKIE_NAME, default=""),
) -> dict[str, bool | str]:
    """Returns whether admin_token cookie is set + valid (no value leaked to JS).

    Useful for frontend to determine "logged in" state without storing token in JS.
    """
    if not admin_token_cookie:
        return {"cookie_present": False, "valid": False, "source": "none"}
    valid = bool(
        settings.ADMIN_TOKEN and secrets.compare_digest(admin_token_cookie, settings.ADMIN_TOKEN)
    )
    return {"cookie_present": True, "valid": valid, "source": "cookie"}
