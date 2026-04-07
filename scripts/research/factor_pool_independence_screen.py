#!/usr/bin/env python3
"""Step 1: PASS候选因子独立性筛选 — 从43个候选中筛选与Active低相关的独立alpha源。

方法:
1. 从factor_ic_history加载IC时序(ic_20d, >100天)
2. 计算48因子间IC相关矩阵
3. 筛选: 与所有Active |corr|<0.7, 且候选间|corr|<0.7
4. 输出独立候选列表 + IC统计

DSR改善逻辑: 独立alpha源→组合后Sharpe提升→DSR下降
"""

import logging
import os
import sys
from pathlib import Path

logging.disable(logging.DEBUG)

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd

from app.services.price_utils import _get_sync_conn


ACTIVE_FACTORS = [
    "turnover_mean_20",
    "volatility_20",
    "reversal_20",
    "amihud_20",
    "bp_ratio",
]

# CLAUDE.md因子方向
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}

CORR_THRESHOLD_VS_ACTIVE = 0.7  # 与Active因子相关性上限
CORR_THRESHOLD_VS_CANDIDATE = 0.7  # 候选因子间相关性上限
MIN_IC_DAYS = 200  # 最少IC数据天数


def main():
    conn = _get_sync_conn()

    print("=" * 70)
    print("因子独立性筛选: 43候选 → 独立alpha源")
    print("=" * 70)

    # 1. 加载IC时序
    print("\n[1/4] 加载IC时序...")
    df = pd.read_sql(
        """SELECT factor_name, trade_date, ic_20d
           FROM factor_ic_history
           WHERE ic_20d IS NOT NULL""",
        conn,
    )
    pivot = df.pivot_table(index="trade_date", columns="factor_name", values="ic_20d")
    print("  %d因子 x %d天" % (pivot.shape[1], pivot.shape[0]))

    # 过滤数据量不足的因子
    valid_factors = [f for f in pivot.columns if pivot[f].notna().sum() >= MIN_IC_DAYS]
    pivot = pivot[valid_factors]
    print("  过滤后(>=%d天): %d因子" % (MIN_IC_DAYS, len(valid_factors)))

    active_in_data = [f for f in ACTIVE_FACTORS if f in valid_factors]
    candidates = [f for f in valid_factors if f not in ACTIVE_FACTORS]
    print("  Active: %d, 候选: %d" % (len(active_in_data), len(candidates)))

    # 2. 计算相关矩阵
    print("\n[2/4] 计算IC相关矩阵...")
    corr_matrix = pivot.corr(method="pearson")

    # 3. 筛选独立候选
    print("\n[3/4] 筛选独立候选因子...")
    print("  条件: 与所有Active |corr|<%.1f, 候选间|corr|<%.1f"
          % (CORR_THRESHOLD_VS_ACTIVE, CORR_THRESHOLD_VS_CANDIDATE))

    # Step A: 与Active低相关
    independent = []
    rejected_active_corr = []
    for c in candidates:
        max_corr_with_active = 0
        blocking_factor = ""
        for a in active_in_data:
            corr_val = abs(corr_matrix.loc[c, a])
            if corr_val > max_corr_with_active:
                max_corr_with_active = corr_val
                blocking_factor = a
        if max_corr_with_active < CORR_THRESHOLD_VS_ACTIVE:
            independent.append(c)
        else:
            rejected_active_corr.append((c, blocking_factor, max_corr_with_active))

    print("\n  与Active低相关: %d个通过, %d个被拒" % (len(independent), len(rejected_active_corr)))
    if rejected_active_corr:
        print("  被拒(与Active高相关):")
        for name, blocker, corr_val in sorted(rejected_active_corr, key=lambda x: -x[2]):
            print("    %-30s |corr|=%.3f with %s" % (name, corr_val, blocker))

    # Step B: 候选间去冗余(贪心: 按|IC|从大到小, 逐个加入, 检查与已选的相关性)
    ic_stats = {}
    for f in independent:
        ic_series = pivot[f].dropna()
        ic_stats[f] = {
            "mean_ic": ic_series.mean(),
            "abs_mean_ic": abs(ic_series.mean()),
            "ic_std": ic_series.std(),
            "icir": ic_series.mean() / ic_series.std() if ic_series.std() > 0 else 0,
            "n_days": len(ic_series),
            "pct_positive": (ic_series > 0).mean(),
        }

    # 按|IC|从大到小排序
    sorted_candidates = sorted(independent, key=lambda f: -ic_stats[f]["abs_mean_ic"])

    final_selected = []
    rejected_candidate_corr = []
    for c in sorted_candidates:
        # 检查与已选候选的相关性
        blocked = False
        for selected in final_selected:
            if abs(corr_matrix.loc[c, selected]) >= CORR_THRESHOLD_VS_CANDIDATE:
                rejected_candidate_corr.append((c, selected, abs(corr_matrix.loc[c, selected])))
                blocked = True
                break
        if not blocked:
            final_selected.append(c)

    print("\n  候选间去冗余: %d个最终通过, %d个被拒" % (len(final_selected), len(rejected_candidate_corr)))
    if rejected_candidate_corr:
        print("  被拒(候选间高相关):")
        for name, blocker, corr_val in rejected_candidate_corr:
            print("    %-30s |corr|=%.3f with %s" % (name, corr_val, blocker))

    # 4. 输出结果
    print("\n[4/4] 独立候选因子结果")
    print("=" * 70)
    print("  %-30s %8s %8s %8s %6s" % ("因子", "|IC|", "ICIR", "IC方向", "天数"))
    print("  " + "-" * 64)
    for f in final_selected:
        s = ic_stats[f]
        direction = "+" if s["mean_ic"] > 0 else "-"
        print("  %-30s %8.4f %8.3f %8s %6d" % (
            f, s["abs_mean_ic"], abs(s["icir"]), direction, s["n_days"],
        ))

    # Active因子对照
    print("\n  --- Active因子(对照) ---")
    for f in active_in_data:
        ic_series = pivot[f].dropna()
        mean_ic = ic_series.mean()
        icir = mean_ic / ic_series.std() if ic_series.std() > 0 else 0
        print("  %-30s %8.4f %8.3f %8s %6d" % (
            f, abs(mean_ic), abs(icir), "+" if mean_ic > 0 else "-", len(ic_series),
        ))

    # 相关矩阵(仅选中+Active)
    selected_all = active_in_data + final_selected
    sub_corr = corr_matrix.loc[selected_all, selected_all]
    print("\n  --- 相关矩阵(选中+Active) ---")
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 120)
    # 简化显示: 只显示短名
    short_names = {f: f[:12] for f in selected_all}
    display_corr = sub_corr.rename(index=short_names, columns=short_names).round(2)
    print(display_corr.to_string())

    print("\n" + "=" * 70)
    print("结论: %d个独立候选因子(与Active corr<%.1f, 候选间corr<%.1f)"
          % (len(final_selected), CORR_THRESHOLD_VS_ACTIVE, CORR_THRESHOLD_VS_CANDIDATE))
    print("下一步: 对这些候选做paired bootstrap回测验证(p<0.05 vs 基线)")
    print("=" * 70)

    conn.close()


if __name__ == "__main__":
    main()
