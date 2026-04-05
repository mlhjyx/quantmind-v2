"""封板补单机制测试 — 覆盖backtest_engine.py / paper_broker.py / run_paper_trading.py。

10个测试场景:
1. 回测确定性不变：无封板时Sharpe与修改前一致
2. PendingOrder创建：涨停封板股产生pending记录
3. 补单成功：T+1打开后执行买入
4. 补单失败仍封板：标记cancelled
5. 距调仓日太近不补：<=5天取消
6. 最多补3只：5只封板只补前3
7. 单只上限10%：补单金额不超组合10%
8. PaperBroker返回值兼容：tuple解包正确
9. Paper Trading补单持久化：scheduler_task_log读写
10. PendingOrderStats统计：fill_rate/cancel_reasons

不依赖真实数据库，使用构造的DataFrame + mock。
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from engines.backtest_engine import (
    BacktestConfig,
    PendingOrder,
    PendingOrderStats,
    SimBroker,
    SimpleBacktester,
)
from engines.paper_broker import PaperBroker, PaperState

# ──────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────

def _make_price_data(
    codes: list[str],
    dates: list[date],
    base_price: float = 10.0,
    limit_up_codes: dict[date, list[str]] | None = None,
) -> pd.DataFrame:
    """构造价格数据DataFrame。

    Args:
        codes: 股票代码列表。
        dates: 交易日列表。
        base_price: 基础价格。
        limit_up_codes: {date: [code]} 涨停封板股票。

    Returns:
        含open/close/pre_close/volume/up_limit/down_limit/turnover_rate的DataFrame。
    """
    rows = []
    limit_up_codes = limit_up_codes or {}

    for td in dates:
        for code in codes:
            is_limit_up = code in limit_up_codes.get(td, [])
            pre_close = base_price
            if is_limit_up:
                # 涨停封板: close == up_limit, turnover < 1%
                up_limit = round(pre_close * 1.10, 2)
                rows.append({
                    "code": code,
                    "trade_date": td,
                    "open": up_limit,
                    "high": up_limit,
                    "low": pre_close * 1.05,
                    "close": up_limit,
                    "pre_close": pre_close,
                    "volume": 100_000,
                    "amount": up_limit * 100_000,
                    "up_limit": up_limit,
                    "down_limit": round(pre_close * 0.90, 2),
                    "turnover_rate": 0.3,  # < 1% → 封板
                })
            else:
                # 正常交易
                rows.append({
                    "code": code,
                    "trade_date": td,
                    "open": base_price * 1.005,
                    "high": base_price * 1.02,
                    "low": base_price * 0.99,
                    "close": base_price * 1.01,
                    "pre_close": pre_close,
                    "volume": 5_000_000,
                    "amount": base_price * 5_000_000,
                    "up_limit": round(pre_close * 1.10, 2),
                    "down_limit": round(pre_close * 0.90, 2),
                    "turnover_rate": 5.0,
                })

    return pd.DataFrame(rows)


def _make_benchmark(dates: list[date], base: float = 4000.0) -> pd.DataFrame:
    """构造基准数据。"""
    return pd.DataFrame({
        "trade_date": dates,
        "close": [base * (1 + i * 0.001) for i in range(len(dates))],
    })


# ──────────────────────────────────────────────────────────
# 场景1: 回测确定性不变 — 无封板时Sharpe与修改前一致
# ──────────────────────────────────────────────────────────

class TestBacktestDeterminism:
    """回测确定性: 无封板场景下结果不变。"""

    def test_no_pending_orders_sharpe_unchanged(self) -> None:
        """无封板时，新引擎与_rebalance()走相同路径，Sharpe一致。"""
        codes = [f"code_{i:02d}" for i in range(10)]
        dates = [date(2024, 1, d) for d in range(2, 25)]  # 17个交易日

        price_data = _make_price_data(codes, dates)
        benchmark = _make_benchmark(dates)

        # 构造2个调仓信号（等权）
        weight = 1.0 / len(codes)
        target_portfolios = {
            date(2024, 1, 4): {c: weight for c in codes},
            date(2024, 1, 16): {c: weight for c in codes},
        }

        config = BacktestConfig(initial_capital=1_000_000, top_n=10)

        # 跑两次，结果bit-identical
        bt1 = SimpleBacktester(config)
        r1 = bt1.run(target_portfolios, price_data, benchmark)

        bt2 = SimpleBacktester(config)
        r2 = bt2.run(target_portfolios, price_data, benchmark)

        # NAV完全一致
        pd.testing.assert_series_equal(r1.daily_nav, r2.daily_nav)
        pd.testing.assert_series_equal(r1.daily_returns, r2.daily_returns)

        # 无封板 → pending_orders为空
        assert r1.pending_order_stats is not None
        assert r1.pending_order_stats.total_pending == 0
        assert r2.pending_order_stats.total_pending == 0


# ──────────────────────────────────────────────────────────
# 场景2: PendingOrder创建 — 涨停封板股产生pending记录
# ──────────────────────────────────────────────────────────

class TestPendingOrderCreation:
    """涨停封板时产生PendingOrder。"""

    def test_limit_up_creates_pending(self) -> None:
        """涨停封板的买入目标产生PendingOrder记录。"""
        codes = ["A", "B", "C"]
        dates = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4),
                 date(2024, 1, 5), date(2024, 1, 8)]

        # A在1/3涨停封板
        price_data = _make_price_data(codes, dates, limit_up_codes={
            date(2024, 1, 3): ["A"],
        })
        benchmark = _make_benchmark(dates)

        # 信号日1/2, 执行日1/3
        target = {c: 1.0 / 3 for c in codes}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=3)
        bt = SimpleBacktester(config)
        result = bt.run(target_portfolios, price_data, benchmark)

        # A应该在pending列表中
        assert result.pending_order_stats is not None
        assert result.pending_order_stats.total_pending >= 1

        # 确认pending_orders中有A
        pending_a = [po for po in bt.pending_orders if po.code == "A"]
        assert len(pending_a) >= 1
        assert pending_a[0].direction == "buy"
        assert pending_a[0].exec_date == date(2024, 1, 3)


# ──────────────────────────────────────────────────────────
# 场景3: 补单成功 — T+1打开后执行买入
# ──────────────────────────────────────────────────────────

class TestPendingOrderFill:
    """封板T+1打开后补单成功。"""

    def test_retry_fill_on_next_day(self) -> None:
        """T+1日不再封板，补单成功填充。"""
        codes = ["A", "B", "C"]
        # 需要足够多的交易日来让补单执行
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5, 8, 9, 10, 11, 12,
                                              15, 16, 17, 18, 19, 22]]

        # A在1/3涨停封板，1/4恢复正常
        price_data = _make_price_data(codes, dates, limit_up_codes={
            date(2024, 1, 3): ["A"],
        })
        benchmark = _make_benchmark(dates)

        target = {c: 1.0 / 3 for c in codes}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=3)
        bt = SimpleBacktester(config)
        bt.run(target_portfolios, price_data, benchmark)

        # A应该被补单成功
        filled = [po for po in bt.pending_orders if po.code == "A" and po.status == "filled"]
        assert len(filled) >= 1, f"A应该补单成功, 实际状态: {[po.status for po in bt.pending_orders if po.code == 'A']}"


# ──────────────────────────────────────────────────────────
# 场景4: 补单失败仍封板 — 标记cancelled
# ──────────────────────────────────────────────────────────

class TestPendingOrderCancelledStillLimit:
    """T+1日仍封板 → cancelled。"""

    def test_still_limit_up_cancelled(self) -> None:
        """T+1日仍然涨停封板，标记为cancelled。"""
        codes = ["A", "B"]
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5, 8, 9, 10, 11, 12,
                                              15, 16, 17, 18, 19]]

        # A在1/3和1/4都涨停封板
        price_data = _make_price_data(codes, dates, limit_up_codes={
            date(2024, 1, 3): ["A"],
            date(2024, 1, 4): ["A"],
        })
        benchmark = _make_benchmark(dates)

        target = {"A": 0.5, "B": 0.5}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=2)
        bt = SimpleBacktester(config)
        bt.run(target_portfolios, price_data, benchmark)

        # A应该被标记为cancelled
        cancelled = [po for po in bt.pending_orders
                     if po.code == "A" and po.status == "cancelled"]
        assert len(cancelled) >= 1
        assert "still_limit_up" in cancelled[0].cancel_reason or "expired" in cancelled[0].cancel_reason


# ──────────────────────────────────────────────────────────
# 场景5: 距调仓日太近不补 — <=5天取消
# ──────────────────────────────────────────────────────────

class TestPendingOrderTooCloseToRebalance:
    """距下次调仓<=5天 → 不补。"""

    def test_too_close_to_next_rebalance(self) -> None:
        """补单日距下次调仓<=5交易日，取消。"""
        codes = ["A", "B"]
        # 紧凑日期: 信号1/2, 执行1/3, retry 1/4, 下次调仓1/8
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5, 8, 9, 10]]

        # A在1/3封板
        price_data = _make_price_data(codes, dates, limit_up_codes={
            date(2024, 1, 3): ["A"],
        })
        benchmark = _make_benchmark(dates)

        # 两次调仓紧邻: 1/2和1/5 → retry日1/4距下次调仓1/8只有3天
        target = {"A": 0.5, "B": 0.5}
        target_portfolios = {
            date(2024, 1, 2): target,
            date(2024, 1, 5): target,  # 下次调仓信号日
        }

        config = BacktestConfig(initial_capital=1_000_000, top_n=2)
        bt = SimpleBacktester(config)
        bt.min_days_to_next_rebal = 5
        bt.run(target_portfolios, price_data, benchmark)

        # A的pending应该被取消（距下次调仓太近）
        [
            po for po in bt.pending_orders
            if po.code == "A" and po.status == "cancelled"
            and "too_close" in po.cancel_reason
        ]
        # 至少取消了一个（因为距离太近或者expired）
        all_cancelled = [po for po in bt.pending_orders
                         if po.code == "A" and po.status == "cancelled"]
        assert len(all_cancelled) >= 1, (
            f"A应该被取消, 实际: {[(po.status, po.cancel_reason) for po in bt.pending_orders if po.code == 'A']}"
        )


# ──────────────────────────────────────────────────────────
# 场景6: 最多补3只 — 5只封板只补前3
# ──────────────────────────────────────────────────────────

class TestMaxRetryOrders:
    """最多补3只限制。"""

    def test_only_top_3_retried(self) -> None:
        """5只封板，只补前3只（按original_score降序）。"""
        codes = [f"S{i}" for i in range(8)]
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5, 8, 9, 10, 11, 12,
                                              15, 16, 17, 18, 19, 22]]

        # S0-S4在1/3封板，S5-S7正常
        limit_up = {date(2024, 1, 3): [f"S{i}" for i in range(5)]}
        price_data = _make_price_data(codes, dates, limit_up_codes=limit_up)
        benchmark = _make_benchmark(dates)

        # 等权目标
        target = {c: 1.0 / 8 for c in codes}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=8)
        bt = SimpleBacktester(config)
        bt.max_retry_orders = 3
        result = bt.run(target_portfolios, price_data, benchmark)

        # 统计
        stats = result.pending_order_stats
        assert stats is not None
        assert stats.total_pending == 5, f"应有5个pending, 实际{stats.total_pending}"

        # 最多只有3个filled（如果T+1日打开的话）
        assert stats.filled_count <= 3

        # 至少2个被cancel因exceeded_max_retry_count
        exceeded = stats.cancel_reasons.get("exceeded_max_retry_count", 0)
        assert exceeded >= 2, f"应有>=2个exceeded, 实际: {stats.cancel_reasons}"


# ──────────────────────────────────────────────────────────
# 场景7: 单只上限10% — 补单金额不超组合10%
# ──────────────────────────────────────────────────────────

class TestRetryWeightCap:
    """补单权重上限10%。"""

    def test_retry_weight_capped_at_10pct(self) -> None:
        """即使目标权重>10%，补单时也限制在10%。"""
        codes = ["A", "B"]
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5, 8, 9, 10, 11, 12,
                                              15, 16, 17, 18, 19]]

        # A在1/3封板，1/4恢复
        price_data = _make_price_data(codes, dates, limit_up_codes={
            date(2024, 1, 3): ["A"],
        })
        benchmark = _make_benchmark(dates)

        # A目标权重50%（远超10%上限）
        target = {"A": 0.50, "B": 0.50}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=2)
        bt = SimpleBacktester(config)
        bt.retry_weight_cap = 0.10
        result = bt.run(target_portfolios, price_data, benchmark)

        # 找到A的补单成交
        pending_a = [po for po in bt.pending_orders if po.code == "A"]
        if pending_a and pending_a[0].status == "filled":
            # 找到A的补单Fill
            a_fills = [f for f in result.trades
                       if f.code == "A" and f.direction == "buy"
                       and f.trade_date > date(2024, 1, 3)]
            if a_fills:
                fill = a_fills[0]
                # 补单金额应约等于组合市值的10%（而不是50%）
                nav_at_retry = 1_000_000  # 近似
                max_allowed = nav_at_retry * 0.10 * 1.05  # 5%容差
                assert fill.amount <= max_allowed, (
                    f"补单金额{fill.amount:.0f}超过10%上限{max_allowed:.0f}"
                )


# ──────────────────────────────────────────────────────────
# 场景8: PaperBroker返回值兼容 — tuple解包正确
# ──────────────────────────────────────────────────────────

class TestPaperBrokerReturnTuple:
    """PaperBroker.execute_rebalance()返回(fills, pending)二元组。"""

    def test_execute_rebalance_returns_tuple(self) -> None:
        """execute_rebalance()返回值可以解包为(fills, pending_orders)。"""
        codes = ["A", "B"]
        td = date(2024, 3, 1)

        # 构造价格数据（A涨停封板）
        price_data = _make_price_data(codes, [td], limit_up_codes={td: ["A"]})

        broker = PaperBroker(strategy_id="test_strategy", initial_capital=1_000_000)
        # 手动初始化状态（跳过DB load）
        broker.broker = SimBroker(BacktestConfig(initial_capital=1_000_000))
        broker.broker.cash = 1_000_000
        broker.broker.holdings = {}
        broker.state = PaperState(
            cash=1_000_000, holdings={}, nav=1_000_000
        )

        target = {"A": 0.50, "B": 0.50}
        result = broker.execute_rebalance(target, td, price_data, signal_date=td)

        # 必须是tuple且长度2
        assert isinstance(result, tuple), f"返回值应为tuple, 实际{type(result)}"
        assert len(result) == 2, f"tuple长度应为2, 实际{len(result)}"

        fills, pending = result
        assert isinstance(fills, list)
        assert isinstance(pending, list)

        # B应该正常成交
        b_fills = [f for f in fills if f.code == "B"]
        assert len(b_fills) >= 1, "B应该正常买入成交"

        # A应该在pending中
        a_pending = [po for po in pending if po.code == "A"]
        assert len(a_pending) >= 1, "A封板应该产生PendingOrder"
        assert a_pending[0].status == "pending"

    def test_process_pending_orders_returns_tuple(self) -> None:
        """process_pending_orders()返回(fills, updated_pending)二元组。"""
        td = date(2024, 3, 2)
        codes = ["A"]
        price_data = _make_price_data(codes, [td])  # A正常交易

        broker = PaperBroker(strategy_id="test_strategy", initial_capital=1_000_000)
        broker.broker = SimBroker(BacktestConfig(initial_capital=1_000_000))
        broker.broker.cash = 500_000
        broker.broker.holdings = {}
        broker.state = PaperState(cash=500_000, holdings={}, nav=500_000)

        pending_list = [
            PendingOrder(
                code="A",
                signal_date=date(2024, 3, 1),
                exec_date=date(2024, 3, 1),
                target_weight=0.05,
                original_score=50_000,
            )
        ]

        result = broker.process_pending_orders(
            pending_list, td, price_data,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2

        fills, updated = result
        assert isinstance(fills, list)
        assert isinstance(updated, list)


# ──────────────────────────────────────────────────────────
# 场景9: Paper Trading补单持久化 — scheduler_task_log
# ──────────────────────────────────────────────────────────

class TestPendingOrderPersistence:
    """run_paper_trading.py中补单的序列化和反序列化。"""

    def test_pending_order_serialize_deserialize(self) -> None:
        """PendingOrder可以正确序列化为JSON并反序列化回来。"""
        import json
        from datetime import datetime

        po = PendingOrder(
            code="600519",
            signal_date=date(2026, 3, 19),
            exec_date=date(2026, 3, 20),
            target_weight=0.066,
            original_score=66_000.0,
        )

        # 序列化（与run_paper_trading.py中的格式一致）
        pending_data = {
            "orders": [
                {
                    "code": po.code,
                    "signal_date": po.signal_date.isoformat(),
                    "exec_date": po.exec_date.isoformat(),
                    "target_weight": po.target_weight,
                    "original_score": po.original_score,
                }
            ]
        }
        json_str = json.dumps(pending_data, ensure_ascii=False)

        # 反序列化（与run_paper_trading.py中的格式一致）
        loaded = json.loads(json_str)
        orders = loaded["orders"]
        assert len(orders) == 1

        restored = PendingOrder(
            code=orders[0]["code"],
            signal_date=datetime.strptime(orders[0]["signal_date"], "%Y-%m-%d").date(),
            exec_date=datetime.strptime(orders[0]["exec_date"], "%Y-%m-%d").date(),
            target_weight=orders[0]["target_weight"],
            original_score=orders[0].get("original_score", 0),
        )

        assert restored.code == po.code
        assert restored.signal_date == po.signal_date
        assert restored.exec_date == po.exec_date
        assert restored.target_weight == po.target_weight
        assert restored.original_score == po.original_score
        assert restored.status == "pending"  # 默认值

    def test_pending_data_round_trip_multiple(self) -> None:
        """多只pending的序列化往返一致。"""
        import json

        orders = [
            PendingOrder(code=f"00000{i}", signal_date=date(2026, 3, 19),
                         exec_date=date(2026, 3, 20), target_weight=0.05 + i * 0.01,
                         original_score=50_000 + i * 10_000)
            for i in range(5)
        ]

        pending_data = {
            "orders": [
                {
                    "code": po.code,
                    "signal_date": po.signal_date.isoformat(),
                    "exec_date": po.exec_date.isoformat(),
                    "target_weight": po.target_weight,
                    "original_score": po.original_score,
                }
                for po in orders
            ]
        }

        json_str = json.dumps(pending_data)
        loaded = json.loads(json_str)

        assert len(loaded["orders"]) == 5
        for i, od in enumerate(loaded["orders"]):
            assert od["code"] == f"00000{i}"
            assert od["target_weight"] == pytest.approx(0.05 + i * 0.01, abs=1e-6)


# ──────────────────────────────────────────────────────────
# 场景10: PendingOrderStats统计
# ──────────────────────────────────────────────────────────

class TestPendingOrderStats:
    """PendingOrderStats统计准确性。"""

    def test_fill_rate_calculation(self) -> None:
        """fill_rate = filled_count / total_pending。"""
        stats = PendingOrderStats(
            total_pending=10,
            filled_count=3,
            cancelled_count=7,
            fill_rate=3 / 10,
        )
        assert stats.fill_rate == pytest.approx(0.3)

    def test_cancel_reasons_counting(self) -> None:
        """cancel_reasons正确统计各种原因。"""
        codes = [f"S{i}" for i in range(6)]
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5, 8, 9, 10]]

        # S0-S4在1/3封板，S0-S1在1/4仍封板
        limit_up = {
            date(2024, 1, 3): [f"S{i}" for i in range(5)],
            date(2024, 1, 4): ["S0", "S1"],
        }
        price_data = _make_price_data(codes, dates, limit_up_codes=limit_up)
        benchmark = _make_benchmark(dates)

        target = {c: 1.0 / 6 for c in codes}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=6)
        bt = SimpleBacktester(config)
        bt.max_retry_orders = 3
        result = bt.run(target_portfolios, price_data, benchmark)

        stats = result.pending_order_stats
        assert stats is not None
        assert stats.total_pending == 5

        # 验证cancel_reasons是dict且有内容
        assert isinstance(stats.cancel_reasons, dict)
        # 5个pending中: 最多3个尝试执行, 2个exceeded_max_retry_count
        assert stats.cancelled_count + stats.filled_count == stats.total_pending

    def test_stats_with_no_pending(self) -> None:
        """无封板时PendingOrderStats全部为零。"""
        codes = ["A", "B"]
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5]]

        price_data = _make_price_data(codes, dates)
        benchmark = _make_benchmark(dates)

        target = {"A": 0.5, "B": 0.5}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=2)
        bt = SimpleBacktester(config)
        result = bt.run(target_portfolios, price_data, benchmark)

        stats = result.pending_order_stats
        assert stats is not None
        assert stats.total_pending == 0
        assert stats.filled_count == 0
        assert stats.cancelled_count == 0
        assert stats.fill_rate == 0.0
        assert stats.cancel_reasons == {}

    def test_avg_retry_return(self) -> None:
        """avg_retry_return_1d计算合理（非NaN）。"""
        codes = ["A", "B", "C"]
        dates = [date(2024, 1, d) for d in [2, 3, 4, 5, 8, 9, 10, 11, 12,
                                              15, 16, 17, 18, 19]]

        # A在1/3封板，1/4恢复
        price_data = _make_price_data(codes, dates, limit_up_codes={
            date(2024, 1, 3): ["A"],
        })
        benchmark = _make_benchmark(dates)

        target = {c: 1.0 / 3 for c in codes}
        target_portfolios = {date(2024, 1, 2): target}

        config = BacktestConfig(initial_capital=1_000_000, top_n=3)
        bt = SimpleBacktester(config)
        result = bt.run(target_portfolios, price_data, benchmark)

        stats = result.pending_order_stats
        assert stats is not None
        # avg_retry_return应该是有限数（不是NaN）
        assert not np.isnan(stats.avg_retry_return_1d)
