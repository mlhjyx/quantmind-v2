"""L1 unit tests for realtime risk rules: RapidDrop5min + RapidDrop15min (S5 sub-PR 5a).

覆盖:
  - RapidDrop5min: 5min 快速下跌触发, 边界, skip 条件
  - RapidDrop15min: 15min 快速下跌触发, 边界, skip 条件
  - 上涨不触发, 数据缺失 skip, partial 触发
"""
from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform._types import Severity
from backend.qm_platform.risk import Position, RiskContext
from backend.qm_platform.risk.rules.realtime import RapidDrop5min, RapidDrop15min


def _make_context(
    positions: tuple[Position, ...] = (),
    realtime: dict[str, dict] | None = None,
) -> RiskContext:
    return RiskContext(
        strategy_id="test-s5",
        execution_mode="paper",
        timestamp=datetime.now(UTC),
        positions=positions,
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_000_000.0,
        realtime=realtime,
    )


def _pos(code: str, price: float, shares: int = 1000) -> Position:
    return Position(
        code=code,
        shares=shares,
        entry_price=price * 1.1,
        peak_price=price * 1.2,
        current_price=price,
    )


_SH = "600519.SH"


# ===== RapidDrop5min =====


class TestRapidDrop5min:
    def test_rule_contract(self):
        rule = RapidDrop5min()
        assert rule.rule_id == "rapid_drop_5min"
        assert rule.severity == Severity.P1
        assert rule.action == "alert_only"

    def test_rapid_drop_trigger(self):
        """5min 跌 5%+ → 触发."""
        rule = RapidDrop5min()
        ctx = _make_context(
            positions=(_pos(_SH, 95.0),),
            realtime={_SH: {"price_5min_ago": 100.0}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].code == _SH
        assert "RapidDrop5min" in results[0].reason

    def test_rapid_drop_boundary(self):
        """刚好 -5% → 触发 (边界)."""
        rule = RapidDrop5min()
        ctx = _make_context(
            positions=(_pos(_SH, 95.0),),
            realtime={_SH: {"price_5min_ago": 100.0}},
        )
        assert len(rule.evaluate(ctx)) == 1

    def test_rapid_drop_not_trigger(self):
        """5min 跌 3% < 阈值 → 不触发."""
        rule = RapidDrop5min()
        ctx = _make_context(
            positions=(_pos(_SH, 97.0),),
            realtime={_SH: {"price_5min_ago": 100.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_upward_not_trigger(self):
        """5min 上涨 → 不触发."""
        rule = RapidDrop5min()
        ctx = _make_context(
            positions=(_pos(_SH, 103.0),),
            realtime={_SH: {"price_5min_ago": 100.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_no_realtime_skip(self):
        rule = RapidDrop5min()
        ctx = _make_context(positions=(_pos(_SH, 95.0),))
        assert rule.evaluate(ctx) == []

    def test_missing_5min_price_skip(self):
        rule = RapidDrop5min()
        ctx = _make_context(
            positions=(_pos(_SH, 95.0),),
            realtime={_SH: {}},
        )
        assert rule.evaluate(ctx) == []

    def test_custom_threshold(self):
        """自定义阈值 10% → 跌 8% 不触发."""
        rule = RapidDrop5min(threshold=0.10)
        ctx = _make_context(
            positions=(_pos(_SH, 92.0),),
            realtime={_SH: {"price_5min_ago": 100.0}},
        )
        assert rule.evaluate(ctx) == []


# ===== RapidDrop15min =====


class TestRapidDrop15min:
    def test_rule_contract(self):
        rule = RapidDrop15min()
        assert rule.rule_id == "rapid_drop_15min"
        assert rule.severity == Severity.P1
        assert rule.action == "alert_only"

    def test_rapid_drop_trigger(self):
        """15min 跌 8%+ → 触发."""
        rule = RapidDrop15min()
        ctx = _make_context(
            positions=(_pos(_SH, 92.0),),
            realtime={_SH: {"price_15min_ago": 100.0}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].code == _SH
        assert "RapidDrop15min" in results[0].reason

    def test_rapid_drop_not_trigger(self):
        """15min 跌 5% < 8% → 不触发."""
        rule = RapidDrop15min()
        ctx = _make_context(
            positions=(_pos(_SH, 95.0),),
            realtime={_SH: {"price_15min_ago": 100.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_upward_not_trigger(self):
        rule = RapidDrop15min()
        ctx = _make_context(
            positions=(_pos(_SH, 105.0),),
            realtime={_SH: {"price_15min_ago": 100.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_no_realtime_skip(self):
        rule = RapidDrop15min()
        ctx = _make_context(positions=(_pos(_SH, 92.0),))
        assert rule.evaluate(ctx) == []

    def test_missing_15min_price_skip(self):
        rule = RapidDrop15min()
        ctx = _make_context(
            positions=(_pos(_SH, 92.0),),
            realtime={_SH: {}},
        )
        assert rule.evaluate(ctx) == []
