"""Layer 1: 回测引擎解析解验证 — 数学精确答案对比。

构造已知精确解的场景，验证引擎计算结果与手算一致。
如果这些测试不通过，回测引擎的基础计算逻辑存在bug。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from engines.backtest_engine import BacktestConfig, PMSConfig, SimpleBacktester


def _make_price_data(
    codes: list[str],
    dates: list[date],
    prices: dict[str, list[float]],
    opens: dict[str, list[float]] | None = None,
) -> pd.DataFrame:
    """构造synthetic价格数据。

    Args:
        codes: 股票代码列表。
        dates: 交易日列表。
        prices: {code: [close_day1, close_day2, ...]}
        opens: {code: [open_day1, ...]}，None时open=close。
    """
    rows = []
    for code in codes:
        close_list = prices[code]
        open_list = opens[code] if opens and code in opens else close_list
        for i, d in enumerate(dates):
            c = close_list[i]
            o = open_list[i]
            pre_c = close_list[i - 1] if i > 0 else o
            rows.append(
                {
                    "code": code,
                    "trade_date": d,
                    "open": o,
                    "high": max(o, c) * 1.01,
                    "low": min(o, c) * 0.99,
                    "close": c,
                    "pre_close": pre_c,
                    "volume": 5_000_000,
                    "amount": 50_000,  # 千元=5000万元
                    "up_limit": round(pre_c * 1.10, 2),
                    "down_limit": round(pre_c * 0.90, 2),
                    "turnover_rate": 5.0,
                }
            )
    return pd.DataFrame(rows)


class TestAnalyticalSolutions:
    """L1: 解析解验证 — 引擎计算结果必须与手算精确一致。"""

    def test_L1_1_single_stock_buy_hold(self):
        """单股买入持有: NAV = 初始资金 - 买入成本 + 持仓市值变化。"""
        # 场景: 100万买入10元股票, 持有5天, 价格涨到12元
        dates = [date(2024, 1, d) for d in range(2, 8)]  # 6天
        prices = {"000001.SZ": [10.0, 10.0, 10.5, 11.0, 11.5, 12.0]}
        opens = {"000001.SZ": [10.0, 10.0, 10.5, 11.0, 11.5, 12.0]}
        price_data = _make_price_data(["000001.SZ"], dates, prices, opens)

        # 固定滑点0bps, 已知费率
        config = BacktestConfig(
            initial_capital=1_000_000,
            top_n=1,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=0,
            commission_rate=0.0000854,
            stamp_tax_rate=0.0005,
            historical_stamp_tax=False,
            transfer_fee_rate=0.00001,
            volume_cap_pct=0,  # 不限制
            pms=PMSConfig(enabled=False),
        )

        # 信号: D1(1/2)发信号, D2(1/3)执行买入
        # 权重1.0 = 全仓买入
        target = {date(2024, 1, 2): {"000001.SZ": 1.0}}

        tester = SimpleBacktester(config)
        result = tester.run(target, price_data)

        # 手算:
        # D2(1/3): 买入 open=10.0, 滑点=0
        # target_amount = 1,000,000 * 1.0 = 1,000,000
        # shares = floor(1,000,000 / 10.0 / 100) * 100 = 10,000 * 100 = 100,000...
        # wait, floor(1_000_000 / 10.0 / 100) = floor(1000) = 1000, * 100 = 100,000
        # but need to account for commission in capital
        # amount = 10.0 * 100,000 = 1,000,000
        # commission = max(1,000,000 * 0.0000854, 5.0) = max(85.4, 5.0) = 85.4
        # transfer_fee = 1,000,000 * 0.00001 = 10.0
        # total_needed = 1,000,000 + 85.4 + 10.0 = 1,000,095.4 > 1,000,000
        # → 资金不足, 重算:
        # shares = floor(1,000,000 / (10.0 * (1 + 0.0000854 + 0.00001)) / 100) * 100
        # = floor(1,000,000 / 10.000954 / 100) * 100
        # = floor(999.9046...) * 100 = 999 * 100 = 99,900
        shares_expected = 99_900
        buy_amount = 10.0 * shares_expected  # = 999,000
        buy_commission = max(buy_amount * 0.0000854, 5.0)  # = max(85.31, 5) = 85.31
        buy_transfer = buy_amount * 0.00001  # = 9.99
        buy_total_cost = buy_commission + buy_transfer  # = 95.31
        cash_after_buy = 1_000_000 - buy_amount - buy_total_cost

        # D7(1/8): 持仓市值 = 99,900 * 12.0 = 1,198,800
        final_nav_expected = cash_after_buy + shares_expected * 12.0

        # 验证
        trades = result.trades
        assert len(trades) == 1, f"应该只有1笔买入, 实际{len(trades)}笔"
        assert trades[0].shares == shares_expected, (
            f"股数应为{shares_expected}, 实际{trades[0].shares}"
        )
        assert trades[0].direction == "buy"

        final_nav = result.daily_nav.iloc[-1]
        assert abs(final_nav - final_nav_expected) < 0.01, (
            f"NAV应为{final_nav_expected:.2f}, 实际{final_nav:.2f}, 差{final_nav - final_nav_expected:.4f}"
        )

    def test_L1_2_zero_cost_nav_tracks_price(self):
        """近零成本回测: NAV变化应精确等于持仓股价变化(扣除最低佣金5元)。

        注: max(amount*0, 5.0)=5.0, 最低佣金硬编码无法绕过, 这是正确行为。
        """
        dates = [date(2024, 1, d) for d in range(2, 7)]  # 5天
        # 股价: 10 → 11 → 9 → 12 → 10.5
        prices = {"000001.SZ": [10.0, 11.0, 9.0, 12.0, 10.5]}
        price_data = _make_price_data(["000001.SZ"], dates, prices)

        config = BacktestConfig(
            initial_capital=1_000_000,
            top_n=1,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=0,
            commission_rate=0,
            stamp_tax_rate=0,
            historical_stamp_tax=False,
            transfer_fee_rate=0,
            volume_cap_pct=0,
            pms=PMSConfig(enabled=False),
        )

        # D1(1/2)信号 → D2(1/3)执行, open=11.0
        target = {date(2024, 1, 2): {"000001.SZ": 1.0}}
        result = SimpleBacktester(config).run(target, price_data)

        # 最低佣金5元无法绕过: max(amount*0, 5.0) = 5.0
        # shares = floor((1,000,000 - margin) / 11.0 / 100) * 100
        # 资金不足重算: floor(1,000,000 / (11.0 * 1.0) / 100) * 100 = 90,900
        shares = 90_900
        min_commission = 5.0
        cash = 1_000_000 - 11.0 * shares - min_commission  # = 100 - 5 = 95

        # 后续每日NAV = cash + shares * close
        expected_navs = {
            date(2024, 1, 3): cash + shares * 11.0,  # 执行日
            date(2024, 1, 4): cash + shares * 9.0,
            date(2024, 1, 5): cash + shares * 12.0,
            date(2024, 1, 6): cash + shares * 10.5,
        }

        for d, expected in expected_navs.items():
            actual = result.daily_nav[d]
            assert abs(actual - expected) < 0.01, f"[{d}] NAV应为{expected:.2f}, 实际{actual:.2f}"

    def test_L1_3_stamp_tax_historical_rate(self):
        """已知印花税: 2022年卖出用0.1%, 2024年卖出用0.05%。"""
        for year, expected_rate in [(2022, 0.001), (2024, 0.0005)]:
            dates = [date(year, 6, d) for d in range(1, 5)]
            prices = {"000001.SZ": [10.0, 10.0, 10.0, 10.0]}
            price_data = _make_price_data(["000001.SZ"], dates, prices)

            config = BacktestConfig(
                initial_capital=100_000,
                top_n=1,
                rebalance_freq="monthly",
                slippage_mode="fixed",
                slippage_bps=0,
                commission_rate=0,
                historical_stamp_tax=True,
                transfer_fee_rate=0,
                volume_cap_pct=0,
                pms=PMSConfig(enabled=False),
            )

            # D1信号买入 → D2执行买入 → D2信号卖出 → D3执行卖出
            target = {
                date(year, 6, 1): {"000001.SZ": 1.0},  # 买入信号
                date(year, 6, 2): {},  # 空目标 = 全部卖出
            }
            result = SimpleBacktester(config).run(target, price_data)

            sell_trades = [t for t in result.trades if t.direction == "sell"]
            assert len(sell_trades) == 1, "应有1笔卖出"
            sell = sell_trades[0]

            expected_tax = sell.amount * expected_rate
            assert abs(sell.tax - expected_tax) < 0.01, (
                f"[{year}] 印花税应为{expected_tax:.2f}(rate={expected_rate}), 实际{sell.tax:.2f}"
            )

    def test_L1_4_min_commission_5_yuan(self):
        """最低佣金5元: 小额交易佣金应为5元而非按比例。"""
        dates = [date(2024, 1, d) for d in range(2, 6)]
        # 低价股2元, 买5000元 → 佣金=max(5000*0.0000854, 5.0)=5.0
        prices = {"600000.SH": [2.0, 2.0, 2.0, 2.0]}
        price_data = _make_price_data(["600000.SH"], dates, prices)

        config = BacktestConfig(
            initial_capital=5_000,  # 只有5000元
            top_n=1,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=0,
            commission_rate=0.0000854,
            historical_stamp_tax=False,
            stamp_tax_rate=0.0005,
            transfer_fee_rate=0,
            volume_cap_pct=0,
            pms=PMSConfig(enabled=False),
        )

        target = {date(2024, 1, 2): {"600000.SH": 1.0}}
        result = SimpleBacktester(config).run(target, price_data)

        buy_trades = [t for t in result.trades if t.direction == "buy"]
        assert len(buy_trades) == 1
        buy = buy_trades[0]

        # amount ≈ 5000 * (1 - fee_margin), commission should be 5.0 (minimum)
        assert buy.commission == 5.0, f"佣金应为最低5元, 实际{buy.commission:.4f}"

    def test_L1_5_lot_size_constraint(self):
        """整手约束: 10万买15元股 → 6600股(66手), 非6666。"""
        dates = [date(2024, 1, d) for d in range(2, 5)]
        prices = {"000002.SZ": [15.0, 15.0, 15.0]}
        price_data = _make_price_data(["000002.SZ"], dates, prices)

        config = BacktestConfig(
            initial_capital=100_000,
            top_n=1,
            rebalance_freq="monthly",
            slippage_mode="fixed",
            slippage_bps=0,
            commission_rate=0,
            historical_stamp_tax=False,
            stamp_tax_rate=0,
            transfer_fee_rate=0,
            volume_cap_pct=0,
            pms=PMSConfig(enabled=False),
        )

        target = {date(2024, 1, 2): {"000002.SZ": 1.0}}
        result = SimpleBacktester(config).run(target, price_data)

        buy = result.trades[0]
        # floor(100,000 / 15.0 / 100) * 100 = floor(666.67) * 100 = 666 * 100 = 66,600
        # wait: floor(100000 / 15 / 100) = floor(66.667) = 66, *100 = 6,600
        expected_shares = 6_600
        assert buy.shares == expected_shares, f"应买{expected_shares}股(66手), 实际{buy.shares}股"
        assert buy.shares % 100 == 0, "必须是100的整数倍"
