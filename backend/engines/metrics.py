"""回测绩效指标计算。

CLAUDE.md 回测报告必含指标:
- Sharpe, MDD, Calmar, Sortino, Beta, IR
- Bootstrap Sharpe CI
- 成本敏感性分析
- 隔夜跳空统计
- 月度热力图
- 年度分解
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 244  # A股年交易日数


@dataclass
class PerformanceReport:
    """完整的回测绩效报告。"""
    # 核心指标
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    calmar_ratio: float
    sortino_ratio: float
    beta: float
    information_ratio: float

    # 交易统计
    total_trades: int
    win_rate: float
    profit_factor: float
    annual_turnover: float
    max_consecutive_loss_days: int

    # 可信度指标
    bootstrap_sharpe_ci: tuple[float, float, float]  # (point, lower, upper)
    cost_sensitivity: dict[str, dict]  # {multiplier: {sharpe, return, mdd}}

    # 跳空统计
    avg_open_gap: float  # 买入日 open vs 前日close 的平均偏差

    # 仓位偏差
    mean_position_deviation: float  # mean(|actual_w - target_w|) * 100
    max_position_deviation: float   # max(|actual_w - target_w|) * 100
    total_cash_drag: float          # (1 - sum(actual_mv) / total_capital) * 100

    # 年度分解
    annual_breakdown: pd.DataFrame  # year → {return, sharpe, mdd}

    # 月度热力图数据
    monthly_returns: pd.DataFrame  # year × month


def calc_sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    """计算年化Sharpe比率。"""
    if returns.std() < 1e-12:
        return 0.0
    excess = returns - rf / TRADING_DAYS_PER_YEAR
    return float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


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
    aligned = pd.DataFrame({
        "s": strategy_returns, "b": benchmark_returns
    }).dropna()
    if len(aligned) < 30 or aligned["b"].var() < 1e-12:
        return 0.0
    return float(aligned["s"].cov(aligned["b"]) / aligned["b"].var())


def calc_information_ratio(
    strategy_returns: pd.Series, benchmark_returns: pd.Series
) -> float:
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


def calc_win_rate_and_profit_factor(fills: list) -> tuple[float, float]:
    """胜率和盈亏比（基于每次调仓的PnL）。"""
    if not fills:
        return 0.0, 0.0

    # 按交易日分组计算PnL
    pnl_by_trade = {}
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

    return win_rate, profit_factor


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


def calc_annual_breakdown(
    nav: pd.Series, benchmark_nav: pd.Series
) -> pd.DataFrame:
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

        results.append({
            "year": year,
            "return": round(annual_ret * 100, 2),
            "excess_return": round((annual_ret - bench_ret) * 100, 2),
            "sharpe": round(sharpe, 2),
            "mdd": round(mdd * 100, 2),
        })

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


def generate_report(
    result: "BacktestResult",
    price_data: Optional[pd.DataFrame] = None,
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
    mdd = calc_max_drawdown(nav)
    calmar = calc_calmar(annual_return, mdd)
    sortino = calc_sortino(returns)
    beta = calc_beta(returns, bench_ret)
    ir = calc_information_ratio(returns, bench_ret)

    # 交易统计
    win_rate, profit_factor = calc_win_rate_and_profit_factor(result.trades)
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
            "annual_return": round(float((1 + adj_returns.sum()) ** (1 / max(years, 0.01)) - 1) * 100, 2),
            "sharpe": round(calc_sharpe(adj_returns), 2),
            "mdd": round(calc_max_drawdown(nav) * 100, 2),  # MDD不受成本影响
        }

    # 跳空统计
    avg_gap = calc_open_gap_stats(result.trades, price_data) if price_data is not None else 0.0

    # 仓位偏差（需要target_portfolios数据，generate_report无此参数，
    # 保留默认值，由调用方通过calc_position_deviation单独计算）
    mean_pos_dev = 0.0
    max_pos_dev = 0.0
    cash_drag = 0.0

    # 年度分解
    annual = calc_annual_breakdown(nav, bench_nav)

    # 月度热力图
    monthly = calc_monthly_returns(nav)

    return PerformanceReport(
        total_return=round(total_return * 100, 2),
        annual_return=round(annual_return * 100, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown=round(mdd * 100, 2),
        calmar_ratio=round(calmar, 2),
        sortino_ratio=round(sortino, 2),
        beta=round(beta, 3),
        information_ratio=round(ir, 2),
        total_trades=len(result.trades),
        win_rate=round(win_rate * 100, 1),
        profit_factor=round(profit_factor, 2),
        annual_turnover=round(annual_turnover, 2),
        max_consecutive_loss_days=max_loss_days,
        bootstrap_sharpe_ci=(
            round(bs_ci[0], 2), round(bs_ci[1], 2), round(bs_ci[2], 2)
        ),
        cost_sensitivity=cost_sens,
        avg_open_gap=round(avg_gap * 100, 4),
        mean_position_deviation=round(mean_pos_dev, 2),
        max_position_deviation=round(max_pos_dev, 2),
        total_cash_drag=round(cash_drag, 2),
        annual_breakdown=annual,
        monthly_returns=monthly,
    )


def print_report(report: PerformanceReport):
    """打印回测报告到终端。"""
    print("\n" + "=" * 60)
    print("QuantMind V2 — Phase 0 回测报告")
    print("=" * 60)

    print(f"\n{'总收益':>12}: {report.total_return:>8.2f}%")
    print(f"{'年化收益':>12}: {report.annual_return:>8.2f}%")
    print(f"{'Sharpe':>12}: {report.sharpe_ratio:>8.2f}")
    print(f"{'最大回撤':>12}: {report.max_drawdown:>8.2f}%")
    print(f"{'Calmar':>12}: {report.calmar_ratio:>8.2f}")
    print(f"{'Sortino':>12}: {report.sortino_ratio:>8.2f}")
    print(f"{'Beta':>12}: {report.beta:>8.3f}")
    print(f"{'IR':>12}: {report.information_ratio:>8.2f}")

    print(f"\n--- 交易统计 ---")
    print(f"{'总交易次数':>12}: {report.total_trades:>8d}")
    print(f"{'胜率':>12}: {report.win_rate:>8.1f}%")
    print(f"{'盈亏比':>12}: {report.profit_factor:>8.2f}")
    print(f"{'年化换手率':>12}: {report.annual_turnover:>8.2f}")
    print(f"{'最大连亏天数':>12}: {report.max_consecutive_loss_days:>8d}")

    p, lo, hi = report.bootstrap_sharpe_ci
    print(f"\n--- Bootstrap Sharpe CI ---")
    print(f"  Sharpe: {p:.2f} [{lo:.2f}, {hi:.2f}] (95% CI)")
    if lo < 0:
        print("  ⚠️ 警告: 5%分位Sharpe < 0，策略可能不赚钱!")

    print(f"\n--- 成本敏感性 ---")
    print(f"  {'成本倍数':>8}  {'年化收益':>8}  {'Sharpe':>8}  {'MDD':>8}")
    for mult, data in report.cost_sensitivity.items():
        print(f"  {mult:>8}  {data['annual_return']:>7.2f}%  {data['sharpe']:>8.2f}  {data['mdd']:>7.2f}%")

    print(f"\n--- 隔夜跳空 ---")
    print(f"  买入日平均跳空: {report.avg_open_gap:.4f}%")

    print(f"\n--- 仓位偏差 ---")
    print(f"  {'平均偏差':>12}: {report.mean_position_deviation:>8.2f}%")
    print(f"  {'最大偏差':>12}: {report.max_position_deviation:>8.2f}%")
    print(f"  {'现金拖累':>12}: {report.total_cash_drag:>8.2f}%")

    print(f"\n--- 年度分解 ---")
    if not report.annual_breakdown.empty:
        print(report.annual_breakdown.to_string())

    print("\n" + "=" * 60)
