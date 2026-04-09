"""共享 IC 计算模块 — Step 6-E Fix 3A.

提供项目范围内**唯一**的 IC 计算实现, 所有下游工具
(compute_factor_ic.py / factor_profiler.py / alpha_decay_attribution.py /
 regime_detection.py) 都必须调用本模块, 避免口径漂移。

## IC 计算口径 (铁律 18 标准)

| 项目 | 规格 |
|------|------|
| IC 类型 | Spearman Rank IC (截面相关系数) |
| 因子值 | `neutral_value` (MAD → fill → WLS 行业+ln市值 → zscore → clip±3) |
| 前瞻收益 | `forward_excess_return = stock_return - csi300_return`, 用前复权价 |
| 时间对齐 | T 日因子 vs T+1 买入, 持有到 T+horizon 卖出 (避免前瞻偏差) |
| horizon | 默认 5/10/20 日 (T+1 到 T+1+h-1 的收益) |
| Universe | 调用方负责 (排除 ST/BJ/停牌/新股) |
| 聚合 | 每日截面 IC → 时间序列, 再按窗口求均值/IR/胜率 |

## 关键 API

- `compute_daily_rank_ic(factor_df, return_df, date_col)`: 单日截面 IC
- `compute_ic_series(factor_wide, returns_wide)`: 多日时间序列 IC
- `compute_forward_excess_returns(price_df, benchmark_df, horizon)`: 构造前瞻超额收益
- `summarize_ic_stats(ic_series)`: mean/std/IR/t-stat/hit_rate

## 使用示例

```python
from engines.ic_calculator import (
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

# 1. 构造 T+1..T+21 的超额收益 (20 日 horizon)
fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=20)
# 2. pivot 因子到宽表 (trade_date × code)
factor_wide = factor_df.pivot_table(
    index='trade_date', columns='code', values='neutral_value'
)
# 3. 时间序列 IC (默认直接用 fwd_ret 和 factor_wide 的共同索引)
ic_series = compute_ic_series(factor_wide, fwd_ret)
# 4. 汇总
stats = summarize_ic_stats(ic_series)
# stats = {'mean': 0.045, 'std': 0.12, 'ir': 0.375, 't_stat': 3.2, 'hit_rate': 0.58, 'n_days': 244}
```
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# ============================================================
# 常量
# ============================================================

DEFAULT_HORIZONS = (5, 10, 20)  # 对应 T+1..T+6 / T+1..T+11 / T+1..T+21
MIN_CROSS_SECTION = 20  # 截面最少股票数 (否则 IC 不可信)

# 铁律 18 标识 (供调用方确认口径一致)
IC_CALCULATOR_VERSION = "1.0.0"
IC_CALCULATOR_ID = "neutral_value_T1_excess_spearman"


# ============================================================
# Forward return 构造
# ============================================================


def compute_forward_excess_returns(
    price_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    horizon: int = 20,
    price_col: str = "adj_close",
    benchmark_price_col: str = "close",
) -> pd.DataFrame:
    """构造 T+1 买入到 T+horizon 卖出的超额收益 (相对 CSI300 或其他 benchmark).

    公式:
        stock_ret(T) = price[T+horizon] / price[T+1] - 1
        bench_ret(T) = bench[T+horizon] / bench[T+1] - 1
        fwd_excess(T) = stock_ret - bench_ret

    T 日的 forward return 含义: 用 T+1 开盘买入 (回测约定), 持有 horizon 天后卖出。
    T 日本身的因子值可以直接与这个 fwd_excess 对齐做 IC。

    Args:
        price_df: 长表 (code, trade_date, adj_close), 已复权
        benchmark_df: 长表 (trade_date, close)
        horizon: 持有天数 (T+1 到 T+horizon)
        price_col: price_df 中的价格列 (默认 adj_close)
        benchmark_price_col: benchmark_df 中的价格列

    Returns:
        DataFrame (trade_date × code) = 前瞻超额收益, T 日的值对应 T+1..T+horizon 的收益
    """
    # 1. pivot 股票价 -> (date, code) 宽表
    price_wide = price_df.pivot_table(
        index="trade_date", columns="code", values=price_col, aggfunc="last"
    ).sort_index()

    # 2. benchmark -> series
    bench = (
        benchmark_df.set_index("trade_date")[benchmark_price_col]
        .sort_index()
        .astype(float)
    )

    # 3. 计算股票 T+1 → T+1+horizon 收益
    #    T 行对应 "从 T+1 开始的 horizon 天持有收益"
    entry = price_wide.shift(-1)  # T+1 价格
    exit_p = price_wide.shift(-(1 + horizon) + 1)  # T+horizon 价格 (含 T+1 共 horizon 天)
    # 等价: shift(-horizon) 给出 T+horizon 行; 但这里我们要"持有 horizon 天"
    # 持有 horizon 天 = 从 T+1 买 到 T+1+horizon-1 卖 = T+horizon
    # 简化: exit = shift(-horizon), entry = shift(-1)
    exit_p = price_wide.shift(-horizon)
    stock_ret = exit_p / entry - 1

    # 4. benchmark 同样
    bench_entry = bench.shift(-1)
    bench_exit = bench.shift(-horizon)
    bench_ret = bench_exit / bench_entry - 1  # Series

    # 5. 超额收益: 每个股票 - benchmark
    # stock_ret 是 (date × code) DataFrame, bench_ret 是 date Series
    # broadcast: stock_ret.sub(bench_ret, axis=0)
    excess = stock_ret.sub(bench_ret, axis=0)

    return excess


# ============================================================
# 日频 IC 计算
# ============================================================


def compute_daily_rank_ic(
    factor_values: pd.Series, forward_returns: pd.Series
) -> float | None:
    """单日截面 Spearman Rank IC.

    Args:
        factor_values: index=code, values=factor_value (该日截面)
        forward_returns: index=code, values=forward excess return (该日截面)

    Returns:
        Spearman 相关系数, 或 None (样本不足/全 NaN)
    """
    # 对齐 + 去 NaN
    df = pd.DataFrame({"f": factor_values, "r": forward_returns}).dropna()
    if len(df) < MIN_CROSS_SECTION:
        return None
    corr, _ = scipy_stats.spearmanr(df["f"].values, df["r"].values)
    return float(corr) if not np.isnan(corr) else None


def compute_ic_series(
    factor_wide: pd.DataFrame, returns_wide: pd.DataFrame
) -> pd.Series:
    """时间序列 IC: 对每个 trade_date 计算截面 Rank IC.

    Args:
        factor_wide: (trade_date × code) 因子宽表
        returns_wide: (trade_date × code) 前瞻超额收益宽表

    Returns:
        Series (index=trade_date, value=日截面 IC), 可能含 NaN
    """
    common_dates = factor_wide.index.intersection(returns_wide.index)
    common_codes = factor_wide.columns.intersection(returns_wide.columns)

    factor_slice = factor_wide.loc[common_dates, common_codes]
    return_slice = returns_wide.loc[common_dates, common_codes]

    ic_list = []
    for td in common_dates:
        ic = compute_daily_rank_ic(factor_slice.loc[td], return_slice.loc[td])
        ic_list.append(ic)

    return pd.Series(ic_list, index=common_dates, name="ic", dtype=float)


# ============================================================
# IC 汇总统计
# ============================================================


def summarize_ic_stats(
    ic_series: pd.Series, annualize: bool = False
) -> dict:
    """对 IC 序列做汇总统计.

    Args:
        ic_series: 日截面 IC 时间序列 (可能含 NaN)
        annualize: 是否对 IR/t-stat 年化

    Returns:
        dict with: mean, std, ir, t_stat, hit_rate, n_days, min, max
    """
    clean = ic_series.dropna()
    n = len(clean)
    if n < 2:
        return {
            "mean": 0.0,
            "std": 0.0,
            "ir": 0.0,
            "t_stat": 0.0,
            "hit_rate": 0.0,
            "n_days": n,
            "min": 0.0,
            "max": 0.0,
        }

    mean = float(clean.mean())
    std = float(clean.std(ddof=1))
    ir = mean / std if std > 0 else 0.0
    t_stat = ir * np.sqrt(n)
    hit_rate = float((clean > 0).sum() / n)

    if annualize:
        ir *= np.sqrt(244)

    return {
        "mean": round(mean, 6),
        "std": round(std, 6),
        "ir": round(ir, 4),
        "t_stat": round(t_stat, 4),
        "hit_rate": round(hit_rate, 4),
        "n_days": int(n),
        "min": round(float(clean.min()), 6),
        "max": round(float(clean.max()), 6),
    }


def summarize_ic_monthly(ic_series: pd.Series) -> pd.DataFrame:
    """按月聚合 IC (mean + hit_rate)."""
    clean = ic_series.dropna()
    if len(clean) == 0:
        return pd.DataFrame(columns=["year_month", "ic_mean", "ic_count", "hit_rate"])

    df = clean.to_frame("ic").copy()
    df.index = pd.to_datetime(df.index)
    monthly = df.resample("ME").agg(
        ic_mean=("ic", "mean"),
        ic_count=("ic", "count"),
        hit_rate=("ic", lambda s: (s > 0).sum() / len(s) if len(s) > 0 else 0),
    )
    monthly = monthly.reset_index().rename(columns={"trade_date": "year_month"})
    return monthly


def summarize_ic_yearly(ic_series: pd.Series) -> pd.DataFrame:
    """按自然年聚合 IC (mean/std/ir/t_stat/hit_rate)."""
    clean = ic_series.dropna()
    if len(clean) == 0:
        return pd.DataFrame(
            columns=["year", "ic_mean", "ic_std", "ic_ir", "t_stat", "hit_rate", "n_days"]
        )

    df = clean.to_frame("ic").copy()
    df.index = pd.to_datetime(df.index)
    df["year"] = df.index.year

    records = []
    for year, grp in df.groupby("year"):
        stats = summarize_ic_stats(grp["ic"])
        stats["year"] = int(year)
        records.append(stats)

    return pd.DataFrame(records)


# ============================================================
# 便捷入口 (给研究脚本用)
# ============================================================


def compute_factor_ic_full(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    horizon: int = 20,
    factor_value_col: str = "neutral_value",
    price_col: str = "adj_close",
    universe_filter: set | None = None,
) -> dict:
    """一站式 IC 计算: 从长表因子+价格+基准 → IC 序列 + 汇总统计.

    Args:
        factor_df: (code, trade_date, factor_name, neutral_value) 长表, 单因子或多因子
        price_df: (code, trade_date, adj_close) 长表
        benchmark_df: (trade_date, close) 长表
        horizon: 前瞻天数
        factor_value_col: factor_df 中的值列 (默认 neutral_value)
        price_col: price_df 中的价格列 (默认 adj_close)
        universe_filter: 可选的 code 集合 (白名单过滤)

    Returns:
        dict: {
            'ic_series': pd.Series,
            'stats': dict (mean/std/ir/t_stat/hit_rate/n_days),
            'yearly': pd.DataFrame,
            'monthly': pd.DataFrame,
            'meta': {version, horizon, n_factors, n_dates, n_codes}
        }
    """
    # Universe filter
    if universe_filter is not None:
        factor_df = factor_df[factor_df["code"].isin(universe_filter)].copy()
        price_df = price_df[price_df["code"].isin(universe_filter)].copy()

    # Pivot 因子
    if "factor_name" in factor_df.columns:
        # 可能有多因子, 检查
        fnames = factor_df["factor_name"].unique()
        if len(fnames) > 1:
            raise ValueError(f"factor_df 含多个因子, 请单因子调用: {list(fnames)}")

    factor_wide = factor_df.pivot_table(
        index="trade_date", columns="code", values=factor_value_col, aggfunc="first"
    ).sort_index()

    # 构造 forward excess return
    fwd_ret = compute_forward_excess_returns(
        price_df, benchmark_df, horizon=horizon, price_col=price_col
    )

    # 计算 IC 序列
    ic_series = compute_ic_series(factor_wide, fwd_ret)

    # 汇总
    stats = summarize_ic_stats(ic_series)
    yearly = summarize_ic_yearly(ic_series)
    monthly = summarize_ic_monthly(ic_series)

    return {
        "ic_series": ic_series,
        "stats": stats,
        "yearly": yearly,
        "monthly": monthly,
        "meta": {
            "version": IC_CALCULATOR_VERSION,
            "id": IC_CALCULATOR_ID,
            "horizon": horizon,
            "n_dates": int(len(ic_series)),
            "n_codes": int(len(factor_wide.columns)),
        },
    }
