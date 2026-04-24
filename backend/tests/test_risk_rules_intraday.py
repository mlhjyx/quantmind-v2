"""L1 unit tests for backend/platform/risk/rules/intraday.py (MVP 3.1 批 2 PR 1).

覆盖 20 tests:
  - IntradayPortfolioDropRule 基类 skip 条件 (prev_close_nav=None / <=0 / nav<=0)
  - 3/5/8% 阈值边界 (正好触发 / 边界内 / 远超)
  - rule_id / severity / action / threshold 契约
  - QMTDisconnectRule connected/disconnected
  - RuleResult metrics schema
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from backend.platform._types import Severity
from backend.platform.risk import RiskContext
from backend.platform.risk.rules.intraday import (
    IntradayPortfolioDrop3PctRule,
    IntradayPortfolioDrop5PctRule,
    IntradayPortfolioDrop8PctRule,
    QMTConnectionReader,
    QMTDisconnectRule,
)


def _make_context(
    portfolio_nav: float = 1_000_000.0,
    prev_close_nav: float | None = 1_000_000.0,
) -> RiskContext:
    """构造测试 RiskContext (空持仓, 默认 NAV 1M)."""
    return RiskContext(
        strategy_id="test-strategy",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=(),  # 组合级规则不看具体持仓
        portfolio_nav=portfolio_nav,
        prev_close_nav=prev_close_nav,
    )


# ---------- IntradayPortfolioDrop 基类 skip 条件 ----------


class TestIntradayPortfolioDropSkipConditions:
    def test_skip_when_prev_close_nav_is_none(self):
        """T+1 首日 / 数据缺失 → silent skip."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=800_000.0, prev_close_nav=None)
        assert rule.evaluate(ctx) == []

    def test_skip_when_prev_close_nav_zero(self):
        """prev_close_nav <= 0 异常 → silent skip (数据层应已 guard)."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=800_000.0, prev_close_nav=0.0)
        assert rule.evaluate(ctx) == []

    def test_skip_when_prev_close_nav_negative(self):
        """prev_close_nav < 0 异常 → silent skip."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=800_000.0, prev_close_nav=-100.0)
        assert rule.evaluate(ctx) == []

    def test_skip_when_portfolio_nav_zero(self):
        """portfolio_nav <= 0 异常 → silent skip."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=0.0, prev_close_nav=1_000_000.0)
        assert rule.evaluate(ctx) == []


# ---------- 3% 阈值触发边界 ----------


class TestIntradayPortfolioDrop3Pct:
    def test_trigger_at_exact_3pct(self):
        """跌 exactly 3% → 触发."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=970_000.0, prev_close_nav=1_000_000.0)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "intraday_portfolio_drop_3pct"
        assert results[0].metrics["drop_pct"] == pytest.approx(-0.03, abs=1e-6)

    def test_not_trigger_at_2_99pct(self):
        """跌 2.99% 未达阈值 → []."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=970_100.0, prev_close_nav=1_000_000.0)
        assert rule.evaluate(ctx) == []

    def test_trigger_at_5pct_deeper(self):
        """跌 5% 深跌 → 3% rule 也触发 (5% rule 独立判)."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=950_000.0, prev_close_nav=1_000_000.0)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].metrics["drop_pct"] == pytest.approx(-0.05, abs=1e-6)

    def test_no_trigger_when_nav_rises(self):
        """NAV 上涨 (drop_pct > 0) → 不触发."""
        rule = IntradayPortfolioDrop3PctRule()
        ctx = _make_context(portfolio_nav=1_050_000.0, prev_close_nav=1_000_000.0)
        assert rule.evaluate(ctx) == []


# ---------- 5% 阈值触发边界 ----------


class TestIntradayPortfolioDrop5Pct:
    def test_trigger_at_5pct(self):
        rule = IntradayPortfolioDrop5PctRule()
        ctx = _make_context(portfolio_nav=950_000.0, prev_close_nav=1_000_000.0)
        assert len(rule.evaluate(ctx)) == 1

    def test_not_trigger_at_4_99pct(self):
        rule = IntradayPortfolioDrop5PctRule()
        ctx = _make_context(portfolio_nav=950_100.0, prev_close_nav=1_000_000.0)
        assert rule.evaluate(ctx) == []


# ---------- 8% 阈值触发边界 ----------


class TestIntradayPortfolioDrop8Pct:
    def test_trigger_at_8pct(self):
        rule = IntradayPortfolioDrop8PctRule()
        ctx = _make_context(portfolio_nav=920_000.0, prev_close_nav=1_000_000.0)
        assert len(rule.evaluate(ctx)) == 1

    def test_not_trigger_at_7_99pct(self):
        rule = IntradayPortfolioDrop8PctRule()
        ctx = _make_context(portfolio_nav=920_100.0, prev_close_nav=1_000_000.0)
        assert rule.evaluate(ctx) == []


# ---------- 契约: rule_id / severity / action / threshold ----------


class TestIntradayRulesContract:
    def test_3pct_contract(self):
        rule = IntradayPortfolioDrop3PctRule()
        assert rule.rule_id == "intraday_portfolio_drop_3pct"
        assert rule.severity == Severity.P2
        assert rule.action == "alert_only"
        assert rule.threshold == 0.03

    def test_5pct_contract(self):
        rule = IntradayPortfolioDrop5PctRule()
        assert rule.rule_id == "intraday_portfolio_drop_5pct"
        assert rule.severity == Severity.P1
        assert rule.threshold == 0.05

    def test_8pct_contract(self):
        rule = IntradayPortfolioDrop8PctRule()
        assert rule.rule_id == "intraday_portfolio_drop_8pct"
        assert rule.severity == Severity.P0
        assert rule.threshold == 0.08

    def test_rule_ids_unique_across_3_levels(self):
        """3 levels rule_id 必须不重复 (Engine.register 去重要求)."""
        ids = {
            IntradayPortfolioDrop3PctRule().rule_id,
            IntradayPortfolioDrop5PctRule().rule_id,
            IntradayPortfolioDrop8PctRule().rule_id,
        }
        assert len(ids) == 3


# ---------- RuleResult metrics schema ----------


class TestIntradayRuleResultSchema:
    def test_metrics_contains_all_required_fields(self):
        rule = IntradayPortfolioDrop5PctRule()
        ctx = _make_context(portfolio_nav=900_000.0, prev_close_nav=1_000_000.0)
        result = rule.evaluate(ctx)[0]
        required = {
            "drop_pct", "portfolio_nav", "prev_close_nav",
            "threshold", "positions_count",
        }
        assert required <= set(result.metrics.keys())

    def test_reason_human_readable(self):
        """reason 含 drop_pct + nav + threshold 便于钉钉告警回溯."""
        rule = IntradayPortfolioDrop5PctRule()
        ctx = _make_context(portfolio_nav=940_000.0, prev_close_nav=1_000_000.0)
        result = rule.evaluate(ctx)[0]
        assert "6.00%" in result.reason or "-6" in result.reason
        assert "5%" in result.reason  # threshold
        assert "nav=940000" in result.reason

    def test_code_empty_for_portfolio_level(self):
        """组合级 code = '' 对齐 risk_event_log.code DEFAULT ''."""
        rule = IntradayPortfolioDrop8PctRule()
        ctx = _make_context(portfolio_nav=910_000.0, prev_close_nav=1_000_000.0)
        result = rule.evaluate(ctx)[0]
        assert result.code == ""

    def test_shares_zero_for_alert_only(self):
        rule = IntradayPortfolioDrop8PctRule()
        ctx = _make_context(portfolio_nav=910_000.0, prev_close_nav=1_000_000.0)
        result = rule.evaluate(ctx)[0]
        assert result.shares == 0


# ---------- QMTDisconnectRule ----------


class TestQMTDisconnectRule:
    def test_connected_returns_empty(self):
        reader = MagicMock(spec=QMTConnectionReader)
        reader.is_connected.return_value = True
        rule = QMTDisconnectRule(qmt_reader=reader)
        ctx = _make_context()
        assert rule.evaluate(ctx) == []

    def test_disconnected_triggers(self):
        reader = MagicMock(spec=QMTConnectionReader)
        reader.is_connected.return_value = False
        rule = QMTDisconnectRule(qmt_reader=reader)
        ctx = _make_context()
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "qmt_disconnect"
        assert results[0].code == ""  # 基础设施级, 非单股
        assert results[0].shares == 0  # alert_only

    def test_contract(self):
        reader = MagicMock(spec=QMTConnectionReader)
        rule = QMTDisconnectRule(qmt_reader=reader)
        assert rule.rule_id == "qmt_disconnect"
        assert rule.severity == Severity.P0
        assert rule.action == "alert_only"

    def test_metrics_schema(self):
        reader = MagicMock(spec=QMTConnectionReader)
        reader.is_connected.return_value = False
        rule = QMTDisconnectRule(qmt_reader=reader)
        ctx = _make_context(portfolio_nav=987_654.0)
        result = rule.evaluate(ctx)[0]
        assert "checked_at_timestamp" in result.metrics
        assert result.metrics["portfolio_nav_at_disconnect"] == 987_654.0
        assert result.metrics["positions_count_at_disconnect"] == 0.0


# ---------- Frozen context invariant ----------


def test_rule_does_not_mutate_context():
    """规则 evaluate 不修改 context (RiskContext frozen + 铁律 31 纯计算)."""
    rule = IntradayPortfolioDrop5PctRule()
    ctx = _make_context(portfolio_nav=900_000.0, prev_close_nav=1_000_000.0)
    ctx_snapshot = replace(ctx)  # 拷贝前
    rule.evaluate(ctx)
    assert ctx == ctx_snapshot


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
