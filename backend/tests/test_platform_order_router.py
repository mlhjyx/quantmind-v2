"""Unit tests for backend.qm_platform.signal.router.PlatformOrderRouter (MVP 3.3 batch 2 Step 1).

测试覆盖:
  - __init__: lot_size validation / cancel_callable DI
  - route() error paths: empty signals / missing price / negative price / negative weight /
    unknown strategy_id / TurnoverCapExceeded / IdempotencyViolation
  - route() happy path: all-buy / all-sell / mixed / no-op delta=0 / target_shares 整手
  - route() idempotent order_id: same input → same id
  - route() turnover_cap 边界
  - cancel_stale: stub raise NotImplementedError / DI delegation
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from backend.qm_platform._types import Order, Signal
from backend.qm_platform.signal.router import (
    DEFAULT_LOT_SIZE,
    IdempotencyViolation,
    InsufficientCapital,
    PlatformOrderRouter,
    TurnoverCapExceeded,
)

# ─── Helpers ──────────────────────────────────────────────────────


def _signal(
    strategy_id: str = "s1-uuid",
    code: str = "600519.SH",
    target_weight: float = 0.05,
    price: float = 100.0,
    trade_date: date = date(2026, 4, 27),
) -> Signal:
    return Signal(
        strategy_id=strategy_id,
        code=code,
        target_weight=target_weight,
        score=1.0,
        trade_date=trade_date,
        metadata={"price": price, "industry": "其他"},
    )


# ─── __init__ 验证 ───────────────────────────────────────────


class TestInit:
    def test_default_lot_size_is_100(self):
        router = PlatformOrderRouter()
        assert router.lot_size == DEFAULT_LOT_SIZE == 100

    def test_custom_lot_size(self):
        router = PlatformOrderRouter(lot_size=1)
        assert router.lot_size == 1

    def test_invalid_lot_size_raises(self):
        with pytest.raises(ValueError, match="lot_size 必须 ≥ 1"):
            PlatformOrderRouter(lot_size=0)
        with pytest.raises(ValueError, match="lot_size 必须 ≥ 1"):
            PlatformOrderRouter(lot_size=-100)


# ─── route() 错误路径 ────────────────────────────────────────


class TestRouteErrors:
    def test_empty_signals_returns_empty(self):
        router = PlatformOrderRouter()
        result = router.route(
            signals=[],
            current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert result == []

    def test_missing_price_in_metadata_raises(self):
        router = PlatformOrderRouter()
        sig = Signal(
            strategy_id="s1-uuid",
            code="600519.SH",
            target_weight=0.05,
            score=1.0,
            trade_date=date(2026, 4, 27),
            metadata={"industry": "其他"},  # 缺 price
        )
        with pytest.raises(KeyError, match="price"):
            router.route(
                signals=[sig],
                current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_negative_price_raises_value_error(self):
        router = PlatformOrderRouter()
        sig = _signal(price=-100.0)
        with pytest.raises(ValueError, match="必须 > 0"):
            router.route(
                signals=[sig],
                current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_zero_price_raises_value_error(self):
        router = PlatformOrderRouter()
        sig = _signal(price=0.0)
        with pytest.raises(ValueError, match="必须 > 0"):
            router.route(
                signals=[sig],
                current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_negative_target_weight_raises(self):
        router = PlatformOrderRouter()
        sig = _signal(target_weight=-0.05)
        with pytest.raises(ValueError, match="target_weight 不能 < 0"):
            router.route(
                signals=[sig],
                current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_unknown_strategy_id_raises_insufficient_capital(self):
        router = PlatformOrderRouter()
        sig = _signal(strategy_id="unknown-uuid")
        with pytest.raises(InsufficientCapital, match="不在 capital_allocation"):
            router.route(
                signals=[sig],
                current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )


# ─── route() happy path ───────────────────────────────────────


class TestRouteHappyPath:
    def test_all_buy_from_empty_positions(self):
        """空仓 → 全 BUY 单."""
        router = PlatformOrderRouter()
        # 100 万 capital, 10% weight, price=100 → target_value=10w → 1000 股 (10 lots).
        sig = _signal(target_weight=0.10, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 1
        order = orders[0]
        assert isinstance(order, Order)
        assert order.side == "BUY"
        assert order.quantity == 1000  # 整手 round-down
        assert order.code == "600519.SH"
        assert order.strategy_id == "s1-uuid"

    def test_all_sell_to_empty(self):
        """target_weight=0 + curr 持仓 1000 → SELL 1000."""
        router = PlatformOrderRouter()
        # 实际场景: signal 不在 target portfolio 才算 sell; 我们模拟 caller 显式发 weight=0
        # 但 weight=0 + curr=0 → delta=0 跳过. 测 weight=0 + curr=1000 → SELL 1000.
        sig = _signal(target_weight=0.0, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={"600519.SH": 1000},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 1
        assert orders[0].side == "SELL"
        assert orders[0].quantity == 1000

    def test_no_op_delta_zero_skipped(self):
        """target_shares == curr_shares → 不生成 order."""
        router = PlatformOrderRouter()
        # 100 万 × 10% / price 100 = 1000 股 = curr 1000 → delta=0
        sig = _signal(target_weight=0.10, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={"600519.SH": 1000},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert orders == []

    def test_mixed_buy_and_sell(self):
        """两 signals: 加仓 600519 + 减仓 000001."""
        router = PlatformOrderRouter()
        sigs = [
            _signal(code="600519.SH", target_weight=0.20, price=100.0),  # target 2000, curr 1000 → BUY 1000
            _signal(code="000001.SZ", target_weight=0.05, price=100.0),  # target 500→500整手 round 500, curr 1000 → SELL 500
        ]
        orders = router.route(
            signals=sigs,
            current_positions={"600519.SH": 1000, "000001.SZ": 1000},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 2
        sides = {o.code: o.side for o in orders}
        qty = {o.code: o.quantity for o in orders}
        assert sides["600519.SH"] == "BUY" and qty["600519.SH"] == 1000
        assert sides["000001.SZ"] == "SELL" and qty["000001.SZ"] == 500

    def test_round_down_to_lot_size(self):
        """integer round-down: target 1099 股 → 1000 股 (99 不足整手丢弃)."""
        router = PlatformOrderRouter(lot_size=100)
        # capital=109900, weight=1.0, price=100 → 1099 股 → 1000 (rounded)
        sig = _signal(target_weight=1.0, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={},
            capital_allocation={"s1-uuid": Decimal("109900")},
            turnover_cap=1.0,  # 防 turnover_cap 触发
        )
        assert len(orders) == 1
        assert orders[0].quantity == 1000  # 1099 round-down to 1000

    def test_lot_size_one_no_rounding(self):
        """lot_size=1 跳过整手, 保留所有股 (test 用)."""
        router = PlatformOrderRouter(lot_size=1)
        sig = _signal(target_weight=1.0, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={},
            capital_allocation={"s1-uuid": Decimal("109900")},
            turnover_cap=1.0,
        )
        assert orders[0].quantity == 1099


# ─── route() 幂等性 ──────────────────────────────────────────


class TestRouteIdempotency:
    def test_same_input_same_order_id(self):
        """同 (strategy_id, trade_date, code, side, target_shares) → 同 order_id."""
        router1 = PlatformOrderRouter()
        router2 = PlatformOrderRouter()
        sig = _signal(target_weight=0.10, price=100.0)
        o1 = router1.route(
            signals=[sig], current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        o2 = router2.route(
            signals=[sig], current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert o1[0].order_id == o2[0].order_id

    def test_order_id_changes_with_inputs(self):
        """不同 (code/side/target_shares) → 不同 order_id."""
        router = PlatformOrderRouter()
        sig_a = _signal(code="600519.SH", target_weight=0.10, price=100.0)
        sig_b = _signal(code="000001.SZ", target_weight=0.10, price=100.0)
        orders = router.route(
            signals=[sig_a, sig_b],
            current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert orders[0].order_id != orders[1].order_id

    def test_duplicate_signal_raises_idempotency_violation(self):
        """同 signal 重复 → IdempotencyViolation (caller 应去重)."""
        router = PlatformOrderRouter()
        sig = _signal(target_weight=0.10, price=100.0)
        with pytest.raises(IdempotencyViolation, match="重复"):
            router.route(
                signals=[sig, sig],  # 重复
                current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_order_id_format_is_16_hex(self):
        """order_id 必 16 hex 字符."""
        router = PlatformOrderRouter()
        sig = _signal(target_weight=0.10, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        oid = orders[0].order_id
        assert len(oid) == 16
        assert all(c in "0123456789abcdef" for c in oid)


# ─── route() turnover_cap ─────────────────────────────────────


class TestRouteTurnoverCap:
    def test_under_cap_passes(self):
        """总 BUY value 30% < 50% cap → 不抛."""
        router = PlatformOrderRouter()
        sig = _signal(target_weight=0.30, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
            turnover_cap=0.50,
        )
        assert len(orders) == 1

    def test_over_cap_raises(self):
        """总 BUY value 60% > 50% cap → TurnoverCapExceeded."""
        router = PlatformOrderRouter()
        sig = _signal(target_weight=0.60, price=100.0)
        with pytest.raises(TurnoverCapExceeded, match="超 turnover_cap"):
            router.route(
                signals=[sig],
                current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
                turnover_cap=0.50,
            )

    def test_sell_only_no_cap_check(self):
        """全 SELL (BUY value=0) 不触发 turnover_cap."""
        router = PlatformOrderRouter()
        sig = _signal(target_weight=0.0, price=100.0)
        orders = router.route(
            signals=[sig],
            current_positions={"600519.SH": 1000},
            capital_allocation={"s1-uuid": Decimal("1000000")},
            turnover_cap=0.01,  # 极严苛 cap, 但 BUY=0 不触发
        )
        assert len(orders) == 1
        assert orders[0].side == "SELL"


# ─── cancel_stale stub ────────────────────────────────────────


class TestCancelStaleStub:
    def test_no_callable_raises_not_implemented(self):
        """默认无 cancel_callable → NotImplementedError (Step 1 stub)."""
        router = PlatformOrderRouter()
        with pytest.raises(NotImplementedError, match="Step 2"):
            router.cancel_stale()

    def test_with_callable_delegates(self):
        """注入 cancel_callable → 透传调用."""
        mock_cancel = MagicMock(return_value=["order-1", "order-2"])
        router = PlatformOrderRouter(cancel_callable=mock_cancel)
        result = router.cancel_stale(cutoff_seconds=600)
        assert result == ["order-1", "order-2"]
        mock_cancel.assert_called_once_with(600)

    def test_default_cutoff_seconds_300(self):
        mock_cancel = MagicMock(return_value=[])
        router = PlatformOrderRouter(cancel_callable=mock_cancel)
        router.cancel_stale()
        mock_cancel.assert_called_once_with(300)


# ─── 多 strategy ─────────────────────────────────────────────


class TestMultiStrategy:
    def test_two_strategies_separate_capital(self):
        """两策略独立 capital + 独立 signals 互不冲突."""
        router = PlatformOrderRouter()
        sigs = [
            _signal(strategy_id="s1-uuid", code="600519.SH", target_weight=0.20, price=100.0),
            _signal(strategy_id="s2-uuid", code="000001.SZ", target_weight=0.30, price=50.0),
        ]
        # s1 capital 50w × 20% = 10w / price 100 = 1000 股
        # s2 capital 50w × 30% = 15w / price 50  = 3000 股
        orders = router.route(
            signals=sigs,
            current_positions={},
            capital_allocation={
                "s1-uuid": Decimal("500000"),
                "s2-uuid": Decimal("500000"),
            },
            turnover_cap=1.0,
        )
        assert len(orders) == 2
        qty_by_code = {o.quantity for o in orders}
        assert qty_by_code == {1000, 3000}
