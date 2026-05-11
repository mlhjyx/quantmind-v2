"""L1 unit tests for realtime risk rule: LiquidityCollapse (S5 sub-PR 5b).

覆盖:
  - 流动性枯竭触发 (ratio < threshold)
  - 正常流动性不触发
  - 数据缺失 skip
  - 自定义阈值
  - 边界值精确测试
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform._types import Severity
from backend.qm_platform.risk import Position, RiskContext
from backend.qm_platform.risk.rules.realtime import LiquidityCollapse


def _make_context(
    positions: tuple[Position, ...] = (),
    realtime: dict[str, dict] | None = None,
) -> RiskContext:
    return RiskContext(
        strategy_id="test-s5-liquidity-collapse",
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
        entry_date=None,
    )


# ===== LiquidityCollapse =====


class TestLiquidityCollapse:
    def test_rule_contract(self):
        rule = LiquidityCollapse()
        assert rule.rule_id == "liquidity_collapse"
        assert rule.severity == Severity.P1
        assert rule.action == "alert_only"

    def test_collapse_trigger(self):
        """day_vol=10k / avg=100k = 0.1x < 0.3, 触发."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 10000, "avg_daily_volume": 100000}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "liquidity_collapse"
        assert results[0].metrics["ratio"] == 0.1

    def test_collapse_at_boundary(self):
        """ratio == 0.3 精确相等, 不触发 (threshold 是 exclusive)."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("000001.SZ", 50.0),),
            realtime={"000001.SZ": {"day_volume": 30000, "avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx) == []

    def test_collapse_just_below(self):
        """ratio == 0.29999 < 0.3, 触发."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("000001.SZ", 50.0),),
            realtime={"000001.SZ": {"day_volume": 29999, "avg_daily_volume": 100000}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1

    def test_normal_volume_not_trigger(self):
        """正常量比不触发."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 80000, "avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx) == []

    def test_no_realtime_skip(self):
        """无 realtime, 返回空."""
        rule = LiquidityCollapse()
        ctx = _make_context(positions=(_pos("600519.SH", 100.0),))
        assert rule.evaluate(ctx) == []

    def test_no_shares_skip(self):
        """零持仓 skip."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0, shares=0),),
            realtime={"600519.SH": {"day_volume": 5000, "avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx) == []

    def test_missing_avg_daily_volume_skip(self):
        """缺 avg_daily_volume."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 5000}},
        )
        assert rule.evaluate(ctx) == []

    def test_zero_avg_daily_volume_skip(self):
        """avg=0, 除零保护."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 5000, "avg_daily_volume": 0}},
        )
        assert rule.evaluate(ctx) == []

    def test_missing_day_volume_skip(self):
        """缺 day_volume."""
        rule = LiquidityCollapse()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx) == []

    def test_custom_threshold(self):
        """自定义 threshold=0.5."""
        rule = LiquidityCollapse(threshold=0.5)
        # ratio=0.4 < 0.5 → 触发
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 40000, "avg_daily_volume": 100000}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1

        # ratio=0.6 >= 0.5 → 不触发
        ctx2 = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 60000, "avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx2) == []
