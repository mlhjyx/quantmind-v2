#!/usr/bin/env python3
"""Compare backtest: volatility_20 vs ivol_20 (5-factor portfolio).

Runs two backtests (2024-2025) with Top15 monthly IndCap=25%:
  A) Original: turnover_mean_20 + volatility_20 + reversal_20 + amihud_20 + bp_ratio
  B) New:      turnover_mean_20 + ivol_20      + reversal_20 + amihud_20 + bp_ratio

IVOL is computed on-the-fly (not in factor_values table).
"""

import sys
import time
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn
from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import generate_report, print_report, calc_sharpe, calc_max_drawdown
from engines.signal_engine import (
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    FACTOR_DIRECTION,
    get_rebalance_dates,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

# ── IVOL Computation (from compute_ivol_ic.py logic) ──

def compute_ivol_wide(conn, start_date="2023-07-01", end_date="2025-12-31"):
    """Compute IVOL factor as wide DataFrame (trade_date x code)."""
    t0 = time.time()
    print("  Loading stock returns for IVOL...")
    stock_df = pd.read_sql(f"""
        SELECT code, trade_date, pct_change::float/100 as ret
        FROM klines_daily
        WHERE trade_date >= '{start_date}' AND volume > 0
        ORDER BY trade_date, code
    """, conn)

    bench_df = pd.read_sql(f"""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '{start_date}'
        ORDER BY trade_date
    """, conn)
    bench_df['mkt_ret'] = bench_df['close'].pct_change()
    bench_df = bench_df[['trade_date', 'mkt_ret']].dropna()

    ret_wide = stock_df.pivot(index='trade_date', columns='code', values='ret')
    ret_wide = ret_wide.reindex(bench_df['trade_date'].values)
    mkt = bench_df.set_index('trade_date')['mkt_ret']

    n_dates, n_codes = ret_wide.shape
    window = 60
    min_obs = 30

    R = ret_wide.values
    M = mkt.values.reshape(-1, 1)
    ivol_matrix = np.full_like(R, np.nan)

    for i in range(window - 1, n_dates):
        start = i - window + 1
        r_win = R[start:i+1, :]
        m_win = M[start:i+1, 0]

        valid = ~np.isnan(r_win) & ~np.isnan(m_win.reshape(-1, 1))
        n_valid = valid.sum(axis=0)

        r_clean = np.where(valid, r_win, 0.0)
        m_clean = np.where(valid, m_win.reshape(-1, 1), 0.0)

        r_mean = r_clean.sum(axis=0) / np.maximum(n_valid, 1)
        m_mean = m_clean.sum(axis=0) / np.maximum(n_valid, 1)

        r_dm = np.where(valid, r_clean - r_mean[np.newaxis, :], 0.0)
        m_dm = np.where(valid, m_clean - m_mean[np.newaxis, :], 0.0)

        cov_rm = (r_dm * m_dm).sum(axis=0) / np.maximum(n_valid - 1, 1)
        var_m = (m_dm * m_dm).sum(axis=0) / np.maximum(n_valid - 1, 1)

        beta = np.where(var_m > 1e-12, cov_rm / var_m, 0.0)
        resid = np.where(valid, r_clean - beta[np.newaxis, :] * m_clean, np.nan)
        resid_std = np.nanstd(resid, axis=0, ddof=1)
        resid_std[n_valid < min_obs] = np.nan
        ivol_matrix[i, :] = resid_std

    ivol_df = pd.DataFrame(ivol_matrix, index=ret_wide.index, columns=ret_wide.columns)
    print(f"  IVOL computed in {time.time()-t0:.1f}s, shape={ivol_df.shape}")
    return ivol_df


def load_factor_values_with_ivol(trade_date, conn, ivol_wide, use_ivol=False):
    """Load factor values for a single date, optionally replacing vol_20 with ivol_20."""
    if use_ivol:
        # Load all factors EXCEPT volatility_20
        fv = pd.read_sql(
            """SELECT code, factor_name, neutral_value
               FROM factor_values
               WHERE trade_date = %s AND factor_name != 'volatility_20'""",
            conn, params=(trade_date,),
        )
        # Add IVOL as ivol_20
        td_str = str(trade_date)
        if td_str in ivol_wide.index.astype(str).values:
            idx = ivol_wide.index.astype(str) == td_str
            ivol_cross = ivol_wide.loc[idx].iloc[0].dropna()
            if len(ivol_cross) > 0:
                # Apply cross-sectional zscore (mimic neutral_value preprocessing)
                vals = ivol_cross.values
                mean_v = np.nanmean(vals)
                std_v = np.nanstd(vals)
                if std_v > 1e-12:
                    zscored = (vals - mean_v) / std_v
                else:
                    zscored = np.zeros_like(vals)
                ivol_rows = pd.DataFrame({
                    'code': ivol_cross.index,
                    'factor_name': 'ivol_20',
                    'neutral_value': zscored,
                })
                fv = pd.concat([fv, ivol_rows], ignore_index=True)
    else:
        fv = pd.read_sql(
            """SELECT code, factor_name, neutral_value
               FROM factor_values WHERE trade_date = %s""",
            conn, params=(trade_date,),
        )
    return fv


def load_universe(trade_date, conn):
    """Load universe."""
    df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000
        """,
        conn, params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def load_industry(conn):
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start_date, end_date, conn):
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s
             AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn, params=(start_date, end_date),
    )


def load_benchmark(start_date, end_date, conn):
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn, params=(start_date, end_date),
    )


def run_single_backtest(label, factor_names, conn, rebalance_dates, industry,
                        price_data, benchmark_data, ivol_wide=None, use_ivol=False):
    """Run a single backtest variant."""
    print(f"\n{'='*60}")
    print(f"  BACKTEST: {label}")
    print(f"  Factors: {factor_names}")
    print(f"{'='*60}")

    sig_config = SignalConfig(
        factor_names=factor_names,
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    bt_config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=15,
        rebalance_freq="monthly",
        slippage_bps=10.0,
    )

    # Add ivol_20 direction to FACTOR_DIRECTION if needed
    if use_ivol:
        FACTOR_DIRECTION['ivol_20'] = -1  # low IVOL outperforms

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values_with_ivol(rd, conn, ivol_wide, use_ivol=use_ivol)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    print(f"  Signal dates: {len(target_portfolios)}")

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    report = generate_report(result, price_data)
    return report, result


def main():
    t0 = time.time()
    conn = _get_sync_conn()

    start = date(2024, 1, 1)
    end = date(2025, 12, 31)

    # ── Precompute IVOL ──
    print("="*60)
    print("Step 1: Computing IVOL factor...")
    conn_ivol = psycopg2.connect(DB_URI)
    ivol_wide = compute_ivol_wide(conn_ivol, start_date="2023-07-01", end_date="2025-12-31")
    conn_ivol.close()

    # ── Shared data ──
    print("\nStep 2: Loading shared data...")
    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    industry = load_industry(conn)
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    print(f"  Rebalance dates: {len(rebalance_dates)}")
    print(f"  Price rows: {len(price_data)}, Benchmark rows: {len(benchmark_data)}")

    # ── Backtest A: Original 5 factors (with volatility_20) ──
    factors_a = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    report_a, result_a = run_single_backtest(
        "ORIGINAL (vol_20)", factors_a, conn, rebalance_dates, industry,
        price_data, benchmark_data, use_ivol=False
    )

    # ── Backtest B: New 5 factors (with ivol_20) ──
    factors_b = ["turnover_mean_20", "ivol_20", "reversal_20", "amihud_20", "bp_ratio"]
    report_b, result_b = run_single_backtest(
        "NEW (ivol_20)", factors_b, conn, rebalance_dates, industry,
        price_data, benchmark_data, ivol_wide=ivol_wide, use_ivol=True
    )

    # ── Comparison Summary ──
    print("\n" + "="*70)
    print("COMPARISON SUMMARY: volatility_20 vs ivol_20")
    print("="*70)
    print(f"  Period: {start} ~ {end}")
    print(f"  Config: Top15, Monthly, IndCap=25%, Equal-weight")
    print()
    fmt = "  {:<25} {:>12} {:>12} {:>12}"
    print(fmt.format("Metric", "Original(vol)", "New(ivol)", "Delta"))
    print(fmt.format("-"*25, "-"*12, "-"*12, "-"*12))

    metrics = [
        ("Annual Return (%)", report_a.annual_return, report_b.annual_return),
        ("Total Return (%)", report_a.total_return, report_b.total_return),
        ("Sharpe Ratio", report_a.sharpe_ratio, report_b.sharpe_ratio),
        ("Max Drawdown (%)", report_a.max_drawdown, report_b.max_drawdown),
        ("Calmar Ratio", report_a.calmar_ratio, report_b.calmar_ratio),
        ("Sortino Ratio", report_a.sortino_ratio, report_b.sortino_ratio),
        ("IR", report_a.information_ratio, report_b.information_ratio),
        ("Beta", report_a.beta, report_b.beta),
        ("Win Rate (%)", report_a.win_rate, report_b.win_rate),
        ("Annual Turnover", report_a.annual_turnover, report_b.annual_turnover),
    ]
    for name, va, vb in metrics:
        delta = vb - va
        sign = "+" if delta > 0 else ""
        print(fmt.format(name, f"{va:.2f}", f"{vb:.2f}", f"{sign}{delta:.2f}"))

    # Bootstrap CI comparison
    pa, la, ua = report_a.bootstrap_sharpe_ci
    pb, lb, ub = report_b.bootstrap_sharpe_ci
    print(f"\n  Bootstrap Sharpe CI:")
    print(f"    Original: {pa:.2f} [{la:.2f}, {ua:.2f}]")
    print(f"    New:      {pb:.2f} [{lb:.2f}, {ub:.2f}]")

    # Annual breakdown
    print(f"\n  Annual Breakdown:")
    print(f"    {'Year':<6} {'Orig Ret%':>10} {'New Ret%':>10} {'Orig Sharpe':>12} {'New Sharpe':>12}")
    for year in report_a.annual_breakdown.index:
        ar = report_a.annual_breakdown.loc[year, 'return'] if year in report_a.annual_breakdown.index else 0
        br = report_b.annual_breakdown.loc[year, 'return'] if year in report_b.annual_breakdown.index else 0
        a_sh = report_a.annual_breakdown.loc[year, 'sharpe'] if year in report_a.annual_breakdown.index else 0
        b_sh = report_b.annual_breakdown.loc[year, 'sharpe'] if year in report_b.annual_breakdown.index else 0
        print(f"    {year:<6} {ar:>10.2f} {br:>10.2f} {a_sh:>12.2f} {b_sh:>12.2f}")

    # ── Q2: Compare vol_20 annual IC ──
    print("\n" + "="*70)
    print("Q2: volatility_20 Annual IC (from factor_values)")
    print("="*70)
    conn2 = psycopg2.connect(DB_URI)

    # Load vol_20 factor values and compute IC against 5-day excess fwd return
    print("  Loading volatility_20 factor values and forward returns...")
    vol_fv = pd.read_sql("""
        SELECT code, trade_date, zscore::float as value
        FROM factor_values
        WHERE factor_name = 'volatility_20'
          AND trade_date >= '2021-01-01'
        ORDER BY trade_date
    """, conn2)

    # Forward returns
    close_df = pd.read_sql("""
        SELECT code, trade_date, close::float * adj_factor::float as adj_close
        FROM klines_daily
        WHERE trade_date >= '2021-01-01' AND volume > 0
        ORDER BY trade_date, code
    """, conn2)
    close_wide = close_df.pivot(index='trade_date', columns='code', values='adj_close')

    bench_close = pd.read_sql("""
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= '2021-01-01'
        ORDER BY trade_date
    """, conn2)
    bench_s = bench_close.set_index('trade_date')['close'].reindex(close_wide.index)

    fwd_ret = close_wide.shift(-5) / close_wide - 1
    bench_fwd = bench_s.shift(-5) / bench_s - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    # vol_20 pivot
    vol_wide = vol_fv.pivot(index='trade_date', columns='code', values='value')

    # Monthly IC for vol_20
    dates = pd.Series(vol_wide.index)
    dates_dt = pd.to_datetime(dates)
    month_ends = dates.groupby(dates_dt.dt.to_period('M')).last().values

    vol_wide.index = vol_wide.index.astype(str)
    excess_fwd.index = excess_fwd.index.astype(str)

    vol_ic_records = []
    for d in month_ends:
        d_str = str(d)
        if d_str not in vol_wide.index or d_str not in excess_fwd.index:
            continue
        v_cross = vol_wide.loc[d_str].dropna()
        f_cross = excess_fwd.loc[d_str].dropna()
        common = v_cross.index.intersection(f_cross.index)
        if len(common) < 100:
            continue
        # Direction: -1 for volatility (low vol = good)
        ic, _ = stats.spearmanr(-v_cross[common].values, f_cross[common].values)
        vol_ic_records.append({'date': pd.Timestamp(d_str), 'ic': ic})

    vol_ic_df = pd.DataFrame(vol_ic_records)
    vol_ic_df['year'] = vol_ic_df['date'].dt.year

    print(f"\n  {'Year':<6} {'vol_20 IC%':>12} {'ivol_20 IC%':>12} {'Delta':>10}")
    print(f"  {'-'*42}")

    # IVOL IC by year (from user-provided data)
    ivol_annual = {2021: 10.04, 2022: 0.00, 2023: 7.19, 2024: 14.54, 2025: 1.58}

    for year, grp in vol_ic_df.groupby('year'):
        vol_ic_mean = grp['ic'].mean() * 100
        ivol_ic = ivol_annual.get(year, float('nan'))
        delta = ivol_ic - vol_ic_mean if not np.isnan(ivol_ic) else float('nan')
        print(f"  {year:<6} {vol_ic_mean:>11.2f}% {ivol_ic:>11.2f}% {delta:>+9.2f}%")

    # Overall
    vol_overall = vol_ic_df['ic'].mean() * 100
    print(f"  {'All':<6} {vol_overall:>11.2f}%   {'6.67':>9}%")

    conn2.close()
    conn.close()

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
