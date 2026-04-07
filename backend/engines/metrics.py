"""回测绩效指标计算。

CLAUDE.md 回测报告必含指标:
- Sharpe, MDD, Calmar, Sortino, Beta, IR
- Bootstrap Sharpe CI
- 成本敏感性分析
- 隔夜跳空统计
- 月度热力图
- 年度分解
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import structlog

if TYPE_CHECKING:
    from engines.backtest_engine import BacktestResult

logger = structlog.get_logger(__name__)

TRADING_DAYS_PER_YEAR = 244  # A股年交易日数


@dataclass
class PerformanceReport:
    """完整的回测绩效报告。"""

    # 核心指标
    total_return: float
    annual_return: float
    sharpe_ratio: float
    autocorr_adjusted_sharpe_ratio: float  # Lo (2002) 自相关调整Sharpe
    autocorr_rho: float  # 一阶自相关系数
    max_drawdown: float
    calmar_ratio: float
    sortino_ratio: float
    beta: float
    information_ratio: float

    # 交易统计
    total_trades: int
    win_rate: float
    profit_factor: float
    profit_loss_ratio: float  # 平均盈利额 / 平均亏损额
    annual_turnover: float
    max_consecutive_loss_days: int

    # 可信度指标
    bootstrap_sharpe_ci: tuple[float, float, float]  # (point, lower, upper)
    cost_sensitivity: dict[str, dict]  # {multiplier: {sharpe, return, mdd}}

    # 跳空统计
    avg_open_gap: float  # 买入日 open vs 前日close 的平均偏差

    # 仓位偏差
    mean_position_deviation: float  # mean(|actual_w - target_w|) * 100
    max_position_deviation: float  # max(|actual_w - target_w|) * 100
    total_cash_drag: float  # (1 - sum(actual_mv) / total_capital) * 100

    # Phase 2: 新增指标
    tracking_error: float = 0.0  # 年化跟踪误差(vs benchmark)
    excess_max_drawdown: float = 0.0  # 超额收益序列最大回撤
    max_dd_duration: int = 0  # 最长水下天数
    deflated_sharpe: float = 0.0  # DSR p-value (Bailey & Lopez de Prado 2014)
    num_trials: int = 0  # M = 多重测试次数
    sub_periods: dict = field(default_factory=dict)  # 子期间分析 {period: metrics}

    # 年度分解
    annual_breakdown: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())

    # 月度热力图数据
    monthly_returns: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())

    # 警告标志（有默认值，放最后）
    warning_negative_ci: bool = False  # Bootstrap CI 5%分位 < 0
    warning_cost_sensitive: bool = False  # 2x成本下Sharpe < 0.5
    warning_dsr_insignificant: bool = False  # DSR > 0.05 (Sharpe不显著)

    def to_dict(self) -> dict:
        """输出回测报告为标准dict（API/存储用）。"""
        ci_point, ci_lower, ci_upper = self.bootstrap_sharpe_ci
        return {
            "total_return": self.total_return,
            "annual_return": self.annual_return,
            "sharpe": self.sharpe_ratio,
            "autocorr_adjusted_sharpe": self.autocorr_adjusted_sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "calmar_ratio": self.calmar_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_consecutive_loss_days": self.max_consecutive_loss_days,
            "win_rate": self.win_rate,
            "profit_loss_ratio": self.profit_loss_ratio,
            "beta": self.beta,
            "information_ratio": self.information_ratio,
            "annual_turnover": self.annual_turnover,
            "sharpe_ci_lower": ci_lower,
            "sharpe_ci_upper": ci_upper,
            "avg_overnight_gap": self.avg_open_gap,
            "position_deviation": self.mean_position_deviation,
            "cost_sensitivity": self.cost_sensitivity,
            "tracking_error": self.tracking_error,
            "excess_max_drawdown": self.excess_max_drawdown,
            "max_dd_duration": self.max_dd_duration,
            "deflated_sharpe": self.deflated_sharpe,
            "num_trials": self.num_trials,
            "sub_periods": self.sub_periods,
            "warning_negative_ci": self.warning_negative_ci,
            "warning_cost_sensitive": self.warning_cost_sensitive,
            "warning_dsr_insignificant": self.warning_dsr_insignificant,
        }


def deflated_sharpe_ratio(
    observed_sr: float,
    num_trials: int,
    T: int,
    skew: float,
    kurtosis: float,
) -> float:
    """Deflated Sharpe Ratio — Bailey & Lopez de Prado (2014)。

    检测多重测试下Sharpe是否显著高于随机预期。
    DSR < 0.05 → Sharpe在M次测试中仍然显著（非运气）。

    Args:
        observed_sr: 观察到的年化Sharpe（已除以sqrt(252)标准化为日频）。
        num_trials: M = 累计测试次数(FACTOR_TEST_REGISTRY总数)。
        T: 观察天数。
        skew: 日收益偏度。
        kurtosis: 日收益峰度(excess kurtosis + 3 = raw kurtosis)。
    """
    from math import e, sqrt

    from scipy.stats import norm

    euler_mascheroni = 0.5772156649

    if T <= 1 or num_trials <= 0:
        return 0.0

    # 标准化为日频Sharpe
    sr_daily = observed_sr / sqrt(TRADING_DAYS_PER_YEAR)

    # Sharpe标准误
    sr_std = sqrt((1 - skew * sr_daily + (kurtosis - 3) / 4 * sr_daily**2) / (T - 1))
    if sr_std < 1e-12:
        return 0.0

    # 多重测试下的期望最大Sharpe
    expected_max_sr = sr_std * (
        (1 - euler_mascheroni) * norm.ppf(1 - 1 / num_trials)
        + euler_mascheroni * norm.ppf(1 - 1 / (num_trials * e))
    )

    # DSR = P(SR* < observed | M trials)
    return float(norm.cdf((sr_daily - expected_max_sr) / sr_std))


def calc_max_dd_duration(nav: pd.Series) -> int:
    """最长水下天数（从峰值到恢复的最长时间）。"""
    peak = nav.cummax()
    underwater = peak > nav  # True = 在水下
    if not underwater.any():
        return 0

    # 找连续水下区间
    groups = (~underwater).cumsum()
    underwater_groups = groups[underwater]
    if underwater_groups.empty:
        return 0
    return int(underwater_groups.value_counts().max())


def calc_excess_max_drawdown(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> float:
    """超额收益序列的最大回撤。"""
    common = strategy_returns.index.intersection(benchmark_returns.index)
    if len(common) < 2:
        return 0.0
    excess = strategy_returns.loc[common] - benchmark_returns.loc[common]
    excess_nav = (1 + excess).cumprod()
    return calc_max_drawdown(excess_nav)


def sub_period_analysis(
    nav: pd.Series,
    benchmark_nav: pd.Series | None = None,
) -> dict[str, dict]:
    """按年度+牛熊regime拆分指标。

    Returns:
        {period_name: {return, sharpe, mdd, sortino}}
    """
    results = {}

    # 按年度 (index可能是date对象而非DatetimeIndex)
    years_list = sorted({d.year for d in nav.index})
    for year in years_list:
        mask = pd.Index([d.year == year for d in nav.index])
        year_nav = nav[mask]
        if len(year_nav) < 10:
            continue
        year_ret = year_nav.pct_change().dropna()
        ann_ret = float(year_nav.iloc[-1] / year_nav.iloc[0] - 1)
        results[f"Y{year}"] = {
            "return": round(ann_ret * 100, 2),
            "sharpe": round(calc_sharpe(year_ret), 2),
            "mdd": round(calc_max_drawdown(year_nav) * 100, 2),
            "sortino": round(calc_sortino(year_ret), 2),
        }

    # 按牛熊(基准累计收益趋势)
    if benchmark_nav is not None and len(benchmark_nav) > 20:
        common = nav.index.intersection(benchmark_nav.index)
        if len(common) > 20:
            bench_ret = benchmark_nav.loc[common].pct_change().dropna()
            bench_cum = bench_ret.cumsum()
            bull_mask = bench_cum > bench_cum.expanding().mean()

            for label, mask in [("Bull", bull_mask), ("Bear", ~bull_mask)]:
                period_nav = nav.loc[common][mask.reindex(common, fill_value=False)]
                if len(period_nav) < 10:
                    continue
                period_ret = period_nav.pct_change().dropna()
                if len(period_ret) < 5:
                    continue
                results[label] = {
                    "return": round(float((period_nav.iloc[-1] / period_nav.iloc[0] - 1) * 100), 2),
                    "sharpe": round(calc_sharpe(period_ret), 2),
                    "mdd": round(calc_max_drawdown(period_nav) * 100, 2),
                    "sortino": round(calc_sortino(period_ret), 2),
                }

    return results


def calc_sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    """计算年化Sharpe比率。"""
    if returns.std() < 1e-12:
        return 0.0
    excess = returns - rf / TRADING_DAYS_PER_YEAR
    return float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def autocorr_adjusted_sharpe(
    returns: pd.Series,
    periods_per_year: int = 12,
    rf: float = 0.0,
) -> tuple[float, float]:
    """自相关调整Sharpe（Lo 2002）。

    月度调仓策略收益序列存在正自相关时，标准Sharpe会高估真实风险调整收益。
    调整公式: adjusted_sharpe = sharpe * sqrt((1 - ρ) / (1 + ρ))

    参考: Lo, A.W. (2002). "The Statistics of Sharpe Ratios".
          Financial Analysts Journal, 58(4), 36-52.

    Args:
        returns: 收益率序列（与periods_per_year频率对应，如月度则传月度收益）。
        periods_per_year: 每年周期数（日频=244，月频=12）。
        rf: 无风险利率（年化）。

    Returns:
        (adjusted_sharpe, rho) — 调整后Sharpe和一阶自相关系数。
        如果 ρ ≤ 0，返回原始Sharpe不调整（不惩罚负自相关）。
    """
    if len(returns) < 3 or returns.std() < 1e-12:
        return 0.0, 0.0

    excess = returns - rf / periods_per_year
    raw_sharpe = float(excess.mean() / excess.std() * np.sqrt(periods_per_year))

    # 一阶自相关：Pearson corr(r_t, r_{t-1})
    rho = float(returns.autocorr(lag=1))

    # NaN（序列太短或常数）→ 无调整
    if np.isnan(rho) or rho <= 0:
        return raw_sharpe, max(rho if not np.isnan(rho) else 0.0, 0.0)

    adjusted = raw_sharpe * np.sqrt((1.0 - rho) / (1.0 + rho))
    return float(adjusted), float(rho)


def calc_max_drawdown(nav: pd.Series) -> float:
    """计算最大回撤。"""
    peak = nav.cummax()
    drawdown = (nav - peak) / peak
    return float(drawdown.min())


def calc_sortino(returns: pd.Series, rf: float = 0.0) -> float:
    """计算年化Sortino比率。"""
    excess = returns - rf / TRADING_DAYS_PER_YEAR
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() < 1e-12:
        return 0.0
    return float(excess.mean() / downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def calc_calmar(annual_return: float, max_dd: float) -> float:
    """Calmar比率 = 年化收益 / |最大回撤|。"""
    if abs(max_dd) < 1e-12:
        return 0.0
    return annual_return / abs(max_dd)


def calc_beta(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """策略Beta。"""
    aligned = pd.DataFrame({"s": strategy_returns, "b": benchmark_returns}).dropna()
    if len(aligned) < 30 or aligned["b"].var() < 1e-12:
        return 0.0
    return float(aligned["s"].cov(aligned["b"]) / aligned["b"].var())


def calc_information_ratio(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """信息比率 = 超额收益均值 / 超额收益标准差。"""
    excess = strategy_returns - benchmark_returns
    excess = excess.dropna()
    if excess.std() < 1e-12:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def calc_max_consecutive_loss_days(returns: pd.Series) -> int:
    """最大连续亏损天数。"""
    is_loss = (returns < 0).astype(int)
    groups = (is_loss != is_loss.shift()).cumsum()
    loss_groups = is_loss.groupby(groups).sum()
    return int(loss_groups.max()) if len(loss_groups) > 0 else 0


def calc_win_rate_and_profit_factor(fills: list) -> tuple[float, float, float]:
    """胜率、盈亏比和平均盈亏比（基于每次调仓的PnL）。

    Returns:
        (win_rate, profit_factor, profit_loss_ratio)
        - profit_factor: sum(wins) / sum(|losses|)（总额比）
        - profit_loss_ratio: mean(wins) / mean(|losses|)（平均额比）
    """
    if not fills:
        return 0.0, 0.0, 0.0

    # 按交易日分组计算PnL
    pnl_by_trade: dict = {}
    for f in fills:
        key = (f.code, f.trade_date)
        if key not in pnl_by_trade:
            pnl_by_trade[key] = 0
        if f.direction == "sell":
            pnl_by_trade[key] += f.amount - f.total_cost
        else:
            pnl_by_trade[key] -= f.amount + f.total_cost

    pnls = list(pnl_by_trade.values())
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / max(len(pnls), 1)
    total_win = sum(wins) if wins else 0
    total_loss = abs(sum(losses)) if losses else 1e-12
    profit_factor = total_win / total_loss

    # 平均盈亏比: mean(wins) / mean(|losses|)
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean([abs(l) for l in losses])) if losses else 1e-12
    profit_loss_ratio = avg_win / avg_loss

    return win_rate, profit_factor, profit_loss_ratio


def bootstrap_sharpe_ci(
    returns: pd.Series,
    n_bootstrap: int = 1000,
    ci: float = 0.95,
) -> tuple[float, float, float]:
    """Bootstrap Sharpe 95%置信区间。

    CLAUDE.md规则4: 如果5%分位的Sharpe < 0，标红警告。

    Returns:
        (point_estimate, lower_bound, upper_bound)
    """
    point = calc_sharpe(returns)
    rng = np.random.RandomState(42)  # 固定种子确保确定性

    sharpes = []
    n = len(returns)
    for _ in range(n_bootstrap):
        sample = returns.iloc[rng.randint(0, n, size=n)]
        sharpes.append(calc_sharpe(sample))

    lower_pct = (1 - ci) / 2
    upper_pct = 1 - lower_pct
    lower = float(np.percentile(sharpes, lower_pct * 100))
    upper = float(np.percentile(sharpes, upper_pct * 100))

    return (point, lower, upper)


def calc_annual_breakdown(nav: pd.Series, benchmark_nav: pd.Series) -> pd.DataFrame:
    """年度分解: 每年的收益/Sharpe/MDD。"""
    results = []
    years = sorted(set(d.year for d in nav.index))

    for year in years:
        mask = [d.year == year for d in nav.index]
        year_nav = nav[mask]
        if len(year_nav) < 10:
            continue

        year_ret = year_nav.pct_change().fillna(0)
        annual_ret = float(year_nav.iloc[-1] / year_nav.iloc[0] - 1)
        sharpe = calc_sharpe(year_ret)
        mdd = calc_max_drawdown(year_nav)

        # 基准 — 用年份筛选而非bool mask（长度可能不同）
        bench_mask = [d.year == year for d in benchmark_nav.index]
        bench_year = benchmark_nav[bench_mask]
        if len(bench_year) < 2:
            bench_ret = 0.0
        else:
            bench_ret = float(bench_year.iloc[-1] / bench_year.iloc[0] - 1)

        results.append(
            {
                "year": year,
                "return": round(annual_ret * 100, 2),
                "excess_return": round((annual_ret - bench_ret) * 100, 2),
                "sharpe": round(sharpe, 2),
                "mdd": round(mdd * 100, 2),
            }
        )

    return pd.DataFrame(results).set_index("year")


def calc_monthly_returns(nav: pd.Series) -> pd.DataFrame:
    """月度收益热力图数据。"""
    results = {}
    for d in nav.index:
        key = (d.year, d.month)
        if key not in results:
            results[key] = {"first": nav[d], "last": nav[d]}
        results[key]["last"] = nav[d]

    monthly = {}
    for (year, month), vals in results.items():
        ret = vals["last"] / vals["first"] - 1
        if year not in monthly:
            monthly[year] = {}
        monthly[year][month] = round(ret * 100, 2)

    return pd.DataFrame(monthly).T.sort_index()


def calc_open_gap_stats(fills: list, price_data: pd.DataFrame) -> float:
    """隔夜跳空统计(CLAUDE.md规则5)。

    买入日 open vs 前日close 的平均偏差。
    """
    if not fills:
        return 0.0

    buy_fills = [f for f in fills if f.direction == "buy"]
    if not buy_fills:
        return 0.0

    gaps = []
    for f in buy_fills:
        # 找到该股票执行日的open和前日close
        stock_data = price_data[price_data["code"] == f.code].sort_values("trade_date")
        exec_idx = stock_data[stock_data["trade_date"] == f.trade_date].index
        if len(exec_idx) == 0:
            continue
        idx = exec_idx[0]
        row_idx = stock_data.index.get_loc(idx)
        if row_idx == 0:
            continue
        prev_close = stock_data.iloc[row_idx - 1]["close"]
        exec_open = stock_data.iloc[row_idx]["open"]
        if prev_close > 0:
            gaps.append((exec_open - prev_close) / prev_close)

    return float(np.mean(gaps)) if gaps else 0.0


def calc_position_deviation(
    holdings: dict[str, int],
    target_weights: dict[str, float],
    prices: dict[str, float],
    total_value: float,
) -> dict[str, float]:
    """计算实际vs理论仓位偏差。

    输出3个指标:
    - mean_position_deviation: mean(|actual_w - target_w|) * 100
    - max_position_deviation: max(|actual_w - target_w|) * 100
    - total_cash_drag: (1 - sum(actual_mv) / total_value) * 100

    Args:
        holdings: {code: shares} 实际持仓。
        target_weights: {code: weight} 目标权重（0-1）。
        prices: {code: price} 当日收盘价。
        total_value: 组合总市值（持仓+现金）。

    Returns:
        包含三个偏差指标的dict。
    """
    if total_value <= 0 or not target_weights:
        return {
            "mean_position_deviation": 0.0,
            "max_position_deviation": 0.0,
            "total_cash_drag": 0.0,
        }

    # 所有涉及的股票
    all_codes = set(target_weights.keys()) | set(holdings.keys())

    deviations: list[float] = []
    total_holdings_mv = 0.0

    for code in all_codes:
        actual_shares = holdings.get(code, 0)
        price = prices.get(code, 0.0)
        actual_mv = actual_shares * price
        total_holdings_mv += actual_mv

        actual_w = actual_mv / total_value
        target_w = target_weights.get(code, 0.0)
        deviations.append(abs(actual_w - target_w))

    mean_dev = float(np.mean(deviations)) * 100 if deviations else 0.0
    max_dev = float(np.max(deviations)) * 100 if deviations else 0.0
    cash_drag = (1 - total_holdings_mv / total_value) * 100

    return {
        "mean_position_deviation": round(mean_dev, 4),
        "max_position_deviation": round(max_dev, 4),
        "total_cash_drag": round(cash_drag, 4),
    }


# ────────────────────── PT毕业评估专用指标 ──────────────────────


def calc_fill_rate(target_orders: int, successful_fills: int) -> float:
    """成交率: 实际成交笔数 / 目标订单笔数 × 100。

    PT毕业标准补充指标（Sprint 1.10 Task 8）。
    反映执行层的有效成交比例，低成交率表示频繁封板或流动性不足。

    Args:
        target_orders: 目标订单笔数（调仓时预期下单的股票数量）。
        successful_fills: 实际成交笔数。

    Returns:
        成交率百分比(0-100)。target_orders=0时返回100.0。
    """
    if target_orders <= 0:
        return 100.0
    return round(successful_fills / target_orders * 100, 2)


def calc_avg_slippage_pct(
    fills: list,
    signal_prices: dict[str, float],
) -> float:
    """平均滑点: mean(|actual_price - signal_price| / signal_price) × 100。

    PT毕业标准补充指标（Sprint 1.10 Task 8）。
    衡量执行价格与信号生成时价格的平均偏差，反映市场冲击和执行质量。

    Args:
        fills: Fill对象列表，需包含 code, price 字段。
        signal_prices: 信号生成时的参考价格 {code: price}。

    Returns:
        平均滑点百分比(>=0)。无有效数据时返回0.0。
    """
    if not fills or not signal_prices:
        return 0.0

    slippages = []
    for f in fills:
        sig_price = signal_prices.get(f.code, 0.0)
        if sig_price > 0 and f.price > 0:
            slip = abs(f.price - sig_price) / sig_price * 100
            slippages.append(slip)

    return round(float(np.mean(slippages)), 4) if slippages else 0.0


def calc_tracking_error(
    actual_returns: pd.Series,
    target_returns: pd.Series,
) -> float:
    """跟踪误差: annualized std(actual_ret - target_ret) × sqrt(TRADING_DAYS_PER_YEAR)。

    PT毕业标准补充指标（Sprint 1.10 Task 8）。
    衡量实际收益率与目标信号收益率的偏差波动性，
    反映执行层（整手约束/封板/滑点）对策略信号的偏离程度。

    Args:
        actual_returns: 实际日收益率序列。
        target_returns: 目标（信号端）日收益率序列，需与actual_returns对齐。

    Returns:
        年化跟踪误差百分比(>=0)。数据不足(<3天)时返回0.0。
    """
    diff = (actual_returns - target_returns).dropna()
    if len(diff) < 3:
        return 0.0
    return round(float(diff.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100), 4)


def calc_signal_execution_gap_hours(
    signal_timestamps: list,
    execution_timestamps: list,
) -> float:
    """信号生成到执行的平均时间差（小时）。

    PT毕业标准补充指标（Sprint 1.10 Task 8）。
    标准链路: T日17:20生成信号 → T+1日09:30执行 ≈ 16h。
    时间差过大（>24h）说明信号日期计算有误或执行脚本未按时运行。

    Args:
        signal_timestamps: 信号生成时间戳列表（datetime对象）。
        execution_timestamps: 对应的执行时间戳列表。

    Returns:
        平均时间差（小时），精确到0.01h。列表为空或长度不匹配时返回0.0。
    """
    if not signal_timestamps or not execution_timestamps:
        return 0.0
    if len(signal_timestamps) != len(execution_timestamps):
        return 0.0

    gaps = []
    for sig_ts, exec_ts in zip(signal_timestamps, execution_timestamps, strict=False):
        try:
            delta_hours = (exec_ts - sig_ts).total_seconds() / 3600
            if delta_hours >= 0:  # 负值说明数据异常，跳过
                gaps.append(delta_hours)
        except (TypeError, AttributeError):
            continue

    return round(float(np.mean(gaps)), 2) if gaps else 0.0


def generate_report(
    result: BacktestResult,
    price_data: pd.DataFrame | None = None,
    **kwargs,
) -> PerformanceReport:
    """生成完整绩效报告。"""
    nav = result.daily_nav
    returns = result.daily_returns
    bench_nav = result.benchmark_nav
    bench_ret = result.benchmark_returns

    # 对齐index
    common_idx = returns.index.intersection(bench_ret.index)
    returns = returns.loc[common_idx]
    bench_ret = bench_ret.loc[common_idx]

    # 核心指标
    years = len(returns) / TRADING_DAYS_PER_YEAR
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (1 / max(years, 0.01)) - 1)
    sharpe = calc_sharpe(returns)
    adj_sharpe, rho = autocorr_adjusted_sharpe(returns)
    mdd = calc_max_drawdown(nav)
    calmar = calc_calmar(annual_return, mdd)
    sortino = calc_sortino(returns)
    beta = calc_beta(returns, bench_ret)
    ir = calc_information_ratio(returns, bench_ret)

    # 交易统计
    win_rate, profit_factor, profit_loss_ratio = calc_win_rate_and_profit_factor(result.trades)
    max_loss_days = calc_max_consecutive_loss_days(returns)

    # 年化换手率
    total_turnover = result.turnover_series.sum() if not result.turnover_series.empty else 0
    annual_turnover = total_turnover / max(years, 0.01)

    # Bootstrap CI
    bs_ci = bootstrap_sharpe_ci(returns)

    # 成本敏感性 (CLAUDE.md规则6)
    cost_sens = {}
    # 这里简化: 用不同成本倍数重算Sharpe
    base_cost = (result.config.commission_rate * 2 + result.config.stamp_tax_rate) * annual_turnover
    for mult_str, mult in [("0.5x", 0.5), ("1.0x", 1.0), ("1.5x", 1.5), ("2.0x", 2.0)]:
        cost_drag = base_cost * mult / TRADING_DAYS_PER_YEAR
        adj_returns = returns - cost_drag
        cost_sens[mult_str] = {
            "annual_return": round(
                float((1 + adj_returns.sum()) ** (1 / max(years, 0.01)) - 1) * 100, 2
            ),
            "sharpe": round(calc_sharpe(adj_returns), 2),
            "mdd": round(calc_max_drawdown(nav) * 100, 2),  # MDD不受成本影响
        }

    # 跳空统计
    avg_gap = calc_open_gap_stats(result.trades, price_data) if price_data is not None else 0.0

    # 仓位偏差
    mean_pos_dev = 0.0
    max_pos_dev = 0.0
    cash_drag = 0.0

    # Phase 2: 新增指标
    # P10: tracking_error (vs benchmark)
    te = 0.0
    if len(common_idx) > 10:
        excess_ret = returns - bench_ret
        te = float(excess_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100)

    # P10: excess_max_drawdown
    excess_mdd = calc_excess_max_drawdown(returns, bench_ret) if len(common_idx) > 10 else 0.0

    # P9: max_dd_duration
    dd_duration = calc_max_dd_duration(nav)

    # P11: Deflated Sharpe Ratio
    num_trials = kwargs.get("num_trials", 69)  # M默认从FACTOR_TEST_REGISTRY
    T = len(returns)
    skew_val = float(returns.skew()) if len(returns) > 10 else 0.0
    kurt_val = float(returns.kurtosis() + 3) if len(returns) > 10 else 3.0  # raw kurtosis
    dsr = deflated_sharpe_ratio(sharpe, num_trials, T, skew_val, kurt_val)

    # P12: 子期间分析
    sub_periods = sub_period_analysis(nav, bench_nav)

    # 年度分解
    annual = calc_annual_breakdown(nav, bench_nav)

    # 月度热力图
    monthly = calc_monthly_returns(nav)

    # 警告标志
    warn_ci = bs_ci[1] < 0
    warn_cost = cost_sens.get("2.0x", {}).get("sharpe", 1.0) < 0.5
    warn_dsr = dsr > 0.05

    return PerformanceReport(
        total_return=round(total_return * 100, 2),
        annual_return=round(annual_return * 100, 2),
        sharpe_ratio=round(sharpe, 2),
        autocorr_adjusted_sharpe_ratio=round(adj_sharpe, 2),
        autocorr_rho=round(rho, 4),
        max_drawdown=round(mdd * 100, 2),
        calmar_ratio=round(calmar, 2),
        sortino_ratio=round(sortino, 2),
        beta=round(beta, 3),
        information_ratio=round(ir, 2),
        total_trades=len(result.trades),
        win_rate=round(win_rate * 100, 1),
        profit_factor=round(profit_factor, 2),
        profit_loss_ratio=round(profit_loss_ratio, 2),
        annual_turnover=round(annual_turnover, 2),
        max_consecutive_loss_days=max_loss_days,
        bootstrap_sharpe_ci=(
            round(bs_ci[0], 2),
            round(bs_ci[1], 2),
            round(bs_ci[2], 2),
        ),
        cost_sensitivity=cost_sens,
        avg_open_gap=round(avg_gap * 100, 4),
        mean_position_deviation=round(mean_pos_dev, 2),
        max_position_deviation=round(max_pos_dev, 2),
        total_cash_drag=round(cash_drag, 2),
        tracking_error=round(te, 2),
        excess_max_drawdown=round(excess_mdd * 100, 2),
        max_dd_duration=dd_duration,
        deflated_sharpe=round(dsr, 4),
        num_trials=num_trials,
        sub_periods=sub_periods,
        annual_breakdown=annual,
        monthly_returns=monthly,
        warning_negative_ci=warn_ci,
        warning_cost_sensitive=warn_cost,
        warning_dsr_insignificant=warn_dsr,
    )


def print_report(report: PerformanceReport):
    """打印回测报告到终端。"""
    print("\n" + "=" * 60)
    print("QuantMind V2 — Phase 0 回测报告")
    print("=" * 60)

    print(f"\n{'总收益':>12}: {report.total_return:>8.2f}%")
    print(f"{'年化收益':>12}: {report.annual_return:>8.2f}%")
    _adj = report.autocorr_adjusted_sharpe_ratio
    _rho = report.autocorr_rho
    print(
        f"{'Sharpe':>12}: {report.sharpe_ratio:>8.2f}"
        f"  (autocorr-adj: {_adj:.2f}, \u03c1={_rho:.2f})"
    )
    print(f"{'最大回撤':>12}: {report.max_drawdown:>8.2f}%")
    print(f"{'Calmar':>12}: {report.calmar_ratio:>8.2f}")
    print(f"{'Sortino':>12}: {report.sortino_ratio:>8.2f}")
    print(f"{'Beta':>12}: {report.beta:>8.3f}")
    print(f"{'IR':>12}: {report.information_ratio:>8.2f}")
    print(f"{'Tracking Err':>12}: {report.tracking_error:>8.2f}%")
    print(f"{'超额MDD':>12}: {report.excess_max_drawdown:>8.2f}%")
    print(f"{'水下天数':>12}: {report.max_dd_duration:>8d}")

    print("\n--- 交易统计 ---")
    print(f"{'总交易次数':>12}: {report.total_trades:>8d}")
    print(f"{'胜率':>12}: {report.win_rate:>8.1f}%")
    print(f"{'盈亏比(总额)':>12}: {report.profit_factor:>8.2f}")
    print(f"{'盈亏比(均额)':>12}: {report.profit_loss_ratio:>8.2f}")
    print(f"{'年化换手率':>12}: {report.annual_turnover:>8.2f}")
    print(f"{'最大连亏天数':>12}: {report.max_consecutive_loss_days:>8d}")

    p, lo, hi = report.bootstrap_sharpe_ci
    print("\n--- Bootstrap Sharpe CI ---")
    print(f"  Sharpe: {p:.2f} [{lo:.2f}, {hi:.2f}] (95% CI)")
    if lo < 0:
        print("  ⚠️ 警告: 5%分位Sharpe < 0，策略可能不赚钱!")

    print("\n--- 成本敏感性 ---")
    print(f"  {'成本倍数':>8}  {'年化收益':>8}  {'Sharpe':>8}  {'MDD':>8}")
    for mult, data in report.cost_sensitivity.items():
        print(
            f"  {mult:>8}  {data['annual_return']:>7.2f}%  {data['sharpe']:>8.2f}  {data['mdd']:>7.2f}%"
        )

    print("\n--- 隔夜跳空 ---")
    print(f"  买入日平均跳空: {report.avg_open_gap:.4f}%")

    print("\n--- 仓位偏差 ---")
    print(f"  {'平均偏差':>12}: {report.mean_position_deviation:>8.2f}%")
    print(f"  {'最大偏差':>12}: {report.max_position_deviation:>8.2f}%")
    print(f"  {'现金拖累':>12}: {report.total_cash_drag:>8.2f}%")

    print(f"\n--- Deflated Sharpe Ratio (M={report.num_trials}) ---")
    print(f"  DSR p-value: {report.deflated_sharpe:.4f}")
    if report.deflated_sharpe < 0.05:
        print("  ✅ Sharpe显著(p<0.05, 非多重测试运气)")
    else:
        print("  ⚠️ Sharpe不显著(p>0.05, 可能是多重测试偶然)")

    print("\n--- 年度分解 ---")
    if not report.annual_breakdown.empty:
        print(report.annual_breakdown.to_string())

    if report.sub_periods:
        print("\n--- 子期间分析 ---")
        print(f"  {'期间':<8} {'收益%':>8} {'Sharpe':>8} {'MDD%':>8} {'Sortino':>8}")
        for period, m in report.sub_periods.items():
            print(
                f"  {period:<8} {m['return']:>8.2f} {m['sharpe']:>8.2f} {m['mdd']:>8.2f} {m['sortino']:>8.2f}"
            )

    print("\n" + "=" * 60)
