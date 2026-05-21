"""S3 LLM rate-limit middleware — Session 58 round-2 close (ISSUES_PENDING_REGISTRY §1 S3).

Per-IP token-bucket rate limit for LLM cost-bearing endpoints (e.g. POST /agent/chat).
反 unauthenticated cost sink IF auth fails OR AI_ASSIST_ENABLED=true with abusive user.

设计原则:
- **In-memory** (no Redis dep): single FastAPI process / per-worker bucket. Sufficient
  for single-operator dev environment. Multi-worker / horizontal scale 需 upgrade
  to Redis-backed (留 future P4 SSE + scale-out).
- **Token-bucket**: refill rate = max_per_min / 60 per second, burst capacity = max_per_min.
- **Per (IP, endpoint_key)**: 不同 endpoint 独立桶, 反 cross-endpoint starvation.
- **Cleanup**: stale entries (no hit > 10 min) purged on next request (反 unbounded growth).

铁律 backref:
- 33: fail-loud at boundary — 429 Too Many Requests + Retry-After header
- 34: settings SSOT for max_per_min / burst capacity
- 35: rate-limit middleware 非 secret, settings as-is

关联:
- LL-188 (Session 58 round-1): defense-in-depth for AI_ASSIST_ENABLED=true cost concern
- F-S7-001 closure (commit 23ebea5): LLM cost tracking 真值 now in place — rate-limit
  is short-window defense complementing monthly budget guard (BudgetGuard).
- backend/app/api/agent.py post_chat — primary protected endpoint
- backend/qm_platform/llm/budget.py BudgetGuard — monthly cap (long-window)
- backend/app/config.py LLM_BUDGET_* settings — monthly $50/80%/100% thresholds
"""

from __future__ import annotations

import time
from threading import Lock
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

from app.config import settings

if TYPE_CHECKING:
    pass


class _TokenBucket:
    """Single token bucket with refill semantics.

    Args:
        capacity: max tokens (burst limit).
        refill_per_sec: tokens added per second (sustained rate).
    """

    __slots__ = ("capacity", "refill_per_sec", "tokens", "last_refill", "_lock")

    def __init__(self, capacity: float, refill_per_sec: float):
        self.capacity = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self.tokens: float = self.capacity
        self.last_refill = time.monotonic()
        self._lock = Lock()

    def take(self, cost: float = 1.0) -> tuple[bool, float]:
        """Attempt to consume `cost` tokens.

        Returns:
            (allowed, retry_after_seconds). retry_after_seconds = 0 if allowed,
            else seconds until enough tokens to retry.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
            self.last_refill = now

            if self.tokens >= cost:
                self.tokens -= cost
                return True, 0.0

            deficit = cost - self.tokens
            retry_after = deficit / self.refill_per_sec
            return False, retry_after


class RateLimiter:
    """Per-(IP, endpoint) token-bucket rate limiter.

    Single instance per process; thread-safe via per-bucket Lock.
    Cleanup of stale buckets on each new bucket creation (反 unbounded growth).
    """

    # Bucket inactivity TTL — older than this triggers cleanup pass
    _CLEANUP_AFTER_SEC: float = 600.0  # 10 min

    def __init__(self):
        self._buckets: dict[tuple[str, str], _TokenBucket] = {}
        self._last_seen: dict[tuple[str, str], float] = {}
        self._global_lock = Lock()

    def _maybe_cleanup(self, now: float) -> None:
        """Purge stale entries (called when adding new bucket)."""
        stale_keys = [k for k, ts in self._last_seen.items() if now - ts > self._CLEANUP_AFTER_SEC]
        for k in stale_keys:
            self._buckets.pop(k, None)
            self._last_seen.pop(k, None)

    def check(
        self,
        key_ip: str,
        endpoint: str,
        *,
        max_per_min: int,
        burst: int | None = None,
    ) -> None:
        """Raise HTTPException 429 if rate-limited, else return None.

        Args:
            key_ip: client IP (or proxy header).
            endpoint: endpoint identifier (e.g. "agent_chat").
            max_per_min: sustained rate (token refill = N/60 per second).
            burst: max burst capacity (default = max_per_min).

        Raises:
            HTTPException 429: with Retry-After header (seconds until refill enough).
        """
        if burst is None:
            burst = max_per_min

        key = (key_ip, endpoint)
        now = time.monotonic()

        with self._global_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._maybe_cleanup(now)
                bucket = _TokenBucket(
                    capacity=float(burst),
                    refill_per_sec=float(max_per_min) / 60.0,
                )
                self._buckets[key] = bucket
            self._last_seen[key] = now

        allowed, retry_after = bucket.take(1.0)
        if not allowed:
            # 反 silent throttle: explicit 429 + Retry-After (铁律 33 at boundary).
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit exceeded for {endpoint} (max {max_per_min}/min per IP). "
                    f"Retry after {retry_after:.1f}s. 反 LLM cost abuse / DoS."
                ),
                headers={"Retry-After": str(max(1, int(retry_after + 1)))},
            )


# Module-level singleton (single FastAPI worker scope).
# Multi-worker deployment: each worker has independent buckets — acceptable for
# single-operator dev (true rate limit ≈ N_workers × max_per_min). Multi-tenant
# production: upgrade to Redis-backed (反 unbounded multi-worker burst).
_limiter = RateLimiter()


def _extract_client_ip(request: Request) -> str:
    """Extract client IP from request, honoring X-Forwarded-For if behind proxy.

    Single-trust-hop: X-Forwarded-For first IP. Multi-hop reverse proxy chain
    sustained future enhancement (real production behind nginx/cloudflare).
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # First IP in chain (client). Strip whitespace.
        return fwd.split(",")[0].strip()
    if request.client is None:
        # Unit test / unusual transport
        return "unknown"
    return request.client.host


def rate_limit_chat(request: Request) -> None:
    """FastAPI dependency — rate-limit /agent/chat per IP.

    Default 10/min per IP (settings.LLM_CHAT_RATE_LIMIT_PER_MIN), burst = max.
    Raises HTTPException 429 if exceeded (with Retry-After header).

    Usage (in router):
        @router.post("/chat", ...)
        async def post_chat(req: ChatRequest, _rl: None = Depends(rate_limit_chat), ...):
            ...
    """
    client_ip = _extract_client_ip(request)
    _limiter.check(
        key_ip=client_ip,
        endpoint="agent_chat",
        max_per_min=settings.LLM_CHAT_RATE_LIMIT_PER_MIN,
    )


__all__ = ["rate_limit_chat", "RateLimiter"]
