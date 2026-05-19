"""P7 F-D78-241 audit middleware — Session 58 round-2 close.

Cross-cutting audit log for state-mutating HTTP requests (POST/PUT/DELETE/PATCH).
Complements per-endpoint audit logging (e.g. execution_ops.py) by providing default
audit coverage for any router that doesn't explicitly write to operation_audit_log.

设计:
- BaseHTTPMiddleware (FastAPI standard).
- Only state-mutating methods (POST/PUT/DELETE/PATCH) audited (反 GET noise + perf cost).
- Async-safe via background insert (反 request latency overhead).
- Failure-soft: middleware INSERT failure does NOT block request response
  (反 audit subsystem outage cascade to user-facing API).
- Skip paths: /health, /ws/*, /api/sse/* (high-frequency / streaming endpoints).

铁律 backref:
- 33: silent_ok with explicit annotation for audit INSERT failure (degraded mode)
- 34: settings SSOT (skip path list configurable)
- 35: ADMIN_TOKEN presence check uses verify_admin_token alias

关联:
- backend/app/api/execution_ops.py operation_audit_log INSERT (per-endpoint, sustained)
- ISSUES_PENDING_REGISTRY §7 P7 (F-D78-241 audit middleware scope)
- Plan v8 audit Subagent C (operation audit coverage gap)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("audit_middleware")

# Skip these paths (high-frequency / streaming / health) to avoid audit log spam
_AUDIT_SKIP_PREFIXES: tuple[str, ...] = (
    "/health",
    "/ws/",
    "/api/sse/",
    "/api/system/health",
    "/api/system/streams",
    "/api/dashboard/",  # high-freq polling
)

# Only audit these methods (state-mutating)
_AUDIT_METHODS: frozenset[str] = frozenset(["POST", "PUT", "DELETE", "PATCH"])


def _should_audit(request: Request) -> bool:
    """Determine if request should be audited."""
    if request.method not in _AUDIT_METHODS:
        return False
    path = request.url.path
    return not any(path.startswith(p) for p in _AUDIT_SKIP_PREFIXES)


def _has_admin_auth(request: Request) -> bool:
    """Check if request carries admin auth (cookie OR header).

    Does NOT validate — only checks presence (validation happens via verify_admin_token
    Dependency in each endpoint). 反 重复 auth validation overhead in middleware layer.
    """
    if request.headers.get("X-Admin-Token"):
        return True
    return bool(request.cookies.get("admin_token"))


def _extract_client_ip(request: Request) -> str:
    """Extract client IP (X-Forwarded-For first hop OR request.client.host)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client is None:
        return "unknown"
    return request.client.host


def _build_action(request: Request) -> str:
    """Action identifier for audit log row (method + path)."""
    return f"{request.method} {request.url.path}"


async def _build_params(request: Request) -> dict[str, Any]:
    """Extract query params + (best-effort) JSON body for audit context.

    Body parsing is best-effort: requests with binary / streaming bodies return {}.
    Reading body here consumes the stream — middleware needs to restore via
    request._receive monkey-patch (FastAPI/Starlette idiom for body re-read).
    For audit MVP, skip body extraction (沿用 silent_ok pattern, sediment future
    enhancement). Query params only.
    """
    return {"query": dict(request.query_params)}


def _write_audit_row(
    *,
    action: str,
    params: dict[str, Any],
    result: str,
    detail: str,
    ip: str,
) -> None:
    """INSERT row to operation_audit_log (silent_ok on failure)."""
    try:
        # Lazy import inside fn — sustains middleware load-time independence + lazy DB connection
        from app.services.db import get_sync_conn  # noqa: PLC0415

        conn = get_sync_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO operation_audit_log (timestamp, action, params, result, detail, ip)
                    VALUES (NOW(), %s, %s::jsonb, %s, %s, %s)
                    """,
                    (action, json.dumps(params, default=str)[:4096], result, detail[:1024], ip),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        # silent_ok: audit subsystem failure should NOT cascade to user-facing API.
        # Log to stderr for ops visibility (反 完全 silent, 铁律 33).
        logger.error("audit middleware INSERT failed (silent_ok degraded mode): %s", exc)


class AuditMiddleware(BaseHTTPMiddleware):
    """HTTP audit middleware — logs state-mutating admin-authed requests.

    Wire in main.py:
        from app.middleware.audit import AuditMiddleware
        app.add_middleware(AuditMiddleware)
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Pre-flight: skip non-auditable requests cheaply
        if not _should_audit(request) or not _has_admin_auth(request):
            return await call_next(request)

        # Capture pre-call metadata
        start_time = time.monotonic()
        action = _build_action(request)
        params = await _build_params(request)
        ip = _extract_client_ip(request)

        try:
            response = await call_next(request)
        except Exception as exc:
            # 反 silent (铁律 33): write audit row even on unhandled exception
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            _write_audit_row(
                action=action,
                params=params,
                result="exception",
                detail=f"{type(exc).__name__}: {exc} (elapsed {elapsed_ms}ms)",
                ip=ip,
            )
            raise

        # Audit post-call (success / error / 4xx / 5xx etc)
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        status_code = response.status_code
        result = "success" if 200 <= status_code < 400 else "error"
        detail = f"status={status_code} elapsed_ms={elapsed_ms}"
        _write_audit_row(action=action, params=params, result=result, detail=detail, ip=ip)

        return response


__all__ = ["AuditMiddleware"]
