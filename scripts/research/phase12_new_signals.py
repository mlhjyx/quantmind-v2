#!/usr/bin/env python
"""Phase 1.2: 新信号维度 — 行业动量 + 北向V2 IC评估 + CORE 5 对比分析。

Part 1.1: 行业动量因子 (ind_mom_20, ind_mom_60)
  经济学假设（铁律13）:
    行业动量效应 (Moskowitz & Grinblatt 1999): 近期表现强势的行业
    倾向于继续强势，背后是行业级信息扩散慢于股票级。
    [行业收益持续性] → [行业等权平均收益信号] → [direction=+1]

Part 1.2: 北向V2 15因子 IC 重评估 (via ic_calculator, 铁律19)

Part 2: IC时序相关性矩阵 + Regime多样化分析 + 推荐报告

使用:
    python scripts/research/phase12_new_signals.py
    python scripts/research/phase12_new_signals.py --dry-run
    python scripts/research/phase12_new_signals.py --years 5
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

CORE_5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
CORE_5_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": -1,
    "amihud_20": -1,
    "bp_ratio": 1,
}

NB_FACTORS = [
    "nb_ratio_change_5d",
    "nb_ratio_change_20d",
    "nb_trend_20d",
    "nb_change_rate_20d",
    "nb_increase_ratio_20d",
    "nb_net_buy_ratio",
    "nb_net_buy_5d_ratio",
    "nb_net_buy_20d_ratio",
    "nb_rank_change_20d",
    "nb_new_entry",
    "nb_consecutive_increase",
    "nb_concentration_signal",
    "nb_acceleration",
    "nb_change_excess",
    "nb_contrarian",
]

IND_MOM_DIRECTIONS = {"ind_mom_20": -1, "ind_mom_60": -1}  # A股行业反转效应
NB_DIRECTIONS = {f: -1 for f in NB_FACTORS}  # IC反向(CLAUDE.md)

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
    """从Parquet缓存加载 price_data + factor_data + benchmark。"""
    t0 = time.monotonic()
    frames_pd, frames_fd, frames_bm = [], [], []
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
        frames_fd.append(pd.read_parquet(ydir / "factor_data.parquet"))
        frames_bm.append(pd.read_parquet(ydir / "benchmark.parquet"))

    price_df = pd.concat(frames_pd, ignore_index=True)
    factor_df = pd.concat(frames_fd, ignore_index=True)
    bench_df = pd.concat(frames_bm, ignore_index=True)
    elapsed = time.monotonic() - t0
    print(
        f"  Parquet加载完成: price={len(price_df)}行, factor={len(factor_df)}行, "
        f"bench={len(bench_df)}行 ({elapsed:.1f}s)"
    )
    return price_df, factor_df, bench_df


def load_industry_mapping() -> dict[str, str]:
    """从DB加载 code → industry_sw1 映射。"""
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    cur.execute(
        "SELECT code, industry_sw1 FROM symbols "
        "WHERE industry_sw1 IS NOT NULL AND industry_sw1 != ''"
    )
    mapping = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    print(f"  行业映射加载: {len(mapping)} 只股票")
    return mapping


def load_single_nb_factor(
    factor_name: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """从DB加载单个北向因子的neutral_value，返回宽表(trade_date × code)。

    内存优化: 逐因子加载+pivot, 避免一次性加载60M行OOM。
    """
    conn = psycopg2.connect(**DB_PARAMS)
    sql = """
        SELECT code, trade_date,
               COALESCE(neutral_value, raw_value) AS value
        FROM factor_values
        WHERE factor_name = %s
    """
    params: list = [factor_name]
    if start_date:
        sql += " AND trade_date >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND trade_date <= %s"
        params.append(end_date)

    t0 = time.monotonic()
    df = pd.read_sql(sql, conn, params=params)
    conn.close()

    if df.empty:
        print(f"    {factor_name}: 无数据")
        return pd.DataFrame()

    # 直接pivot为宽表, 然后丢弃长表
    wide = df.pivot_table(
        index="trade_date", columns="code", values="value", aggfunc="last"
    ).sort_index()
    elapsed = time.monotonic() - t0
    print(f"    {factor_name}: {len(df)}行 → {wide.shape[0]}日×{wide.shape[1]}股 ({elapsed:.1f}s)")
    del df
    return wide


# ═══════════════════════════════════════════════════
# Part 1.1: 行业动量因子计算
# ═══════════════════════════════════════════════════


def compute_industry_momentum(
    price_df: pd.DataFrame,
    industry_map: dict[str, str],
    windows: tuple[int, ...] = (20, 60),
) -> dict[str, pd.DataFrame]:
    """计算行业动量因子。

    算法:
      1. 每只股票的日收益率 = adj_close.pct_change(1)
      2. 每日每行业的等权平均收益率
      3. 行业累计收益 = rolling(window).sum() (近似)
      4. 映射回个股: 每只股票取其所属行业的累计收益

    Returns:
        dict[factor_name, DataFrame(trade_date × code)]  宽表格式
    """
    t0 = time.monotonic()
    print("  计算行业动量因子...")

    # 过滤: 排除BJ/ST/停牌/新股
    mask = (
        (price_df["board"] != "bse")
        & (~price_df["is_st"])
        & (~price_df["is_suspended"])
        & (~price_df["is_new_stock"])
    )
    clean = price_df[mask][["code", "trade_date", "adj_close"]].copy()

    # 映射行业
    clean["industry"] = clean["code"].map(industry_map)
    clean = clean.dropna(subset=["industry"])

    # pivot → (trade_date × code) 宽表
    price_wide = clean.pivot_table(
        index="trade_date", columns="code", values="adj_close", aggfunc="last"
    ).sort_index()

    # 日收益率
    daily_ret = price_wide.pct_change(1, fill_method=None)

    # code → industry 映射 (只保留在price_wide中有的code)
    code_ind = {c: industry_map.get(c) for c in price_wide.columns}
    code_ind = {c: ind for c, ind in code_ind.items() if ind is not None}

    # 按行业分组计算等权平均日收益
    ind_groups: dict[str, list[str]] = {}
    for c, ind in code_ind.items():
        ind_groups.setdefault(ind, []).append(c)

    # 行业日均收益 (trade_date × industry) — 用dict+concat避免fragmentation
    ind_series: dict[str, pd.Series] = {}
    for ind, codes in ind_groups.items():
        valid_codes = [c for c in codes if c in daily_ret.columns]
        if valid_codes:
            ind_series[ind] = daily_ret[valid_codes].mean(axis=1)
    ind_daily_ret = pd.DataFrame(ind_series)

    results = {}
    for w in windows:
        factor_name = f"ind_mom_{w}"
        # 行业累计收益: rolling sum 近似于 log return 累加
        ind_cum = ind_daily_ret.rolling(w, min_periods=w // 2).sum()

        # 映射回个股 — 用numpy数组避免逐列赋值
        ind_cols = list(ind_cum.columns)
        ind_col_idx = {ind: i for i, ind in enumerate(ind_cols)}
        ind_cum_arr = ind_cum.values  # (n_dates, n_industries)
        code_cols = list(price_wide.columns)
        factor_arr = np.full((len(price_wide.index), len(code_cols)), np.nan)
        for col_i, c in enumerate(code_cols):
            ind = code_ind.get(c)
            if ind and ind in ind_col_idx:
                factor_arr[:, col_i] = ind_cum_arr[:, ind_col_idx[ind]]

        factor_wide = pd.DataFrame(factor_arr, index=price_wide.index, columns=code_cols)
        results[factor_name] = factor_wide
        n_valid = factor_wide.notna().sum().sum()
        print(
            f"    {factor_name}: {n_valid:,} 有效值, "
            f"{factor_wide.shape[0]}日 × {factor_wide.shape[1]}股"
        )

    elapsed = time.monotonic() - t0
    print(f"  行业动量计算完成 ({elapsed:.1f}s)")
    return results


# ═══════════════════════════════════════════════════
# IC 评估 + 汇总
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
    stats["ic_series"] = ic_series  # 保留用于相关性分析
    return stats


def build_core5_wide(factor_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """从Parquet factor_data构建CORE 5因子宽表。"""
    # factor_data的raw_value实际是neutral_value (见SCHEMA.md)
    results = {}
    for fname in CORE_5:
        sub = factor_df[factor_df["factor_name"] == fname]
        wide = sub.pivot_table(
            index="trade_date", columns="code", values="raw_value", aggfunc="last"
        ).sort_index()
        results[fname] = wide
        print(f"    {fname}: {wide.shape[0]}日 × {wide.shape[1]}股")
    return results


def evaluate_nb_factor_streaming(
    factor_name: str,
    fwd_returns: pd.DataFrame,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[dict, pd.Series] | None:
    """逐因子加载+评估+释放, 避免OOM。返回(stats, ic_series)或None。"""
    wide = load_single_nb_factor(factor_name, start_date, end_date)
    if wide.empty:
        return None
    stats = evaluate_factor_ic(wide, fwd_returns, factor_name)
    ic_s = stats.pop("ic_series")
    del wide
    gc.collect()
    return stats, ic_s


# ═══════════════════════════════════════════════════
# Part 2: 相关性分析 + Regime分析
# ═══════════════════════════════════════════════════


def compute_ic_correlation_matrix(
    all_ic_series: dict[str, pd.Series],
) -> pd.DataFrame:
    """计算IC时序相关性矩阵。"""
    ic_df = pd.DataFrame(all_ic_series)
    # 对齐日期 + 去NaN
    ic_df = ic_df.dropna(how="all")
    corr = ic_df.corr(method="spearman")
    return corr


def regime_analysis(
    all_ic_series: dict[str, pd.Series],
    bench_df: pd.DataFrame,
    window: int = 60,
) -> pd.DataFrame:
    """Regime分析: 牛市/熊市期间各因子IC表现。

    定义: bench 60日收益 > 0 → 牛市, 否则 → 熊市
    """
    bench = bench_df.set_index("trade_date")["close"].sort_index()
    bench_ret = bench.pct_change(window)

    results = []
    for fname, ic_s in all_ic_series.items():
        # 对齐日期
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
    """将IC结果写入factor_ic_history（简化版, 只写ic_20d）。"""
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
                None,  # ic_1d (未计算)
                None,  # ic_5d
                None,  # ic_10d
                float(clean.loc[td]),  # ic_20d
                None,  # ic_abs_1d
                None,  # ic_abs_5d
                float(ic_ma20.loc[td]) if pd.notna(ic_ma20.get(td)) else None,
                float(ic_ma60.loc[td]) if pd.notna(ic_ma60.get(td)) else None,
                "unknown",  # decay_level
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
# 报告生成
# ═══════════════════════════════════════════════════


def generate_report(
    all_stats: dict[str, dict],
    corr_matrix: pd.DataFrame,
    regime_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """生成Markdown分析报告。"""
    lines = [
        "# Phase 1.2: 新信号维度 IC 评估报告",
        "",
        f"**日期**: {date.today()} | **来源**: Phase 1.2 自动生成",
        "",
        "---",
        "",
        "## 1. 因子IC统计汇总",
        "",
        "| 因子 | 方向 | IC均值 | IC_IR | t-stat | 胜率 | 有效天数 | 评级 |",
        "|------|------|--------|-------|--------|------|---------|------|",
    ]

    all_directions = {**CORE_5_DIRECTIONS, **IND_MOM_DIRECTIONS, **NB_DIRECTIONS}

    for fname in sorted(all_stats.keys()):
        s = all_stats[fname]
        direction = all_directions.get(fname, 1)
        # 评级 (方向已在direction中体现)
        if abs(s["t_stat"]) >= 3.0 and abs(s["mean"]) >= 0.03:
            rating = "⭐⭐⭐"
        elif abs(s["t_stat"]) >= 2.5 and abs(s["mean"]) >= 0.02:
            rating = "⭐⭐"
        elif abs(s["t_stat"]) >= 2.0:
            rating = "⭐"
        else:
            rating = "—"

        lines.append(
            f"| {fname} | {direction:+d} | {s['mean']:.4f} | "
            f"{s['ir']:.3f} | {s['t_stat']:.2f} | "
            f"{s['hit_rate']:.1%} | {s['n_days']} | {rating} |"
        )

    # 新因子 vs CORE 5 对比
    lines.extend(
        [
            "",
            "## 2. 新因子 vs CORE 5 IC 时序相关性矩阵",
            "",
            "低相关性(<0.3)表示信息维度独立, 有组合价值。",
            "",
        ]
    )

    # 格式化相关矩阵
    new_factors = [f for f in corr_matrix.columns if f.startswith("ind_mom") or f.startswith("nb_")]
    core_factors = [f for f in corr_matrix.columns if f in CORE_5]

    if new_factors and core_factors:
        header = "| 新因子 \\ CORE | " + " | ".join(core_factors) + " |"
        sep = "|" + "---|" * (len(core_factors) + 1)
        lines.append(header)
        lines.append(sep)
        for nf in new_factors:
            vals = " | ".join(
                f"{corr_matrix.loc[nf, cf]:.3f}" if pd.notna(corr_matrix.loc[nf, cf]) else "N/A"
                for cf in core_factors
            )
            lines.append(f"| {nf} | {vals} |")

    # Regime 分析
    lines.extend(
        [
            "",
            "## 3. Regime 多样化分析 (牛/熊市IC)",
            "",
            "| 因子 | IC全期 | IC牛市 | IC熊市 | 牛市胜率 | 熊市胜率 | 方向反转 |",
            "|------|--------|--------|--------|---------|---------|---------|",
        ]
    )
    for _, row in regime_df.iterrows():
        flip = "⚠️ YES" if row["regime_sign_flip"] else "No"
        lines.append(
            f"| {row['factor']} | {row['ic_all']:.4f} | "
            f"{row['ic_bull']:.4f} | {row['ic_bear']:.4f} | "
            f"{row['bull_hit']:.1%} | {row['bear_hit']:.1%} | {flip} |"
        )

    # 推荐
    lines.extend(
        [
            "",
            "## 4. E2E 特征池推荐",
            "",
            "### 推荐入池 (独立信息 + IC显著)",
            "",
        ]
    )

    # 筛选推荐
    recommended = []
    for fname, s in all_stats.items():
        if fname in CORE_5:
            continue
        max_core_corr = 0.0
        for cf in CORE_5:
            if cf in corr_matrix.columns and fname in corr_matrix.index:
                c = abs(corr_matrix.loc[fname, cf])
                if pd.notna(c):
                    max_core_corr = max(max_core_corr, c)

        if abs(s["t_stat"]) >= 2.0 and max_core_corr < 0.5:
            recommended.append(
                {
                    "factor": fname,
                    "ic_mean": s["mean"],
                    "t_stat": s["t_stat"],
                    "max_core_corr": max_core_corr,
                }
            )

    recommended.sort(key=lambda x: abs(x["t_stat"]), reverse=True)

    if recommended:
        for r in recommended:
            lines.append(
                f"- **{r['factor']}**: IC={r['ic_mean']:.4f}, "
                f"t={r['t_stat']:.2f}, max_core_corr={r['max_core_corr']:.3f}"
            )
    else:
        lines.append("- 无因子满足推荐标准 (|t|≥2.0 且 max_core_corr<0.5)")

    lines.extend(
        [
            "",
            "### 不推荐 (高相关或IC不显著)",
            "",
        ]
    )
    not_recommended = [
        f for f in all_stats if f not in CORE_5 and f not in {r["factor"] for r in recommended}
    ]
    for fname in sorted(not_recommended):
        s = all_stats[fname]
        lines.append(f"- {fname}: IC={s['mean']:.4f}, t={s['t_stat']:.2f}")

    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已保存: {output_path}")


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════


def main() -> None:
    """主入口。"""
    parser = argparse.ArgumentParser(description="Phase 1.2 新信号维度 IC评估")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写DB")
    parser.add_argument("--years", type=int, default=12, help="回测年数(默认12)")
    parser.add_argument("--skip-nb", action="store_true", help="跳过北向因子加载(省时间)")
    args = parser.parse_args()

    end_year = 2026
    start_year = end_year - args.years + 1
    print(f"{'=' * 60}")
    print(f"Phase 1.2: 新信号维度 IC评估 ({start_year}-{end_year})")
    print(f"{'=' * 60}")

    # ── Step 1: 加载数据 ──
    print("\n[Step 1] 加载数据...")
    price_df, factor_df, bench_df = load_parquet_cache(start_year, end_year)
    industry_map = load_industry_mapping()

    # ── Step 2: 构建前瞻超额收益 (共享, 只算一次) ──
    print("\n[Step 2] 构建20日前瞻超额收益...")
    t0 = time.monotonic()
    # 过滤: 排除BJ/ST/停牌/新股
    clean_price = price_df[
        (price_df["board"] != "bse")
        & (~price_df["is_st"])
        & (~price_df["is_suspended"])
        & (~price_df["is_new_stock"])
    ][["code", "trade_date", "adj_close"]].copy()

    fwd_returns = compute_forward_excess_returns(
        clean_price, bench_df, horizon=20, price_col="adj_close"
    )
    print(
        f"  前瞻收益: {fwd_returns.shape[0]}日 × {fwd_returns.shape[1]}股 "
        f"({time.monotonic() - t0:.1f}s)"
    )

    # ── Step 3: 计算行业动量因子 ──
    print("\n[Step 3] 计算行业动量因子...")
    ind_mom_wide = compute_industry_momentum(price_df, industry_map)

    # 释放price_df (已不需要, fwd_returns已独立)
    del price_df, clean_price
    gc.collect()
    print("  [MEM] price_df已释放")

    # ── Step 4: 构建CORE 5因子宽表 ──
    print("\n[Step 4] 构建CORE 5因子宽表...")
    core5_wide = build_core5_wide(factor_df)

    # 释放factor_df
    del factor_df
    gc.collect()
    print("  [MEM] factor_df已释放")

    # ── Step 5+6: IC评估 ──
    all_stats: dict[str, dict] = {}
    all_ic_series: dict[str, pd.Series] = {}

    # 6a: 行业动量
    print("\n[Step 5] IC评估 — 行业动量...")
    for fname, fwide in ind_mom_wide.items():
        print(f"  评估 {fname}...")
        stats = evaluate_factor_ic(fwide, fwd_returns, fname)
        ic_s = stats.pop("ic_series")
        all_stats[fname] = stats
        all_ic_series[fname] = ic_s
        print(
            f"    IC={stats['mean']:.4f}, IR={stats['ir']:.3f}, "
            f"t={stats['t_stat']:.2f}, hit={stats['hit_rate']:.1%}"
        )
    del ind_mom_wide
    gc.collect()

    # 6b: CORE 5
    print("\n[Step 6] IC评估 — CORE 5...")
    for fname, fwide in core5_wide.items():
        print(f"  评估 {fname}...")
        stats = evaluate_factor_ic(fwide, fwd_returns, fname)
        ic_s = stats.pop("ic_series")
        all_stats[fname] = stats
        all_ic_series[fname] = ic_s
        print(
            f"    IC={stats['mean']:.4f}, IR={stats['ir']:.3f}, "
            f"t={stats['t_stat']:.2f}, hit={stats['hit_rate']:.1%}"
        )
    del core5_wide
    gc.collect()

    # 6c: 北向因子 (逐因子streaming, 避免OOM — 铁律9: 32GB硬约束)
    nb_evaluated: list[str] = []
    if not args.skip_nb:
        print(f"\n[Step 7] IC评估 — 北向{len(NB_FACTORS)}因子 (逐因子streaming)...")
        nb_start = date(start_year, 1, 1)
        nb_end = date(end_year, 12, 31)
        for fname in NB_FACTORS:
            result = evaluate_nb_factor_streaming(fname, fwd_returns, nb_start, nb_end)
            if result is not None:
                stats, ic_s = result
                all_stats[fname] = stats
                all_ic_series[fname] = ic_s
                nb_evaluated.append(fname)
                print(
                    f"    IC={stats['mean']:.4f}, IR={stats['ir']:.3f}, "
                    f"t={stats['t_stat']:.2f}, hit={stats['hit_rate']:.1%}"
                )
        print(f"  北向因子评估完成: {len(nb_evaluated)}/{len(NB_FACTORS)}")
    else:
        print("\n[Step 7] 跳过北向因子")

    # ── Step 8: IC写入DB (铁律11) ──
    print("\n[Step 8] IC写入factor_ic_history...")
    new_factor_names = ["ind_mom_20", "ind_mom_60"]  # 只写新因子的IC
    for fname in new_factor_names:
        if fname in all_ic_series:
            store_ic_to_db(fname, all_ic_series[fname], dry_run=args.dry_run)

    # ── Step 9: 相关性矩阵 ──
    print("\n[Step 9] IC时序相关性矩阵...")
    corr_matrix = compute_ic_correlation_matrix(all_ic_series)

    # 打印新因子 vs CORE 5 关键相关性
    all_new_names = new_factor_names + nb_evaluated
    for nf in all_new_names:
        if nf in corr_matrix.index:
            core_corrs = {
                cf: f"{corr_matrix.loc[nf, cf]:.3f}" for cf in CORE_5 if cf in corr_matrix.columns
            }
            max_corr = max(
                abs(corr_matrix.loc[nf, cf]) for cf in CORE_5 if cf in corr_matrix.columns
            )
            print(f"  {nf} vs CORE5: max|corr|={max_corr:.3f} {core_corrs}")

    # ── Step 10: Regime分析 ──
    print("\n[Step 10] Regime多样化分析...")
    regime_df = regime_analysis(all_ic_series, bench_df)

    # 找熊市表现好的新因子
    for _, row in regime_df.iterrows():
        if row["factor"] not in CORE_5 and not row["regime_sign_flip"]:
            if pd.notna(row["ic_bear"]) and abs(row["ic_bear"]) > 0.01:
                print(
                    f"  ✅ {row['factor']}: 熊市IC={row['ic_bear']:.4f} (牛市={row['ic_bull']:.4f})"
                )

    # ── Step 11: 生成报告 ──
    print("\n[Step 11] 生成报告...")
    report_path = (
        PROJECT_ROOT / "docs" / "research-kb" / "findings" / "phase12-new-signal-dimensions.md"
    )
    generate_report(all_stats, corr_matrix, regime_df, report_path)

    # ── 汇总 ──
    print(f"\n{'=' * 60}")
    print("Phase 1.2 IC评估完成")
    print(f"  总因子数: {len(all_stats)}")
    print(f"  新因子(行业动量): {new_factor_names}")
    print(f"  北向因子: {len(nb_evaluated)}个")
    print(f"  报告: {report_path}")
    if args.dry_run:
        print("  [DRY-RUN] 未写入DB")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
