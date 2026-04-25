"""MVP 2.1a CacheCoherencyPolicy + MaxDateChecker + TTLGuard + check_stale 单测."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from backend.qm_platform.data.cache_coherency import (
    CacheCoherencyPolicy,
    MaxDateChecker,
    TTLGuard,
    check_stale,
)

# ---------- CacheCoherencyPolicy ----------


def test_policy_defaults() -> None:
    p = CacheCoherencyPolicy()
    assert p.db_max_date_check is True
    assert p.ttl_seconds == 86400
    assert p.content_hash_check is False
    assert p.invalidate_on_write is False


def test_policy_negative_ttl_raises() -> None:
    with pytest.raises(ValueError, match="ttl_seconds 不得为负"):
        CacheCoherencyPolicy(ttl_seconds=-1)


def test_policy_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    p = CacheCoherencyPolicy()
    with pytest.raises(FrozenInstanceError):
        p.ttl_seconds = 100  # type: ignore[misc]


# ---------- MaxDateChecker ----------


def test_max_date_db_ahead_is_stale() -> None:
    p = CacheCoherencyPolicy()
    checker = MaxDateChecker()
    assert checker.is_stale(
        db_max=date(2026, 4, 17),
        cache_max=date(2026, 4, 10),
        policy=p,
    ) is True


def test_max_date_equal_is_fresh() -> None:
    p = CacheCoherencyPolicy()
    checker = MaxDateChecker()
    assert checker.is_stale(
        db_max=date(2026, 4, 17),
        cache_max=date(2026, 4, 17),
        policy=p,
    ) is False


def test_max_date_cache_none_is_stale() -> None:
    """cache 空 (未写过) → stale, 需初次 refill."""
    p = CacheCoherencyPolicy()
    checker = MaxDateChecker()
    assert checker.is_stale(
        db_max=date(2026, 4, 17),
        cache_max=None,
        policy=p,
    ) is True


def test_max_date_db_none_cache_empty_is_fresh() -> None:
    """DB 无数据 & cache 也空 — 都是空, 视为一致."""
    p = CacheCoherencyPolicy()
    checker = MaxDateChecker()
    assert checker.is_stale(db_max=None, cache_max=None, policy=p) is False


def test_max_date_db_none_cache_has_data_is_stale() -> None:
    """DB 无数据但 cache 有数据 → stale (安全策略)."""
    p = CacheCoherencyPolicy()
    checker = MaxDateChecker()
    assert checker.is_stale(
        db_max=None,
        cache_max=date(2026, 4, 10),
        policy=p,
    ) is True


def test_max_date_check_disabled_never_stale() -> None:
    """policy.db_max_date_check=False → 永远 fresh (离线场景)."""
    p = CacheCoherencyPolicy(db_max_date_check=False)
    checker = MaxDateChecker()
    assert checker.is_stale(
        db_max=date(2026, 4, 17),
        cache_max=date(2026, 4, 10),
        policy=p,
    ) is False


# ---------- TTLGuard ----------


def test_ttl_within_window_not_expired() -> None:
    p = CacheCoherencyPolicy(ttl_seconds=86400)
    guard = TTLGuard()
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=UTC)
    written_at = now - timedelta(hours=12)
    assert guard.is_expired(written_at, p, now=now) is False


def test_ttl_beyond_window_expired() -> None:
    p = CacheCoherencyPolicy(ttl_seconds=86400)
    guard = TTLGuard()
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=UTC)
    written_at = now - timedelta(hours=25)
    assert guard.is_expired(written_at, p, now=now) is True


def test_ttl_custom_seconds() -> None:
    p = CacheCoherencyPolicy(ttl_seconds=3600)  # 1h
    guard = TTLGuard()
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=UTC)
    assert guard.is_expired(now - timedelta(minutes=30), p, now=now) is False
    assert guard.is_expired(now - timedelta(minutes=70), p, now=now) is True


def test_ttl_zero_disables_guard() -> None:
    """ttl_seconds=0 → 禁用 TTL, 永不过期."""
    p = CacheCoherencyPolicy(ttl_seconds=0)
    guard = TTLGuard()
    very_old = datetime(2000, 1, 1, tzinfo=UTC)
    assert guard.is_expired(very_old, p) is False


def test_ttl_naive_datetime_raises() -> None:
    """铁律 41: timezone 必须 aware."""
    p = CacheCoherencyPolicy()
    guard = TTLGuard()
    naive = datetime(2026, 4, 17, 12, 0, 0)  # 无 tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        guard.is_expired(naive, p)


def test_ttl_non_utc_timezone_works() -> None:
    """任意 tz-aware datetime 都可, 不强制 UTC."""
    p = CacheCoherencyPolicy(ttl_seconds=3600)
    guard = TTLGuard()
    cst = timezone(timedelta(hours=8))
    now = datetime(2026, 4, 17, 20, 0, 0, tzinfo=cst)
    written_at = now - timedelta(minutes=30)
    assert guard.is_expired(written_at, p, now=now) is False


# ---------- check_stale (组合) ----------


def test_check_stale_fresh_returns_none() -> None:
    p = CacheCoherencyPolicy()
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=UTC)
    reason = check_stale(
        db_max=date(2026, 4, 17),
        cache_max=date(2026, 4, 17),
        cache_written_at=now - timedelta(hours=1),
        policy=p,
        now=now,
    )
    assert reason is None


def test_check_stale_detects_db_ahead() -> None:
    p = CacheCoherencyPolicy()
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=UTC)
    reason = check_stale(
        db_max=date(2026, 4, 17),
        cache_max=date(2026, 4, 10),  # 7 天前
        cache_written_at=now - timedelta(hours=1),
        policy=p,
        now=now,
    )
    assert reason == "db_max_ahead"


def test_check_stale_detects_ttl_expired_when_db_matches() -> None:
    """DB max_date 匹配 cache 但 TTL 过期 → ttl_expired (保守策略)."""
    p = CacheCoherencyPolicy(ttl_seconds=3600)
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=UTC)
    reason = check_stale(
        db_max=date(2026, 4, 17),
        cache_max=date(2026, 4, 17),
        cache_written_at=now - timedelta(hours=2),  # 2h > 1h TTL
        policy=p,
        now=now,
    )
    assert reason == "ttl_expired"


def test_check_stale_cache_empty_returns_reason() -> None:
    p = CacheCoherencyPolicy()
    reason = check_stale(
        db_max=date(2026, 4, 17),
        cache_max=None,
        cache_written_at=None,
        policy=p,
    )
    assert reason == "cache_empty"
