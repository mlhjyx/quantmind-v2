"""QMTFallbackTriggeredRule unit tests (T0-15 LL-081 v2).

批 2 P0 修 (2026-04-30) Commit 4.

Coverage:
- cache 0 keys → 1 RuleResult (P0 alert_only)
- cache > 0 keys → [] (no trigger)
- cache 1 key → no trigger (boundary)
- metrics 字段完整性
- rule_id / severity / action 契约
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from backend.qm_platform._types import Severity
from backend.qm_platform.risk.interface import RiskContext
from backend.qm_platform.risk.rules.qmt_fallback import (
    QMTFallbackTriggeredRule,
    RedisCacheHealthReader,
)


def _make_context(
    *, positions_count: int = 0, nav: float = 993520.16
) -> RiskContext:
    """构造 RiskContext (沿用 intraday.py 测试 pattern)."""
    return RiskContext(
        strategy_id="test-strategy",
        execution_mode="live",
        timestamp=datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc),
        positions=[{"code": f"00000{i}.SZ", "qty": 100} for i in range(positions_count)],
        portfolio_nav=nav,
        prev_close_nav=nav,
    )


def test_rule_contract_immutable():
    """rule_id / severity / action 契约不变."""
    reader = MagicMock(spec=RedisCacheHealthReader)
    reader.get_portfolio_cache_key_count.return_value = 0
    rule = QMTFallbackTriggeredRule(cache_reader=reader)

    assert rule.rule_id == "ll081_qmt_fallback_triggered"
    assert rule.severity == Severity.P0
    assert rule.action == "alert_only"


def test_cache_0_keys_triggers_p0_alert():
    """portfolio:current 0 keys → 1 RuleResult (LL-081 v2 fallback 触发)."""
    reader = MagicMock(spec=RedisCacheHealthReader)
    reader.get_portfolio_cache_key_count.return_value = 0
    rule = QMTFallbackTriggeredRule(cache_reader=reader)
    ctx = _make_context(positions_count=0, nav=993520.16)

    results = rule.evaluate(ctx)

    assert len(results) == 1
    r = results[0]
    assert r.rule_id == "ll081_qmt_fallback_triggered"
    assert r.code == ""
    assert r.shares == 0
    assert "portfolio:current" in r.reason
    assert "T0-15" in r.reason
    assert r.metrics["portfolio_cache_key_count"] == 0
    assert r.metrics["portfolio_nav_at_check"] == 993520.16


def test_cache_positive_keys_no_trigger():
    """portfolio:current > 0 keys → [] (qmt_data_service 正常 sync)."""
    reader = MagicMock(spec=RedisCacheHealthReader)
    reader.get_portfolio_cache_key_count.return_value = 19
    rule = QMTFallbackTriggeredRule(cache_reader=reader)
    ctx = _make_context()

    assert rule.evaluate(ctx) == []


def test_cache_1_key_boundary_no_trigger():
    """boundary: 1 key (最少有效 sync) → 不触发."""
    reader = MagicMock(spec=RedisCacheHealthReader)
    reader.get_portfolio_cache_key_count.return_value = 1
    rule = QMTFallbackTriggeredRule(cache_reader=reader)

    assert rule.evaluate(_make_context()) == []


def test_metrics_includes_positions_count_and_nav():
    """metrics 含 context positions count + nav (审计完整性)."""
    reader = MagicMock(spec=RedisCacheHealthReader)
    reader.get_portfolio_cache_key_count.return_value = 0
    rule = QMTFallbackTriggeredRule(cache_reader=reader)
    ctx = _make_context(positions_count=19, nav=1011714.08)

    results = rule.evaluate(ctx)

    assert len(results) == 1
    metrics = results[0].metrics
    assert metrics["positions_count_at_check"] == 19
    assert metrics["portfolio_nav_at_check"] == 1011714.08
    assert "checked_at_timestamp" in metrics


def test_reader_called_once_per_evaluate():
    """每次 evaluate 仅调用 reader 1 次 (无重复 IO)."""
    reader = MagicMock(spec=RedisCacheHealthReader)
    reader.get_portfolio_cache_key_count.return_value = 0
    rule = QMTFallbackTriggeredRule(cache_reader=reader)

    rule.evaluate(_make_context())
    rule.evaluate(_make_context())

    assert reader.get_portfolio_cache_key_count.call_count == 2
