#!/usr/bin/env python3
"""方法4/4b/5/6回测: 因子动态择时 / 半衰期加权 / 历史收益率加权。

方法4 (因子动态择时, KyFactor知乎实证):
  - 每月末计算5因子过去3个月滚动RankIC(月度截面Spearman)
  - 3个月平均IC < 0 的因子当月剔除
  - 剩余因子等权合成
  - 全部因子IC<0 → 当月不调仓

方法4b (因子择时 + PEAD):
  - 6因子(5+PEAD)跑方法4
  - PEAD某月IC<0自动剔除, IC>0时自动加入

方法5 (半衰期加权, 华泰实证):
  - 每只股票的每个因子, 用最近3个月末因子值加权平均
  - 权重: 当月=1.0, 上月=0.5, 上上月=0.25 (半衰期=1个月)
  - halflife_score = (f_t*1.0 + f_{t-1}*0.5 + f_{t-2}*0.25) / 1.75
  - 5因子各自半衰期加权后, 再等权合成

方法6 (历史收益率加权, 华泰实证优于IC加权):
  - 每月末计算5因子过去12个月多空组合累积收益率
  - 每个因子: Top20%等权 - Bottom20%等权的月度收益累积
  - 权重 = 累积收益率(负的设为0, 归一化到sum=1)

回测配置(全部统一): 2021-01-01~2025-12-31, 100万, Top15月频, IndCap=25%, SimBroker

输出: 5配置对比表: 0(基线) vs 4(择时5F) vs 4b(择时6F+PEAD) vs 5(半衰期) vs 6(收益率加权)
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import generate_report
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from run_backtest import (
    load_benchmark,
    load_factor_values,
    load_industry,
    load_price_data,
    load_universe,
)
from run_pead_backtest import bootstrap_sharpe_ci, compute_pead_factor_panel

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 基线因子配置
# ============================================================
BASELINE_5F = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

BASELINE_6F = BASELINE_5F + ["earnings_surprise_car"]


# ============================================================
# 公共: 加载月末因子截面 + 20日超额收益(用于IC计算)
# ============================================================


def load_forward_returns_20d(
    rebalance_dates: list[date], conn
) -> dict[date, pd.Series]:
    """加载每个调仓日的20日超额收益(vs CSI300)。

    Args:
        rebalance_dates: 调仓日列表(月末)。
        conn: DB连接。

    Returns:
        {调仓日: pd.Series(code -> 20日超额收益)}
    """
    logger.info("加载20日超额收益(用于IC计算)...")

    # 加载全部日收益
    min_date = min(rebalance_dates) - pd.Timedelta(days=30)
    max_date = max(rebalance_dates) + pd.Timedelta(days=60)

    ret_df = pd.read_sql(
        """SELECT code, trade_date, pct_change::float / 100 as ret
           FROM klines_daily
           WHERE trade_date BETWEEN %s AND %s AND volume > 0
           ORDER BY trade_date, code""",
        conn,
        params=(min_date, max_date),
    )

    bench_df = pd.read_sql(
        """SELECT trade_date, close::float
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(min_date, max_date),
    )
    bench_df["bench_ret"] = bench_df["close"].pct_change()
    bench_ret = bench_df.set_index("trade_date")["bench_ret"]

    trading_dates = sorted(ret_df["trade_date"].unique())
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}

    # 宽表: trade_date x code -> ret
    ret_wide = ret_df.pivot(index="trade_date", columns="code", values="ret")
    ret_wide = ret_wide.reindex(trading_dates)
    excess_ret_wide = ret_wide.sub(bench_ret, axis=0)

    result = {}
    for rd in rebalance_dates:
        if rd not in date_to_idx:
            # 找最近的交易日
            idx = np.searchsorted(trading_dates, rd)
            if idx >= len(trading_dates):
                continue
            rd_actual = trading_dates[idx]
        else:
            rd_actual = rd

        idx = date_to_idx[rd_actual]
        end_idx = min(idx + 20, len(trading_dates) - 1)
        if end_idx <= idx:
            continue

        window = trading_dates[idx + 1 : end_idx + 1]
        if len(window) < 10:
            continue

        # 20日累积超额收益
        fwd_ret = excess_ret_wide.loc[window].sum()
        fwd_ret = fwd_ret.dropna()
        if len(fwd_ret) > 100:
            result[rd] = fwd_ret

    logger.info(f"  20日超额收益: {len(result)}个月")
    return result


def calc_monthly_rank_ic(
    factor_series: pd.Series,
    fwd_return: pd.Series,
) -> float:
    """计算单月截面RankIC(Spearman)。

    Args:
        factor_series: 因子值(code -> value)。
        fwd_return: 20日超额收益(code -> value)。

    Returns:
        Spearman相关系数。
    """
    common = factor_series.index.intersection(fwd_return.index)
    if len(common) < 30:
        return np.nan
    f = factor_series.reindex(common).dropna()
    r = fwd_return.reindex(f.index).dropna()
    common2 = f.index.intersection(r.index)
    if len(common2) < 30:
        return np.nan
    corr, _ = sp_stats.spearmanr(f.loc[common2], r.loc[common2])
    return float(corr)


def load_factor_panel(
    rebalance_dates: list[date],
    factor_names: list[str],
    conn,
) -> dict[date, dict[str, pd.Series]]:
    """加载每个调仓日、每个因子的截面数据。

    Returns:
        {调仓日: {factor_name: pd.Series(code -> neutral_value)}}
    """
    logger.info("加载因子面板...")
    result = {}
    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        panel = {}
        for fname in factor_names:
            sub = fv[fv["factor_name"] == fname]
            if not sub.empty:
                series = sub.set_index("code")["neutral_value"].dropna()
                # 方向调整
                direction = FACTOR_DIRECTION.get(fname, 1)
                if direction == -1:
                    series = -series
                panel[fname] = series
        if panel:
            result[rd] = panel
    logger.info(f"  因子面板: {len(result)}个月")
    return result


def load_monthly_returns(
    rebalance_dates: list[date], conn
) -> dict[date, pd.Series]:
    """加载每个月末到下月末的股票收益率(用于方法6多空收益计算)。

    Returns:
        {月末日期: pd.Series(code -> 月度收益率)}
    """
    logger.info("加载月度收益率(用于方法6)...")

    all_klines = pd.read_sql(
        """SELECT code, trade_date, close::float
           FROM klines_daily
           WHERE trade_date BETWEEN %s AND %s AND volume > 0
           ORDER BY trade_date, code""",
        conn,
        params=(
            min(rebalance_dates) - pd.Timedelta(days=400),
            max(rebalance_dates) + pd.Timedelta(days=60),
        ),
    )

    # pivot: trade_date x code -> close
    close_wide = all_klines.pivot(index="trade_date", columns="code", values="close")
    trading_dates = sorted(close_wide.index)

    result = {}
    for i in range(len(rebalance_dates) - 1):
        rd = rebalance_dates[i]
        rd_next = rebalance_dates[i + 1]

        # 找最近的交易日
        rd_idx = np.searchsorted(trading_dates, rd)
        rd_next_idx = np.searchsorted(trading_dates, rd_next)
        if rd_idx >= len(trading_dates) or rd_next_idx >= len(trading_dates):
            continue

        rd_actual = trading_dates[rd_idx]
        rd_next_actual = trading_dates[rd_next_idx]

        close_start = close_wide.loc[rd_actual]
        close_end = close_wide.loc[rd_next_actual]

        monthly_ret = (close_end / close_start - 1).dropna()
        if len(monthly_ret) > 100:
            result[rd] = monthly_ret

    logger.info(f"  月度收益率: {len(result)}个月")
    return result


# ============================================================
# 方法4: 因子动态择时
# ============================================================


def method4_compose(
    rd: date,
    factor_panel: dict[date, dict[str, pd.Series]],
    fwd_returns: dict[date, pd.Series],
    rebalance_dates: list[date],
    factor_names: list[str],
    universe: set[str],
    pead_panel: dict[date, pd.Series] | None = None,
) -> pd.Series:
    """方法4: 因子动态择时 -- 3个月滚动IC筛选。

    Args:
        rd: 当前调仓日。
        factor_panel: 因子面板。
        fwd_returns: 20日超额收益。
        rebalance_dates: 全部调仓日列表。
        factor_names: 候选因子名列表。
        universe: 当月可交易universe。
        pead_panel: PEAD因子面板(仅方法4b需要)。

    Returns:
        pd.Series(code -> composite_score), 空Series表示不调仓。
    """
    rd_idx = rebalance_dates.index(rd) if rd in rebalance_dates else -1
    if rd_idx < 0:
        return pd.Series(dtype=float)

    # 取过去3个月的调仓日
    lookback_months = 3
    start_idx = max(0, rd_idx - lookback_months)
    past_dates = rebalance_dates[start_idx:rd_idx]

    if len(past_dates) == 0:
        # 前几个月没历史 -> fallback等权
        return _equal_weight_compose(rd, factor_panel, factor_names, universe, pead_panel)

    # 计算每个因子过去3个月的平均RankIC
    factor_avg_ic = {}
    for fname in factor_names:
        ic_list = []
        for pd_date in past_dates:
            if pd_date not in factor_panel or pd_date not in fwd_returns:
                continue

            if fname == "earnings_surprise_car" and pead_panel is not None:
                # PEAD因子从pead_panel取
                f_series = pead_panel.get(pd_date)
                if f_series is None or f_series.empty:
                    continue
            else:
                f_series = factor_panel.get(pd_date, {}).get(fname)
                if f_series is None or f_series.empty:
                    continue

            ic = calc_monthly_rank_ic(f_series, fwd_returns[pd_date])
            if not np.isnan(ic):
                ic_list.append(ic)

        if ic_list:
            factor_avg_ic[fname] = np.mean(ic_list)

    # 筛选: 平均IC >= 0 的因子
    active_factors = [f for f, ic in factor_avg_ic.items() if ic >= 0]

    if not active_factors:
        # 全部因子IC<0 -> 不调仓
        logger.debug(f"  [{rd}] 方法4: 全部因子IC<0, 不调仓")
        return pd.Series(dtype=float)

    logger.debug(
        f"  [{rd}] 方法4: 活跃因子={active_factors} "
        f"(IC: {', '.join(f'{f}={factor_avg_ic.get(f,0):.3f}' for f in factor_names)})"
    )

    # 等权合成活跃因子
    return _equal_weight_compose(rd, factor_panel, active_factors, universe, pead_panel)


def _equal_weight_compose(
    rd: date,
    factor_panel: dict[date, dict[str, pd.Series]],
    active_factors: list[str],
    universe: set[str],
    pead_panel: dict[date, pd.Series] | None = None,
) -> pd.Series:
    """等权合成指定因子列表。"""
    if rd not in factor_panel:
        return pd.Series(dtype=float)

    scores_list = []
    for fname in active_factors:
        if fname == "earnings_surprise_car" and pead_panel is not None:
            f_series = pead_panel.get(rd)
            if f_series is None or f_series.empty:
                continue
            # 只保留universe中的
            f_series = f_series[f_series.index.isin(universe)]
            # zscore
            mean_v = f_series.mean()
            std_v = f_series.std()
            if std_v > 0:
                f_series = (f_series - mean_v) / std_v
            scores_list.append(f_series)
        else:
            f_series = factor_panel[rd].get(fname)
            if f_series is None or f_series.empty:
                continue
            f_series = f_series[f_series.index.isin(universe)]
            scores_list.append(f_series)

    if not scores_list:
        return pd.Series(dtype=float)

    # 等权合成
    combined = pd.concat(scores_list, axis=1)
    composite = combined.mean(axis=1).dropna()
    return composite.sort_values(ascending=False)


# ============================================================
# 方法5: 半衰期加权
# ============================================================


def method5_compose(
    rd: date,
    factor_panel: dict[date, dict[str, pd.Series]],
    rebalance_dates: list[date],
    factor_names: list[str],
    universe: set[str],
) -> pd.Series:
    """方法5: 半衰期加权因子值。

    对每只股票的每个因子, 用最近3个月末的因子值加权平均:
    权重: 当月=1.0, 上月=0.5, 上上月=0.25
    halflife_score = (f_t*1.0 + f_{t-1}*0.5 + f_{t-2}*0.25) / 1.75

    Args:
        rd: 当前调仓日。
        factor_panel: 因子面板。
        rebalance_dates: 全部调仓日列表。
        factor_names: 因子名列表。
        universe: 当月可交易universe。

    Returns:
        pd.Series(code -> composite_score)。
    """
    rd_idx = rebalance_dates.index(rd) if rd in rebalance_dates else -1
    if rd_idx < 0 or rd not in factor_panel:
        return pd.Series(dtype=float)

    # 半衰期权重: 当月=1.0, t-1=0.5, t-2=0.25
    halflife_weights = [1.0, 0.5, 0.25]
    weight_sum = sum(halflife_weights)  # 1.75

    # 取最近3个月的调仓日(含当月)
    lookback_indices = [rd_idx - k for k in range(3) if rd_idx - k >= 0]
    lookback_dates = [rebalance_dates[i] for i in lookback_indices]

    factor_scores = []
    for fname in factor_names:
        weighted_values = []
        for k, ld in enumerate(lookback_dates):
            if ld not in factor_panel:
                continue
            f_series = factor_panel[ld].get(fname)
            if f_series is None or f_series.empty:
                continue
            f_series = f_series[f_series.index.isin(universe)]
            weighted_values.append((halflife_weights[k], f_series))

        if not weighted_values:
            continue

        # 加权平均
        all_codes = set()
        for _, s in weighted_values:
            all_codes |= set(s.index)

        halflife_score = pd.Series(0.0, index=list(all_codes))
        total_w = pd.Series(0.0, index=list(all_codes))

        for w, s in weighted_values:
            aligned = s.reindex(list(all_codes)).fillna(0)
            mask = s.reindex(list(all_codes)).notna()
            halflife_score += aligned * w
            total_w += mask.astype(float) * w

        # 归一化: 只对有数据的code取均值
        valid = total_w > 0
        halflife_score[valid] = halflife_score[valid] / total_w[valid]
        halflife_score[~valid] = np.nan
        halflife_score = halflife_score.dropna()

        factor_scores.append(halflife_score)

    if not factor_scores:
        return pd.Series(dtype=float)

    # 等权合成
    combined = pd.concat(factor_scores, axis=1)
    composite = combined.mean(axis=1).dropna()
    return composite.sort_values(ascending=False)


# ============================================================
# 方法6: 历史收益率加权
# ============================================================


def method6_compose(
    rd: date,
    factor_panel: dict[date, dict[str, pd.Series]],
    monthly_returns: dict[date, pd.Series],
    rebalance_dates: list[date],
    factor_names: list[str],
    universe: set[str],
) -> pd.Series:
    """方法6: 历史收益率加权。

    每月末:
    1. 计算5因子过去12个月的多空组合累积收益率
       - 每个因子: Top20%等权 - Bottom20%等权的月度收益累积
    2. 权重 = 累积收益率(负的设为0, 归一化到sum=1)

    Args:
        rd: 当前调仓日。
        factor_panel: 因子面板。
        monthly_returns: 月度收益率面板。
        rebalance_dates: 全部调仓日列表。
        factor_names: 因子名列表。
        universe: 当月可交易universe。

    Returns:
        pd.Series(code -> composite_score)。
    """
    rd_idx = rebalance_dates.index(rd) if rd in rebalance_dates else -1
    if rd_idx < 0 or rd not in factor_panel:
        return pd.Series(dtype=float)

    # 过去12个月
    lookback = 12
    start_idx = max(0, rd_idx - lookback)
    past_dates = rebalance_dates[start_idx:rd_idx]

    if len(past_dates) < 3:
        # 不够历史 -> fallback等权
        return _equal_weight_compose(rd, factor_panel, factor_names, universe)

    # 计算每个因子的多空累积收益
    factor_cum_ret = {}
    for fname in factor_names:
        monthly_ls_returns = []
        for pd_date in past_dates:
            if pd_date not in factor_panel or pd_date not in monthly_returns:
                continue

            f_series = factor_panel[pd_date].get(fname)
            if f_series is None or len(f_series) < 50:
                continue

            m_ret = monthly_returns[pd_date]
            common = f_series.index.intersection(m_ret.index)
            if len(common) < 50:
                continue

            f_vals = f_series.reindex(common).dropna()
            r_vals = m_ret.reindex(f_vals.index).dropna()
            common2 = f_vals.index.intersection(r_vals.index)
            if len(common2) < 50:
                continue

            f_ranked = f_vals.loc[common2].rank(pct=True)
            n_top = max(1, int(len(common2) * 0.20))

            # Top20% (因子值最大, 已方向调整过)
            top_codes = f_ranked.nlargest(n_top).index
            bot_codes = f_ranked.nsmallest(n_top).index

            top_ret = r_vals.loc[top_codes].mean()
            bot_ret = r_vals.loc[bot_codes].mean()
            ls_ret = top_ret - bot_ret
            monthly_ls_returns.append(ls_ret)

        if monthly_ls_returns:
            # 累积收益 = prod(1+r) - 1
            cum_ret = np.prod([1 + r for r in monthly_ls_returns]) - 1
            factor_cum_ret[fname] = cum_ret

    if not factor_cum_ret:
        return _equal_weight_compose(rd, factor_panel, factor_names, universe)

    # 权重: 负的设为0, 归一化
    weights = {f: max(0, r) for f, r in factor_cum_ret.items()}
    total_w = sum(weights.values())
    if total_w <= 0:
        # 全部累积收益<=0 -> 等权fallback
        return _equal_weight_compose(rd, factor_panel, factor_names, universe)

    weights = {f: w / total_w for f, w in weights.items()}

    logger.debug(
        f"  [{rd}] 方法6: 权重 = "
        + ", ".join(f"{f}={w:.2f}" for f, w in weights.items())
    )

    # 加权合成
    scores_list = []
    weight_list = []
    for fname, w in weights.items():
        if w <= 0:
            continue
        f_series = factor_panel[rd].get(fname)
        if f_series is None or f_series.empty:
            continue
        f_series = f_series[f_series.index.isin(universe)]
        scores_list.append(f_series * w)
        weight_list.append(w)

    if not scores_list:
        return pd.Series(dtype=float)

    combined = pd.concat(scores_list, axis=1)
    composite = combined.sum(axis=1).dropna()
    return composite.sort_values(ascending=False)


# ============================================================
# 通用回测runner
# ============================================================


def run_generic_backtest(
    label: str,
    target_portfolios: dict[date, dict[str, float]],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    factor_names: list[str],
) -> dict:
    """运行通用回测, 返回绩效摘要。

    Args:
        label: 配置标签。
        target_portfolios: {信号日: {code: weight}}。
        price_data: 价格数据。
        benchmark_data: 基准数据。
        factor_names: 因子名列表。

    Returns:
        绩效摘要字典。
    """
    bt_config = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=15,
        rebalance_freq="monthly",
        slippage_bps=10.0,
    )

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    dr = result.daily_returns.copy()
    dr.index = pd.to_datetime(dr.index)

    # Bootstrap CI
    sharpe_mean, ci_low, ci_high = bootstrap_sharpe_ci(dr)

    # 年度分解
    annual = {}
    for year in range(2021, 2026):
        mask = dr.index.year == year
        yr = dr[mask]
        if len(yr) > 0:
            ann_ret = (1 + yr).prod() - 1
            ann_sharpe = yr.mean() / yr.std() * np.sqrt(252) if yr.std() > 0 else 0
            cum = (1 + yr).cumprod()
            drawdown = cum / cum.cummax() - 1
            mdd = drawdown.min()
            annual[year] = {
                "return": float(ann_ret),
                "sharpe": float(ann_sharpe),
                "mdd": float(mdd),
            }

    # 整体
    total_ret = (1 + dr).prod() - 1
    ann_ret = (1 + total_ret) ** (252 / len(dr)) - 1 if len(dr) > 0 else 0
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    cum_nav = (1 + dr).cumprod()
    mdd = (cum_nav / cum_nav.cummax() - 1).min()

    # Calmar / Sortino
    calmar = float(ann_ret / abs(mdd)) if mdd != 0 else 0
    downside = dr[dr < 0].std() * np.sqrt(252) if len(dr[dr < 0]) > 0 else 1
    sortino = float(ann_ret / downside) if downside > 0 else 0

    return {
        "label": label,
        "factors": factor_names,
        "n_factors": len(factor_names),
        "total_return": float(total_ret),
        "ann_return": float(ann_ret),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": calmar,
        "sortino": sortino,
        "bootstrap_sharpe_mean": sharpe_mean,
        "bootstrap_ci_low": ci_low,
        "bootstrap_ci_high": ci_high,
        "annual": annual,
        "n_rebalances": len(target_portfolios),
        "n_trades": len(result.trades),
    }


# ============================================================
# 对比输出
# ============================================================


def print_comparison(summaries: list[dict]) -> None:
    """打印5配置对比表。"""
    print("\n" + "=" * 100)
    print("  方法4/4b/5/6 因子合成方法对比回测")
    print("  区间: 2021-01-01 ~ 2025-12-31, 100万, Top15, 月频, IndCap=25%")
    print("=" * 100)

    # 整体对比
    col_w = 18
    print(f"\n{'指标':<22}", end="")
    for s in summaries:
        print(f"  {s['label']:>{col_w}}", end="")
    print()
    print("-" * (22 + (col_w + 2) * len(summaries)))

    rows = [
        ("因子数", "n_factors", "d"),
        ("总收益", "total_return", ".1%"),
        ("年化收益", "ann_return", ".1%"),
        ("Sharpe", "sharpe", ".3f"),
        ("最大回撤", "mdd", ".1%"),
        ("Calmar", "calmar", ".2f"),
        ("Sortino", "sortino", ".2f"),
        ("Bootstrap Sharpe", "bootstrap_sharpe_mean", ".3f"),
        ("  95% CI 下界", "bootstrap_ci_low", ".3f"),
        ("  95% CI 上界", "bootstrap_ci_high", ".3f"),
        ("调仓次数", "n_rebalances", "d"),
        ("成交笔数", "n_trades", "d"),
    ]

    for label, key, fmt in rows:
        print(f"{label:<22}", end="")
        for s in summaries:
            val = s[key]
            print(f"  {val:>{col_w}{fmt}}", end="")
        print()

    # 年度分解
    print(f"\n{'年度分解':=^100}")
    for year in range(2021, 2026):
        print(f"\n  {year}年:")
        print(f"  {'指标':<18}", end="")
        for s in summaries:
            print(f"  {s['label']:>{col_w}}", end="")
        print()

        for label, key, fmt in [
            ("收益", "return", ".1%"),
            ("Sharpe", "sharpe", ".3f"),
            ("MDD", "mdd", ".1%"),
        ]:
            print(f"  {label:<18}", end="")
            for s in summaries:
                if year in s["annual"]:
                    val = s["annual"][year][key]
                    print(f"  {val:>{col_w}{fmt}}", end="")
                else:
                    print(f"  {'N/A':>{col_w}}", end="")
            print()

    # 增量分析(每个方法 vs 基线)
    baseline = summaries[0]
    print(f"\n{'增量分析(vs 基线)':=^100}")
    print(f"  {'指标':<22}", end="")
    for s in summaries[1:]:
        print(f"  {s['label']:>{col_w}}", end="")
    print()
    print("-" * (22 + (col_w + 2) * (len(summaries) - 1)))

    for label, key, fmt, sign in [
        ("Sharpe增量", "sharpe", "+.3f", True),
        ("年化收益增量", "ann_return", "+.1%", True),
        ("MDD变化", "mdd", "+.1%", True),
        ("CI下界增量", "bootstrap_ci_low", "+.3f", True),
    ]:
        print(f"  {label:<20}", end="")
        for s in summaries[1:]:
            delta = s[key] - baseline[key]
            print(f"  {delta:>{col_w}{fmt}}", end="")
        print()

    # 年度逐年: 每个方法 vs 基线 胜负
    print(f"\n  年度Sharpe胜负:")
    for year in range(2021, 2026):
        if year not in baseline["annual"]:
            continue
        b_sharpe = baseline["annual"][year]["sharpe"]
        row_str = f"    {year}: 基线={b_sharpe:.3f}"
        for s in summaries[1:]:
            if year in s["annual"]:
                s_sharpe = s["annual"][year]["sharpe"]
                diff = s_sharpe - b_sharpe
                tag = "W" if diff > 0.05 else ("L" if diff < -0.05 else "~")
                row_str += f"  | {s['label'][:8]}={s_sharpe:.3f}({diff:+.3f}){tag}"
        print(row_str)

    # 核心判定
    print(f"\n{'核心判定':=^100}")

    best = max(summaries, key=lambda s: s["sharpe"])
    print(f"  最高Sharpe: {best['label']} = {best['sharpe']:.3f}")

    # 方法4b特别关注
    m4b = next((s for s in summaries if "4b" in s["label"]), None)
    if m4b:
        delta = m4b["sharpe"] - baseline["sharpe"]
        if delta > 0.05:
            print(f"  方法4b(择时+PEAD) Sharpe={m4b['sharpe']:.3f}, "
                  f"增量={delta:+.3f} > 0.05 => 因子择时+PEAD突破天花板")
        elif delta > 0:
            print(f"  方法4b(择时+PEAD) Sharpe={m4b['sharpe']:.3f}, "
                  f"增量={delta:+.3f} > 0但<0.05 => 边际改善, 不显著")
        else:
            print(f"  方法4b(择时+PEAD) Sharpe={m4b['sharpe']:.3f}, "
                  f"增量={delta:+.3f} <= 0 => 未突破天花板")

    # 全部方法是否突破基线
    better_count = sum(1 for s in summaries[1:] if s["sharpe"] > baseline["sharpe"] + 0.05)
    print(f"  显著优于基线的方法: {better_count}/{len(summaries)-1}")
    if better_count == 0:
        print("  结论: 等权基线天花板未被突破, 建议继续探索其他维度")
    else:
        winners = [s["label"] for s in summaries[1:] if s["sharpe"] > baseline["sharpe"] + 0.05]
        print(f"  结论: {', '.join(winners)} 突破等权天花板, 可作为v1.2候选")

    print()


# ============================================================
# 主程序
# ============================================================


def main():
    """方法4/4b/5/6回测主程序。"""
    print("\n" + "=" * 80)
    print("  方法4/4b/5/6: 因子动态择时 / 半衰期加权 / 历史收益率加权")
    print("  区间: 2021-01-01 ~ 2025-12-31")
    print("  资金: 100万, 月频, Top15, IndCap=25%")
    print("=" * 80)

    start = date(2021, 1, 1)
    end = date(2025, 12, 31)

    conn = _get_sync_conn()
    t0 = time.time()

    # 1. 公共数据
    logger.info("获取调仓日历...")
    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    # 方法4/5/6需要IC计算, 需要更早的调仓日(用于lookback)
    early_start = date(2020, 1, 1)
    extended_rebalance_dates = get_rebalance_dates(early_start, end, freq="monthly", conn=conn)
    logger.info(f"扩展调仓日(含lookback): {len(extended_rebalance_dates)}个")

    logger.info("加载行业分类...")
    industry = load_industry(conn)

    logger.info("加载价格数据...")
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

    # 2. 因子面板(扩展区间, 含lookback)
    factor_panel_5f = load_factor_panel(extended_rebalance_dates, BASELINE_5F, conn)
    factor_panel_6f = load_factor_panel(extended_rebalance_dates, BASELINE_6F, conn)

    # 3. 20日超额收益(用于IC计算)
    fwd_returns = load_forward_returns_20d(extended_rebalance_dates, conn)

    # 4. 月度收益率(用于方法6)
    monthly_returns = load_monthly_returns(extended_rebalance_dates, conn)

    # 5. PEAD因子面板(方法4b)
    logger.info("计算PEAD因子面板...")
    pead_panel = compute_pead_factor_panel(conn, early_start, end)
    if not pead_panel:
        logger.warning("PEAD因子面板为空, 方法4b将无法运行")

    summaries = []

    # ================================================================
    # 方法0: 基线v1.1(5因子等权)
    # ================================================================
    logger.info("\n[方法0] v1.1基线 — 5因子等权")
    sig_config_0 = SignalConfig(
        factor_names=BASELINE_5F,
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    composer_0 = SignalComposer(sig_config_0)
    builder_0 = PortfolioBuilder(sig_config_0)

    targets_0 = {}
    prev_weights_0 = {}
    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)
        scores = composer_0.compose(fv, universe)
        if scores.empty:
            continue
        target = builder_0.build(scores, industry, prev_weights_0)
        if target:
            targets_0[rd] = target
            prev_weights_0 = target

    logger.info(f"  [基线] 信号完成: {len(targets_0)}个调仓日")
    s0 = run_generic_backtest("0:基线(5F等权)", targets_0, price_data, benchmark_data, BASELINE_5F)
    summaries.append(s0)

    # ================================================================
    # 方法4: 因子动态择时(5因子)
    # ================================================================
    logger.info("\n[方法4] 因子动态择时 — 5因子, 3个月滚动IC筛选")
    sig_config_4 = SignalConfig(
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    builder_4 = PortfolioBuilder(sig_config_4)

    targets_4 = {}
    prev_weights_4 = {}
    skip_count_4 = 0
    for rd in rebalance_dates:
        universe = load_universe(rd, conn)
        scores = method4_compose(
            rd, factor_panel_5f, fwd_returns,
            extended_rebalance_dates, BASELINE_5F, universe
        )
        if scores.empty:
            skip_count_4 += 1
            # 不调仓: 沿用上期持仓
            continue
        target = builder_4.build(scores, industry, prev_weights_4)
        if target:
            targets_4[rd] = target
            prev_weights_4 = target

    logger.info(f"  [方法4] 信号完成: {len(targets_4)}个调仓日, 跳过: {skip_count_4}")
    s4 = run_generic_backtest("4:择时(5F)", targets_4, price_data, benchmark_data, BASELINE_5F)
    summaries.append(s4)

    # ================================================================
    # 方法4b: 因子动态择时(6因子 + PEAD)
    # ================================================================
    if pead_panel:
        logger.info("\n[方法4b] 因子动态择时 — 6因子(5F+PEAD), 3个月滚动IC筛选")
        builder_4b = PortfolioBuilder(sig_config_4)

        targets_4b = {}
        prev_weights_4b = {}
        skip_count_4b = 0
        for rd in rebalance_dates:
            universe = load_universe(rd, conn)
            scores = method4_compose(
                rd, factor_panel_6f, fwd_returns,
                extended_rebalance_dates, BASELINE_6F, universe,
                pead_panel=pead_panel,
            )
            if scores.empty:
                skip_count_4b += 1
                continue
            target = builder_4b.build(scores, industry, prev_weights_4b)
            if target:
                targets_4b[rd] = target
                prev_weights_4b = target

        logger.info(f"  [方法4b] 信号完成: {len(targets_4b)}个调仓日, 跳过: {skip_count_4b}")
        s4b = run_generic_backtest(
            "4b:择时(6F+PEAD)", targets_4b, price_data, benchmark_data, BASELINE_6F
        )
        summaries.append(s4b)
    else:
        logger.warning("PEAD面板为空, 跳过方法4b")
        summaries.append({
            "label": "4b:择时(6F+PEAD)", "factors": BASELINE_6F, "n_factors": 6,
            "total_return": 0, "ann_return": 0, "sharpe": 0, "mdd": 0,
            "calmar": 0, "sortino": 0, "bootstrap_sharpe_mean": 0,
            "bootstrap_ci_low": 0, "bootstrap_ci_high": 0,
            "annual": {}, "n_rebalances": 0, "n_trades": 0,
        })

    # ================================================================
    # 方法5: 半衰期加权
    # ================================================================
    logger.info("\n[方法5] 半衰期加权 — 5因子, 3个月半衰期")
    builder_5 = PortfolioBuilder(sig_config_4)

    targets_5 = {}
    prev_weights_5 = {}
    for rd in rebalance_dates:
        universe = load_universe(rd, conn)
        scores = method5_compose(
            rd, factor_panel_5f, extended_rebalance_dates, BASELINE_5F, universe
        )
        if scores.empty:
            continue
        target = builder_5.build(scores, industry, prev_weights_5)
        if target:
            targets_5[rd] = target
            prev_weights_5 = target

    logger.info(f"  [方法5] 信号完成: {len(targets_5)}个调仓日")
    s5 = run_generic_backtest("5:半衰期(5F)", targets_5, price_data, benchmark_data, BASELINE_5F)
    summaries.append(s5)

    # ================================================================
    # 方法6: 历史收益率加权
    # ================================================================
    logger.info("\n[方法6] 历史收益率加权 — 5因子, 12个月累积多空收益")
    builder_6 = PortfolioBuilder(sig_config_4)

    targets_6 = {}
    prev_weights_6 = {}
    for rd in rebalance_dates:
        universe = load_universe(rd, conn)
        scores = method6_compose(
            rd, factor_panel_5f, monthly_returns,
            extended_rebalance_dates, BASELINE_5F, universe
        )
        if scores.empty:
            continue
        target = builder_6.build(scores, industry, prev_weights_6)
        if target:
            targets_6[rd] = target
            prev_weights_6 = target

    logger.info(f"  [方法6] 信号完成: {len(targets_6)}个调仓日")
    s6 = run_generic_backtest("6:收益率加权(5F)", targets_6, price_data, benchmark_data, BASELINE_5F)
    summaries.append(s6)

    conn.close()

    # 输出对比
    print_comparison(summaries)

    elapsed = time.time() - t0
    logger.info(f"回测完成, 总耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    main()
