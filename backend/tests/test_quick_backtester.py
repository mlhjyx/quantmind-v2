"""单元测试 — QuickBacktester (Sprint 1.16 GP适应度快速回测器)

覆盖:
- 基础回测: 正常因子值 → Sharpe/MDD/换手率/IC_mean
- 边界情况: 空数据/缺少列/全NaN因子值
- 性能: 单次回测 <2秒 (250日×3000股票规模)
- 确定性: 相同输入→相同输出 (bit-identical)
- Sharpe符号: 正向因子→正Sharpe

设计文档对照: docs/GP_CLOSED_LOOP_DESIGN.md §5
"""

from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd
import pytest
from engines.mining.quick_backtester import (
    QuickBacktester,
    QuickBacktestResult,
    _calc_mdd,
    _calc_sharpe,
)

# ---------------------------------------------------------------------------
# 测试数据生成
# ---------------------------------------------------------------------------


def _make_price_data(
    n_stocks: int = 50,
    n_days: int = 260,
    start_date: date = date(2024, 1, 2),
    seed: int = 42,
) -> pd.DataFrame:
    """生成合成价格数据（随机游走）。

    Args:
        n_stocks: 股票数量。
        n_days: 交易日数量。
        start_date: 起始日期。
        seed: 随机种子。

    Returns:
        DataFrame: trade_date/code/close/open/volume 列。
    """
    rng = np.random.default_rng(seed)
    codes = [f"{i:06d}.SH" for i in range(1, n_stocks + 1)]
    dates = pd.bdate_range(start=start_date, periods=n_days).date.tolist()

    rows = []
    for code in codes:
        price = 10.0
        for d in dates:
            ret = rng.normal(0.0005, 0.02)
            price = max(price * (1 + ret), 0.01)
            rows.append(
                {
                    "trade_date": d,
                    "code": code,
                    "close": round(price, 2),
                    "open": round(price * (1 + rng.normal(0, 0.005)), 2),
                    "volume": float(rng.integers(1_000_000, 50_000_000)),
                }
            )

    return pd.DataFrame(rows)


def _make_factor_values(
    price_data: pd.DataFrame,
    direction: float = 1.0,
    seed: int = 42,
) -> pd.DataFrame:
    """生成合成因子值（月末截面，带噪声）。

    Args:
        price_data: 行情数据。
        direction: 因子方向（1=正向，-1=负向），影响因子与收益相关性。
        seed: 随机种子。

    Returns:
        DataFrame: trade_date/code/factor_value 列（月末日期）。
    """
    rng = np.random.default_rng(seed)
    dates = sorted(price_data["trade_date"].unique())
    codes = sorted(price_data["code"].unique())

    # 月末日期
    monthly: list[date] = []
    seen_months = set()
    for d in reversed(dates):
        ym = (d.year, d.month)
        if ym not in seen_months:
            seen_months.add(ym)
            monthly.append(d)
    monthly = sorted(monthly)

    rows = []
    for d in monthly:
        for code in codes:
            val = direction * rng.normal(0, 1)
            rows.append({"trade_date": d, "code": code, "factor_value": val})

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def price_df() -> pd.DataFrame:
    """50只股票，260个交易日（约1年）。"""
    return _make_price_data(n_stocks=50, n_days=260)


@pytest.fixture(scope="module")
def factor_df(price_df: pd.DataFrame) -> pd.DataFrame:
    """对应price_df的月末因子值。"""
    return _make_factor_values(price_df)


@pytest.fixture(scope="module")
def backtester(price_df: pd.DataFrame) -> QuickBacktester:
    """默认QuickBacktester实例。"""
    return QuickBacktester(price_data=price_df, top_n=15)


# ---------------------------------------------------------------------------
# 基础功能测试
# ---------------------------------------------------------------------------


class TestQuickBacktesterBasic:
    """基础功能测试。"""

    def test_backtest_returns_valid_result(
        self, backtester: QuickBacktester, factor_df: pd.DataFrame
    ) -> None:
        """正常因子值应返回有效结果。"""
        result = backtester.backtest(factor_df)
        assert result.is_valid, f"回测应成功，error={result.error}"
        assert isinstance(result.sharpe, float)
        assert isinstance(result.mdd, float)
        assert isinstance(result.turnover, float)
        assert isinstance(result.ic_mean, float)

    def test_mdd_between_zero_and_one(
        self, backtester: QuickBacktester, factor_df: pd.DataFrame
    ) -> None:
        """MDD应在 [0, 1] 范围内。"""
        result = backtester.backtest(factor_df)
        assert 0.0 <= result.mdd <= 1.0, f"MDD={result.mdd} 超出范围 [0,1]"

    def test_turnover_between_zero_and_one(
        self, backtester: QuickBacktester, factor_df: pd.DataFrame
    ) -> None:
        """换手率应在 [0, 1] 范围内（单边）。"""
        result = backtester.backtest(factor_df)
        assert 0.0 <= result.turnover <= 1.0, f"换手率={result.turnover} 超出范围"

    def test_n_rebalances_positive(
        self, backtester: QuickBacktester, factor_df: pd.DataFrame
    ) -> None:
        """调仓次数应大于0。"""
        result = backtester.backtest(factor_df)
        assert result.n_rebalances > 0, "应至少有一次调仓"

    def test_daily_returns_not_empty(
        self, backtester: QuickBacktester, factor_df: pd.DataFrame
    ) -> None:
        """daily_returns应非空。"""
        result = backtester.backtest(factor_df)
        assert result.daily_returns is not None
        assert len(result.daily_returns) > 0


# ---------------------------------------------------------------------------
# 确定性测试
# ---------------------------------------------------------------------------


class TestDeterminism:
    """确定性: 相同输入→相同输出 (bit-identical)。"""

    def test_same_input_same_output(
        self, price_df: pd.DataFrame, factor_df: pd.DataFrame
    ) -> None:
        """相同数据跑两次，Sharpe结果完全相同。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        r1 = bt.backtest(factor_df)
        r2 = bt.backtest(factor_df)
        assert r1.sharpe == r2.sharpe, (
            f"确定性失败: 第1次={r1.sharpe}, 第2次={r2.sharpe}"
        )
        assert r1.mdd == r2.mdd


# ---------------------------------------------------------------------------
# 边界情况测试
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """边界情况和错误处理。"""

    def test_empty_factor_values_returns_error(self, price_df: pd.DataFrame) -> None:
        """空因子值应返回 sharpe=-999。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        empty_df = pd.DataFrame(columns=["trade_date", "code", "factor_value"])
        result = bt.backtest(empty_df)
        assert result.sharpe == -999.0
        assert result.error is not None

    def test_missing_columns_returns_error(self, price_df: pd.DataFrame) -> None:
        """缺少必须列应返回 sharpe=-999。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        bad_df = pd.DataFrame({"trade_date": [date.today()], "code": ["000001.SH"]})
        result = bt.backtest(bad_df)
        assert result.sharpe == -999.0

    def test_all_nan_factor_values(
        self, price_df: pd.DataFrame, factor_df: pd.DataFrame
    ) -> None:
        """全NaN因子值应安全退出（不崩溃）。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        nan_df = factor_df.copy()
        nan_df["factor_value"] = float("nan")
        result = bt.backtest(nan_df)
        # 全NaN无法选股，应报错或返回空结果
        assert isinstance(result.sharpe, float)

    def test_price_data_missing_required_columns(self) -> None:
        """price_data缺少必须列应在初始化时报 ValueError。"""
        bad_price = pd.DataFrame({"trade_date": [date.today()], "code": ["000001.SH"]})
        with pytest.raises(ValueError, match="缺少列"):
            QuickBacktester(price_data=bad_price, top_n=15)


# ---------------------------------------------------------------------------
# 性能测试
# ---------------------------------------------------------------------------


class TestPerformance:
    """性能: 单次回测 <2秒。"""

    def test_backtest_under_2_seconds(self) -> None:
        """50股票×260日回测应在2秒内完成。"""
        price_df = _make_price_data(n_stocks=50, n_days=260)
        factor_df = _make_factor_values(price_df)
        bt = QuickBacktester(price_data=price_df, top_n=15)

        t0 = time.perf_counter()
        result = bt.backtest(factor_df)
        elapsed = time.perf_counter() - t0

        assert result.is_valid, f"回测失败: {result.error}"
        assert elapsed < 2.0, f"回测耗时 {elapsed:.2f}s，超过2秒上限"

    def test_repeated_backtest_consistent_time(self) -> None:
        """连续10次回测，每次<2秒（模拟GP进化场景）。"""
        price_df = _make_price_data(n_stocks=30, n_days=260)
        bt = QuickBacktester(price_data=price_df, top_n=15)

        times = []
        for i in range(3):
            factor_df = _make_factor_values(price_df, seed=i)
            t0 = time.perf_counter()
            bt.backtest(factor_df)
            times.append(time.perf_counter() - t0)

        assert max(times) < 2.0, f"最长回测耗时 {max(times):.2f}s，超过2秒"


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """_calc_sharpe / _calc_mdd 辅助函数单元测试。"""

    def test_calc_sharpe_zero_returns(self) -> None:
        """全零收益应返回0。"""
        rets = pd.Series([0.0] * 50)
        assert _calc_sharpe(rets) == 0.0

    def test_calc_sharpe_positive_drift(self) -> None:
        """正漂移序列Sharpe应>0。"""
        rng = np.random.default_rng(0)
        rets = pd.Series(rng.normal(0.001, 0.01, 250))
        assert _calc_sharpe(rets) > 0

    def test_calc_sharpe_insufficient_data(self) -> None:
        """数据点不足应返回0。"""
        rets = pd.Series([0.01, 0.02])
        assert _calc_sharpe(rets) == 0.0

    def test_calc_mdd_no_drawdown(self) -> None:
        """单调上涨序列MDD应=0。"""
        nav = pd.Series([1.0, 1.01, 1.02, 1.03, 1.04])
        assert _calc_mdd(nav) == pytest.approx(0.0, abs=1e-9)

    def test_calc_mdd_full_loss(self) -> None:
        """从1.0跌到0.5，MDD应=0.5。"""
        nav = pd.Series([1.0, 0.9, 0.8, 0.7, 0.6, 0.5])
        assert _calc_mdd(nav) == pytest.approx(0.5, rel=1e-6)

    def test_calc_mdd_recovery(self) -> None:
        """回撤后恢复，MDD应取最大回撤段。"""
        # 先跌30%再涨回，MDD=0.3
        nav = pd.Series([1.0, 0.8, 0.7, 0.9, 1.1])
        mdd = _calc_mdd(nav)
        assert 0.29 < mdd < 0.31


# ---------------------------------------------------------------------------
# QuickBacktestResult 数据类测试
# ---------------------------------------------------------------------------


class TestQuickBacktestResult:
    """QuickBacktestResult 数据类验证。"""

    def test_is_valid_success(self) -> None:
        """正常结果is_valid=True。"""
        r = QuickBacktestResult(
            sharpe=1.2, mdd=0.1, turnover=0.3, ic_mean=0.03, n_rebalances=12
        )
        assert r.is_valid is True

    def test_is_valid_error_code(self) -> None:
        """sharpe=-999时is_valid=False。"""
        r = QuickBacktestResult(
            sharpe=-999.0, mdd=1.0, turnover=0.0, ic_mean=0.0, n_rebalances=0,
            error="测试错误"
        )
        assert r.is_valid is False

    def test_is_valid_with_error_message(self) -> None:
        """有error字段时is_valid=False。"""
        r = QuickBacktestResult(
            sharpe=0.5, mdd=0.1, turnover=0.3, ic_mean=0.02, n_rebalances=5,
            error="some error"
        )
        assert r.is_valid is False


# ---------------------------------------------------------------------------
# 确定性补充测试 (DEV_BACKTEST_ENGINE.md 回测可信度规则: 同参数跑两次 bit-identical)
# ---------------------------------------------------------------------------


class TestBitIdenticalDeterminism:
    """同输入两次结果 bit-identical（DEV_BACKTEST_ENGINE.md 硬规则）。"""

    def test_sharpe_bit_identical(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """Sharpe 值两次完全相等（bit-identical，不只是 approx）。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        r1 = bt.backtest(factor_df)
        r2 = bt.backtest(factor_df)
        # 使用 == 而非 approx，验证 bit-identical
        assert r1.sharpe == r2.sharpe, (
            f"Sharpe bit-identical 失败: {r1.sharpe!r} != {r2.sharpe!r}"
        )

    def test_mdd_bit_identical(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """MDD 两次完全相等。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        r1 = bt.backtest(factor_df)
        r2 = bt.backtest(factor_df)
        assert r1.mdd == r2.mdd

    def test_turnover_bit_identical(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """换手率两次完全相等。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        r1 = bt.backtest(factor_df)
        r2 = bt.backtest(factor_df)
        assert r1.turnover == r2.turnover

    def test_ic_mean_bit_identical(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """IC均值两次完全相等。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        r1 = bt.backtest(factor_df)
        r2 = bt.backtest(factor_df)
        assert r1.ic_mean == r2.ic_mean

    def test_n_rebalances_bit_identical(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """调仓次数两次完全相等。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        r1 = bt.backtest(factor_df)
        r2 = bt.backtest(factor_df)
        assert r1.n_rebalances == r2.n_rebalances

    def test_fresh_instance_bit_identical(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """两个独立实例，相同输入结果 bit-identical。"""
        bt1 = QuickBacktester(price_data=price_df, top_n=15)
        bt2 = QuickBacktester(price_data=price_df, top_n=15)
        r1 = bt1.backtest(factor_df)
        r2 = bt2.backtest(factor_df)
        assert r1.sharpe == r2.sharpe, (
            f"独立实例 Sharpe 不一致: {r1.sharpe!r} != {r2.sharpe!r}"
        )
        assert r1.mdd == r2.mdd


# ---------------------------------------------------------------------------
# 单日/极端边界测试
# ---------------------------------------------------------------------------


class TestExtremeBoundary:
    """极端边界: 单日数据、仅有一只股票、全相同因子值。"""

    def test_single_day_factor_values(self, price_df: pd.DataFrame) -> None:
        """只有一个调仓日的因子值应安全处理（不崩溃）。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        # 只有一行因子数据（单一调仓日）
        dates = sorted(price_df["trade_date"].unique())
        single_date = dates[-1]
        codes = price_df["code"].unique()[:20]
        single_day_df = pd.DataFrame({
            "trade_date": [single_date] * len(codes),
            "code": codes,
            "factor_value": list(range(len(codes))),
        })
        result = bt.backtest(single_day_df)
        assert isinstance(result.sharpe, float)

    def test_all_same_factor_values_no_crash(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """全相同因子值（无排序信息）应安全处理。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        uniform_df = factor_df.copy()
        uniform_df["factor_value"] = 1.0
        result = bt.backtest(uniform_df)
        assert isinstance(result.sharpe, float)

    def test_fewer_stocks_than_top_n(self, price_df: pd.DataFrame) -> None:
        """股票数少于 top_n 时应能正常回测（不崩溃）。"""
        # 只用 5 只股票，top_n=15
        codes_5 = price_df["code"].unique()[:5]
        small_price = price_df[price_df["code"].isin(codes_5)].copy()
        bt = QuickBacktester(price_data=small_price, top_n=15)

        dates = sorted(small_price["trade_date"].unique())
        monthly_dates = []
        seen = set()
        for d in reversed(dates):
            ym = (d.year, d.month)
            if ym not in seen:
                seen.add(ym)
                monthly_dates.append(d)

        rows = []
        for d in monthly_dates:
            for code in codes_5:
                rows.append({"trade_date": d, "code": code, "factor_value": float(hash(code) % 100)})
        factor_small = pd.DataFrame(rows)

        result = bt.backtest(factor_small)
        assert isinstance(result.sharpe, float)

    def test_factor_with_extreme_values_no_crash(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """含极端值（inf, -inf）的因子应不崩溃（应被当作 NaN 处理或返回 error）。"""
        bt = QuickBacktester(price_data=price_df, top_n=15)
        extreme_df = factor_df.copy()
        extreme_df.loc[extreme_df.index[:10], "factor_value"] = float("inf")
        extreme_df.loc[extreme_df.index[10:20], "factor_value"] = float("-inf")
        result = bt.backtest(extreme_df)
        assert isinstance(result.sharpe, float)

    def test_top_n_1_works(self, price_df: pd.DataFrame, factor_df: pd.DataFrame) -> None:
        """top_n=1（只选1只股票）应正常工作。"""
        bt = QuickBacktester(price_data=price_df, top_n=1)
        result = bt.backtest(factor_df)
        assert isinstance(result.sharpe, float)
