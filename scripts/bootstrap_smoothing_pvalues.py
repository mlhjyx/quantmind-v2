"""Bootstrap p-value计算: 信号平滑方案 vs Raw LGB.

计算3个paired block bootstrap p值:
1. Inertia(0.7σ) vs Raw
2. Inertia(1.0σ) vs Raw
3. EMA(0.3)+Inertia(1.0σ) vs Raw

复用 lgb_signal_smoothing.py 的核心逻辑。
"""

import sys
import time
from pathlib import Path

import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

from scripts.lgb_signal_smoothing import (
    OOS_END,
    OOS_START,
    apply_ema_plus_inertia,
    apply_holding_inertia,
    build_portfolio_returns,
    calc_metrics,
    get_conn,
    load_oos_predictions,
    load_price_data,
    load_trade_dates,
    paired_block_bootstrap,
)


def main():
    t0 = time.time()

    # Load data
    oos_df = load_oos_predictions()
    conn = get_conn()
    try:
        price_df = load_price_data(conn, OOS_START, OOS_END)
        trade_dates = load_trade_dates(conn, OOS_START, OOS_END)
    finally:
        conn.close()

    returns_pivot = price_df.pivot(
        index="trade_date", columns="code", values="adj_close"
    ).pct_change().iloc[1:]

    # Raw LGB baseline
    raw_signal = oos_df[["trade_date", "code", "predicted"]].copy()
    raw_signal = raw_signal.rename(columns={"predicted": "score"})
    raw_ret_df, _ = build_portfolio_returns(raw_signal, returns_pivot, trade_dates)
    raw_rets = raw_ret_df["portfolio_return"].values
    raw_metrics = calc_metrics(raw_rets)
    print(f"Raw LGB: Sharpe={raw_metrics['ann_sharpe']:.3f}, n_days={raw_metrics['n_days']}")

    # --- Variant 1: Inertia(0.7σ) ---
    inertia07_signal = apply_holding_inertia(oos_df, trade_dates, bonus_std=0.7)
    inertia07_ret_df, _ = build_portfolio_returns(inertia07_signal, returns_pivot, trade_dates)
    inertia07_rets = inertia07_ret_df["portfolio_return"].values
    inertia07_metrics = calc_metrics(inertia07_rets)
    print(f"Inertia(0.7σ): Sharpe={inertia07_metrics['ann_sharpe']:.3f}, n_days={inertia07_metrics['n_days']}")

    # --- Variant 2: Inertia(1.0σ) ---
    inertia10_signal = apply_holding_inertia(oos_df, trade_dates, bonus_std=1.0)
    inertia10_ret_df, _ = build_portfolio_returns(inertia10_signal, returns_pivot, trade_dates)
    inertia10_rets = inertia10_ret_df["portfolio_return"].values
    inertia10_metrics = calc_metrics(inertia10_rets)
    print(f"Inertia(1.0σ): Sharpe={inertia10_metrics['ann_sharpe']:.3f}, n_days={inertia10_metrics['n_days']}")

    # --- Variant 3: EMA(0.3)+Inertia(1.0σ) ---
    combo_signal = apply_ema_plus_inertia(oos_df, trade_dates, alpha=0.3, bonus_std=1.0)
    combo_ret_df, _ = build_portfolio_returns(combo_signal, returns_pivot, trade_dates)
    combo_rets = combo_ret_df["portfolio_return"].values
    combo_metrics = calc_metrics(combo_rets)
    print(f"EMA(0.3)+Inertia(1.0σ): Sharpe={combo_metrics['ann_sharpe']:.3f}, n_days={combo_metrics['n_days']}")

    # --- Paired Block Bootstrap (block=20, n=10000) ---
    print("\n" + "=" * 60)
    print("Paired Block Bootstrap (block=20, n=10000, seed=42)")
    print("H0: smoothed Sharpe <= raw Sharpe")
    print("=" * 60)

    comparisons = [
        ("Inertia(0.7σ) vs Raw", inertia07_rets, raw_rets),
        ("Inertia(1.0σ) vs Raw", inertia10_rets, raw_rets),
        ("EMA(0.3)+Inertia(1.0σ) vs Raw", combo_rets, raw_rets),
    ]

    for label, smooth_rets, base_rets in comparisons:
        result = paired_block_bootstrap(
            smooth_rets, base_rets,
            n_boot=10000, block_size=20, seed=42,
        )
        sig = "***" if result["p_value"] < 0.01 else (
            "**" if result["p_value"] < 0.05 else (
                "*" if result["p_value"] < 0.10 else "n.s."
            )
        )
        print(f"\n{label}:")
        print(f"  Diff Sharpe: {result['orig_diff_sharpe']:.3f}")
        print(f"  p-value:     {result['p_value']:.4f}  {sig}")
        print(f"  95% CI:      [{result['ci_lo']:.3f}, {result['ci_hi']:.3f}]")

    # Save daily returns for reproducibility
    out_dir = project_root / "models"
    all_rets = pd.DataFrame({
        "trade_date": raw_ret_df["trade_date"].values,
        "raw_lgb": raw_rets,
    })
    # Align by trade_date for variants (they may differ slightly in length)
    for name, ret_df in [
        ("inertia_07", inertia07_ret_df),
        ("inertia_10", inertia10_ret_df),
        ("ema03_inertia10", combo_ret_df),
    ]:
        tmp = ret_df.rename(columns={"portfolio_return": name})
        all_rets = all_rets.merge(tmp[["trade_date", name]], on="trade_date", how="outer")

    all_rets = all_rets.sort_values("trade_date").reset_index(drop=True)
    save_path = out_dir / "smoothing_daily_returns.csv"
    all_rets.to_csv(save_path, index=False)
    print(f"\nDaily returns saved to {save_path}")

    elapsed = time.time() - t0
    print(f"Total time: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
