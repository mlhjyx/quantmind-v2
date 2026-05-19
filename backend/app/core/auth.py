"""共享 admin auth dependency — 单一来源, 防 DRY 违规.

S1 P0-22 fix (Session 57+1, 2026-05-19) — admin_token httpOnly cookie 支持:
- verify_admin_token 现支持 2 token source: HttpOnly cookie `admin_token` (preferred)
  OR `X-Admin-Token` header (legacy fallback)
- Cookie path 反 XSS: 浏览器 JS 不可读 HttpOnly cookie, 反 localStorage 攻击向量
- Header path 留 back-compat: legacy frontend / curl / api test 仍可用
- Timing attack fix: secrets.compare_digest sustained constant-time compare

历史 (沿用 prior batch sediment):
- 2026-04-30 治理债清理 batch 1.7: 提取 3-copy verify_admin_token 到本模块 SSOT
- D2.2 Finding P2 timing attack — 本 PR fix (secrets.compare_digest)
- execution_ops.py 仍有 local _verify_admin_token (留 Phase I cleanup follow-up)

return None (而非 token 值): 沿用旧体例, 不向 endpoint 泄 secret 值.
endpoint signature 用 `_: None = Depends(verify_admin_token)` 显式 discard.
"""

from __future__ import annotations

import secrets

from fastapi import Cookie, Header, HTTPException

from app.config import settings


def verify_admin_token(
    x_admin_token: str = Header(alias="X-Admin-Token", default=""),
    admin_token_cookie: str = Cookie(alias="admin_token", default=""),
) -> None:
    """验证 admin token via HttpOnly cookie (preferred) OR X-Admin-Token header (legacy).

    Source priority:
        1. HttpOnly cookie `admin_token` (XSS-safe, set via POST /api/auth/admin-token)
        2. `X-Admin-Token` header (back-compat, legacy frontend / curl / test path)

    Both compared via secrets.compare_digest (constant-time, 反 timing attack).

    Raises:
        HTTPException 500: settings.ADMIN_TOKEN 未配置 (生产前置必须配)
        HTTPException 401: token 不匹配 OR 完全缺失
    """
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN未配置")

    expected = settings.ADMIN_TOKEN
    # Cookie wins if present (preferred, XSS-safe)
    if admin_token_cookie:
        if secrets.compare_digest(admin_token_cookie, expected):
            return
        raise HTTPException(status_code=401, detail="无效的Admin Token (cookie)")
    # Fallback: header path (legacy)
    if x_admin_token:
        if secrets.compare_digest(x_admin_token, expected):
            return
        raise HTTPException(status_code=401, detail="无效的Admin Token (header)")
    # Neither provided
    raise HTTPException(status_code=401, detail="缺少 admin_token (cookie 或 X-Admin-Token header)")
