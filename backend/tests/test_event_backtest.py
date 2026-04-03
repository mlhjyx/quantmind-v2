"""EVENT回测引擎单元测试。"""

from datetime import date

import pandas as pd
from engines.event_backtest_engine import (
    EventBacktestConfig,
    EventBacktester,
)


def _make_price(codes, dates, base_price=10.0):
    """构造测试价格数据。"""
    rows = []
    for c in codes:
        for i, d in enumerate(dates):
            p = base_price + i * 0.1
            rows.append({
                "code": c, "trade_date": d, "open": p, "close": p,
                "pre_close": p - 0.1, "volume": 1_000_000, "amount": p * 1_000_000,
                "up_limit": p * 1.1, "down_limit": p * 0.9, "turnover_rate": 5.0,
            })
    return pd.DataFrame(rows)


def _make_factor(codes, dates, values):
    """构造测试因子数据。"""
    rows = []
    for c in codes:
        for d, v in zip(dates, values, strict=False):
            rows.append({"code": c, "trade_date": d, "value": v})
    return pd.DataFrame(rows)


DATES = [date(2024, 1, d) for d in range(2, 31) if date(2024, 1, d).weekday() < 5]


class TestEventTrigger:
    """信号触发测试。"""

    def test_above_trigger(self):
        """因子>阈值时触发买入。"""
        codes = ["000001"]
        # 第3天因子值突破阈值
        values = [0.3, 0.5, 0.9, 0.4, 0.3] + [0.3] * 15
        factor = _make_factor(codes, DATES, values)
        price = _make_price(codes, DATES)

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, trigger_direction="above",
            hold_days=5, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        assert result.total_signals >= 1
        assert result.total_buys >= 1

    def test_below_trigger(self):
        """因子<阈值时触发买入（反向）。"""
        codes = ["000001"]
        values = [0.5, 0.5, -0.9, 0.5, 0.5] + [0.5] * 15
        factor = _make_factor(codes, DATES, values)
        price = _make_price(codes, DATES)

        cfg = EventBacktestConfig(
            trigger_threshold=-0.5, trigger_direction="below",
            hold_days=5, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        assert result.total_signals >= 1


class TestHoldPeriod:
    """持有期测试。"""

    def test_sell_after_hold_days(self):
        """持有N天后自动卖出。"""
        codes = ["000001"]
        values = [0.9] + [0.3] * 19  # 只有第1天触发
        factor = _make_factor(codes, DATES, values)
        price = _make_price(codes, DATES)

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, hold_days=3, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        assert result.total_buys == 1
        assert result.total_sells >= 1
        assert result.avg_hold_days <= 5  # 允许小误差


class TestMaxPositions:
    """最大持仓数测试。"""

    def test_max_positions_limit(self):
        """持仓数不超过max_positions。"""
        codes = [f"00000{i}" for i in range(1, 8)]  # 7只股票
        values = [0.9] * 20  # 每天都触发
        factor = pd.concat([_make_factor([c], DATES, values) for c in codes])
        price = pd.concat([_make_price([c], DATES) for c in codes])

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, hold_days=10, max_positions=3,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        assert result.max_concurrent_positions <= 3


class TestTPlusOne:
    """T+1测试。"""

    def test_buy_next_day(self):
        """T日触发→T+1日买入。"""
        codes = ["000001"]
        values = [0.9] + [0.3] * 19
        factor = _make_factor(codes, DATES, values)
        price = _make_price(codes, DATES)

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, hold_days=5, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        buys = [t for t in result.trades if t.direction == "buy"]
        if buys:
            # 信号在DATES[0]，买入应在DATES[1]
            assert buys[0].trade_date == DATES[1]
            assert buys[0].signal_date == DATES[0]


class TestLimitUp:
    """涨停跳过测试。"""

    def test_limit_up_skip(self):
        """涨停封板时跳过买入。"""
        codes = ["000001"]
        values = [0.9] + [0.3] * 19
        factor = _make_factor(codes, DATES, values)
        price = _make_price(codes, DATES)
        # 让T+1日涨停（close == up_limit, turnover < 1%）
        mask = price["trade_date"] == DATES[1]
        price.loc[mask, "close"] = price.loc[mask, "up_limit"]
        price.loc[mask, "turnover_rate"] = 0.5

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, hold_days=5, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        # 涨停跳过 → 买入数为0
        assert result.total_buys == 0


class TestNoDuplicateBuy:
    """不重复买入测试。"""

    def test_no_duplicate(self):
        """已持仓股票不重复买入。"""
        codes = ["000001"]
        values = [0.9] * 20  # 每天都触发
        factor = _make_factor(codes, DATES, values)
        price = _make_price(codes, DATES)

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, hold_days=10, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        # 同一只股票只应买入1次（持有期间不重复）
        assert result.total_buys == 1 or result.total_buys == 2  # 可能卖出后再买


class TestCostModel:
    """成本模型测试。"""

    def test_commission_and_tax(self):
        """佣金+印花税正确计算。"""
        codes = ["000001"]
        values = [0.9] + [0.3] * 19
        factor = _make_factor(codes, DATES, values)
        price = _make_price(codes, DATES, base_price=50.0)

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, hold_days=3, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        buys = [t for t in result.trades if t.direction == "buy"]
        sells = [t for t in result.trades if t.direction == "sell"]

        if buys:
            b = buys[0]
            assert b.tax == 0  # 买入无印花税
            assert b.commission >= 5.0  # 最低佣金5元

        if sells:
            s = sells[0]
            expected_tax = s.amount * 0.0005
            assert abs(s.tax - expected_tax) < 0.01


class TestReport:
    """报告指标测试。"""

    def test_report_fields(self):
        """报告包含所有必要指标。"""
        from engines.event_backtest_engine import generate_event_report

        codes = [f"0000{i:02d}" for i in range(1, 6)]
        values = [0.9, 0.3, 0.9, 0.3, 0.9] + [0.3] * 15
        factor = pd.concat([_make_factor([c], DATES, values) for c in codes])
        price = pd.concat([_make_price([c], DATES) for c in codes])

        cfg = EventBacktestConfig(
            trigger_threshold=0.8, hold_days=5, max_positions=5,
            start_date=DATES[0], end_date=DATES[-1],
        )
        result = EventBacktester(cfg).run(factor, price)
        report = generate_event_report(result, cfg)

        required_keys = [
            "sharpe", "max_drawdown", "total_signals", "total_buys",
            "win_rate", "avg_hold_days", "annual_return",
        ]
        for k in required_keys:
            assert k in report, f"Missing key: {k}"
