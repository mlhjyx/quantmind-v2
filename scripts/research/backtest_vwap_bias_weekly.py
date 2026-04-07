#!/usr/bin/env python3
"""vwap_bias_1d 周度FastRanking回测 vs 月度5因子基线。

测试方案:
  A) 基线: 5因子月度等权 Top-20 (当前PT配置)
  B) 卫星: vwap_bias_1d 单因子周度 Top-15 (FastRanking)
  C) 对比: vwap_bias_1d 单因子月度 Top-15 (验证频率差异)

全部使用生产级成本模型(volume_impact滑点+佣金+印花税)。

Usage:
    python scripts/research/backtest_vwap_bias_weekly.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import logging
import warnings

warnings.filterwarnings("ignore", category=UserWarning)

# 抑制回测引擎debug日志(封板等)
logging.basicConfig(level=logging.WARNING)
import structlog

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

import pandas as pd
import psycopg2
from engines.backtest_engine import BacktestConfig, PMSConfig, run_hybrid_backtest

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

# 基线5因子
BASELINE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
BASELINE_DIRECTIONS = {
    "turnover_mean_20": -1, "volatility_20": -1, "reversal_20": +1,
    "amihud_20": +1, "bp_ratio": +1,
}

# vwap_bias_1d
VWAP_FACTOR = "vwap_bias_1d"
VWAP_DIRECTION = {VWAP_FACTOR: -1}


def load_data(conn, factors: list[str], start: str, end: str):
    """加载因子和价格数据。"""
    placeholders = ",".join(f"'{f}'" for f in factors)

    print(f"  Loading factor_values for {factors}...")
    factor_df = pd.read_sql(
        f"""SELECT code, trade_date, factor_name, zscore::float as raw_value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
              AND trade_date >= '{start}' AND trade_date <= '{end}'
              AND zscore IS NOT NULL
            ORDER BY trade_date, code""",
        conn,
    )
    print(f"    Rows: {len(factor_df):,}")

    print("  Loading price_data...")
    price_data = pd.read_sql(
        f"""SELECT k.code, k.trade_date,
                   k.open::float, k.close::float, k.high::float, k.low::float,
                   k.pre_close::float,
                   k.volume::bigint, k.amount::float,
                   k.adj_factor::float,
                   COALESCE(k.up_limit::float, k.close::float * 1.1) as up_limit,
                   COALESCE(k.down_limit::float, k.close::float * 0.9) as down_limit,
                   COALESCE(db.turnover_rate::float, 0) as turnover_rate
            FROM klines_daily k
            LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
            WHERE k.trade_date >= '{start}' AND k.trade_date <= '{end}'
              AND k.volume > 0
            ORDER BY k.trade_date, k.code""",
        conn,
    )
    print(f"    Rows: {len(price_data):,}")

    print("  Loading benchmark...")
    benchmark = pd.read_sql(
        f"""SELECT trade_date, close::float
            FROM index_daily
            WHERE index_code='000300.SH'
              AND trade_date >= '{start}' AND trade_date <= '{end}'
            ORDER BY trade_date""",
        conn,
    )

    return factor_df, price_data, benchmark


def calc_metrics(result) -> dict:
    """从BacktestResult计算核心指标。"""
    nav = result.daily_nav
    rets = result.daily_returns
    n_years = len(rets) / 252
    annual_ret = (nav.iloc[-1] / nav.iloc[0]) ** (1 / n_years) - 1 if n_years > 0 else 0
    sharpe = rets.mean() / rets.std() * (252 ** 0.5) if rets.std() > 0 else 0
    drawdown = (nav / nav.cummax() - 1)
    mdd = drawdown.min()
    calmar = annual_ret / abs(mdd) if abs(mdd) > 1e-6 else 0
    total_trades = len(result.trades)
    avg_turnover = result.turnover_series.mean() if len(result.turnover_series) > 0 else 0
    return {
        "annual_return": annual_ret,
        "sharpe_ratio": sharpe,
        "max_drawdown": mdd,
        "calmar_ratio": calmar,
        "total_trades": total_trades,
        "avg_turnover": avg_turnover,
    }


def print_result(name: str, result):
    """打印回测结果摘要。"""
    m = calc_metrics(result)
    print(f"\n  {'─' * 50}")
    print(f"  {name}")
    print(f"  {'─' * 50}")
    print(f"    Annual Return:  {m['annual_return']:>+8.2%}")
    print(f"    Sharpe Ratio:   {m['sharpe_ratio']:>8.2f}")
    print(f"    Max Drawdown:   {m['max_drawdown']:>8.2%}")
    print(f"    Calmar Ratio:   {m['calmar_ratio']:>8.2f}")
    print(f"    Total Trades:   {m['total_trades']:>8d}")
    print(f"    Avg Turnover:   {m['avg_turnover']:>8.2%}")


def main():
    t0 = time.time()
    conn = psycopg2.connect(DB_URI)

    start = "2021-01-01"
    end = "2025-12-31"

    print("=" * 70)
    print("  vwap_bias_1d Weekly FastRanking Backtest")
    print("=" * 70)

    # 加载所有需要的因子数据
    all_factors = BASELINE_FACTORS + [VWAP_FACTOR]
    factor_df, price_data, benchmark = load_data(conn, all_factors, start, end)
    conn.close()

    # ── 回测A: 基线 5因子月度 Top-20 ──
    print("\n[A] Baseline: 5-factor monthly Top-20")
    config_a = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        pms=PMSConfig(enabled=False),
    )
    fdf_baseline = factor_df[factor_df["factor_name"].isin(BASELINE_FACTORS)].copy()
    result_a = run_hybrid_backtest(
        fdf_baseline, BASELINE_DIRECTIONS, price_data, config_a, benchmark,
    )
    print_result("A) 5-factor Monthly Top-20 (Baseline)", result_a)

    # ── 回测B: vwap_bias_1d 周度 Top-15 ──
    print("\n[B] Satellite: vwap_bias_1d weekly Top-15")
    config_b = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=15,
        rebalance_freq="weekly",
        slippage_mode="volume_impact",
        pms=PMSConfig(enabled=False),
    )
    fdf_vwap = factor_df[factor_df["factor_name"] == VWAP_FACTOR].copy()
    result_b = run_hybrid_backtest(
        fdf_vwap, VWAP_DIRECTION, price_data, config_b, benchmark,
    )
    print_result("B) vwap_bias_1d Weekly Top-15", result_b)

    # ── 回测C: vwap_bias_1d 月度 Top-15 (对照) ──
    print("\n[C] Control: vwap_bias_1d monthly Top-15")
    config_c = BacktestConfig(
        initial_capital=1_000_000.0,
        top_n=15,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        pms=PMSConfig(enabled=False),
    )
    result_c = run_hybrid_backtest(
        fdf_vwap, VWAP_DIRECTION, price_data, config_c, benchmark,
    )
    print_result("C) vwap_bias_1d Monthly Top-15 (Control)", result_c)

    # ── 汇总对比 ──
    print(f"\n{'=' * 70}")
    print("  COMPARISON SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n  {'Strategy':<35} {'Sharpe':>7} {'AnnRet':>8} {'MDD':>8} {'Calmar':>7}")
    print("  " + "-" * 65)
    metrics_map = {}
    for name, r in [
        ("A) 5fac Monthly Top-20 (baseline)", result_a),
        ("B) vwap Weekly Top-15", result_b),
        ("C) vwap Monthly Top-15 (control)", result_c),
    ]:
        m = calc_metrics(r)
        metrics_map[name] = m
        print(
            f"  {name:<35} {m['sharpe_ratio']:>7.2f} "
            f"{m['annual_return']:>+8.2%} "
            f"{m['max_drawdown']:>8.2%} "
            f"{m['calmar_ratio']:>7.2f}"
        )

    # B vs C: 频率影响
    sharpe_b = calc_metrics(result_b)["sharpe_ratio"]
    sharpe_c = calc_metrics(result_c)["sharpe_ratio"]
    print(f"\n  Weekly vs Monthly Sharpe diff: {sharpe_b - sharpe_c:+.2f}")
    if sharpe_b > sharpe_c:
        print("  >>> Weekly rebalance captures vwap_bias_1d signal better (as expected from IC decay)")
    else:
        print("  >>> Monthly performs better — weekly turnover cost exceeds signal gain")

    elapsed = time.time() - t0
    print(f"\n  Total elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
