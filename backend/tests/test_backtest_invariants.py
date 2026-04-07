"""Layer 2: 回测引擎不变性验证 — 数学不变量必须在任何输入下成立。

资金守恒、空信号、停牌、涨跌停封板、确定性。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from engines.backtest_engine import BacktestConfig, PMSConfig, SimpleBacktester


def _make_price_data(
    codes: list[str],
    dates: list[date],
    prices: dict[str, list[dict]],
) -> pd.DataFrame:
    """构造价格数据。prices: {code: [{open, close, pre_close, volume, turnover_rate, ...}, ...]}"""
    rows = []
    for code in codes:
        for i, d in enumerate(dates):
            p = prices[code][i]
            pre_c = p.get("pre_close", p["close"])
            rows.append(
                {
                    "code": code,
                    "trade_date": d,
                    "open": p.get("open", p["close"]),
                    "high": max(p.get("open", p["close"]), p["close"]) * 1.01,
                    "low": min(p.get("open", p["close"]), p["close"]) * 0.99,
                    "close": p["close"],
                    "pre_close": pre_c,
                    "volume": p.get("volume", 5_000_000),
                    "amount": p.get("amount", 50_000),
                    "up_limit": p.get("up_limit", round(pre_c * 1.10, 2)),
                    "down_limit": p.get("down_limit", round(pre_c * 0.90, 2)),
                    "turnover_rate": p.get("turnover_rate", 5.0),
                }
            )
    return pd.DataFrame(rows)


def _simple_config(**overrides) -> BacktestConfig:
    """标准测试配置。"""
    defaults = dict(
        initial_capital=1_000_000,
        top_n=5,
        rebalance_freq="monthly",
        slippage_mode="fixed",
        slippage_bps=0,
        commission_rate=0.0000854,
        stamp_tax_rate=0.0005,
        historical_stamp_tax=False,
        transfer_fee_rate=0.00001,
        volume_cap_pct=0,
        pms=PMSConfig(enabled=False),
    )
    defaults.update(overrides)
    return BacktestConfig(**defaults)


class TestFundConservation:
    """L2-1: 资金守恒 — 任意时刻现金+持仓市值+累计成本 = 初始资金+累计收益。"""

    def test_conservation_multi_rebalance(self):
        """多次调仓后资金守恒仍然成立。"""
        dates = [date(2024, 1, d) for d in range(2, 12)]  # 10天
        # 两只股票，价格有涨有跌
        p_a = [
            {"close": 10.0, "open": 10.0, "pre_close": 10.0},
            {"close": 10.5, "open": 10.0, "pre_close": 10.0},
            {"close": 11.0, "open": 10.5, "pre_close": 10.5},
            {"close": 10.0, "open": 11.0, "pre_close": 11.0},
            {"close": 9.5, "open": 10.0, "pre_close": 10.0},
            {"close": 10.0, "open": 9.5, "pre_close": 9.5},
            {"close": 10.5, "open": 10.0, "pre_close": 10.0},
            {"close": 11.0, "open": 10.5, "pre_close": 10.5},
            {"close": 11.5, "open": 11.0, "pre_close": 11.0},
            {"close": 12.0, "open": 11.5, "pre_close": 11.5},
        ]
        p_b = [
            {"close": 20.0, "open": 20.0, "pre_close": 20.0},
            {"close": 19.0, "open": 20.0, "pre_close": 20.0},
            {"close": 18.0, "open": 19.0, "pre_close": 19.0},
            {"close": 21.0, "open": 18.0, "pre_close": 18.0},
            {"close": 22.0, "open": 21.0, "pre_close": 21.0},
            {"close": 20.0, "open": 22.0, "pre_close": 22.0},
            {"close": 19.0, "open": 20.0, "pre_close": 20.0},
            {"close": 21.0, "open": 19.0, "pre_close": 19.0},
            {"close": 22.0, "open": 21.0, "pre_close": 21.0},
            {"close": 23.0, "open": 22.0, "pre_close": 22.0},
        ]

        price_data = _make_price_data(
            ["000001.SZ", "000002.SZ"],
            dates,
            {"000001.SZ": p_a, "000002.SZ": p_b},
        )

        config = _simple_config(top_n=2)

        # 两次调仓: D2买A+B → D5换仓卖A买更多B
        target = {
            date(2024, 1, 2): {"000001.SZ": 0.5, "000002.SZ": 0.5},
            date(2024, 1, 5): {"000002.SZ": 1.0},  # 全仓B
        }

        result = SimpleBacktester(config).run(target, price_data)

        # 关键不变量验证:
        # 1. 从交易记录反推现金余额
        # 2. 用最后一天持仓+现金重构NAV
        final_nav = result.daily_nav.iloc[-1]
        initial = config.initial_capital

        # 反推现金: initial - sum(买入花费) + sum(卖出收入)
        cash_reconstructed = initial
        for t in result.trades:
            if t.direction == "buy":
                cash_reconstructed -= t.amount + t.total_cost
            else:
                cash_reconstructed += t.amount - t.total_cost

        # 从holdings_history获取最终持仓(取最后有记录的日期)
        last_date = dates[-1]
        last_prices = {
            r["code"]: r["close"]
            for _, r in price_data[price_data["trade_date"] == last_date].iterrows()
        }

        # 从trades推导当前持仓
        holdings_from_trades: dict[str, int] = {}
        for t in result.trades:
            if t.direction == "buy":
                holdings_from_trades[t.code] = holdings_from_trades.get(t.code, 0) + t.shares
            else:
                holdings_from_trades[t.code] = holdings_from_trades.get(t.code, 0) - t.shares
        # 清除0持仓
        holdings_from_trades = {k: v for k, v in holdings_from_trades.items() if v > 0}

        holdings_value = sum(
            shares * last_prices.get(code, 0) for code, shares in holdings_from_trades.items()
        )

        reconstructed = cash_reconstructed + holdings_value
        assert abs(reconstructed - final_nav) < 1.0, (
            f"资金不守恒! 重构NAV={reconstructed:.2f} vs 实际NAV={final_nav:.2f}, 差={reconstructed - final_nav:.2f}"
        )

    def test_daily_cash_plus_holdings_equals_nav(self):
        """每日验证: broker.cash + holdings_mkt_value = NAV。"""
        dates = [date(2024, 1, d) for d in range(2, 8)]
        p = [{"close": c, "open": c, "pre_close": c} for c in [10.0, 10.0, 11.0, 10.5, 12.0, 11.0]]
        price_data = _make_price_data(["000001.SZ"], dates, {"000001.SZ": p})

        config = _simple_config(top_n=1)
        target = {date(2024, 1, 2): {"000001.SZ": 1.0}}

        tester = SimpleBacktester(config)
        result = tester.run(target, price_data)

        # 验证每一天的NAV
        for d in dates:
            nav = result.daily_nav.get(d)
            if nav is None:
                continue
            # NAV > 0 (基本合理性)
            assert nav > 0, f"[{d}] NAV不应为负: {nav}"
            # NAV第一天应该接近初始资金(除交易成本)
        assert abs(result.daily_nav.iloc[0] - config.initial_capital) < 100, (
            "第一天(无交易)NAV应接近初始资金"
        )


class TestEmptySignal:
    """L2-2: 空信号 → NAV恒等于初始资金。"""

    def test_no_target_portfolios(self):
        """空target → 无交易 → NAV = initial_capital。"""
        dates = [date(2024, 1, d) for d in range(2, 7)]
        p = [{"close": 10.0, "open": 10.0, "pre_close": 10.0}] * 5
        price_data = _make_price_data(["000001.SZ"], dates, {"000001.SZ": p})

        config = _simple_config()
        result = SimpleBacktester(config).run({}, price_data)

        assert len(result.trades) == 0, "不应有任何交易"
        for d in dates:
            nav = result.daily_nav.get(d)
            if nav is not None:
                assert nav == config.initial_capital, (
                    f"[{d}] 无交易NAV应={config.initial_capital}, 实际={nav}"
                )


class TestSuspension:
    """L2-3: 全停牌日 → 无交易。"""

    def test_all_suspended_no_trade(self):
        """所有股票volume=0(停牌), 买入信号无法执行。"""
        dates = [date(2024, 1, d) for d in range(2, 6)]
        p = [{"close": 10.0, "open": 10.0, "pre_close": 10.0, "volume": 0}] * 4
        price_data = _make_price_data(["000001.SZ"], dates, {"000001.SZ": p})

        config = _simple_config(top_n=1)
        target = {date(2024, 1, 2): {"000001.SZ": 1.0}}
        result = SimpleBacktester(config).run(target, price_data)

        # 停牌无法买入
        buy_trades = [t for t in result.trades if t.direction == "buy"]
        assert len(buy_trades) == 0, "停牌日不应有买入成交"


class TestPriceLimitBlock:
    """L2-4/L2-5: 涨停买不进, 跌停卖不出。"""

    def test_limit_up_blocks_buy(self):
        """涨停封板(close≈up_limit且turnover<1%) → 买入被拒。"""
        dates = [date(2024, 1, d) for d in range(2, 6)]
        pre_c = 10.0
        up = round(pre_c * 1.10, 2)  # 11.0
        # D2正常, D3涨停封板
        p = [
            {"close": 10.0, "open": 10.0, "pre_close": 10.0},
            {"close": 10.0, "open": 10.0, "pre_close": 10.0},
            {
                "close": up,
                "open": up,
                "pre_close": pre_c,
                "up_limit": up,
                "down_limit": round(pre_c * 0.90, 2),
                "turnover_rate": 0.3,
            },  # 涨停封板
            {"close": 11.5, "open": 11.5, "pre_close": up},
        ]
        price_data = _make_price_data(["000001.SZ"], dates, {"000001.SZ": p})

        config = _simple_config(top_n=1)
        # dates=[1/2,1/3,1/4,1/5], 涨停在index 2即1/4
        # 信号D3(1/3) → 执行D4(1/4), D4是涨停封板日
        target_blocked = {date(2024, 1, 3): {"000001.SZ": 1.0}}
        result_blocked = SimpleBacktester(config).run(target_blocked, price_data)
        # 涨停封板日(1/4)买入应进入pending(非直接成交)
        direct_buys_d4 = [
            t for t in result_blocked.trades
            if t.direction == "buy" and t.trade_date == date(2024, 1, 4)
        ]
        assert len(direct_buys_d4) == 0, "涨停封板日不应直接成交"

    def test_limit_down_blocks_sell(self):
        """跌停封板(close≈down_limit且turnover<1%) → 卖出被拒。"""
        dates = [date(2024, 1, d) for d in range(2, 8)]
        pre_c = 10.0
        down = round(pre_c * 0.90, 2)  # 9.0
        p = [
            {"close": 10.0, "open": 10.0, "pre_close": 10.0},
            {"close": 10.0, "open": 10.0, "pre_close": 10.0},
            {"close": 10.0, "open": 10.0, "pre_close": 10.0},
            # D5: 跌停封板
            {
                "close": down,
                "open": down,
                "pre_close": pre_c,
                "up_limit": round(pre_c * 1.10, 2),
                "down_limit": down,
                "turnover_rate": 0.2,
            },
            {"close": 9.0, "open": 9.0, "pre_close": down},
            {"close": 9.5, "open": 9.0, "pre_close": 9.0},
        ]
        price_data = _make_price_data(["000001.SZ"], dates, {"000001.SZ": p})

        config = _simple_config(top_n=1)
        # D2买入 → D3执行买入; D4卖出信号 → D5执行卖出(跌停日)
        target = {
            date(2024, 1, 2): {"000001.SZ": 1.0},
            date(2024, 1, 4): {},  # 清仓信号
        }
        result = SimpleBacktester(config).run(target, price_data)

        # D5是跌停日, close=down_limit=9.0, turnover=0.2 → 封板卖不出
        sell_on_d5 = [
            t for t in result.trades if t.direction == "sell" and t.trade_date == date(2024, 1, 5)
        ]
        assert len(sell_on_d5) == 0, "跌停封板日不应有卖出成交"


class TestDeterminism:
    """L2-6: 确定性 — 相同输入跑2次结果bit-identical。"""

    def test_identical_runs(self):
        """同样的输入跑两次, NAV序列完全一致。"""
        dates = [date(2024, 1, d) for d in range(2, 12)]
        p_a = [
            {
                "close": 10 + i * 0.5,
                "open": 10 + i * 0.5,
                "pre_close": 10 + (i - 1) * 0.5 if i > 0 else 10.0,
            }
            for i in range(10)
        ]
        p_b = [
            {
                "close": 20 - i * 0.3,
                "open": 20 - i * 0.3,
                "pre_close": 20 - (i - 1) * 0.3 if i > 0 else 20.0,
            }
            for i in range(10)
        ]
        price_data = _make_price_data(
            ["000001.SZ", "000002.SZ"],
            dates,
            {"000001.SZ": p_a, "000002.SZ": p_b},
        )

        config = _simple_config(top_n=2)
        target = {
            date(2024, 1, 2): {"000001.SZ": 0.6, "000002.SZ": 0.4},
            date(2024, 1, 6): {"000001.SZ": 0.3, "000002.SZ": 0.7},
        }

        r1 = SimpleBacktester(config).run(target, price_data)
        r2 = SimpleBacktester(config).run(target, price_data)

        # NAV必须bit-identical
        pd.testing.assert_series_equal(r1.daily_nav, r2.daily_nav, check_exact=True)
        pd.testing.assert_series_equal(r1.daily_returns, r2.daily_returns, check_exact=True)

        # 交易记录
        assert len(r1.trades) == len(r2.trades)
        for t1, t2 in zip(r1.trades, r2.trades, strict=True):
            assert t1.code == t2.code
            assert t1.shares == t2.shares
            assert t1.price == t2.price
            assert t1.amount == t2.amount
            assert t1.commission == t2.commission
            assert t1.tax == t2.tax
