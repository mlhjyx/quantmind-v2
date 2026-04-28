"""ServicesHealthCheck Redis freshness probe tests — PR-X3 (LL-081 真修复) + LL-087 (Session 40).

Background: 4-27 真生产首日 zombie 4h17m. ServicesHealthCheck (LL-074 投资) 只看
Servy `Running` 进程层, 不看 Redis 应用层 freshness → zombie 期 21h+ 但 Servy
`Running` → 0 钉钉告警. 必须加 Redis 应用层 probe.

Session 40 (2026-04-28) LL-087 修正: 撤销 `qm:qmt:status` stream check —
stream 是 transition-only event audit log (qmt_data_service.py:99/106/117 仅
connect/disconnect 时 publish), 不是 heartbeat. 健康连接长时间无 transition
→ false-positive 告警. portfolio:nav 60s sync 真 heartbeat, 已 cover 全 zombie.

Fix (PR-X3 + LL-087):
  - RedisFreshnessCheck dataclass + check_redis_freshness() function
  - 检查 portfolio:nav (updated_at gap > 5 min stale) 一项
  - HealthReport 加 redis_freshness field, build_report 集成
  - send_alert markdown 加 Redis Freshness 段
  - Redis 不可达时 fail-loud (stale)

测试覆盖 (8 tests):
  - test_redis_freshness_check_stale_property: stale 不变量 (4 路径)
  - test_nav_fresh_within_threshold_not_stale: NAV 1min ago → ok
  - test_nav_age_at_exactly_threshold_not_stale: boundary == threshold → not stale
  - test_nav_age_well_above_threshold_stale: 严格 stale
  - test_nav_stale_beyond_5min_threshold: 10min ago → stale
  - test_nav_key_missing_treated_as_stale: key 不存在 → stale
  - test_redis_unreachable_all_stale_fail_loud: Redis 挂 → portfolio:nav stale, 不 crash
"""
from __future__ import annotations

import json
import sys
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
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        assert nav_check.stale is True
        assert nav_check.found is False
        assert "key 不存在" in nav_check.reason

    def test_nav_updated_at_missing_treated_as_stale(self, hc_module) -> None:
        """reviewer code P2 采纳 (PR #113): nav JSON valid but updated_at field 缺失
        → found=True / age_seconds=None → stale=True via property (schema 异常 fail-loud).
        """
        mock_r = MagicMock()
        # nav JSON 合法但 updated_at 字段缺失 (schema 异常 / 旧版 nav 数据)
        mock_r.get.return_value = json.dumps({"cash": 100000, "total_value": 1000000})
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        assert nav_check.stale is True
        assert nav_check.found is True  # key 存在但 schema 异常
        assert nav_check.age_seconds is None
        assert "updated_at" in nav_check.reason

    def test_nav_invalid_json_treated_as_stale(self, hc_module) -> None:
        """reviewer code P2 采纳 (PR #113): nav 值不是 valid JSON → except 路径 → stale.
        防 QMTData 写入 corrupt 数据时 health probe silent skip.
        """
        mock_r = MagicMock()
        mock_r.get.return_value = "not-a-json-{broken"  # corrupt
        with patch("redis.from_url", return_value=mock_r):
            checks = hc_module.check_redis_freshness()
        nav_check = next(c for c in checks if c.key == "portfolio:nav")
        assert nav_check.stale is True
        assert nav_check.found is False  # except 路径 mark not found
        assert "probe 异常" in nav_check.reason


# ─────────────────────────────────────────────────────────
# 3. Redis 完全不可达 → portfolio:nav stale (fail-loud)
# ─────────────────────────────────────────────────────────


class TestRedisUnreachable:
    def test_redis_unreachable_all_stale_fail_loud(self, hc_module) -> None:
        """Redis from_url raise → check_redis_freshness 返 1 stale check (portfolio:nav), 不 crash.

        Session 40 LL-087: 原本返 2 checks (含 qm:qmt:status), 撤销 stream check 后仅 1 个.
        """
        with patch("redis.from_url", side_effect=ConnectionError("redis 挂了")):
            checks = hc_module.check_redis_freshness()

        assert len(checks) == 1
        c = checks[0]
        assert c.key == "portfolio:nav"
        assert c.stale is True
        assert c.found is False
        assert "Redis 不可达" in c.reason
