#!/usr/bin/env python
"""Phase 1.2: Alpha158六因子 — 用户定义版本 IC评估。

六因子定义（非Qlib Alpha158版本, 按用户规格实现）:
  RSQR_20: 个股收益 ~ 市场收益 OLS R² (CAPM式, rolling 20d)
  RESI_20: 同上回归的截距/alpha (rolling 20d)
  IMAX_20: 窗口内最大日收益率 (rolling 20d)
  IMIN_20: 窗口内最小日收益率 (rolling 20d)
  QTLU_20: 窗口内收益率75th分位 (rolling 20d)
  CORD_20: 收盘价与时间序列的相关性 (rolling 20d)

经济学假设（铁律13）:
  RSQR_20: 系统风险暴露度——R²高=与市场联动强, R²低=特质风险大,
           A股散户溢价→低R²好 [direction=-1]
  RESI_20: 个股超额alpha——回归截距=扣除市场beta后的个股超额,
           正residual=近期跑赢市场 [direction=+1]
  IMAX_20: 极端正收益倾向——窗口内最大日收益率捕获彩票型收益偏好,
           A股散户追涨→高IMAX被高估 [direction=-1]
  IMIN_20: 极端负收益倾向——窗口内最小日收益率捕获尾部风险,
           深跌后均值回归 [direction=+1]
  QTLU_20: 收益分布右尾——75th分位数衡量上行潜力偏度,
           高QTLU=近期频繁上涨→动量/过度乐观 [direction=-1]
  CORD_20: 价格趋势强度——收盘价与时间的相关性=趋势线性度,
           高CORD=强上行趋势（可能反转） [direction=-1]

使用:
    python scripts/research/phase12_alpha158_six.py
    python scripts/research/phase12_alpha158_six.py --dry-run
    python scripts/research/phase12_alpha158_six.py --years 5
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))

from engines.ic_calculator import (
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

# ═══════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════

CACHE_DIR = PROJECT_ROOT / "cache" / "backtest"

CORE_5 = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

FACTOR_DIRECTIONS = {
    "RSQR_20": +1,  # 高R²好（A股机构重仓=市场联动强, 实证IC=+0.05）
    "RESI_20": -1,  # 负alpha(近期跑输)→均值回归, 实证IC=-0.068
    "IMAX_20": -1,  # 高极端正收益→高估
    "IMIN_20": +1,  # 深跌后均值回归
    "QTLU_20": -1,  # 高右尾→过度乐观
    "CORD_20": -1,  # 强趋势→反转
}

DB_PARAMS = {
    "dbname": "quantmind_v2",
    "user": "xin",
    "password": "quantmind",
    "host": "localhost",
}


# ═══════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════


def load_parquet_cache(start_year: int = 2014, end_year: int = 2026) -> tuple:
    """从Parquet缓存加载 price_data + benchmark。"""
    t0 = time.monotonic()
    frames_pd, frames_bm = [], []
    for year in range(start_year, end_year + 1):
        ydir = CACHE_DIR / str(year)
        if not ydir.exists():
            continue
        frames_pd.append(
            pd.read_parquet(
                ydir / "price_data.parquet",
                columns=[
                    "code",
                    "trade_date",
                    "adj_close",
                    "close",
                    "board",
                    "is_st",
                    "is_suspended",
                    "is_new_stock",
                ],
            )
        )
        frames_bm.append(pd.read_parquet(ydir / "benchmark.parquet"))

    price_df = pd.concat(frames_pd, ignore_index=True)
    bench_df = pd.concat(frames_bm, ignore_index=True)
    elapsed = time.monotonic() - t0
    print(
        f"  Parquet加载完成: price={len(price_df):,}行, bench={len(bench_df):,}行 ({elapsed:.1f}s)"
    )
    return price_df, bench_df


# ═══════════════════════════════════════════════════
# 因子计算: 简单四因子 (IMAX/IMIN/QTLU/CORD)
# ═══════════════════════════════════════════════════


def compute_simple_four(
    price_wide: pd.DataFrame,
    daily_ret: pd.DataFrame,
    window: int = 20,
) -> dict[str, pd.DataFrame]:
    """计算IMAX/IMIN/QTLU/CORD (简单rolling, 秒级完成)。"""
    t0 = time.monotonic()
    results = {}

    # IMAX_20: 窗口内最大日收益率
    results["IMAX_20"] = daily_ret.rolling(window, min_periods=window).max()
    n_valid = results["IMAX_20"].notna().sum().sum()
    print(f"    IMAX_20: {n_valid:,} 有效值 ({time.monotonic() - t0:.1f}s)")

    # IMIN_20: 窗口内最小日收益率
    results["IMIN_20"] = daily_ret.rolling(window, min_periods=window).min()
    n_valid = results["IMIN_20"].notna().sum().sum()
    print(f"    IMIN_20: {n_valid:,} 有效值 ({time.monotonic() - t0:.1f}s)")

    # QTLU_20: 窗口内收益率75th分位
    results["QTLU_20"] = daily_ret.rolling(window, min_periods=window).quantile(0.75)
    n_valid = results["QTLU_20"].notna().sum().sum()
    print(f"    QTLU_20: {n_valid:,} 有效值 ({time.monotonic() - t0:.1f}s)")

    # CORD_20: corr(close, time_index) over rolling window
    # corr(close, [0..W-1]) is invariant to shift, so corr(close, global_index) is equivalent
    time_idx = pd.Series(np.arange(len(price_wide), dtype=float), index=price_wide.index)
    cord = price_wide.rolling(window, min_periods=window).corr(time_idx)
    results["CORD_20"] = cord
    n_valid = cord.notna().sum().sum()
    print(f"    CORD_20: {n_valid:,} 有效值 ({time.monotonic() - t0:.1f}s)")

    print(f"  简单四因子计算完成 ({time.monotonic() - t0:.1f}s)")
    return results


# ═══════════════════════════════════════════════════
# 因子计算: RSQR/RESI (向量化rolling OLS)
# ═══════════════════════════════════════════════════


def compute_rsqr_resi(
    daily_ret: pd.DataFrame,
    market_ret: pd.Series,
    window: int = 20,
) -> dict[str, pd.DataFrame]:
    """计算RSQR_20和RESI_20 (向量化, 无逐元素OLS)。

    对于简单线性回归 y = alpha + beta * x + eps:
      R² = corr(x, y)²   ← 关键优化: 不需要逐窗口OLS
      beta = cov(x, y) / var(x)
      alpha = mean(y) - beta * mean(x)

    其中 x = market_return, y = stock_return, rolling window.
    """
    t0 = time.monotonic()
    print("  计算RSQR/RESI (向量化rolling OLS)...")

    # 对齐市场收益到stock日期, broadcast到所有列
    # market_ret是Series(index=trade_date), daily_ret是DataFrame(trade_date × code)
    mkt = market_ret.reindex(daily_ret.index)

    # RSQR_20 = corr(stock_ret, market_ret)²
    # pandas rolling.corr 支持 Series 对 DataFrame 的列广播
    rolling_corr = daily_ret.rolling(window, min_periods=window).corr(mkt)
    rsqr = rolling_corr**2
    n_valid = rsqr.notna().sum().sum()
    print(f"    RSQR_20: {n_valid:,} 有效值 ({time.monotonic() - t0:.1f}s)")

    # RESI_20 = alpha = mean(y) - beta * mean(x)
    # beta = cov(x,y) / var(x)
    rolling_mean_y = daily_ret.rolling(window, min_periods=window).mean()
    rolling_mean_x = mkt.rolling(window, min_periods=window).mean()

    # cov(x,y) = E[xy] - E[x]*E[y]
    xy = daily_ret.multiply(mkt, axis=0)
    rolling_mean_xy = xy.rolling(window, min_periods=window).mean()
    rolling_cov_xy = rolling_mean_xy - rolling_mean_y.multiply(rolling_mean_x, axis=0)

    # var(x) = E[x²] - E[x]²
    x2 = mkt**2
    rolling_mean_x2 = x2.rolling(window, min_periods=window).mean()
    rolling_var_x = rolling_mean_x2 - rolling_mean_x**2

    # beta = cov(x,y) / var(x), 防除零
    # 注意: var_x是Series, cov_xy是DataFrame, 必须用div(axis=0)按index对齐
    beta = rolling_cov_xy.div(rolling_var_x.replace(0, np.nan), axis=0)

    # alpha (intercept) = mean(y) - beta * mean(x)
    resi = rolling_mean_y - beta.multiply(rolling_mean_x, axis=0)
    n_valid = resi.notna().sum().sum()
    print(f"    RESI_20: {n_valid:,} 有效值 ({time.monotonic() - t0:.1f}s)")

    print(f"  RSQR/RESI计算完成 ({time.monotonic() - t0:.1f}s)")
    return {"RSQR_20": rsqr, "RESI_20": resi}


# ═══════════════════════════════════════════════════
# IC 评估
# ═══════════════════════════════════════════════════


def evaluate_factor_ic(
    factor_wide: pd.DataFrame,
    fwd_returns: pd.DataFrame,
    factor_name: str,
) -> dict:
    """评估单个因子的IC统计。"""
    ic_series = compute_ic_series(factor_wide, fwd_returns)
    stats = summarize_ic_stats(ic_series)
    stats["factor_name"] = factor_name
    stats["ic_series"] = ic_series
    return stats


# ═══════════════════════════════════════════════════
# 相关性 + Regime分析
# ═══════════════════════════════════════════════════


def compute_ic_correlation_matrix(
    all_ic_series: dict[str, pd.Series],
) -> pd.DataFrame:
    """计算IC时序相关性矩阵。"""
    ic_df = pd.DataFrame(all_ic_series)
    ic_df = ic_df.dropna(how="all")
    return ic_df.corr(method="spearman")


def regime_analysis(
    all_ic_series: dict[str, pd.Series],
    bench_df: pd.DataFrame,
    window: int = 60,
) -> pd.DataFrame:
    """Regime分析: 牛市/熊市期间各因子IC表现。"""
    bench = bench_df.set_index("trade_date")["close"].sort_index()
    bench_ret = bench.pct_change(window)

    results = []
    for fname, ic_s in all_ic_series.items():
        common = ic_s.index.intersection(bench_ret.index)
        if len(common) < 20:
            continue
        ic_aligned = ic_s.loc[common].dropna()
        br_aligned = bench_ret.loc[ic_aligned.index]

        bull_mask = br_aligned > 0
        bear_mask = br_aligned <= 0
        ic_bull = ic_aligned[bull_mask]
        ic_bear = ic_aligned[bear_mask]

        results.append(
            {
                "factor": fname,
                "ic_all": float(ic_aligned.mean()),
                "ic_bull": float(ic_bull.mean()) if len(ic_bull) > 10 else np.nan,
                "ic_bear": float(ic_bear.mean()) if len(ic_bear) > 10 else np.nan,
                "n_bull": len(ic_bull),
                "n_bear": len(ic_bear),
                "bull_hit": float((ic_bull > 0).mean()) if len(ic_bull) > 10 else np.nan,
                "bear_hit": float((ic_bear > 0).mean()) if len(ic_bear) > 10 else np.nan,
                "regime_sign_flip": (
                    bool(np.sign(ic_bull.mean()) != np.sign(ic_bear.mean()))
                    if len(ic_bull) > 10 and len(ic_bear) > 10
                    else False
                ),
            }
        )

    return pd.DataFrame(results).sort_values("factor").reset_index(drop=True)


# ═══════════════════════════════════════════════════
# IC写入DB (铁律11)
# ═══════════════════════════════════════════════════


def store_ic_to_db(
    factor_name: str,
    ic_series_20d: pd.Series,
    dry_run: bool = False,
) -> int:
    """将IC结果写入factor_ic_history。"""
    if ic_series_20d.dropna().empty:
        print(f"    {factor_name}: IC序列为空, 跳过写入")
        return 0

    clean = ic_series_20d.dropna()
    ic_ma20 = clean.rolling(20, min_periods=10).mean()
    ic_ma60 = clean.rolling(60, min_periods=30).mean()

    rows = []
    for td in clean.index:
        rows.append(
            (
                factor_name,
                td,
                None,
                None,
                None,  # ic_1d, ic_5d, ic_10d
                float(clean.loc[td]),  # ic_20d
                None,
                None,  # ic_abs_1d, ic_abs_5d
                float(ic_ma20.loc[td]) if pd.notna(ic_ma20.get(td)) else None,
                float(ic_ma60.loc[td]) if pd.notna(ic_ma60.get(td)) else None,
                "unknown",
            )
        )

    if dry_run:
        print(f"    [DRY-RUN] {factor_name}: 将写入 {len(rows)} 行")
        return len(rows)

    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    upsert_sql = """
        INSERT INTO factor_ic_history
            (factor_name, trade_date, ic_1d, ic_5d, ic_10d, ic_20d,
             ic_abs_1d, ic_abs_5d, ic_ma20, ic_ma60, decay_level)
        VALUES %s
        ON CONFLICT (factor_name, trade_date) DO UPDATE SET
            ic_20d     = EXCLUDED.ic_20d,
            ic_ma20    = EXCLUDED.ic_ma20,
            ic_ma60    = EXCLUDED.ic_ma60,
            decay_level = EXCLUDED.decay_level
    """
    psycopg2.extras.execute_values(cur, upsert_sql, rows, page_size=500)
    conn.commit()
    conn.close()
    print(f"    {factor_name}: 写入 {len(rows)} 行到 factor_ic_history")
    return len(rows)


# ═══════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════


def generate_report(
    all_stats: dict[str, dict],
    corr_matrix: pd.DataFrame,
    regime_df: pd.DataFrame,
    max_core_corr: dict[str, tuple[str, float]],
    output_path: Path,
) -> None:
    """生成Markdown分析报告。"""
    lines = [
        "# Phase 1.2: Alpha158六因子 IC评估报告",
        "",
        f"**日期**: {date.today()} | **来源**: phase12_alpha158_six.py",
        "",
        "---",
        "",
        "## 1. 因子IC统计汇总",
        "",
        "| 因子 | 方向 | IC均值 | IC_IR | t-stat | 胜率 | 有效天数 | 评级 |",
        "|------|------|--------|-------|--------|------|---------|------|",
    ]

    for fname in sorted(all_stats.keys()):
        s = all_stats[fname]
        direction = FACTOR_DIRECTIONS.get(fname, 1)
        if abs(s["t_stat"]) >= 3.0 and abs(s["mean"]) >= 0.03:
            rating = "***"
        elif abs(s["t_stat"]) >= 2.5 and abs(s["mean"]) >= 0.02:
            rating = "**"
        elif abs(s["t_stat"]) >= 2.0:
            rating = "*"
        else:
            rating = "-"

        lines.append(
            f"| {fname} | {direction:+d} | {s['mean']:.4f} | "
            f"{s['ir']:.3f} | {s['t_stat']:.2f} | "
            f"{s['hit_rate']:.1%} | {s['n_days']} | {rating} |"
        )

    # CORE 5 vs 新因子 IC时序相关性
    lines.extend(
        [
            "",
            "---",
            "",
            "## 2. 新因子 vs CORE 5 IC时序相关性",
            "",
            "| 新因子 | 最高CORE相关 | CORE因子 | 冗余? |",
            "|--------|-------------|----------|-------|",
        ]
    )
    for fname in sorted(FACTOR_DIRECTIONS.keys()):
        if fname in max_core_corr:
            core_name, corr_val = max_core_corr[fname]
            redundant = "YES" if abs(corr_val) > 0.5 else "no"
            lines.append(f"| {fname} | {corr_val:.3f} | {core_name} | {redundant} |")

    # Regime分析
    lines.extend(
        [
            "",
            "---",
            "",
            "## 3. Regime分析 (牛/熊市IC)",
            "",
            "| 因子 | IC_all | IC_bull | IC_bear | 方向翻转? | 牛N | 熊N |",
            "|------|--------|---------|---------|----------|-----|-----|",
        ]
    )
    if not regime_df.empty:
        for _, r in regime_df.iterrows():
            flip = "YES" if r["regime_sign_flip"] else "no"
            lines.append(
                f"| {r['factor']} | {r['ic_all']:.4f} | "
                f"{r['ic_bull']:.4f} | {r['ic_bear']:.4f} | "
                f"{flip} | {r['n_bull']} | {r['n_bear']} |"
            )

    # 完整相关性矩阵
    lines.extend(
        [
            "",
            "---",
            "",
            "## 4. 全因子IC时序相关性矩阵",
            "",
        ]
    )
    if not corr_matrix.empty:
        header = "| | " + " | ".join(corr_matrix.columns) + " |"
        sep = "|---" * (len(corr_matrix.columns) + 1) + "|"
        lines.extend([header, sep])
        for idx, row in corr_matrix.iterrows():
            vals = " | ".join(f"{v:.3f}" for v in row)
            lines.append(f"| {idx} | {vals} |")

    lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  报告写入: {output_path}")


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Phase 1.2: Alpha158六因子IC评估")
    parser.add_argument("--dry-run", action="store_true", help="不写DB")
    parser.add_argument("--years", type=int, default=12, help="回溯年数(默认12)")
    args = parser.parse_args()

    start_year = max(2014, 2026 - args.years)
    print(f"{'=' * 60}")
    print("Phase 1.2: Alpha158六因子 IC评估")
    print(f"  范围: {start_year}-2026, dry_run={args.dry_run}")
    print(f"{'=' * 60}")

    # ─── 1. 加载数据 ───
    print("\n[1/6] 加载Parquet缓存...")
    price_df, bench_df = load_parquet_cache(start_year, 2026)

    # 过滤: 排除BJ/ST/停牌/新股
    mask = (
        (price_df["board"] != "bse")
        & (~price_df["is_st"])
        & (~price_df["is_suspended"])
        & (~price_df["is_new_stock"])
    )
    clean = price_df[mask][["code", "trade_date", "adj_close", "close"]].copy()
    print(f"  过滤后: {len(clean)}行, {clean['code'].nunique()}只股票")

    # ─── 2. 构建price宽表 + daily returns ───
    print("\n[2/6] 构建宽表...")
    price_wide = clean.pivot_table(
        index="trade_date",
        columns="code",
        values="adj_close",
        aggfunc="last",
    ).sort_index()
    daily_ret = price_wide.pct_change(1, fill_method=None)
    print(f"  price_wide: {price_wide.shape[0]}日 × {price_wide.shape[1]}股")

    # 市场收益 (CSI300)
    bench_price = bench_df.set_index("trade_date")["close"].sort_index().astype(float)
    market_ret = bench_price.pct_change(1)
    print(f"  market_ret: {market_ret.dropna().shape[0]}日")

    # ─── 3. 计算forward excess returns ───
    print("\n[3/6] 计算前瞻超额收益 (horizon=20d)...")
    t0 = time.monotonic()
    # ic_calculator expects long format (code, trade_date, adj_close)
    price_long = clean[["code", "trade_date", "adj_close"]].copy()
    bench_long = bench_df[["trade_date", "close"]].drop_duplicates("trade_date").copy()
    fwd_returns = compute_forward_excess_returns(price_long, bench_long, horizon=20)
    del price_long, bench_long
    print(f"  fwd_returns: {fwd_returns.shape}, {time.monotonic() - t0:.1f}s")

    # ─── 4. 计算六因子 (先简单四个, 后RSQR/RESI) ───
    print("\n[4/6] 计算因子...")

    # 4a. 简单四因子
    print("  --- 简单四因子 (IMAX/IMIN/QTLU/CORD) ---")
    simple_factors = compute_simple_four(price_wide, daily_ret, window=20)

    # 4b. RSQR/RESI
    print("  --- RSQR/RESI (向量化rolling OLS) ---")
    ols_factors = compute_rsqr_resi(daily_ret, market_ret, window=20)

    all_factors = {**simple_factors, **ols_factors}
    del simple_factors, ols_factors
    gc.collect()

    # ─── 5. IC评估 + 入库 ───
    print("\n[5/6] IC评估...")
    all_stats = {}
    all_ic_series = {}

    for fname, factor_wide in sorted(all_factors.items()):
        print(f"  评估 {fname}...")
        stats = evaluate_factor_ic(factor_wide, fwd_returns, fname)
        ic_s = stats.pop("ic_series")
        all_stats[fname] = stats
        all_ic_series[fname] = ic_s

        direction = FACTOR_DIRECTIONS.get(fname, 1)
        dir_aligned = np.sign(stats["mean"]) == np.sign(direction) if stats["mean"] != 0 else False
        print(
            f"    IC={stats['mean']:.4f}, IR={stats['ir']:.3f}, t={stats['t_stat']:.2f}, "
            f"hit={stats['hit_rate']:.1%}, n={stats['n_days']}, "
            f"方向{'✓' if dir_aligned else '✗'}"
        )

        # IC入库(铁律11)
        store_ic_to_db(fname, ic_s, dry_run=args.dry_run)

    del all_factors
    gc.collect()

    # ─── 5b. CORE 5 IC (用于相关性比对, 从DB加载) ───
    print("\n  构建CORE 5 IC (from DB)...")
    conn = psycopg2.connect(**DB_PARAMS)
    core5_ic = {}
    for fname in CORE_5:
        df_c5 = pd.read_sql(
            "SELECT code, trade_date, COALESCE(neutral_value, raw_value) as value "
            "FROM factor_values WHERE factor_name = %s AND raw_value IS NOT NULL",
            conn,
            params=(fname,),
        )
        if df_c5.empty:
            continue
        df_c5["trade_date"] = pd.to_datetime(df_c5["trade_date"]).dt.date
        wide_c5 = df_c5.pivot_table(
            index="trade_date", columns="code", values="value", aggfunc="last"
        ).sort_index()
        common_d = wide_c5.index.intersection(fwd_returns.index)
        common_c = wide_c5.columns.intersection(fwd_returns.columns)
        if len(common_d) < 30:
            continue
        ic_s = compute_ic_series(
            wide_c5.loc[common_d, common_c], fwd_returns.loc[common_d, common_c]
        )
        core5_ic[fname] = ic_s
        all_ic_series[fname] = ic_s
        print(f"    {fname}: IC={ic_s.mean():.4f}, {len(ic_s)}天")
        del df_c5, wide_c5
    conn.close()
    gc.collect()

    # ─── 6. 相关性 + Regime + 报告 ───
    print("\n[6/6] 分析与报告...")

    # IC时序相关性矩阵
    corr_matrix = compute_ic_correlation_matrix(all_ic_series)
    print("  IC相关性矩阵:")
    new_factors = sorted(FACTOR_DIRECTIONS.keys())
    for fname in new_factors:
        core_corrs = {
            c: abs(corr_matrix.loc[fname, c])
            for c in CORE_5
            if fname in corr_matrix.index and c in corr_matrix.columns
        }
        if core_corrs:
            max_core = max(core_corrs, key=core_corrs.get)
            print(f"    {fname} vs CORE max: |{corr_matrix.loc[fname, max_core]:.3f}| ({max_core})")

    # max_core_corr for report
    max_core_corr = {}
    for fname in new_factors:
        core_corrs = {}
        for c in CORE_5:
            if fname in corr_matrix.index and c in corr_matrix.columns:
                core_corrs[c] = corr_matrix.loc[fname, c]
        if core_corrs:
            max_c = max(core_corrs, key=lambda k: abs(core_corrs[k]))
            max_core_corr[fname] = (max_c, core_corrs[max_c])

    # Regime分析
    regime_df = regime_analysis(all_ic_series, bench_df)
    print("\n  Regime分析 (新因子):")
    for _, r in regime_df[regime_df["factor"].isin(new_factors)].iterrows():
        flip = "FLIP!" if r["regime_sign_flip"] else "stable"
        print(f"    {r['factor']}: bull={r['ic_bull']:.4f}, bear={r['ic_bear']:.4f} [{flip}]")

    # 报告
    report_path = PROJECT_ROOT / "docs" / "research-kb" / "findings" / "phase12-alpha158-six.md"
    generate_report(all_stats, corr_matrix, regime_df, max_core_corr, report_path)

    # 总结
    print(f"\n{'=' * 60}")
    print("Alpha158六因子 IC评估完成")
    print(f"{'=' * 60}")
    print("\n因子IC汇总:")
    print(f"{'因子':<12} {'IC均值':>8} {'IR':>8} {'t-stat':>8} {'方向':>4} {'评级':>4}")
    print("-" * 52)
    for fname in sorted(all_stats.keys()):
        s = all_stats[fname]
        d = FACTOR_DIRECTIONS.get(fname, 1)
        if abs(s["t_stat"]) >= 2.5:
            rating = "PASS"
        else:
            rating = "FAIL"
        print(
            f"{fname:<12} {s['mean']:>8.4f} {s['ir']:>8.3f} {s['t_stat']:>8.2f} {d:>+4d} {rating:>4}"
        )

    print(f"\nIC入库: {'DRY-RUN(未写入)' if args.dry_run else '已写入factor_ic_history'}")
    print(f"报告: {report_path}")


if __name__ == "__main__":
    main()
