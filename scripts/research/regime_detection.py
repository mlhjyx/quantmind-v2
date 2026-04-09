#!/usr/bin/env python3
"""Step 6-E Part 2: Regime 检测研究 — 5 个月度先行指标 + 预测能力分析.

构建候选 regime 指标 (2014-2026 月度):
  1. factor_rolling_ic   — 5 因子 3 月滚动截面 IC 均值 (自身信号)
  2. smb_momentum        — 小盘 3 月超额 (vs 大盘)
  3. market_breadth      — 月度上涨股票比例 (全 A)
  4. factor_corr_mean    — 5 因子截面相关系数均值 (拥挤度)
  5. vol_regime          — CSI300 20 日已实现波动率

预测能力分析:
  - 每个指标 vs 未来 1/3/6 月策略 Sharpe (滚动) 的相关系数 + t-stat
  - 特别关注 2017-2018 / 2022-2023 两次失效前的信号

OOS regime-flag 回测 (概念验证):
  - 训练: 2014-2020 阈值校准
  - 测试: 2021-2026 验证 Sharpe/MDD 改善

输出:
  cache/baseline/regime_indicators.json     月度指标时间序列
  cache/baseline/regime_analysis.json       预测力分析 + OOS 结果

用法:
    python scripts/research/regime_detection.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
import warnings
from pathlib import Path

logging.disable(logging.DEBUG)
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from engines.ic_calculator import (  # noqa: E402
    IC_CALCULATOR_ID,
    IC_CALCULATOR_VERSION,
    compute_forward_excess_returns,
    compute_ic_series,
)
from scipy import stats as scipy_stats  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "baseline"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "backtest"

CORE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

ROLLING_MONTHS = 3  # 滚动窗口 (3 月)
PREDICTION_HORIZONS_MONTHS = [1, 3, 6]  # 预测未来 N 月 Sharpe
HORIZON = 20  # IC 前瞻 T+20


# ============================================================
# 数据加载
# ============================================================


def load_all_data():
    """加载 12 年 price + benchmark + factors (5 CORE)."""
    print("[Load] 12 年全数据...")
    t0 = time.time()
    price_parts, bench_parts, factor_parts = [], [], []
    years = sorted([int(d.name) for d in CACHE_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    for year in years:
        yr_dir = CACHE_DIR / str(year)
        price_parts.append(pd.read_parquet(yr_dir / "price_data.parquet"))
        bench_parts.append(pd.read_parquet(yr_dir / "benchmark.parquet"))
        factor_parts.append(pd.read_parquet(yr_dir / "factor_data.parquet"))

    price_df = pd.concat(price_parts, ignore_index=True)
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date").sort_values("trade_date")
    factor_df = pd.concat(factor_parts, ignore_index=True)

    # Parquet raw_value 实际是 neutral
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # Universe filter
    price_df = price_df[
        (~price_df["is_st"])
        & (~price_df["is_suspended"])
        & (~price_df["is_new_stock"])
        & (price_df["board"].fillna("") != "bse")
    ].copy()

    print(f"  price: {price_df.shape}, bench: {bench_df.shape}, factor: {factor_df.shape}, {time.time()-t0:.1f}s")
    return price_df, bench_df, factor_df


def load_strategy_nav():
    """加载 yearly_chain_nav (Step 6-D 输出)."""
    p = BASELINE_DIR / "yearly_chain_nav.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} 不存在, 请先跑 scripts/yearly_breakdown_backtest.py"
        )
    df = pd.read_parquet(p)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.set_index("trade_date")["nav"]


# ============================================================
# 指标构建
# ============================================================


def build_factor_rolling_ic(factor_df, price_df, bench_df, rolling_months: int = 3) -> pd.Series:
    """指标 1: 5 因子 N 月滚动截面 IC 均值."""
    print(f"  [1] factor_rolling_ic ({rolling_months} 月滚动)...")
    fwd_ret = compute_forward_excess_returns(
        price_df, bench_df, horizon=HORIZON, price_col="adj_close"
    )

    all_ic = {}
    for f in CORE_FACTORS:
        fdf = factor_df[factor_df["factor_name"] == f]
        if fdf.empty:
            continue
        factor_wide = fdf.pivot_table(
            index="trade_date", columns="code", values="neutral_value", aggfunc="first"
        ).sort_index()
        common = factor_wide.index.intersection(fwd_ret.index)
        ic = compute_ic_series(factor_wide.loc[common], fwd_ret.loc[common])
        # 方向对齐: turnover/vol direction=-1, reversal/amihud/bp direction=+1
        direction = -1 if f in ("turnover_mean_20", "volatility_20") else 1
        all_ic[f] = ic * direction  # 调整后 IC 越大越好

    ic_df = pd.DataFrame(all_ic)  # (date × factor)
    # 每日跨因子均值 (5 因子信号强度)
    daily_mean_ic = ic_df.mean(axis=1)
    daily_mean_ic.index = pd.to_datetime(daily_mean_ic.index)

    # 月度滚动: 先按月聚合到当月平均, 再 rolling
    monthly = daily_mean_ic.resample("ME").mean()
    rolling = monthly.rolling(rolling_months, min_periods=1).mean()
    rolling.name = "factor_rolling_ic"
    return rolling


def build_smb_momentum(price_df, rolling_months: int = 3) -> pd.Series:
    """指标 2: 小盘 (市值后 50%) 过去 N 月相对大盘 (市值前 50%) 的超额收益."""
    print(f"  [2] smb_momentum ({rolling_months} 月)...")
    # 需要 market cap — 从 price_df 没有 total_mv, 从 daily_basic 会慢
    # 替代: 用 price_df 的 volume * close 作为 "活跃度 proxy", 或直接从 DB 读 daily_basic
    from app.services.db import get_sync_conn

    conn = get_sync_conn()
    mv = pd.read_sql(
        """SELECT k.code, k.trade_date, k.close, k.pre_close, db.total_mv
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           LEFT JOIN stock_status_daily ss ON k.code = ss.code AND k.trade_date = ss.trade_date
           WHERE k.volume > 0 AND k.pre_close > 0 AND db.total_mv > 0
             AND COALESCE(ss.is_st, false) = false
             AND COALESCE(ss.is_suspended, false) = false
             AND COALESCE(ss.is_new_stock, false) = false
             AND COALESCE(ss.board, '') != 'bse'""",
        conn,
    )
    conn.close()
    print(f"    market cap data: {len(mv):,} rows")

    mv["ret"] = mv["close"] / mv["pre_close"] - 1
    mv = mv[(mv["ret"] > -0.5) & (mv["ret"] < 0.5)]  # 清理异常

    # 每月末按市值分组
    smb_list = []
    grouped = mv.groupby("trade_date")
    for trade_date, day_df in grouped:
        if len(day_df) < 50:
            continue
        med = day_df["total_mv"].median()
        small = day_df[day_df["total_mv"] <= med]["ret"].mean()
        large = day_df[day_df["total_mv"] > med]["ret"].mean()
        smb_list.append({"trade_date": trade_date, "smb_daily": small - large})

    smb_df = pd.DataFrame(smb_list).sort_values("trade_date").set_index("trade_date")
    smb_df.index = pd.to_datetime(smb_df.index)

    # 月度复利
    monthly_smb = smb_df["smb_daily"].resample("ME").apply(lambda x: (1 + x).prod() - 1 if len(x) > 0 else 0)
    rolling_smb = monthly_smb.rolling(rolling_months, min_periods=1).sum()
    rolling_smb.name = "smb_momentum"
    return rolling_smb


def build_market_breadth(price_df) -> pd.Series:
    """指标 3: 月度上涨股票比例 (全 A).

    对每个月末, 计算该月 (adj_close(月末) / adj_close(月初) - 1) > 0 的比例.
    """
    print("  [3] market_breadth (monthly)...")
    price = price_df[["code", "trade_date", "adj_close"]].copy()
    price["trade_date"] = pd.to_datetime(price["trade_date"])
    price = price.sort_values(["code", "trade_date"])

    # 按月聚合, 每 code 每月取首末
    price["year_month"] = price["trade_date"].dt.to_period("M")

    def breadth(grp):
        first = grp.groupby("code")["adj_close"].first()
        last = grp.groupby("code")["adj_close"].last()
        ret = last / first - 1
        return (ret > 0).sum() / len(ret) if len(ret) > 0 else 0.5

    monthly_breadth = price.groupby("year_month").apply(breadth)
    monthly_breadth.index = monthly_breadth.index.to_timestamp("M")
    monthly_breadth.name = "market_breadth"
    return monthly_breadth


def build_factor_corr_mean(factor_df) -> pd.Series:
    """指标 4: 5 因子每月末截面相关系数均值 (因子拥挤度)."""
    print("  [4] factor_corr_mean (5-factor pairwise)...")
    # 5 因子宽表 (factor_name × date × code)
    wide = factor_df.pivot_table(
        index=["trade_date", "code"], columns="factor_name", values="neutral_value"
    ).reset_index()

    # 每月末取该月最后一天的截面, 计算 5 因子两两相关
    wide["trade_date"] = pd.to_datetime(wide["trade_date"])
    wide["year_month"] = wide["trade_date"].dt.to_period("M")

    results = []
    for ym, grp in wide.groupby("year_month"):
        # 取该月最后一个交易日
        last_date = grp["trade_date"].max()
        day = grp[grp["trade_date"] == last_date][CORE_FACTORS].dropna()
        if len(day) < 30:
            continue
        corr_matrix = day.corr(method="spearman")
        # 提取上三角 (不含对角)
        upper = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
        mean_corr = float(np.mean(np.abs(upper)))
        results.append({"year_month": ym.to_timestamp("M"), "factor_corr_mean": mean_corr})

    if not results:
        return pd.Series(dtype=float, name="factor_corr_mean")
    df = pd.DataFrame(results).set_index("year_month")
    return df["factor_corr_mean"]


def build_vol_regime(bench_df) -> pd.Series:
    """指标 5: CSI300 20 日已实现波动率 (月度末采样)."""
    print("  [5] vol_regime (CSI300 20d realized)...")
    df = bench_df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").set_index("trade_date")
    df["ret"] = df["close"].pct_change()
    df["vol_20d"] = df["ret"].rolling(20).std() * np.sqrt(244)

    # 月末采样
    monthly = df["vol_20d"].resample("ME").last()
    monthly.name = "vol_regime"
    return monthly


# ============================================================
# 预测能力分析
# ============================================================


def compute_future_strategy_sharpe(strategy_nav: pd.Series, horizons_months: list) -> pd.DataFrame:
    """计算从每月末开始的未来 N 月策略 Sharpe."""
    nav = strategy_nav.copy()
    nav.index = pd.to_datetime(nav.index)
    daily_ret = nav.pct_change().dropna()

    # 每月末作为评估点
    month_ends = daily_ret.resample("ME").last().index

    records = []
    for me in month_ends:
        row = {"month_end": me}
        for h in horizons_months:
            # 未来 h 月的日收益
            future_start = me + pd.Timedelta(days=1)
            future_end = me + pd.Timedelta(days=h * 30 + 10)
            future_ret = daily_ret[(daily_ret.index >= future_start) & (daily_ret.index <= future_end)]
            if len(future_ret) < 20:
                row[f"future_sharpe_{h}m"] = np.nan
                continue
            mean = future_ret.mean()
            std = future_ret.std()
            sharpe = (mean / std * np.sqrt(244)) if std > 0 else 0.0
            row[f"future_sharpe_{h}m"] = sharpe
        records.append(row)

    return pd.DataFrame(records).set_index("month_end")


def analyze_predictive_power(
    indicators: pd.DataFrame, future_sharpe: pd.DataFrame
) -> dict:
    """每个指标 vs 未来 Sharpe 的相关系数 + t-stat."""
    results = {}

    # 对齐月末索引
    indicators.index = pd.to_datetime(indicators.index)
    future_sharpe.index = pd.to_datetime(future_sharpe.index)

    # 归一到 month-end
    ind = indicators.copy()
    fut = future_sharpe.copy()
    ind = ind.groupby(ind.index.to_period("M")).last()
    fut = fut.groupby(fut.index.to_period("M")).last()
    ind.index = ind.index.to_timestamp("M")
    fut.index = fut.index.to_timestamp("M")

    common = ind.index.intersection(fut.index)
    ind = ind.loc[common]
    fut = fut.loc[common]

    for ind_name in ind.columns:
        ind_series = ind[ind_name]
        row = {"indicator": ind_name}
        for h in [1, 3, 6]:
            fut_col = f"future_sharpe_{h}m"
            if fut_col not in fut.columns:
                continue
            pair = pd.DataFrame({"i": ind_series, "f": fut[fut_col]}).dropna()
            if len(pair) < 12:
                row[f"corr_{h}m"] = None
                row[f"p_{h}m"] = None
                continue
            corr, p = scipy_stats.pearsonr(pair["i"].values, pair["f"].values)
            row[f"corr_{h}m"] = round(float(corr), 4)
            row[f"p_{h}m"] = round(float(p), 4)
            row[f"n_{h}m"] = int(len(pair))
        results[ind_name] = row

    return results


def regime_flag_oos_backtest(
    factor_rolling_ic: pd.Series, strategy_nav: pd.Series
) -> dict:
    """基于 factor_rolling_ic 的 regime flag OOS 测试.

    训练: 2014-2020, 用 rolling_ic 中位数作为阈值
    测试: 2021-2026, flag=1 时 Sharpe, flag=0 时 0 (现金)
    """
    strategy_nav = strategy_nav.copy()
    strategy_nav.index = pd.to_datetime(strategy_nav.index)
    daily_ret = strategy_nav.pct_change().dropna()

    ic_series = factor_rolling_ic.copy()
    ic_series.index = pd.to_datetime(ic_series.index)

    train_mask = ic_series.index < pd.Timestamp("2021-01-01")
    train_ic = ic_series[train_mask]

    if len(train_ic) < 12:
        return {"error": "insufficient training data"}

    # 阈值: 训练期 IC 中位数
    threshold = float(train_ic.median())

    # 生成月度 flag: 月末 rolling_ic > threshold → flag=1 (下月持仓)
    flags = (ic_series > threshold).astype(int)
    # flag lag 1 月: 本月末看 IC → 下月执行
    flags = flags.shift(1).fillna(1)  # 首月默认持仓

    # 应用到日频收益: 将 month-end flag 扩展到每天
    daily_flag = pd.Series(index=daily_ret.index, dtype=float)
    for month_end, flag in flags.items():
        mask = (daily_ret.index.to_period("M") == month_end.to_period("M"))
        daily_flag.loc[mask] = flag
    daily_flag = daily_flag.fillna(1)

    # flagged 策略日收益 = flag × original, 0 或 1
    flagged_ret = daily_ret * daily_flag

    # 分期对比
    def metrics(returns):
        r = returns.dropna()
        if len(r) < 20:
            return {}
        mean = r.mean()
        std = r.std()
        sharpe = (mean / std * np.sqrt(244)) if std > 0 else 0.0
        nav = (1 + r).cumprod()
        peak = nav.cummax()
        dd = (nav / peak - 1).min()
        total = nav.iloc[-1] - 1
        years = len(r) / 244
        annual = (1 + total) ** (1 / max(years, 0.01)) - 1
        return {
            "sharpe": round(float(sharpe), 4),
            "mdd": round(float(dd), 4),
            "annual": round(float(annual), 4),
            "total_return": round(float(total), 4),
            "days": int(len(r)),
        }

    train_mask_d = daily_ret.index < pd.Timestamp("2021-01-01")
    test_mask_d = daily_ret.index >= pd.Timestamp("2021-01-01")

    return {
        "threshold": round(threshold, 6),
        "train_baseline_2014_2020": metrics(daily_ret[train_mask_d]),
        "train_flagged_2014_2020": metrics(flagged_ret[train_mask_d]),
        "test_baseline_2021_2026": metrics(daily_ret[test_mask_d]),
        "test_flagged_2021_2026": metrics(flagged_ret[test_mask_d]),
        "test_days_active": int(daily_flag[test_mask_d].sum()),
        "test_days_total": int(test_mask_d.sum()),
    }


# ============================================================
# Main
# ============================================================


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    price_df, bench_df, factor_df = load_all_data()
    strategy_nav = load_strategy_nav()
    print(f"[Strategy NAV] {len(strategy_nav)} days, {strategy_nav.index[0]}..{strategy_nav.index[-1]}")

    print("\n[Indicators] 构建 5 个候选 regime 指标...")
    indicators = {}
    indicators["factor_rolling_ic"] = build_factor_rolling_ic(factor_df, price_df, bench_df)
    indicators["smb_momentum"] = build_smb_momentum(price_df)
    indicators["market_breadth"] = build_market_breadth(price_df)
    indicators["factor_corr_mean"] = build_factor_corr_mean(factor_df)
    indicators["vol_regime"] = build_vol_regime(bench_df)

    # 合并到 DataFrame
    ind_df = pd.concat(indicators, axis=1).sort_index()
    # 对齐月末
    ind_df.index = pd.to_datetime(ind_df.index)
    print(f"  Indicator DataFrame: {ind_df.shape}")
    print(f"  Date range: {ind_df.index.min()}..{ind_df.index.max()}")

    # 未来 Sharpe
    print("\n[Future Sharpe] 计算每月末的未来 1/3/6 月 Sharpe...")
    future_sharpe = compute_future_strategy_sharpe(strategy_nav, PREDICTION_HORIZONS_MONTHS)

    # 预测能力
    print("\n[Predictive Power] 各指标 vs 未来 Sharpe 相关系数...")
    predictive = analyze_predictive_power(ind_df, future_sharpe)

    print(f"\n  {'Indicator':<22} {'corr 1m':>9} {'p 1m':>7} {'corr 3m':>9} {'p 3m':>7} {'corr 6m':>9} {'p 6m':>7}")
    print("  " + "-" * 75)
    for ind_name, row in predictive.items():
        print(
            f"  {ind_name:<22} "
            f"{str(row.get('corr_1m', 'N/A')):>9} {str(row.get('p_1m', 'N/A')):>7} "
            f"{str(row.get('corr_3m', 'N/A')):>9} {str(row.get('p_3m', 'N/A')):>7} "
            f"{str(row.get('corr_6m', 'N/A')):>9} {str(row.get('p_6m', 'N/A')):>7}"
        )

    # OOS regime flag (仅当 factor_rolling_ic 有预测力)
    print("\n[Regime Flag OOS] 基于 factor_rolling_ic 的 flag 回测...")
    flag_result = regime_flag_oos_backtest(indicators["factor_rolling_ic"], strategy_nav)
    print(json.dumps(flag_result, indent=2, ensure_ascii=False))

    # 2017/2018/2022/2023 失效期指标快照
    print("\n[Crisis Periods] 失效年份前后指标值...")
    crisis_snapshots = {}
    for crisis_year in [2017, 2018, 2022, 2023]:
        start = pd.Timestamp(f"{crisis_year-1}-10-01")
        end = pd.Timestamp(f"{crisis_year}-03-31")
        period_ind = ind_df.loc[(ind_df.index >= start) & (ind_df.index <= end)]
        if period_ind.empty:
            continue
        crisis_snapshots[f"pre_{crisis_year}"] = {
            col: round(float(period_ind[col].mean()), 4)
            for col in period_ind.columns
            if not period_ind[col].isna().all()
        }

    # 保存指标
    ind_df_reset = ind_df.reset_index()
    ind_df_reset.columns = [
        "month_end" if c in ("index", "trade_date") else c for c in ind_df_reset.columns
    ]
    ind_path = BASELINE_DIR / "regime_indicators.json"
    ind_df_reset["month_end"] = ind_df_reset["month_end"].astype(str)
    ind_path.write_text(ind_df_reset.to_json(orient="records", indent=2, force_ascii=False))
    print(f"\n[Save] {ind_path}")

    # 保存分析结果
    analysis = {
        "meta": {
            "version": IC_CALCULATOR_VERSION,
            "id": IC_CALCULATOR_ID,
            "rolling_months": ROLLING_MONTHS,
            "prediction_horizons": PREDICTION_HORIZONS_MONTHS,
        },
        "predictive_power": predictive,
        "crisis_snapshots": crisis_snapshots,
        "regime_flag_oos": flag_result,
    }
    analysis_path = BASELINE_DIR / "regime_analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False, default=str))
    print(f"[Save] {analysis_path}")


if __name__ == "__main__":
    main()
