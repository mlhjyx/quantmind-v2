#!/usr/bin/env python3
"""模板11参数优化: nb_sh_sz_divergence + nb_vol_change。

在template11_modifier_backtest.py的基线+MODIFIER面板基础上，
对阈值/力度/平滑/死区做正交网格搜索，找最优参数组合。

搜索空间: 2信号 × 4阈值 × 3力度 × 4平滑 × 4死区 = 384组
每组只做数组运算(~0.1ms)，总计<30秒。

合格条件(同时满足):
  1. 减仓天数 < 35%
  2. 额外交易成本 < 5%年化
  3. MDD < -38.5% (vs基线-48.5%改善≥10pp)
  4. Sharpe ≥ 1.31 (基线90%)

用法:
    python scripts/research/template11_param_optimize.py
"""

from __future__ import annotations

import itertools
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

import numpy as np
import pandas as pd

from app.services.price_utils import _get_sync_conn

# 复用template11的基线构建和面板构建
sys.path.insert(0, str(Path(__file__).resolve().parent))
from template11_modifier_backtest import (
    BT_END,
    BT_START,
    EXTRA_COST_BPS,
    RF_ANNUAL,
    RF_DAILY,
    build_modifier_panel,
    build_top20_daily_returns,
)

# ── 搜索网格 ─────────────────────────────────────────
SIGNALS = ["nb_sh_sz_divergence", "nb_vol_change"]
SIGNAL_DIRECTIONS = {"nb_sh_sz_divergence": -1, "nb_vol_change": -1}

# 阈值: 信号百分位低于此值触发减仓
THRESHOLDS = [0.30, 0.20, 0.10, 0.05]
# 减仓力度: 触发时的仓位系数
REDUCE_LEVELS = [0.7, 0.5, 0.3]
# 信号平滑窗口(天)
SMOOTH_WINDOWS = [1, 3, 5, 10]  # 1=无平滑
# 死区: 信号连续N天满足条件才执行
DEAD_ZONES = [1, 2, 3, 5]  # 1=无死区

# 合格条件
MAX_REDUCE_PCT = 0.35
MAX_EXTRA_COST_ANNUAL = 0.05
MAX_MDD = -0.385  # 改善≥10pp vs 基线-48.5%
MIN_SHARPE = 1.31  # 基线90%


# ═══════════════════════════════════════════════════════
# 参数化仓位系数计算
# ═══════════════════════════════════════════════════════
def compute_coeff_parameterized(
    signal: pd.Series,
    direction: int,
    threshold: float,
    reduce_level: float,
    smooth: int,
    dead_zone: int,
) -> pd.Series:
    """参数化仓位系数计算。

    1. 可选平滑信号
    2. 计算expanding百分位（无前瞻偏差）
    3. 根据阈值+力度映射仓位
    4. 应用死区（连续N天满足才触发）
    """
    f = signal.dropna()
    if len(f) < 60:
        return pd.Series(1.0, index=signal.index)

    # 1. 平滑
    if smooth > 1:
        f = f.rolling(smooth, min_periods=1).mean()

    # 2. Expanding百分位（无前瞻偏差）
    pct = f.expanding(min_periods=60).apply(
        lambda x: np.sum(x[:-1] < x[-1]) / max(len(x) - 1, 1), raw=True
    )
    if direction == -1:
        pct = 1 - pct

    # 3. 阈值映射: 低于threshold → reduce_level, 否则 → 1.0
    raw_coeff = pd.Series(1.0, index=pct.index)
    raw_coeff[pct <= threshold] = reduce_level

    # 4. 死区: 信号连续dead_zone天满足减仓条件才执行
    if dead_zone > 1:
        is_reduce = (raw_coeff < 1.0).astype(int)
        # 连续减仓天数
        consecutive = pd.Series(0, index=is_reduce.index)
        count = 0
        for i in range(len(is_reduce)):
            if is_reduce.iloc[i]:
                count += 1
            else:
                count = 0
            consecutive.iloc[i] = count

        # 只有连续≥dead_zone天才真正减仓
        coeff = pd.Series(1.0, index=raw_coeff.index)
        coeff[consecutive >= dead_zone] = reduce_level

        # 恢复满仓也需要死区（对称）
        is_full = (coeff >= 1.0).astype(int)
        consec_full = pd.Series(0, index=is_full.index)
        count = 0
        for i in range(len(is_full)):
            if is_full.iloc[i]:
                count += 1
            else:
                count = 0
            consec_full.iloc[i] = count

        # 在满仓连续<dead_zone天内保持前一个状态
        final_coeff = coeff.copy()
        prev = 1.0
        for i in range(len(final_coeff)):
            if coeff.iloc[i] < 1.0:
                prev = coeff.iloc[i]
            elif consec_full.iloc[i] < dead_zone:
                final_coeff.iloc[i] = prev
            else:
                prev = 1.0
        coeff = final_coeff
    else:
        coeff = raw_coeff

    return coeff


# ═══════════════════════════════════════════════════════
# 快速回测（纯数组运算）
# ═══════════════════════════════════════════════════════
@dataclass
class OptResult:
    signal: str
    threshold: float
    reduce_level: float
    smooth: int
    dead_zone: int
    sharpe: float
    mdd: float
    calmar: float
    reduce_pct: float
    extra_cost_annual: float
    switch_count: int
    yearly: dict


def fast_backtest(
    base_ret: pd.Series,
    coeff: pd.Series,
    signal_name: str,
    threshold: float,
    reduce_level: float,
    smooth: int,
    dead_zone: int,
) -> OptResult:
    """快速叠加回测（纯数组运算）。"""
    # 对齐index
    br = base_ret.copy()
    br.index = pd.Index([d.date() if hasattr(d, "date") and callable(d.date) else d for d in br.index])
    cf = coeff.copy()
    cf.index = pd.Index([d.date() if hasattr(d, "date") and callable(d.date) else d for d in cf.index])
    common = br.index.intersection(cf.index)

    if len(common) < 60:
        return OptResult(signal_name, threshold, reduce_level, smooth, dead_zone,
                         0, 0, 0, 0, 0, 0, {})

    br = br.loc[common]
    cf = cf.loc[common]

    # 叠加
    modified_ret = br * cf + (1 - cf) * RF_DAILY
    delta_coeff = cf.diff().abs().fillna(0)
    extra_cost_series = delta_coeff * (EXTRA_COST_BPS / 10000)
    modified_ret = modified_ret - extra_cost_series

    # 指标
    nav = (1 + modified_ret).cumprod()
    n_years = len(modified_ret) / 252
    cagr = (float(nav.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0
    vol = float(modified_ret.std() * np.sqrt(252))
    sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0
    mdd = float(((nav - nav.cummax()) / nav.cummax()).min())
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0
    reduce_pct = float((cf < 0.95).mean())
    extra_cost_annual = float(extra_cost_series.sum()) / n_years if n_years > 0 else 0
    switch_count = int((cf.diff().abs() > 0.01).sum())

    # 年度分解
    yearly = {}
    dates_series = pd.Series([d.year for d in modified_ret.index], index=modified_ret.index)
    for year in range(BT_START.year, BT_END.year + 1):
        mask = dates_series == year
        yr = modified_ret[mask]
        if len(yr) < 20:
            continue
        yr_nav = (1 + yr).cumprod()
        yr_cagr = float(yr_nav.iloc[-1]) ** (252 / len(yr)) - 1
        yr_vol = float(yr.std() * np.sqrt(252))
        yr_sharpe = (yr_cagr - RF_ANNUAL) / yr_vol if yr_vol > 0 else 0
        yr_mdd = float(((yr_nav - yr_nav.cummax()) / yr_nav.cummax()).min())
        yr_reduce = float((cf[mask] < 0.95).mean())
        yearly[year] = (round(yr_sharpe, 2), round(yr_mdd * 100, 1), round(yr_reduce * 100, 0))

    return OptResult(
        signal=signal_name, threshold=threshold, reduce_level=reduce_level,
        smooth=smooth, dead_zone=dead_zone, sharpe=sharpe, mdd=mdd,
        calmar=calmar, reduce_pct=reduce_pct, extra_cost_annual=extra_cost_annual,
        switch_count=switch_count, yearly=yearly,
    )


# ═══════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════
def print_results(
    signal_name: str,
    all_results: list[OptResult],
    qualified: list[OptResult],
    baseline_sharpe: float,
    baseline_mdd: float,
) -> None:
    print(f"\n── {signal_name} ──")
    print(f"  总组数: {len(all_results)} | 合格组数: {len(qualified)}")

    if not qualified:
        # 显示最接近合格的Top-3
        near = sorted(all_results, key=lambda r: r.calmar, reverse=True)[:3]
        print("  无合格参数组。最接近的Top-3:")
        for i, r in enumerate(near, 1):
            fails = []
            if r.reduce_pct >= MAX_REDUCE_PCT:
                fails.append(f"减仓{r.reduce_pct*100:.0f}%>{MAX_REDUCE_PCT*100:.0f}%")
            if r.extra_cost_annual >= MAX_EXTRA_COST_ANNUAL:
                fails.append(f"成本{r.extra_cost_annual*100:.1f}%>{MAX_EXTRA_COST_ANNUAL*100:.0f}%")
            if r.mdd < MAX_MDD:
                fails.append(f"MDD{r.mdd*100:.1f}%<{MAX_MDD*100:.1f}%")
            if r.sharpe < MIN_SHARPE:
                fails.append(f"Sharpe{r.sharpe:.2f}<{MIN_SHARPE:.2f}")
            print(
                f"  {i}. P<{r.threshold:.2f} coeff={r.reduce_level} "
                f"smooth={r.smooth}d dead={r.dead_zone}d | "
                f"Sharpe={r.sharpe:.2f} MDD={r.mdd*100:.1f}% Calmar={r.calmar:.2f} "
                f"减仓{r.reduce_pct*100:.0f}% 成本{r.extra_cost_annual*100:.2f}% "
                f"切换{r.switch_count}次 | FAIL: {', '.join(fails)}"
            )
        return

    top5 = sorted(qualified, key=lambda r: r.calmar, reverse=True)[:5]
    print("\n  Top-5（按Calmar排序）:")
    header = (
        f"  {'#':>2s}  {'阈值':>6s}  {'力度':>4s}  {'平滑':>4s}  {'死区':>4s}  "
        f"{'Sharpe':>7s}  {'MDD%':>7s}  {'Calmar':>7s}  {'减仓%':>6s}  {'成本%':>6s}  {'切换':>5s}"
    )
    print(header)
    print(f"  {'─' * 2}  {'─' * 6}  {'─' * 4}  {'─' * 4}  {'─' * 4}  {'─' * 7}  {'─' * 7}  {'─' * 7}  {'─' * 6}  {'─' * 6}  {'─' * 5}")

    for i, r in enumerate(top5, 1):
        print(
            f"  {i:>2d}  P<{r.threshold:.2f}  {r.reduce_level:.1f}   "
            f"{r.smooth:>2d}dMA  {r.dead_zone:>2d}d   "
            f"{r.sharpe:>+7.2f}  {r.mdd * 100:>+7.1f}  {r.calmar:>7.2f}  "
            f"{r.reduce_pct * 100:>5.1f}%  {r.extra_cost_annual * 100:>5.2f}%  {r.switch_count:>5d}"
        )

    # 最优参数稳健性检查（邻近参数表现）
    best = top5[0]
    neighbors = [
        r for r in all_results
        if r.signal == best.signal
        and abs(THRESHOLDS.index(r.threshold) - THRESHOLDS.index(best.threshold)) <= 1
        and abs(REDUCE_LEVELS.index(r.reduce_level) - REDUCE_LEVELS.index(best.reduce_level)) <= 1
        and abs(SMOOTH_WINDOWS.index(r.smooth) - SMOOTH_WINDOWS.index(best.smooth)) <= 1
        and abs(DEAD_ZONES.index(r.dead_zone) - DEAD_ZONES.index(best.dead_zone)) <= 1
        and r is not best
    ]
    if neighbors:
        nbr_calmars = [r.calmar for r in neighbors]
        avg_nbr = np.mean(nbr_calmars)
        min_nbr = np.min(nbr_calmars)
        robust = "稳健(参数平原)" if min_nbr > best.calmar * 0.7 else "脆弱(孤立尖峰⚠️)"
        print(f"\n  稳健性: 最优Calmar={best.calmar:.2f}, 邻近{len(neighbors)}组 avg={avg_nbr:.2f} min={min_nbr:.2f} → {robust}")

    # 年度分解
    print(f"\n  最优参数年度分解 (P<{best.threshold} coeff={best.reduce_level} smooth={best.smooth}d dead={best.dead_zone}d):")
    print(f"  {'年份':>6s}  {'Sharpe':>8s}  {'MDD%':>7s}  {'减仓天%':>7s}")
    for year in sorted(best.yearly.keys()):
        s, m, rp = best.yearly[year]
        print(f"  {year:>6d}  {s:>+8.2f}  {m:>+7.1f}  {rp:>6.0f}%")


def main() -> None:
    conn = _get_sync_conn()

    # 基线
    base_ret = build_top20_daily_returns(conn)

    # 基线指标
    nav = (1 + base_ret).cumprod()
    n_years = len(base_ret) / 252
    cagr = (float(nav.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 else 0
    vol = float(base_ret.std() * np.sqrt(252))
    baseline_sharpe = (cagr - RF_ANNUAL) / vol if vol > 0 else 0
    baseline_mdd = float(((nav - nav.cummax()) / nav.cummax()).min())
    print(f"\n  基线: Sharpe={baseline_sharpe:.2f}, MDD={baseline_mdd*100:.1f}%")

    # MODIFIER面板
    panel = build_modifier_panel(conn)

    print(f"\n{'═' * 80}")
    print("  模板11参数优化")
    print(f"  搜索空间: {len(SIGNALS)} × {len(THRESHOLDS)} × {len(REDUCE_LEVELS)} × {len(SMOOTH_WINDOWS)} × {len(DEAD_ZONES)} = {len(SIGNALS)*len(THRESHOLDS)*len(REDUCE_LEVELS)*len(SMOOTH_WINDOWS)*len(DEAD_ZONES)}组")
    print(f"  合格条件: 减仓<{MAX_REDUCE_PCT*100:.0f}% + 成本<{MAX_EXTRA_COST_ANNUAL*100:.0f}% + MDD>{MAX_MDD*100:.1f}% + Sharpe≥{MIN_SHARPE:.2f}")
    print(f"{'═' * 80}")

    t0 = time.perf_counter()

    for signal_name in SIGNALS:
        if signal_name not in panel.columns:
            print(f"\n── {signal_name}: 不在面板中，跳过 ──")
            continue

        raw_signal = panel[signal_name]
        direction = SIGNAL_DIRECTIONS[signal_name]
        all_results: list[OptResult] = []

        for threshold, reduce_level, smooth, dead_zone in itertools.product(
            THRESHOLDS, REDUCE_LEVELS, SMOOTH_WINDOWS, DEAD_ZONES
        ):
            coeff = compute_coeff_parameterized(
                raw_signal, direction, threshold, reduce_level, smooth, dead_zone,
            )
            r = fast_backtest(
                base_ret, coeff, signal_name,
                threshold, reduce_level, smooth, dead_zone,
            )
            all_results.append(r)

        qualified = [
            r for r in all_results
            if r.reduce_pct < MAX_REDUCE_PCT
            and r.extra_cost_annual < MAX_EXTRA_COST_ANNUAL
            and r.mdd > MAX_MDD
            and r.sharpe >= MIN_SHARPE
        ]

        print_results(signal_name, all_results, qualified, baseline_sharpe, baseline_mdd)

    elapsed = time.perf_counter() - t0
    print(f"\n  总耗时: {elapsed:.1f}秒")

    # 综合结论
    print("\n── 综合结论 ──")
    print("  合格条件: 减仓<35% + 成本<5% + MDD改善≥10pp + Sharpe≥基线90%")
    print("  见上方各信号结果")
    print(f"{'═' * 80}\n")

    conn.close()


if __name__ == "__main__":
    main()
