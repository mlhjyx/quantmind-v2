"""L1 unit tests for realtime risk rule: VolumeSpike (S5 sub-PR 5b).

覆盖:
  - 成交量异动触发 (ratio >= threshold)
  - 正常成交量不触发
  - 数据缺失 skip (day_volume / avg_daily_volume)
  - 自定义阈值
  - 边界值精确测试
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform._types import Severity
from backend.qm_platform.risk import Position, RiskContext
from backend.qm_platform.risk.rules.realtime import VolumeSpike


def _make_context(
    positions: tuple[Position, ...] = (),
    realtime: dict[str, dict] | None = None,
) -> RiskContext:
    return RiskContext(
        strategy_id="test-s5-volume-spike",
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


# ===== VolumeSpike =====


class TestVolumeSpike:
    def test_rule_contract(self):
        rule = VolumeSpike()
        assert rule.rule_id == "volume_spike"
        assert rule.severity == Severity.P1
        assert rule.action == "alert_only"

    def test_spike_trigger(self):
        """成交量 5x = 5倍均量, 触发 spike."""
        rule = VolumeSpike(threshold=3.0)
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 500000, "avg_daily_volume": 100000}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "volume_spike"
        assert results[0].metrics["ratio"] == 5.0

    def test_spike_at_boundary(self):
        """ratio == 3.0 精确相等, 触发."""
        rule = VolumeSpike(threshold=3.0)
        ctx = _make_context(
            positions=(_pos("000001.SZ", 50.0),),
            realtime={"000001.SZ": {"day_volume": 300000, "avg_daily_volume": 100000}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1

    def test_spike_below_threshold(self):
        """ratio 2.9 < 3.0, 不触发."""
        rule = VolumeSpike()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 290000, "avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx) == []

    def test_no_realtime_skip(self):
        """无 realtime 数据, 返回空."""
        rule = VolumeSpike()
        ctx = _make_context(positions=(_pos("600519.SH", 100.0),))
        assert rule.evaluate(ctx) == []

    def test_no_shares_skip(self):
        """零持仓股, 跳过."""
        rule = VolumeSpike()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0, shares=0),),
            realtime={"600519.SH": {"day_volume": 500000, "avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx) == []

    def test_missing_avg_daily_volume_skip(self):
        """缺 avg_daily_volume, 跳过."""
        rule = VolumeSpike()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 500000}},
        )
        assert rule.evaluate(ctx) == []

    def test_zero_avg_daily_volume_skip(self):
        """avg_daily_volume=0, 跳过 (除零保护)."""
        rule = VolumeSpike()
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 500000, "avg_daily_volume": 0}},
        )
        assert rule.evaluate(ctx) == []

    def test_custom_threshold(self):
        """自定义阈值 threshold=5.0, ratio=4.5 不触发."""
        rule = VolumeSpike(threshold=5.0)
        ctx = _make_context(
            positions=(_pos("600519.SH", 100.0),),
            realtime={"600519.SH": {"day_volume": 450000, "avg_daily_volume": 100000}},
        )
        assert rule.evaluate(ctx) == []

    def test_multi_stock_partial_trigger(self):
        """多股持仓, 仅部分触发."""
        rule = VolumeSpike(threshold=3.0)
        ctx = _make_context(
            positions=(
                _pos("600519.SH", 100.0),
                _pos("000001.SZ", 50.0),
                _pos("300750.SZ", 200.0),
            ),
            realtime={
                "600519.SH": {"day_volume": 500000, "avg_daily_volume": 100000},
                "000001.SZ": {
                    "day_volume": 200000,
                    "avg_daily_volume": 100000,
                },  # 3.0x 边界, ratio=2.0 < 3.0
                "300750.SZ": {"day_volume": 400000, "avg_daily_volume": 100000},
            },
        )
        results = rule.evaluate(ctx)
        assert len(results) == 2
        triggered = {r.code for r in results}
        assert triggered == {"600519.SH", "300750.SZ"}

    def test_missing_tick_in_realtime(self):
        """某股不在 realtime dict 中, 跳过."""
        rule = VolumeSpike()
        ctx = _make_context(
            positions=(
                _pos("600519.SH", 100.0),
                _pos("000001.SZ", 50.0),
            ),
            realtime={"600519.SH": {"day_volume": 500000, "avg_daily_volume": 100000}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].code == "600519.SH"
