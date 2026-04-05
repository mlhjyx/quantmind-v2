"""A3/A5/A7/A10 修复验证测试。

A3: turnover_rate NULL → can_trade() 返回 True（不因数据缺失误拒交易）
A5: 单笔成交额超过 daily_amount * 10% → 截断到上限（部分成交）
A7: update_nav_sync 传入 avg_costs 时正确写入 unrealized_pnl / avg_cost
A10: 相同输入两次运行回测结果完全一致（mergesort 确定性）
"""

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from engines.backtest_engine import (
    BacktestConfig,
    SimBroker,
    SimpleBacktester,
)

# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def base_config() -> BacktestConfig:
    return BacktestConfig(
        initial_capital=1_000_000,
        slippage_mode="fixed",
        slippage_bps=0,
        volume_cap_pct=0.10,
    )


@pytest.fixture
def broker(base_config) -> SimBroker:
    return SimBroker(base_config)


def _make_row(**kwargs) -> pd.Series:
    defaults = {
        "close": 10.0,
        "pre_close": 10.0,
        "volume": 1_000_000,
        "turnover_rate": 5.0,
        "amount": 100_000,  # 千元 → 1亿元
        "open": 10.0,
        "trade_date": date(2024, 1, 2),
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


# ============================================================
# A3: turnover_rate NULL 修复
# ============================================================

class TestA3TurnoverNullFix:
    """A3: turnover_rate 为 NULL/NaN 时不误判为封板。"""

    def test_turnover_none_not_blocked_buy(self, broker):
        """turnover_rate=None → 高换手默认值(999) → 买入不被封板。"""
        row = _make_row(close=10.0, pre_close=10.0, turnover_rate=None)
        assert broker.can_trade("600519.SH", "buy", row) is True

    def test_turnover_nan_not_blocked_buy(self, broker):
        """turnover_rate=NaN → 高换手默认值(999) → 买入不被封板。"""
        row = _make_row(close=10.0, pre_close=10.0, turnover_rate=float("nan"))
        assert broker.can_trade("600519.SH", "buy", row) is True

    def test_turnover_nan_not_blocked_sell(self, broker):
        """turnover_rate=NaN → 卖出也不被封板。"""
        row = _make_row(close=10.0, pre_close=10.0, turnover_rate=float("nan"))
        assert broker.can_trade("600519.SH", "sell", row) is True

    def test_turnover_null_near_limit_price_still_allowed(self, broker):
        """收盘价接近涨停价 + turnover_rate=NaN → 默认高换手 → 允许（未封死）。"""
        # close=11.0 ≈ 涨停价(10% limit), 但 turnover=NaN 默认999 → 未封板
        row = _make_row(close=11.0, pre_close=10.0, turnover_rate=float("nan"))
        assert broker.can_trade("000001.SZ", "buy", row) is True

    def test_turnover_low_still_blocks(self, broker):
        """正常低换手+涨停价 → 仍然被封板（验证正常路径不受影响）。"""
        row = _make_row(close=11.0, pre_close=10.0, turnover_rate=0.5)
        assert broker.can_trade("000001.SZ", "buy", row) is False

    def test_turnover_missing_key_not_blocked(self, broker):
        """行情行中完全没有 turnover_rate 键 → 默认999 → 不封板。"""
        row = pd.Series({"close": 10.0, "pre_close": 10.0, "volume": 500_000,
                         "amount": 100_000, "open": 10.0})
        assert broker.can_trade("600519.SH", "buy", row) is True


# ============================================================
# A5: 成交量约束（volume cap）
# ============================================================

class TestA5VolumeCap:
    """A5: 单笔成交额不超过当日成交额的 volume_cap_pct。"""

    def test_buy_within_cap_passes(self, broker):
        """正常买入金额不超上限 → 不截断。"""
        # daily_amount=100_000千元=1亿元, cap=10%=1000万元
        # target=500万元 < 1000万元 → 不截断
        row = _make_row(amount=100_000, open=10.0)
        fill = broker.execute_buy("000001.SZ", 5_000_000, row)
        assert fill is not None
        # 买入金额应 ≤ 5_000_000（不截断，或因整手约束略少）
        assert fill.amount <= 5_050_000  # 允许滑点偏差

    def test_buy_exceeds_cap_truncated(self, broker):
        """大额买入超过10%成交额上限 → 截断到上限。"""
        # daily_amount=1_000千元=100万元, cap=10%=10万元
        # target=50万元 >> 10万元 → 截断到10万元
        row = _make_row(amount=1_000, open=10.0)  # 1000千元=100万元
        fill = broker.execute_buy("000001.SZ", 500_000, row)
        if fill is not None:
            # 成交金额应≤ 10万元 * (1 + epsilon)
            assert fill.amount <= 110_000, \
                f"超过cap的买入应被截断，实际成交={fill.amount:.0f}元"

    def test_sell_exceeds_cap_truncated(self, base_config):
        """大额卖出超过10%成交额上限 → 截断股数。"""
        broker = SimBroker(base_config)
        broker.holdings["000001.SZ"] = 100_000  # 持有10万股
        broker.cash = 0

        # daily_amount=1_000千元=100万元, cap=10%=10万元 → max_shares=10000
        row = _make_row(amount=1_000, open=10.0)
        fill = broker.execute_sell("000001.SZ", 50_000, row)  # 试图卖5万股
        if fill is not None:
            assert fill.shares <= 10_100, \
                f"超过cap的卖出应被截断, 实际={fill.shares}股"

    def test_missing_amount_skips_cap(self, broker):
        """daily_amount 数据缺失 → 跳过 volume cap 检查。"""
        row = pd.Series({"close": 10.0, "pre_close": 10.0, "volume": 500_000,
                         "turnover_rate": 5.0, "open": 10.0,
                         "trade_date": date(2024, 1, 2)})
        # 无 amount 字段，应正常执行不报错
        fill = broker.execute_buy("000001.SZ", 500_000, row)
        # 不因缺少amount而崩溃，fill可能为None(资金不足)或正常
        assert fill is None or fill.shares > 0

    def test_zero_cap_disables_check(self):
        """volume_cap_pct=0.0 → 禁用成交量检查。"""
        config = BacktestConfig(
            initial_capital=1_000_000,
            slippage_mode="fixed",
            slippage_bps=0,
            volume_cap_pct=0.0,
        )
        broker = SimBroker(config)
        # 即使超过，也不截断
        row = _make_row(amount=1_000, open=10.0)
        fill = broker.execute_buy("000001.SZ", 500_000, row)
        if fill is not None:
            assert fill.amount > 100_000  # 不被截断（资金允许范围内）

    def test_daily_amount_yuan_helper(self, broker):
        """_daily_amount_yuan: 千元→元转换正确。"""
        row_qian = _make_row(amount=1_000)   # 千元 → 100万元
        assert abs(broker._daily_amount_yuan(row_qian) - 1_000_000) < 1

        row_none = pd.Series({"close": 10.0})
        assert broker._daily_amount_yuan(row_none) == 0.0


# ============================================================
# A7: unrealized_pnl / avg_cost 写入
# ============================================================

class TestA7UnrealizedPnl:
    """A7: update_nav_sync 正确计算并写入 avg_cost / unrealized_pnl。"""

    def _make_mock_conn(self):
        """构造 mock psycopg2 连接。"""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        # fetchone 默认返回 (初始资金,) 作为 prev_nav/peak_nav
        cur.fetchone.side_effect = [
            None,              # prev_nav (无历史)
            (1_000_000.0,),    # peak_nav
        ]
        return conn, cur

    def test_avg_cost_written_when_provided(self):
        """avg_costs 提供时 → INSERT 包含 avg_cost 和 unrealized_pnl。"""
        from app.services.paper_trading_service import PaperTradingService

        conn, cur = self._make_mock_conn()
        holdings = {"000001.SZ": 1000}
        prices = {"000001.SZ": 12.0}
        avg_costs = {"000001.SZ": 10.0}  # 成本10元/股

        PaperTradingService.update_nav_sync(
            conn=conn,
            strategy_id="test-strategy-id",
            trade_date=date(2024, 1, 5),
            holdings=holdings,
            prices=prices,
            cash=0.0,
            initial_capital=1_000_000.0,
            avg_costs=avg_costs,
        )

        # 检查 INSERT 调用中包含 avg_cost 和 unrealized_pnl
        insert_calls = [c for c in cur.execute.call_args_list
                        if "INSERT INTO position_snapshot" in str(c)]
        assert len(insert_calls) == 1

        # 参数中应包含 avg_cost=10.0 和 unrealized_pnl=(12000-10000)=2000
        args = insert_calls[0][0][1]  # (sql, params)
        assert 10.0 in args, f"avg_cost=10.0 应在 INSERT 参数中，实际={args}"
        assert 2000.0 in args, f"unrealized_pnl=2000.0 应在 INSERT 参数中，实际={args}"

    def test_avg_cost_null_when_not_provided(self):
        """avg_costs=None → INSERT 中 avg_cost=None, unrealized_pnl=None。"""
        from app.services.paper_trading_service import PaperTradingService

        conn, cur = self._make_mock_conn()
        holdings = {"000001.SZ": 1000}
        prices = {"000001.SZ": 12.0}

        PaperTradingService.update_nav_sync(
            conn=conn,
            strategy_id="test-strategy-id",
            trade_date=date(2024, 1, 5),
            holdings=holdings,
            prices=prices,
            cash=0.0,
            initial_capital=1_000_000.0,
            # avg_costs 未传入 → 向后兼容
        )

        insert_calls = [c for c in cur.execute.call_args_list
                        if "INSERT INTO position_snapshot" in str(c)]
        assert len(insert_calls) == 1
        args = insert_calls[0][0][1]
        # avg_cost 和 unrealized_pnl 应为 None
        none_count = sum(1 for a in args if a is None)
        assert none_count >= 2, f"avg_cost/unrealized_pnl 应为 None，参数={args}"

    def test_zero_avg_cost_unrealized_pnl_null(self):
        """avg_cost=0 → unrealized_pnl=NULL（避免除零）。"""
        from app.services.paper_trading_service import PaperTradingService

        conn, cur = self._make_mock_conn()
        holdings = {"000001.SZ": 1000}
        prices = {"000001.SZ": 12.0}
        avg_costs = {"000001.SZ": 0.0}  # 0成本

        PaperTradingService.update_nav_sync(
            conn=conn,
            strategy_id="test-strategy-id",
            trade_date=date(2024, 1, 5),
            holdings=holdings,
            prices=prices,
            cash=0.0,
            initial_capital=1_000_000.0,
            avg_costs=avg_costs,
        )

        insert_calls = [c for c in cur.execute.call_args_list
                        if "INSERT INTO position_snapshot" in str(c)]
        args = insert_calls[0][0][1]
        # avg_cost=0 → 跳过，写入 None
        none_count = sum(1 for a in args if a is None)
        assert none_count >= 2


# ============================================================
# A10: 回测确定性排序
# ============================================================

def _build_determinism_data() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """构造标准回测数据（相同输入两次运行应产生相同结果）。"""
    dates = [date(2024, 1, d) for d in range(2, 20) if date(2024, 1, d).weekday() < 5]
    codes = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ",
             "300001.SZ", "300002.SZ", "600001.SH", "600002.SH", "600003.SH"]

    np.random.seed(777)
    rows = []
    for d in dates:
        for code in codes:
            pre_close = 10.0 + np.random.uniform(-1, 1)
            close = pre_close * (1 + np.random.uniform(-0.05, 0.05))
            rows.append({
                "code": code,
                "trade_date": d,
                "open": pre_close * 1.001,
                "close": close,
                "pre_close": pre_close,
                "volume": int(np.random.uniform(500_000, 2_000_000)),
                "amount": float(np.random.uniform(5_000, 50_000)),  # 千元
                "turnover_rate": float(np.random.uniform(1, 10)),
                "total_mv": float(np.random.uniform(10_000, 100_000)),
                "volatility_20": float(np.random.uniform(20, 40)),
            })

    price_data = pd.DataFrame(rows)

    benchmark_dates = dates
    benchmark = pd.DataFrame({
        "trade_date": benchmark_dates,
        "close": [100.0 + i * 0.2 for i in range(len(benchmark_dates))],
    })

    # 信号: 每次调仓买等权
    signal_dates = dates[::5]
    target = {}
    for sd in signal_dates:
        weight = 1.0 / 5
        target[sd] = {c: weight for c in codes[:5]}

    return target, price_data, benchmark


class TestA10Determinism:
    """A10: mergesort确保回测结果确定性。"""

    def test_backtest_same_input_same_output_hash(self):
        """相同输入两次运行, trades列表完全一致。"""
        config = BacktestConfig(
            initial_capital=1_000_000,
            slippage_mode="fixed",
            slippage_bps=5,
            volume_cap_pct=0.0,  # 禁用vol cap避免干扰
        )
        target, price_data, benchmark = _build_determinism_data()

        # 第一次运行
        engine1 = SimpleBacktester(config)
        result1 = engine1.run(target, price_data.copy(), benchmark.copy())

        # 第二次运行（相同输入）
        engine2 = SimpleBacktester(config)
        result2 = engine2.run(target, price_data.copy(), benchmark.copy())

        # 交易记录应完全一致
        assert len(result1.trades) == len(result2.trades), \
            f"两次运行交易数量不同: {len(result1.trades)} vs {len(result2.trades)}"

        # 每笔交易的关键字段一致
        for i, (t1, t2) in enumerate(zip(result1.trades, result2.trades, strict=False)):
            assert t1.code == t2.code, f"第{i}笔: code不同 {t1.code} vs {t2.code}"
            assert t1.trade_date == t2.trade_date, f"第{i}笔: date不同"
            assert abs(t1.shares - t2.shares) == 0, f"第{i}笔: shares不同"
            assert abs(t1.price - t2.price) < 1e-9, f"第{i}笔: price不同"

    def test_backtest_nav_series_deterministic(self):
        """NAV序列两次运行完全一致。"""
        config = BacktestConfig(
            initial_capital=1_000_000,
            slippage_mode="fixed",
            slippage_bps=5,
            volume_cap_pct=0.0,
        )
        target, price_data, benchmark = _build_determinism_data()

        engine1 = SimpleBacktester(config)
        r1 = engine1.run(target, price_data.copy(), benchmark.copy())

        engine2 = SimpleBacktester(config)
        r2 = engine2.run(target, price_data.copy(), benchmark.copy())

        assert len(r1.daily_nav) == len(r2.daily_nav)
        for d in r1.daily_nav.index:
            assert abs(r1.daily_nav[d] - r2.daily_nav[d]) < 1e-6, \
                f"{d}: NAV不一致 {r1.daily_nav[d]} vs {r2.daily_nav[d]}"

    def test_price_data_sort_is_stable(self):
        """相同 (trade_date, code) 的行在 sort 后顺序稳定。"""
        df = pd.DataFrame([
            {"trade_date": date(2024, 1, 2), "code": "000001.SZ", "close": 10.0, "seq": 1},
            {"trade_date": date(2024, 1, 2), "code": "000001.SZ", "close": 10.0, "seq": 2},
            {"trade_date": date(2024, 1, 2), "code": "000002.SZ", "close": 11.0, "seq": 3},
        ])
        sorted_df = df.sort_values(["trade_date", "code"], kind="mergesort")
        # 相同(date, code)的行应保持插入顺序
        same_rows = sorted_df[sorted_df["code"] == "000001.SZ"]["seq"].tolist()
        assert same_rows == [1, 2], f"mergesort 应保持原始顺序，实际={same_rows}"
