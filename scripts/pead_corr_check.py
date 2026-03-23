#!/usr/bin/env python3
"""PEAD因子 vs 现有5因子 截面相关性验证。

直接从行情数据计算现有5因子，避免依赖factor_values表日期匹配问题。
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn
from engines.factor_engine import (
    calc_reversal, calc_volatility, calc_turnover_mean, calc_amihud, calc_bp_ratio,
)
from analyze_pead_factors import (
    load_prices_and_index, load_financial_data,
    calc_earnings_surprise_car, calc_earnings_revision, calc_ann_date_proximity,
)


def main():
    conn = _get_sync_conn()

    # 选6个截面日期覆盖全期
    eval_dates = [
        date(2021, 6, 30), date(2022, 3, 31), date(2022, 12, 30),
        date(2023, 6, 30), date(2024, 3, 29), date(2024, 12, 31),
    ]

    print("加载数据...")
    prices_raw, bench = load_prices_and_index(
        conn, date(2020, 9, 1), date(2025, 6, 30)
    )
    fina_df = pd.read_sql(
        """SELECT code, report_date, actual_ann_date, roe, roe_dt
           FROM financial_indicators WHERE actual_ann_date IS NOT NULL AND roe IS NOT NULL
           ORDER BY code, actual_ann_date""",
        conn,
    )

    # 加载行情 pivot
    prices_pivot = prices_raw.pivot_table(
        index="trade_date", columns="code", values="adj_close", aggfunc="first"
    ).sort_index()

    # 加载计算现有因子需要的数据
    klines = pd.read_sql(
        """SELECT k.code, k.trade_date,
                  k.close * COALESCE(k.adj_factor, 1) AS adj_close,
                  k.volume, k.amount, k.turnover_rate
           FROM klines_daily k
           WHERE k.trade_date >= '2020-09-01' AND k.trade_date <= '2025-06-30'
             AND k.volume > 0
           ORDER BY k.code, k.trade_date""",
        conn,
    )
    daily_basic = pd.read_sql(
        """SELECT code, trade_date, pb
           FROM daily_basic
           WHERE trade_date >= '2020-09-01' AND trade_date <= '2025-06-30'""",
        conn,
    )

    # 预计算现有因子的rolling值
    print("预计算现有5因子rolling值...")
    klines = klines.sort_values(["code", "trade_date"])

    klines["reversal_20"] = klines.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 20)
    )
    klines["volatility_20"] = klines.groupby("code")["adj_close"].transform(
        lambda x: calc_volatility(x, 20)
    )
    klines["turnover_mean_20"] = klines.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_mean(x, 20)
    )
    # amihud needs apply
    amihud_vals = klines.groupby("code").apply(
        lambda g: calc_amihud(g["adj_close"], g["volume"], g["amount"], 20)
    ).reset_index(level=0, drop=True)
    klines["amihud_20"] = amihud_vals

    # bp_ratio from daily_basic
    bp = daily_basic.copy()
    bp["bp_ratio"] = calc_bp_ratio(bp["pb"])

    print(f"\n{'='*70}")
    print("earnings_surprise_car vs 现有5因子 截面Spearman相关性")
    print(f"{'='*70}")

    existing_names = ["reversal_20", "volatility_20", "turnover_mean_20", "amihud_20", "bp_ratio"]
    all_corrs = {en: [] for en in existing_names}

    for eval_d in eval_dates:
        # 实际交易日
        td_list = sorted(prices_pivot.index)
        actual = [d for d in td_list if d <= eval_d]
        if not actual:
            continue
        eval_d_actual = actual[-1]

        # PEAD因子
        car = calc_earnings_surprise_car(fina_df, prices_pivot, bench, eval_d_actual)
        if car.empty or len(car) < 100:
            continue

        # 现有因子截面
        kl_day = klines[klines["trade_date"] == eval_d_actual].set_index("code")
        bp_day = bp[bp["trade_date"] == eval_d_actual].set_index("code")

        for en in existing_names:
            if en == "bp_ratio":
                ev = bp_day["bp_ratio"] if not bp_day.empty else pd.Series(dtype=float)
            else:
                ev = kl_day[en] if en in kl_day.columns else pd.Series(dtype=float)

            if ev.empty:
                continue

            common = car.index.intersection(ev.dropna().index)
            if len(common) < 100:
                continue

            corr, _ = stats.spearmanr(car.loc[common], ev.loc[common])
            all_corrs[en].append(corr)

        print(f"\n{eval_d_actual}:")
        for en in existing_names:
            if all_corrs[en]:
                print(f"  vs {en:25s}: {all_corrs[en][-1]:+.4f}")

    # 汇总
    print(f"\n{'─'*70}")
    print("平均截面相关性:")
    for en in existing_names:
        if all_corrs[en]:
            avg = np.mean(all_corrs[en])
            flag = "WARNING >0.5" if abs(avg) > 0.5 else "OK <0.5"
            print(f"  vs {en:25s}: {avg:+.4f}  [{flag}]")

    conn.close()


if __name__ == "__main__":
    main()
