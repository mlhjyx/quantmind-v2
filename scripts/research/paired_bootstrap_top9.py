#!/usr/bin/env python3
"""17个独立候选中top 9做paired bootstrap回测。

方法:
1. 基线: 5因子等权 → daily_returns_base
2. 每个候选: 5+1因子等权 → daily_returns_variant
3. Paired bootstrap: Sharpe(variant) - Sharpe(base) > 0 的概率

p<0.05 → 候选因子显著提升策略
"""

import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

logging.disable(logging.DEBUG)

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import numpy as np
import pandas as pd
from engines.backtest_engine import BacktestConfig, PMSConfig, run_hybrid_backtest
from engines.slippage_model import SlippageConfig

from app.services.price_utils import _get_sync_conn

ACTIVE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
ACTIVE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}

# Top 9候选(ICIR>0.5, 排除ln_market_cap/size beta)
CANDIDATES = [
    ("price_volume_corr_20", -1),  # ICIR=1.02
    ("a158_corr5", -1),  # ICIR=0.91
    ("large_order_ratio", -1),  # ICIR=0.87
    ("relative_volume_20", -1),  # ICIR=0.83
    ("rsrs_raw_18", -1),  # ICIR=0.80
    ("kbar_kup", -1),  # ICIR=0.77
    ("mf_divergence", -1),  # ICIR=0.63
    ("momentum_5", -1),  # ICIR=0.52
    ("ep_ratio", 1),  # ICIR=0.50
]

N_BOOTSTRAP = 1000


def load_all_data(conn, start, end):
    """加载所有因子+价格+基准。"""
    all_factors = ACTIVE_FACTORS + [c[0] for c in CANDIDATES]
    placeholders = ",".join(["%s"] * len(all_factors))
    factor_df = pd.read_sql(
        f"""SELECT code, trade_date, factor_name, neutral_value as raw_value
           FROM factor_values
           WHERE factor_name IN ({placeholders})
             AND trade_date BETWEEN %s AND %s""",
        conn,
        params=(*all_factors, start, end),
    )
    price_data = pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(start, end),
    )
    benchmark = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start, end),
    )
    return factor_df, price_data, benchmark


def calc_sharpe(daily_returns):
    if len(daily_returns) < 20:
        return 0.0
    return float(daily_returns.mean() / daily_returns.std() * np.sqrt(244))


def paired_bootstrap_sharpe(ret_base, ret_variant, n=1000, seed=42):
    """Paired bootstrap: P(Sharpe_variant > Sharpe_base)."""
    rng = np.random.default_rng(seed)
    common = ret_base.index.intersection(ret_variant.index)
    rb = ret_base.loc[common].values
    rv = ret_variant.loc[common].values
    T = len(rb)
    if T < 50:
        return 1.0  # 数据不足

    wins = 0
    for _ in range(n):
        idx = rng.integers(0, T, size=T)
        s_base = rb[idx].mean() / rb[idx].std() * np.sqrt(244)
        s_var = rv[idx].mean() / rv[idx].std() * np.sqrt(244)
        if s_var > s_base:
            wins += 1
    return 1.0 - wins / n  # p-value: P(variant <= base)


def main():
    conn = _get_sync_conn()
    start, end = date(2021, 1, 1), date(2025, 12, 31)

    print("=" * 70)
    print("Paired Bootstrap: 9个独立候选 vs 5因子基线")
    print("=" * 70)

    print("\n[1/3] 加载数据...")
    t0 = time.time()
    factor_df, price_data, benchmark = load_all_data(conn, start, end)
    print("  因子: %d行, 价格: %d行 (%ds)" % (len(factor_df), len(price_data), time.time() - t0))

    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    # 基线
    print("\n[2/3] 运行回测...")
    print("  基线(5因子)...", end="", flush=True)
    t1 = time.time()
    base_factors = factor_df[factor_df["factor_name"].isin(ACTIVE_FACTORS)]
    result_base = run_hybrid_backtest(
        base_factors, ACTIVE_DIRECTIONS, price_data, config, benchmark
    )
    base_sharpe = calc_sharpe(result_base.daily_returns)
    print(" Sharpe=%.3f (%ds)" % (base_sharpe, time.time() - t1))

    # 逐个候选
    print(
        "\n  %-25s %8s %8s %8s %8s %6s" % ("候选因子", "Sharpe", "Delta", "p-value", "MDD%", "判定")
    )
    print("  " + "-" * 67)

    results = []
    for factor_name, direction in CANDIDATES:
        t2 = time.time()
        # 6因子 = 5 Active + 1 候选
        variant_factors = factor_df[factor_df["factor_name"].isin(ACTIVE_FACTORS + [factor_name])]
        variant_directions = {**ACTIVE_DIRECTIONS, factor_name: direction}

        try:
            result_var = run_hybrid_backtest(
                variant_factors,
                variant_directions,
                price_data,
                config,
                benchmark,
            )
            var_sharpe = calc_sharpe(result_var.daily_returns)
            var_mdd = float((result_var.daily_nav / result_var.daily_nav.cummax() - 1).min()) * 100

            # Paired bootstrap
            p_val = paired_bootstrap_sharpe(
                result_base.daily_returns,
                result_var.daily_returns,
                N_BOOTSTRAP,
            )

            delta = var_sharpe - base_sharpe
            verdict = "✅ PASS" if p_val < 0.05 else ("🟡 边际" if p_val < 0.10 else "❌ FAIL")

            print(
                "  %-25s %8.3f %+8.3f %8.4f %8.2f %6s (%ds)"
                % (factor_name, var_sharpe, delta, p_val, var_mdd, verdict, time.time() - t2)
            )
            results.append((factor_name, direction, var_sharpe, delta, p_val, var_mdd, verdict))
        except Exception as e:
            print("  %-25s ERROR: %s" % (factor_name, e))

    # 总结
    print("\n[3/3] 总结")
    print("=" * 70)
    passed = [r for r in results if r[4] < 0.05]
    marginal = [r for r in results if 0.05 <= r[4] < 0.10]
    print("  PASS (p<0.05): %d个" % len(passed))
    for r in passed:
        print("    %-25s Sharpe=%+.3f p=%.4f" % (r[0], r[3], r[4]))
    print("  边际 (0.05≤p<0.10): %d个" % len(marginal))
    for r in marginal:
        print("    %-25s Sharpe=%+.3f p=%.4f" % (r[0], r[3], r[4]))
    print("=" * 70)

    conn.close()


if __name__ == "__main__":
    main()
