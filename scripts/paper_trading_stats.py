#!/usr/bin/env python3
"""Paper Trading 每日统计追踪。

每日快速浏览：累计天数、收益、滚动Sharpe/MDD、因子IC、毕业标准差距、DSR趋势。

用法:
    python scripts/paper_trading_stats.py              # 全量报告
    python scripts/paper_trading_stats.py --brief      # 简洁摘要
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import warnings

warnings.filterwarnings("ignore", category=UserWarning, message=".*pandas only supports.*")

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from app.config import settings
from app.services.price_utils import _get_sync_conn

# ── 毕业标准 & 基线参数 ──
BASELINE_SHARPE = 1.037       # v1.1回测Sharpe (2021-2025)
BASELINE_MDD = 0.397          # v1.1回测MDD (39.7%)
GRAD_MIN_DAYS = 60
GRAD_SHARPE = BASELINE_SHARPE * 0.70   # ≥ 0.726
GRAD_MDD = BASELINE_MDD * 1.50         # ≤ 59.6% (但CLAUDE.md写35%)
GRAD_MDD_HARD = 0.35                   # CLAUDE.md硬标准

V11_FACTORS = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio",
]
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": +1,
    "amihud_20": +1,
    "bp_ratio": +1,
}

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"


def load_performance(conn, sid: str) -> pd.DataFrame:
    """加载全部Paper Trading performance_series。"""
    df = pd.read_sql(
        """SELECT trade_date, nav::float, daily_return::float,
                  cumulative_return::float, drawdown::float,
                  position_count, cash_ratio::float, turnover::float,
                  benchmark_nav::float, excess_return::float
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date""",
        conn,
        params=(sid,),
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def calc_rolling_sharpe(returns: np.ndarray, window: int = 20) -> float:
    """滚动Sharpe（年化）。用最近window个交易日。"""
    r = returns if len(returns) < window else returns[-window:]
    if len(r) < 2:
        return np.nan
    mu = np.mean(r)
    sigma = np.std(r, ddof=1)
    if sigma < 1e-10:
        return np.nan
    return float(mu / sigma * np.sqrt(252))


def calc_full_sharpe(returns: np.ndarray) -> float:
    """全样本Sharpe（年化）。"""
    if len(returns) < 2:
        return np.nan
    mu = np.mean(returns)
    sigma = np.std(returns, ddof=1)
    if sigma < 1e-10:
        return np.nan
    return float(mu / sigma * np.sqrt(252))


def calc_mdd(returns: np.ndarray) -> float:
    """最大回撤（从cumulative returns序列算，起始NAV=1）。"""
    cum = np.concatenate([[1.0], np.cumprod(1 + returns)])
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(np.min(dd))


def calc_dsr(sharpe: float, n_days: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014)。

    DSR = Phi( (SR_hat - SR_0) * sqrt(n-1) / sqrt(1 - skew*SR + (kurt-1)/4 * SR^2) )
    SR_0 = 0 (null hypothesis: strategy doesn't beat zero)

    返回p-value（DSR概率），越高越显著。
    """
    if n_days < 3 or np.isnan(sharpe):
        return np.nan
    sr = sharpe / np.sqrt(252)  # 转日频SR
    denom_sq = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom_sq <= 0:
        return np.nan
    test_stat = sr * np.sqrt(n_days - 1) / np.sqrt(denom_sq)
    return float(sp_stats.norm.cdf(test_stat))


def load_factor_ic(conn) -> pd.DataFrame:
    """从factor_ic_history加载v1.1因子的最新IC数据。"""
    placeholders = ",".join(f"'{f}'" for f in V11_FACTORS)
    df = pd.read_sql(
        f"""SELECT factor_name, trade_date, ic_1d::float, ic_5d::float,
                   ic_20d::float, ic_ma20::float, decay_level
            FROM factor_ic_history
            WHERE factor_name IN ({placeholders})
            ORDER BY factor_name, trade_date""",
        conn,
    )
    return df


def load_realtime_factor_ic(conn, n_recent_days: int = 20) -> pd.DataFrame:
    """如果factor_ic_history为空，直接从factor_values + klines计算最近IC。"""
    placeholders = ",".join(f"'{f}'" for f in V11_FACTORS)

    # 取最近的交易日期
    dates_df = pd.read_sql(
        f"""SELECT DISTINCT trade_date FROM factor_values
            WHERE factor_name IN ({placeholders})
            ORDER BY trade_date DESC LIMIT {n_recent_days + 5}""",
        conn,
    )
    if len(dates_df) < 5:
        return pd.DataFrame()

    min_date = dates_df["trade_date"].min()

    # 因子值
    fv = pd.read_sql(
        f"""SELECT code, trade_date, factor_name, zscore::float as value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
              AND trade_date >= %s
            ORDER BY trade_date, code""",
        conn,
        params=(min_date,),
    )

    # 行情（计算5日forward return）
    kl = pd.read_sql(
        """SELECT code, trade_date, close::float * adj_factor::float as adj_close
           FROM klines_daily
           WHERE trade_date >= %s AND volume > 0
           ORDER BY trade_date, code""",
        conn,
        params=(min_date,),
    )

    # 基准
    bench = pd.read_sql(
        """SELECT trade_date, close::float
           FROM index_daily WHERE index_code='000300.SH' AND trade_date >= %s
           ORDER BY trade_date""",
        conn,
        params=(min_date,),
    )

    if kl.empty or bench.empty:
        return pd.DataFrame()

    adj_wide = kl.pivot(index="trade_date", columns="code", values="adj_close")
    bench_s = bench.set_index("trade_date")["close"]

    fwd_ret = adj_wide.shift(-5) / adj_wide - 1
    bench_fwd = bench_s.shift(-5) / bench_s - 1
    excess_fwd = fwd_ret.sub(bench_fwd, axis=0)

    records = []
    for fname in V11_FACTORS:
        sub = fv[fv["factor_name"] == fname]
        if sub.empty:
            continue
        fw = sub.pivot(index="trade_date", columns="code", values="value")
        direction = FACTOR_DIRECTIONS.get(fname, 1)

        for td in fw.index:
            if td not in excess_fwd.index:
                continue
            fac_cross = (direction * fw.loc[td]).dropna()
            fwd_cross = excess_fwd.loc[td].dropna()
            common = fac_cross.index.intersection(fwd_cross.index)
            if len(common) < 100:
                continue
            ic, _ = sp_stats.spearmanr(fac_cross[common].values, fwd_cross[common].values)
            records.append({"factor_name": fname, "trade_date": td, "ic_5d": ic})

    if not records:
        return pd.DataFrame()

    ic_df = pd.DataFrame(records)
    # 计算滚动20日IC均值
    result = []
    for fname, grp in ic_df.groupby("factor_name"):
        grp = grp.sort_values("trade_date")
        ic_mean = grp["ic_5d"].mean()
        ic_std = grp["ic_5d"].std()
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        n = len(grp)
        result.append({
            "factor_name": fname,
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "ic_ir": ic_ir,
            "n_days": n,
            "pct_positive": (grp["ic_5d"] > 0).mean() * 100,
        })
    return pd.DataFrame(result)


def print_header(n_days: int, latest_date, nav: float, cum_ret: float):
    print("=" * 70)
    print("  QuantMind v1.1 Paper Trading — Daily Stats Tracker")
    print("=" * 70)
    print(f"  Date:       {latest_date}")
    print(f"  Day:        {n_days} / {GRAD_MIN_DAYS} ({n_days/GRAD_MIN_DAYS*100:.0f}%)")
    print(f"  NAV:        {nav:,.0f}")
    print(f"  Cum Return: {cum_ret:+.2%}")
    print()


def print_performance_section(df: pd.DataFrame):
    rets = df["daily_return"].values
    n = len(rets)

    full_sharpe = calc_full_sharpe(rets)
    rolling_sharpe_20 = calc_rolling_sharpe(rets, 20)
    # Use DB drawdown column if available (more authoritative), fallback to calc
    mdd_from_db = df["drawdown"].min() if "drawdown" in df.columns else None
    mdd_from_calc = calc_mdd(rets)
    mdd = mdd_from_db if mdd_from_db is not None and not np.isnan(mdd_from_db) else mdd_from_calc
    skew = float(sp_stats.skew(rets)) if n >= 3 else 0.0
    kurt = float(sp_stats.kurtosis(rets, fisher=False)) if n >= 3 else 3.0
    dsr = calc_dsr(full_sharpe, n, skew, kurt)

    # Calmar, Sortino
    ann_ret = float(np.mean(rets) * 252)
    downside = rets[rets < 0]
    sortino = float(np.mean(rets) / np.std(downside, ddof=1) * np.sqrt(252)) if len(downside) > 1 and np.std(downside, ddof=1) > 0 else np.nan
    calmar = float(ann_ret / abs(mdd)) if abs(mdd) > 0.001 else np.nan

    # Win rate
    win_rate = float(np.mean(rets > 0) * 100)
    avg_win = float(np.mean(rets[rets > 0])) if np.any(rets > 0) else 0
    avg_loss = float(np.mean(rets[rets < 0])) if np.any(rets < 0) else 0
    pnl_ratio = abs(avg_win / avg_loss) if abs(avg_loss) > 1e-10 else np.nan

    # Max consecutive loss days
    losing_streak = 0
    max_streak = 0
    for r in rets:
        if r < 0:
            losing_streak += 1
            max_streak = max(max_streak, losing_streak)
        else:
            losing_streak = 0

    print("  --- Performance ---")
    print(f"  {'Full-sample Sharpe:':28s} {full_sharpe:+.3f}   (target: >= {GRAD_SHARPE:.3f})")
    sharpe_gap = full_sharpe - GRAD_SHARPE if not np.isnan(full_sharpe) else np.nan
    status = "PASS" if not np.isnan(sharpe_gap) and sharpe_gap >= 0 else "BELOW"
    print(f"  {'  Gap to graduation:':28s} {sharpe_gap:+.3f}   [{status}]")
    print(f"  {'Rolling 20d Sharpe:':28s} {rolling_sharpe_20:+.3f}" if not np.isnan(rolling_sharpe_20) else f"  {'Rolling 20d Sharpe:':28s} N/A (need 20d)")
    print(f"  {'Max Drawdown:':28s} {mdd:+.2%}   (hard limit: <{GRAD_MDD_HARD:.0%})")
    mdd_status = "PASS" if abs(mdd) < GRAD_MDD_HARD else "BREACH"
    print(f"  {'  Status:':28s} [{mdd_status}]")
    print(f"  {'Annualized Return:':28s} {ann_ret:+.2%}")
    print(f"  {'Sortino Ratio:':28s} {sortino:+.3f}" if not np.isnan(sortino) else f"  {'Sortino Ratio:':28s} N/A")
    print(f"  {'Calmar Ratio:':28s} {calmar:.3f}" if not np.isnan(calmar) else f"  {'Calmar Ratio:':28s} N/A")
    print(f"  {'Win Rate:':28s} {win_rate:.1f}%   PnL Ratio: {pnl_ratio:.2f}" if not np.isnan(pnl_ratio) else f"  {'Win Rate:':28s} {win_rate:.1f}%")
    print(f"  {'Max Losing Streak:':28s} {max_streak}d")
    print()

    # DSR section
    print("  --- Deflated Sharpe Ratio ---")
    print(f"  {'DSR (p-value):':28s} {dsr:.4f}" if not np.isnan(dsr) else f"  {'DSR:':28s} N/A")
    print(f"  {'  Skewness:':28s} {skew:+.3f}")
    print(f"  {'  Kurtosis:':28s} {kurt:.3f}")

    # DSR trend at different sample sizes
    if n >= 5:
        print(f"  {'  DSR trajectory:':28s}", end="")
        checkpoints = [5, 10, 20, 30, 40, 50, 60]
        for cp in checkpoints:
            if cp > n:
                break
            cp_rets = rets[:cp]
            cp_sharpe = calc_full_sharpe(cp_rets)
            cp_skew = float(sp_stats.skew(cp_rets)) if cp >= 3 else 0
            cp_kurt = float(sp_stats.kurtosis(cp_rets, fisher=False)) if cp >= 3 else 3
            cp_dsr = calc_dsr(cp_sharpe, cp, cp_skew, cp_kurt)
            if not np.isnan(cp_dsr):
                print(f" d{cp}={cp_dsr:.3f}", end="")
        print()
    print()


def print_factor_ic_section(conn):
    """打印因子IC追踪。"""
    print("  --- Factor IC (5d excess, Spearman) ---")

    # 先尝试factor_ic_history
    ic_hist = load_factor_ic(conn)
    if not ic_hist.empty:
        print("  Source: factor_ic_history table")
        for fname in V11_FACTORS:
            sub = ic_hist[ic_hist["factor_name"] == fname].sort_values("trade_date")
            if sub.empty:
                print(f"  {fname:25s}  NO DATA")
                continue
            latest = sub.iloc[-1]
            latest.get("ic_5d", np.nan)
            ic_ma20 = latest.get("ic_ma20", np.nan)
            decay = latest.get("decay_level", "?")
            n = len(sub)
            ic_mean = sub["ic_5d"].mean() if "ic_5d" in sub.columns else np.nan
            pct_pos = (sub["ic_5d"] > 0).mean() * 100 if "ic_5d" in sub.columns else np.nan
            print(f"  {fname:25s}  IC_mean={ic_mean:+.4f}  MA20={ic_ma20:+.4f}  IC>0={pct_pos:.0f}%  [{decay}]  (N={n})")
    else:
        # 计算实时IC
        ic_rt = load_realtime_factor_ic(conn, n_recent_days=20)
        if ic_rt.empty:
            print("  No factor IC data available (neither ic_history nor factor_values)")
            return
        print("  Source: computed from factor_values + klines (recent)")
        for _, row in ic_rt.iterrows():
            fname = row["factor_name"]
            print(
                f"  {fname:25s}  IC_mean={row['ic_mean']:+.4f}  "
                f"IC_IR={row['ic_ir']:.3f}  IC>0={row['pct_positive']:.0f}%  "
                f"(N={int(row['n_days'])}d)"
            )
    print()


def print_graduation_checklist(df: pd.DataFrame):
    """毕业标准检查清单。"""
    rets = df["daily_return"].values
    n = len(rets)
    full_sharpe = calc_full_sharpe(rets)
    mdd_from_db = df["drawdown"].min() if "drawdown" in df.columns else None
    mdd = mdd_from_db if mdd_from_db is not None and not np.isnan(mdd_from_db) else calc_mdd(rets)

    print("  --- Graduation Checklist ---")
    checks = [
        ("Duration >= 60 days", n >= GRAD_MIN_DAYS, f"{n}/{GRAD_MIN_DAYS}"),
        (f"Sharpe >= {GRAD_SHARPE:.3f}", not np.isnan(full_sharpe) and full_sharpe >= GRAD_SHARPE, f"{full_sharpe:.3f}" if not np.isnan(full_sharpe) else "N/A"),
        (f"MDD < {GRAD_MDD_HARD:.0%}", abs(mdd) < GRAD_MDD_HARD, f"{mdd:+.2%}"),
        ("Slippage deviation < 50%", None, "TBD (need live comparison)"),
        ("Full pipeline intact", None, "TBD (check scheduler_task_log)"),
    ]

    for desc, passed, value in checks:
        if passed is None:
            icon = "[ ]"
        elif passed:
            icon = "[x]"
        else:
            icon = "[ ]"
        print(f"  {icon} {desc:35s}  ({value})")

    all_met = all(p for _, p, _ in checks if p is not None)
    days_remaining = max(0, GRAD_MIN_DAYS - n)
    print()
    if all_met and days_remaining == 0:
        print("  >>> ALL QUANTITATIVE CRITERIA MET — ready for live review <<<")
    else:
        print(f"  Days remaining: {days_remaining}")
        if not np.isnan(full_sharpe) and full_sharpe < GRAD_SHARPE:
            needed_daily = (GRAD_SHARPE / np.sqrt(252)) * np.std(rets, ddof=1) if np.std(rets, ddof=1) > 0 else 0
            print(f"  To reach Sharpe {GRAD_SHARPE:.3f}: need avg daily return >= {needed_daily:.4%}")
    print()


def print_daily_table(df: pd.DataFrame, n_rows: int = 10):
    """最近N天表格。"""
    recent = df.tail(n_rows)
    print(f"  --- Last {len(recent)} Trading Days ---")
    print(f"  {'Date':>12} {'NAV':>10} {'Daily':>8} {'Cum':>8} {'DD':>8} {'Pos':>4} {'Cash':>6}")
    print("  " + "-" * 62)
    for _, r in recent.iterrows():
        print(
            f"  {str(r['trade_date']):>12} "
            f"{r['nav']:>10,.0f} "
            f"{r['daily_return']:>+7.2%} "
            f"{r['cumulative_return']:>+7.2%} "
            f"{r['drawdown']:>+7.2%} "
            f"{int(r['position_count']):>4} "
            f"{r['cash_ratio']:>5.1%}"
        )
    print()


def main():
    parser = argparse.ArgumentParser(description="Paper Trading Daily Stats")
    parser.add_argument("--brief", action="store_true", help="Only show summary")
    parser.add_argument("--days", type=int, default=10, help="Number of recent days to show")
    args = parser.parse_args()

    sid = settings.PAPER_STRATEGY_ID
    if not sid:
        print("PAPER_STRATEGY_ID not configured in .env")
        sys.exit(1)

    conn = _get_sync_conn()
    try:
        df = load_performance(conn, sid)
        if df.empty:
            print("No Paper Trading data in performance_series.")
            sys.exit(0)

        n_days = len(df)
        latest = df.iloc[-1]

        print_header(n_days, latest["trade_date"], latest["nav"], latest["cumulative_return"])
        print_performance_section(df)

        if not args.brief:
            print_factor_ic_section(conn)

        print_graduation_checklist(df)

        if not args.brief:
            print_daily_table(df, args.days)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
