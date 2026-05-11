"""L1 unit tests for realtime risk rules: LimitDownDetection + NearLimitDown (S5 sub-PR 5a).

覆盖:
  - LimitDownDetection: 主板/科创触发边界, 上涨不触发, 数据缺失 skip
  - NearLimitDown: 接近跌停触发, 已跌停互斥 skip, 上涨 skip
  - GapDownOpen: 集合竞价跳空触发, 正常开盘 skip
"""
from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform._types import Severity
from backend.qm_platform.risk import Position, RiskContext
from backend.qm_platform.risk.rules.realtime import (
    GapDownOpen,
    LimitDownDetection,
    NearLimitDown,
)


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
        entry_date=None,
    )


_SH = "600519.SH"  # 主板
_SZ = "000001.SZ"  # 主板
_STAR = "688121.SH"  # 科创
_GEM = "300750.SZ"  # 创业板


# ===== LimitDownDetection =====


class TestLimitDownDetection:
    def test_rule_contract(self):
        rule = LimitDownDetection()
        assert rule.rule_id == "limit_down_detection"
        assert rule.severity == Severity.P0
        assert rule.action == "alert_only"

    def test_main_board_limit_down_trigger(self):
        """主板跌 9.9%+ → 触发."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_SH, 180.0),),
            realtime={_SH: {"prev_close": 200.0}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].code == _SH
        assert results[0].shares == 0  # alert_only
        assert "LimitDownDetection" in results[0].reason
        assert results[0].metrics["drop_pct"] <= -0.099

    def test_main_board_not_limit_down(self):
        """主板跌 5% → 不触发."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_SH, 190.0),),
            realtime={_SH: {"prev_close": 200.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_star_board_limit_down_trigger(self):
        """科创跌 19.8%+ → 触发."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_STAR, 16.0),),
            realtime={_STAR: {"prev_close": 20.0}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].metrics["drop_pct"] <= -0.198

    def test_gem_board_limit_down_trigger(self):
        """创业板跌 19.8%+ → 触发."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_GEM, 32.0),),
            realtime={_GEM: {"prev_close": 40.0}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1

    def test_upward_not_trigger(self):
        """上涨不触发."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_SH, 210.0),),
            realtime={_SH: {"prev_close": 200.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_skip_no_realtime(self):
        """realtime=None → silent skip."""
        rule = LimitDownDetection()
        ctx = _make_context(positions=(_pos(_SH, 180.0),))
        assert rule.evaluate(ctx) == []

    def test_skip_no_prev_close(self):
        """股缺失 prev_close → silent skip."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_SH, 180.0),),
            realtime={_SH: {"prev_close": 0}},
        )
        assert rule.evaluate(ctx) == []

    def test_skip_missing_in_realtime(self):
        """股不在 realtime dict → silent skip."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_SH, 180.0),),
            realtime={"999999.SH": {"prev_close": 200.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_multi_stock_partial_trigger(self):
        """多股: 一股跌停 + 一股正常 → 仅跌停触发."""
        rule = LimitDownDetection()
        ctx = _make_context(
            positions=(_pos(_SH, 180.0), _pos(_SZ, 10.0)),
            realtime={
                _SH: {"prev_close": 200.0},
                _SZ: {"prev_close": 10.5},
            },
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].code == _SH


# ===== NearLimitDown =====


class TestNearLimitDown:
    def test_rule_contract(self):
        rule = NearLimitDown()
        assert rule.rule_id == "near_limit_down"
        assert rule.severity == Severity.P0
        assert rule.action == "alert_only"

    def test_near_limit_down_trigger(self):
        """跌幅 9.5%-9.9% → 接近跌停触发."""
        rule = NearLimitDown()
        ctx = _make_context(
            positions=(_pos(_SH, 181.0),),  # -9.5% from 200
            realtime={_SH: {"prev_close": 200.0}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].code == _SH

    def test_already_limit_down_skip(self):
        """已跌停 (跌幅 >= 9.9%) → NearLimitDown skip (互斥)."""
        rule = NearLimitDown()
        ctx = _make_context(
            positions=(_pos(_SH, 180.0),),  # -10% from 200
            realtime={_SH: {"prev_close": 200.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_near_limit_down_not_reached(self):
        """跌幅 < 9.5% → 不触发."""
        rule = NearLimitDown()
        ctx = _make_context(
            positions=(_pos(_SH, 185.0),),  # -7.5% from 200
            realtime={_SH: {"prev_close": 200.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_upward_not_trigger(self):
        """上涨不触发."""
        rule = NearLimitDown()
        ctx = _make_context(
            positions=(_pos(_SH, 210.0),),
            realtime={_SH: {"prev_close": 200.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_no_realtime_skip(self):
        rule = NearLimitDown()
        ctx = _make_context(positions=(_pos(_SH, 181.0),))
        assert rule.evaluate(ctx) == []


# ===== GapDownOpen =====


class TestGapDownOpen:
    def test_rule_contract(self):
        rule = GapDownOpen()
        assert rule.rule_id == "gap_down_open"
        assert rule.severity == Severity.P0
        assert rule.action == "alert_only"

    def test_gap_down_trigger(self):
        """跳空 -5%+ → 触发."""
        rule = GapDownOpen()
        ctx = _make_context(
            positions=(_pos(_SH, 190.0, shares=1000),),
            realtime={_SH: {"prev_close": 200.0, "open_price": 189.0}},
        )
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].code == _SH
        assert results[0].shares == 0

    def test_small_gap_not_trigger(self):
        """跳空 -3% < 阈值 → 不触发."""
        rule = GapDownOpen()
        ctx = _make_context(
            positions=(_pos(_SH, 200.0),),
            realtime={_SH: {"prev_close": 200.0, "open_price": 194.0}},
        )
        assert rule.evaluate(ctx) == []

    def test_no_realtime_skip(self):
        rule = GapDownOpen()
        ctx = _make_context(positions=(_pos(_SH, 190.0),))
        assert rule.evaluate(ctx) == []

    def test_missing_open_price_skip(self):
        rule = GapDownOpen()
        ctx = _make_context(
            positions=(_pos(_SH, 190.0),),
            realtime={_SH: {"prev_close": 200.0}},
        )
        assert rule.evaluate(ctx) == []
