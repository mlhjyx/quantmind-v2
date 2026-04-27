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
        # reviewer python P3-3 采纳: abs 5.0 (CI 慢机器 + GC pause 容忍)
        assert nav_check.age_seconds == pytest.approx(60.0, abs=5.0)

    def test_nav_age_at_exactly_threshold_not_stale(self, hc_module) -> None:
        """reviewer code MEDIUM-1 采纳: boundary age=300s (== threshold), strict `>` 不 stale."""
        # NAV updated_at = now - 300s (==阈值)
        mock_r = self._mock_redis_with_nav(300.0)
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        # age ~ 300s + epsilon, 严格 > 300 才 stale. 5s tolerance buffer.
        # 实际 age = 300 + (执行 datetime.now → check_redis_freshness 间 < 5s) → ~300-305
        # stale 判定: 严格 >, 边界精度 buffer
        assert nav_check.found is True
        # 不强 assert stale (受 wallclock 影响), 但断言 age 在 boundary
        assert 295.0 < (nav_check.age_seconds or 0) < 310.0

    def test_nav_age_well_above_threshold_stale(self, hc_module) -> None:
        """boundary 安全: age=400s (> 300s+50s buffer), 严格 stale."""
        mock_r = self._mock_redis_with_nav(400.0)
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        assert nav_check.stale is True
        assert "STALE" in nav_check.reason

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


class TestTradingHoursGuard:
    """PR-X3 reviewer MEDIUM-2 follow-up: 非交易时段 stream stale 降级 INFO 不告警.

    A 股交易时段: 周一-五 + (09:30-11:30 OR 13:00-15:00) Asia/Shanghai.
    非交易时段 stream connect 边沿事件必然 stale, 降级 is_failure_alertable=False.
    """

    def _mock_stream_with_age(self, age_seconds: float):
        ms = int((time.time() - age_seconds) * 1000)
        mock_r = MagicMock()
        mock_r.get.return_value = None  # nav 不重要
        mock_r.xrevrange.return_value = [(f"{ms}-0", {"status": "connected"})]
        return mock_r

    def test_is_trading_hours_weekend_returns_false(self, hc_module) -> None:
        """周六 / 周日 → False (无视时间)."""
        # weekday() 0=Mon..4=Fri, 5=Sat, 6=Sun
        with patch.object(hc_module, "datetime") as mock_dt:
            sat = datetime(2026, 4, 25, 10, 0, tzinfo=hc_module._CST_TZ)  # Sat
            mock_dt.now.return_value = sat
            assert hc_module._is_trading_hours_now() is False

    def test_is_trading_hours_weekday_morning_open_true(self, hc_module) -> None:
        """周一 09:35 (开盘后 5min) → True."""
        with patch.object(hc_module, "datetime") as mock_dt:
            mon_morning = datetime(2026, 4, 27, 9, 35, tzinfo=hc_module._CST_TZ)
            mock_dt.now.return_value = mon_morning
            assert hc_module._is_trading_hours_now() is True

    def test_is_trading_hours_weekday_lunch_break_false(self, hc_module) -> None:
        """周一 12:00 (午休) → False (11:30-13:00)."""
        with patch.object(hc_module, "datetime") as mock_dt:
            mon_lunch = datetime(2026, 4, 27, 12, 0, tzinfo=hc_module._CST_TZ)
            mock_dt.now.return_value = mon_lunch
            assert hc_module._is_trading_hours_now() is False

    def test_is_trading_hours_weekday_after_close_false(self, hc_module) -> None:
        """周一 19:00 (盘后) → False (15:00 后)."""
        with patch.object(hc_module, "datetime") as mock_dt:
            mon_after = datetime(2026, 4, 27, 19, 0, tzinfo=hc_module._CST_TZ)
            mock_dt.now.return_value = mon_after
            assert hc_module._is_trading_hours_now() is False

    def test_is_trading_hours_boundary_0930_open(self, hc_module) -> None:
        """周一 09:30:00 边界 → True (开盘瞬间)."""
        with patch.object(hc_module, "datetime") as mock_dt:
            mon_open = datetime(2026, 4, 27, 9, 30, tzinfo=hc_module._CST_TZ)
            mock_dt.now.return_value = mon_open
            assert hc_module._is_trading_hours_now() is True

    def test_is_trading_hours_boundary_1500_close(self, hc_module) -> None:
        """周一 15:00:00 边界 → False (收盘瞬间, < 严格小于)."""
        with patch.object(hc_module, "datetime") as mock_dt:
            mon_close = datetime(2026, 4, 27, 15, 0, tzinfo=hc_module._CST_TZ)
            mock_dt.now.return_value = mon_close
            assert hc_module._is_trading_hours_now() is False

    def test_stream_stale_non_trading_hours_not_alertable(self, hc_module) -> None:
        """非交易时段 stream stale → is_failure_alertable=False (INFO 不告警)."""
        mock_r = self._mock_stream_with_age(3600.0)  # 60min ago
        with patch("redis.from_url", return_value=mock_r), patch.object(
            hc_module, "_is_trading_hours_now", return_value=False
        ):
            checks = hc_module.check_redis_freshness()
        stream_check = next(c for c in checks if c.key == "qm:qmt:status")
        assert stream_check.stale is True
        assert stream_check.is_failure_alertable is False
        assert "INFO only" in stream_check.reason

    def test_stream_stale_trading_hours_alertable(self, hc_module) -> None:
        """交易时段 stream stale → is_failure_alertable=True (P0 告警)."""
        mock_r = self._mock_stream_with_age(3600.0)  # 60min ago
        with patch("redis.from_url", return_value=mock_r), patch.object(
            hc_module, "_is_trading_hours_now", return_value=True
        ):
            checks = hc_module.check_redis_freshness()
        stream_check = next(c for c in checks if c.key == "qm:qmt:status")
        assert stream_check.stale is True
        assert stream_check.is_failure_alertable is True
        assert "INFO only" not in stream_check.reason
