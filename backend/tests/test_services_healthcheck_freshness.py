"""ServicesHealthCheck Redis freshness probe tests — PR-X3 (LL-081 真修复).

Background: 4-27 真生产首日 zombie 4h17m. ServicesHealthCheck (LL-074 投资) 只看
Servy `Running` 进程层, 不看 Redis 应用层 freshness → zombie 期 21h+ stream 0 events
但 Servy `Running` → 0 钉钉告警. 必须加 Redis 应用层 probe.

Fix (PR-X3):
  - 加 RedisFreshnessCheck dataclass + check_redis_freshness() function
  - 检查 portfolio:nav (updated_at gap > 5 min stale) + qm:qmt:status stream
    (last event > 30 min stale)
  - HealthReport 加 redis_freshness field, build_report 集成
  - send_alert markdown 加 Redis Freshness 段
  - Redis 不可达时全 stale (fail-loud)

测试覆盖 (8 tests):
  - test_redis_freshness_check_stale_property: stale 不变量 (4 路径)
  - test_nav_fresh_within_threshold_not_stale: NAV 1min ago → ok
  - test_nav_stale_beyond_threshold: NAV 10min ago → stale
  - test_nav_key_missing_treated_as_stale: key 不存在 → stale
  - test_stream_fresh_event_not_stale: stream 5min ago → ok
  - test_stream_stale_event: stream 60min ago → stale (> 30min)
  - test_stream_empty_treated_as_stale: 0 events → stale
  - test_redis_unreachable_all_stale_fail_loud: Redis 挂 → 2 checks 全 stale
"""
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/ sys.path hack 跟现有 backend/tests 风格一致
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture
def hc_module():
    """import services_healthcheck module 一次, 跨测试共享."""
    import services_healthcheck  # noqa: PLC0415

    return services_healthcheck


# ─────────────────────────────────────────────────────────
# 1. RedisFreshnessCheck.stale property invariants
# ─────────────────────────────────────────────────────────


class TestRedisFreshnessCheckStaleProperty:
    def test_stale_when_not_found(self, hc_module) -> None:
        c = hc_module.RedisFreshnessCheck(
            key="any", found=False, age_seconds=10.0, threshold_seconds=300, reason="x"
        )
        assert c.stale is True

    def test_stale_when_age_none(self, hc_module) -> None:
        c = hc_module.RedisFreshnessCheck(
            key="any", found=True, age_seconds=None, threshold_seconds=300, reason="x"
        )
        assert c.stale is True

    def test_not_stale_when_age_below_threshold(self, hc_module) -> None:
        c = hc_module.RedisFreshnessCheck(
            key="any", found=True, age_seconds=100.0, threshold_seconds=300, reason="x"
        )
        assert c.stale is False

    def test_stale_when_age_exceeds_threshold(self, hc_module) -> None:
        c = hc_module.RedisFreshnessCheck(
            key="any", found=True, age_seconds=400.0, threshold_seconds=300, reason="x"
        )
        assert c.stale is True


# ─────────────────────────────────────────────────────────
# 2. portfolio:nav probe scenarios
# ─────────────────────────────────────────────────────────


class TestPortfolioNavFreshness:
    def _mock_redis_with_nav(self, age_seconds: float):
        """构造 mock Redis returning nav with updated_at = now - age."""
        ts = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
        nav = {"cash": 100000, "total_value": 1000000, "updated_at": ts}
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps(nav)
        mock_r.xrevrange.return_value = []  # 不影响本测试
        return mock_r

    def test_nav_fresh_1min_ago_not_stale(self, hc_module) -> None:
        mock_r = self._mock_redis_with_nav(60.0)
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        assert nav_check.stale is False
        assert nav_check.found is True
        assert nav_check.age_seconds == pytest.approx(60.0, abs=2.0)

    def test_nav_stale_beyond_5min_threshold(self, hc_module) -> None:
        mock_r = self._mock_redis_with_nav(600.0)  # 10 min ago
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        assert nav_check.stale is True
        assert "STALE" in nav_check.reason

    def test_nav_key_missing_treated_as_stale(self, hc_module) -> None:
        mock_r = MagicMock()
        mock_r.get.return_value = None  # key 不存在
        mock_r.xrevrange.return_value = []
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        assert nav_check.stale is True
        assert nav_check.found is False
        assert "key 不存在" in nav_check.reason


# ─────────────────────────────────────────────────────────
# 3. qm:qmt:status stream probe scenarios
# ─────────────────────────────────────────────────────────


class TestQmtStatusStreamFreshness:
    def _mock_redis_with_stream_event(self, age_seconds: float):
        """构造 mock Redis returning xrevrange with event_id ms = now - age."""
        ms = int((time.time() - age_seconds) * 1000)
        event = [(f"{ms}-0", {"status": "connected"})]
        mock_r = MagicMock()
        mock_r.get.return_value = None  # 不影响本测试
        mock_r.xrevrange.return_value = event
        return mock_r

    def test_stream_fresh_5min_ago_not_stale(self, hc_module) -> None:
        mock_r = self._mock_redis_with_stream_event(300.0)  # 5 min ago
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        stream_check = next(c for c in checks if c.key == "qm:qmt:status")
        assert stream_check.stale is False
        assert stream_check.found is True

    def test_stream_stale_beyond_30min(self, hc_module) -> None:
        mock_r = self._mock_redis_with_stream_event(3600.0)  # 60 min ago
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        stream_check = next(c for c in checks if c.key == "qm:qmt:status")
        assert stream_check.stale is True
        assert "STALE" in stream_check.reason

    def test_stream_empty_treated_as_stale(self, hc_module) -> None:
        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_r.xrevrange.return_value = []  # stream 空
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        stream_check = next(c for c in checks if c.key == "qm:qmt:status")
        assert stream_check.stale is True
        assert stream_check.found is False
        assert "stream 空" in stream_check.reason


# ─────────────────────────────────────────────────────────
# 4. Redis 完全不可达 → 全 stale (fail-loud)
# ─────────────────────────────────────────────────────────


class TestRedisUnreachable:
    def test_redis_unreachable_all_stale_fail_loud(self, hc_module) -> None:
        """Redis from_url raise → check_redis_freshness 返 2 stale check, 不 crash."""
        with patch("redis.from_url", side_effect=ConnectionError("redis 挂了")):
            checks = hc_module.check_redis_freshness()

        assert len(checks) == 2
        keys = {c.key for c in checks}
        assert keys == {"portfolio:nav", "qm:qmt:status"}
        for c in checks:
            assert c.stale is True
            assert c.found is False
            assert "Redis 不可达" in c.reason
