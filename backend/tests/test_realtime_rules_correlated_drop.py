"""L1 unit tests for realtime risk rule: CorrelatedDrop (S5 sub-PR 5b).

覆盖:
  - 多股联动下跌触发 (3+ 股同时跌幅 ≥ 3%)
  - 不足 min_count 不触发
  - 单股超出阈值但总股数不足
  - 上涨不触发
  - 缺 rolling price skip
  - 自定义 min_count / drop_threshold
  - 空持仓
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform._types import Severity
from backend.qm_platform.risk import Position, RiskContext
from backend.qm_platform.risk.rules.realtime import CorrelatedDrop


def _make_context(
    positions: tuple[Position, ...] = (),
    realtime: dict[str, dict] | None = None,
) -> RiskContext:
    return RiskContext(
        strategy_id="test-s5-correlated",
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


_SH = "600519.SH"
_SZ = "000001.SZ"
_GEM = "300750.SZ"
_STAR = "688121.SH"
_MED = "600276.SH"


# ===== CorrelatedDrop =====


class TestCorrelatedDrop:
    def test_rule_contract(self):
        rule = CorrelatedDrop()
        assert rule.rule_id == "correlated_drop"
        assert rule.severity == Severity.P0
        assert rule.action == "alert_only"

    def test_correlated_drop_trigger(self):
        """4 股中 3 股跌幅 ≥ 3%, 触发."""
        rule = CorrelatedDrop(min_count=3, drop_threshold=0.03)
        positions = (
            _pos(_SH, 97.0),  # from 100 → -3.0%, triggers
            _pos(_SZ, 95.0),  # from 100 → -5.0%, triggers
            _pos(_GEM, 96.5),  # from 100 → -3.5%, triggers
            _pos(_STAR, 99.0),  # from 100 → -1.0%, no trigger
        )
        realtime = {
            _SH: {"price_5min_ago": 100.0},
            _SZ: {"price_5min_ago": 100.0},
            _GEM: {"price_5min_ago": 100.0},
            _STAR: {"price_5min_ago": 100.0},
        }
        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].rule_id == "correlated_drop"
        assert results[0].metrics["triggered_count"] == 3
        assert _SH in results[0].metrics["triggered_codes"]
        assert _SZ in results[0].metrics["triggered_codes"]
        assert _GEM in results[0].metrics["triggered_codes"]

    def test_correlated_drop_not_enough(self):
        """仅 2 股触发 < min_count=3, 不触发."""
        rule = CorrelatedDrop(min_count=3, drop_threshold=0.03)
        positions = (
            _pos(_SH, 96.0),  # -4.0%
            _pos(_SZ, 96.0),  # -4.0%
            _pos(_GEM, 99.0),  # -1.0%
        )
        realtime = {
            _SH: {"price_5min_ago": 100.0},
            _SZ: {"price_5min_ago": 100.0},
            _GEM: {"price_5min_ago": 100.0},
        }
        ctx = _make_context(positions=positions, realtime=realtime)
        assert rule.evaluate(ctx) == []

    def test_no_realtime_skip(self):
        """无 realtime, 返回空."""
        rule = CorrelatedDrop()
        ctx = _make_context(positions=(_pos(_SH, 96.0), _pos(_SZ, 96.0), _pos(_GEM, 96.0)))
        assert rule.evaluate(ctx) == []

    def test_no_shares_skip(self):
        """零持仓股不参与计数."""
        rule = CorrelatedDrop(min_count=2, drop_threshold=0.03)
        positions = (
            _pos(_SH, 96.0, shares=1000),
            _pos(_SZ, 96.0, shares=1000),
            _pos(_GEM, 96.0, shares=0),  # zero shares, skipped
        )
        realtime = {
            _SH: {"price_5min_ago": 100.0},
            _SZ: {"price_5min_ago": 100.0},
            _GEM: {"price_5min_ago": 100.0},
        }
        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].metrics["triggered_count"] == 2

    def test_upward_not_trigger(self):
        """上涨不计入联动下跌."""
        rule = CorrelatedDrop()
        positions = (
            _pos(_SH, 105.0),  # +5.0%, upward
            _pos(_SZ, 106.0),  # +6.0%, upward
            _pos(_GEM, 104.0),  # +4.0%, upward
        )
        realtime = {
            _SH: {"price_5min_ago": 100.0},
            _SZ: {"price_5min_ago": 100.0},
            _GEM: {"price_5min_ago": 100.0},
        }
        ctx = _make_context(positions=positions, realtime=realtime)
        assert rule.evaluate(ctx) == []

    def test_missing_price_5min_ago_skip(self):
        """某股缺 price_5min_ago, 不参与计数."""
        rule = CorrelatedDrop(min_count=2, drop_threshold=0.03)
        positions = (
            _pos(_SH, 96.0),
            _pos(_SZ, 96.0),
            _pos(_GEM, 96.0),  # missing price_5min_ago
        )
        realtime = {
            _SH: {"price_5min_ago": 100.0},
            _SZ: {"price_5min_ago": 100.0},
            _GEM: {},
        }
        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].metrics["triggered_count"] == 2

    def test_custom_min_count(self):
        """自定义 min_count=5, 3 股不触发."""
        rule = CorrelatedDrop(min_count=5, drop_threshold=0.03)
        positions = tuple(_pos(f"00000{i}.SZ", 96.0) for i in range(1, 6))
        realtime = {f"00000{i}.SZ": {"price_5min_ago": 100.0} for i in range(1, 6)}
        ctx = _make_context(positions=positions, realtime=realtime)
        # 5 股触发 = min_count → 触发
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].metrics["triggered_count"] == 5

    def test_custom_drop_threshold(self):
        """自定义 drop_threshold=0.05."""
        rule = CorrelatedDrop(min_count=2, drop_threshold=0.05)
        positions = (
            _pos(_SH, 94.0),  # -6.0%, triggers
            _pos(_SZ, 96.0),  # -4.0%, no trigger
            _pos(_GEM, 93.0),  # -7.0%, triggers
        )
        realtime = {
            _SH: {"price_5min_ago": 100.0},
            _SZ: {"price_5min_ago": 100.0},
            _GEM: {"price_5min_ago": 100.0},
        }
        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        assert len(results) == 1
        assert results[0].metrics["triggered_count"] == 2

    def test_empty_positions(self):
        """空持仓, 返回空."""
        rule = CorrelatedDrop()
        ctx = _make_context(positions=())
        assert rule.evaluate(ctx) == []

    def test_correlated_at_boundary(self):
        """跌幅刚好 -3% (边界), 触发."""
        rule = CorrelatedDrop(min_count=1, drop_threshold=0.03)
        positions = (_pos(_SH, 97.0),)
        realtime = {_SH: {"price_5min_ago": 100.0}}
        ctx = _make_context(positions=positions, realtime=realtime)
        results = rule.evaluate(ctx)
        assert len(results) == 1

    def test_correlated_just_above(self):
        """跌幅 -2.999% 不触发."""
        rule = CorrelatedDrop(min_count=1, drop_threshold=0.03)
        positions = (_pos(_SH, 97.001),)  # 100 → 97.001, drop = -0.02999
        realtime = {_SH: {"price_5min_ago": 100.0}}
        ctx = _make_context(positions=positions, realtime=realtime)
        assert rule.evaluate(ctx) == []
