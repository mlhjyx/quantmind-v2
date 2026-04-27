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
        # P2 python-reviewer (PR #108) 采纳: dict 而非 set, 验 quantity-to-code 映射.
        qty_by_code = {o.code: o.quantity for o in orders}
        assert qty_by_code["600519.SH"] == 1000
        assert qty_by_code["000001.SZ"] == 3000


# ─── P1/P2 reviewer (PR #108) 新增 ──────────────────────────


class TestPriceTypeFlexibility:
    """P1 reviewer (PR #108) 采纳: float() coerce 拓宽到 np.float64 / Decimal / int."""

    def test_decimal_price_accepted(self):
        """Decimal price 不再被 type guard 拒 (Step 2 wire 时 DAL 可能传 Decimal)."""
        router = PlatformOrderRouter()
        sig = Signal(
            strategy_id="s1-uuid",
            code="600519.SH",
            target_weight=0.10,
            score=1.0,
            trade_date=date(2026, 4, 27),
            metadata={"price": Decimal("100.0")},  # Decimal!
        )
        orders = router.route(
            signals=[sig], current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 1
        assert orders[0].quantity == 1000

    def test_int_price_accepted(self):
        """int price 也接受 (e.g. close == 100 整数)."""
        router = PlatformOrderRouter()
        sig = _signal(price=100)  # int 而非 float
        sig = Signal(
            strategy_id="s1-uuid", code="600519.SH",
            target_weight=0.10, score=1.0,
            trade_date=date(2026, 4, 27),
            metadata={"price": 100},  # int!
        )
        orders = router.route(
            signals=[sig], current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 1

    def test_nan_price_raises_value_error(self):
        """NaN price 必 fail-loud (原 isinstance + > 0 检查会 silent pass)."""
        router = PlatformOrderRouter()
        sig = _signal(price=float("nan"))
        with pytest.raises(ValueError, match="NaN/inf"):
            router.route(
                signals=[sig], current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_inf_price_raises_value_error(self):
        """Infinity price 必 fail-loud."""
        router = PlatformOrderRouter()
        sig = _signal(price=float("inf"))
        with pytest.raises(ValueError, match="NaN/inf"):
            router.route(
                signals=[sig], current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_numeric_string_price_accepted(self):
        """numeric str (e.g. JSON 反序列化漏 cast) 可 float() 转换 — 接受不报错."""
        router = PlatformOrderRouter()
        sig = Signal(
            strategy_id="s1-uuid", code="600519.SH",
            target_weight=0.10, score=1.0,
            trade_date=date(2026, 4, 27),
            metadata={"price": "100.0"},  # str numeric
        )
        orders = router.route(
            signals=[sig], current_positions={},
            capital_allocation={"s1-uuid": Decimal("1000000")},
        )
        assert len(orders) == 1

    def test_non_numeric_string_price_raises_type_error(self):
        """非数值 str price → TypeError 明确诊断 (e.g. corruption / 占位字符串)."""
        router = PlatformOrderRouter()
        sig = Signal(
            strategy_id="s1-uuid", code="600519.SH",
            target_weight=0.10, score=1.0,
            trade_date=date(2026, 4, 27),
            metadata={"price": "abc"},  # 非数值
        )
        with pytest.raises(TypeError, match="必须可 float"):
            router.route(
                signals=[sig], current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )

    def test_none_price_raises_type_error(self):
        """None price → TypeError."""
        router = PlatformOrderRouter()
        sig = Signal(
            strategy_id="s1-uuid", code="600519.SH",
            target_weight=0.10, score=1.0,
            trade_date=date(2026, 4, 27),
            metadata={"price": None},
        )
        with pytest.raises(TypeError, match="必须可 float"):
            router.route(
                signals=[sig], current_positions={},
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )


class TestOrphanPositionWarning:
    """P1 code-reviewer (PR #108) 采纳: current_positions 中 code 未在 signals
    时 router 不自动 SELL, 但必 warn (caller 契约)."""

    def test_orphan_logged_warning(self, caplog):
        import logging
        router = PlatformOrderRouter()
        # signal 只覆盖 600519, 但 current 还有 000001 (orphan)
        sig = _signal(code="600519.SH", target_weight=0.10, price=100.0)
        with caplog.at_level(logging.WARNING, logger="backend.qm_platform.signal.router"):
            router.route(
                signals=[sig],
                current_positions={"600519.SH": 500, "000001.SZ": 1000},  # orphan!
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("orphan positions" in r.message for r in warnings), (
            f"missing orphan warning: {[r.message for r in warnings]}"
        )

    def test_no_orphan_no_warning(self, caplog):
        """所有 current_positions 都在 signals → 无 warning."""
        import logging
        router = PlatformOrderRouter()
        sig = _signal(code="600519.SH", target_weight=0.10, price=100.0)
        with caplog.at_level(logging.WARNING, logger="backend.qm_platform.signal.router"):
            router.route(
                signals=[sig],
                current_positions={"600519.SH": 500},  # 无 orphan
                capital_allocation={"s1-uuid": Decimal("1000000")},
            )
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("orphan positions" in r.message for r in warnings)


class TestZeroCapital:
    """P2 python-reviewer (PR #108) 采纳: total_capital==0 不 silent skip turnover check, 必 warn."""

    def test_zero_capital_warning(self, caplog):
        import logging
        router = PlatformOrderRouter()
        sig = _signal(target_weight=0.0, price=100.0)
        with caplog.at_level(logging.WARNING, logger="backend.qm_platform.signal.router"):
            # capital=0 + curr 持仓 → SELL only, turnover_cap 检查跳过但应 warn
            router.route(
                signals=[sig],
                current_positions={"600519.SH": 1000},
                capital_allocation={"s1-uuid": Decimal("0")},
            )
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("total_capital=0" in r.message for r in warnings), (
            f"expected total_capital=0 warning, got: {[r.message for r in warnings]}"
        )


class TestOrderIdCollisionResistance:
    """P1 python-reviewer (PR #108) 采纳: order_id 不再用 `|` 分隔, 防 strategy_id
    含 `|` 造碰撞."""

    def test_strategy_id_with_pipe_no_collision(self):
        """strategy_id='s|x' vs 's' + 'x' 字段拼接, 用 json 后 hash 不同."""
        router = PlatformOrderRouter()
        sig_a = Signal(
            strategy_id="strat|v2", code="600519.SH", target_weight=0.10,
            score=1.0, trade_date=date(2026, 4, 27),
            metadata={"price": 100.0},
        )
        sig_b = Signal(
            strategy_id="strat", code="v2|600519.SH", target_weight=0.10,
            score=1.0, trade_date=date(2026, 4, 27),
            metadata={"price": 100.0},
        )
        # 不同 strategy_id + code 必生成不同 order_id (无碰撞)
        orders_a = router.route(
            signals=[sig_a], current_positions={},
            capital_allocation={"strat|v2": Decimal("1000000")},
        )
        orders_b = router.route(
            signals=[sig_b], current_positions={},
            capital_allocation={"strat": Decimal("1000000")},
        )
        assert orders_a[0].order_id != orders_b[0].order_id, (
            "P1 regression: '|' 分隔 hash 碰撞 — strategy_id+code 拼接应不同"
        )

    def test_chinese_strategy_id_works(self):
        """中文 strategy_id (json ensure_ascii=False 保) 可 hash."""
        router = PlatformOrderRouter()
        sig = Signal(
            strategy_id="策略一", code="600519.SH", target_weight=0.10,
            score=1.0, trade_date=date(2026, 4, 27),
            metadata={"price": 100.0},
        )
        orders = router.route(
            signals=[sig], current_positions={},
            capital_allocation={"策略一": Decimal("1000000")},
        )
        assert len(orders[0].order_id) == 16  # 仍 16 hex


class TestDecimalPrecision:
    """P1 code-reviewer (PR #108) 采纳: capital × target_weight 走 Decimal 路径,
    不 float() 提前精度损失."""

    def test_decimal_precision_preserved(self):
        """Decimal × float weight 走 Decimal × Decimal(str(weight)), 精度不损."""
        router = PlatformOrderRouter(lot_size=1)  # lot=1 显微观察
        # capital = 99999.99, weight = 0.01 → target_value = 999.9999, /price=100 = 9.99
        # int(9.99) = 9, * lot_size 1 = 9. 用 Decimal 路径仍 9 (无浮点 noise).
        sig = _signal(target_weight=0.01, price=100.0)
        orders = router.route(
            signals=[sig], current_positions={},
            capital_allocation={"s1-uuid": Decimal("99999.99")},
            turnover_cap=1.0,
        )
        assert len(orders) == 1
        # 99999.99 × 0.01 = 999.9999, / 100 = 9.999999, int=9
        assert orders[0].quantity == 9
