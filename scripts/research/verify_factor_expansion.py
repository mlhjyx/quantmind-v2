#!/usr/bin/env python3
"""因子扩展验证 — 生产级回测引擎重跑。

复用 backtest_7factor_comparison.py 的数据加载+回测框架，
只替换因子列表参数。4组串行运行。

用法:
    python scripts/research/verify_factor_expansion.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(project_root / "backend"))

import numpy as np
import pandas as pd
from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import (
    calc_max_drawdown,
    calc_sharpe,
)
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)

from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# 抑制backtest_engine/structlog的debug日志
logging.getLogger("backtest_engine").setLevel(logging.WARNING)
logging.getLogger("engines").setLevel(logging.WARNING)
try:
    import structlog
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
except Exception:
    pass

# ── 配置 ─────────────────────────────────────────────
START_DATE = date(2021, 1, 1)
END_DATE = date(2025, 12, 31)
INITIAL_CAPITAL = 1_000_000.0

# 因子组定义
CORE_5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

FACTORS_10 = CORE_5 + [
    "money_flow_strength", "a158_vsump5", "a158_vma5", "kbar_kmid", "a158_rank5",
]

FACTORS_15 = FACTORS_10 + [
    "kbar_ksft", "vwap_bias_1d", "a158_corr5", "turnover_surge_ratio", "chmom_60_20",
]

FACTORS_20 = FACTORS_15 + [
    "ep_ratio", "reversal_5", "kbar_kup", "dv_ttm", "relative_volume_20",
]

GROUPS = [
    ("A(CORE 5)", CORE_5),
    ("C(10因子)", FACTORS_10),
    ("D(15因子)", FACTORS_15),
    ("E(20因子)", FACTORS_20),
]

# 新因子方向（不在FACTOR_DIRECTION里的）
EXTRA_DIRECTIONS = {
    "money_flow_strength": 1,
    "a158_vsump5": -1,
    "a158_vma5": 1,
    "kbar_kmid": -1,
    "a158_rank5": -1,
    "kbar_ksft": -1,
    "a158_corr5": -1,
    "chmom_60_20": -1,
    "kbar_kup": -1,
}


# ── 数据加载（复用7factor脚本的完整SQL） ──────────────
def load_factor_values_for_date(trade_date: date, factor_names: list[str], conn) -> pd.DataFrame:
    """加载单日因子neutral_value — 动态因子列表。"""
    placeholders = ",".join(["%s"] * len(factor_names))
    return pd.read_sql(
        f"""SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s
             AND factor_name IN ({placeholders})""",
        conn,
        params=[trade_date] + factor_names,
    )


def load_universe(trade_date: date, conn) -> set[str]:
    """Universe过滤（与7factor脚本完全一致）。"""
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
        conn,
        params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def load_price_data(conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db
             ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s
             AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(START_DATE, END_DATE),
    )


def load_benchmark(conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(START_DATE, END_DATE),
    )


def load_industry(conn) -> pd.Series:
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


# ── 回测函数 ─────────────────────────────────────────
def run_backtest_for_factors(
    factor_names: list[str],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    industry: pd.Series,
    rebalance_dates: list[date],
    conn,
    label: str = "",
) -> dict:
    """用生产引擎运行单组回测。"""
    sig_config = SignalConfig(
        factor_names=factor_names,
        top_n=PAPER_TRADING_CONFIG.top_n,          # 20 (from .env)
        rebalance_freq="monthly",
        industry_cap=PAPER_TRADING_CONFIG.industry_cap,  # 1.0 (from .env)
        weight_method="equal",
    )
    bt_config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        top_n=sig_config.top_n,
        rebalance_freq=sig_config.rebalance_freq,
        # volume_impact滑点 (默认)
    )

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)
    target_portfolios = {}
    prev_weights = {}

    logger.info(f"[{label}] 生成信号 ({len(rebalance_dates)} 调仓日)...")
    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values_for_date(rd, factor_names, conn)
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

        if (i + 1) % 12 == 0:
            logger.info(f"[{label}]   [{i+1}/{len(rebalance_dates)}] {rd}: {len(target)}只")

    logger.info(f"[{label}] 信号完成: {len(target_portfolios)} 个调仓日")

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    # 提取指标
    daily_ret = result.daily_returns
    nav = result.daily_nav
    sharpe = calc_sharpe(daily_ret)
    mdd = calc_max_drawdown(nav)
    n_years = len(daily_ret) / 252
    final_nav = float(nav.iloc[-1])
    cagr = (final_nav / INITIAL_CAPITAL) ** (1 / n_years) - 1 if n_years > 0 else 0
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # 年度分解（手动计算，避免依赖benchmark_nav参数）
    yearly = {}
    for year in range(START_DATE.year, END_DATE.year + 1):
        mask = [d.year == year for d in daily_ret.index]
        yr_ret = daily_ret[mask]
        if len(yr_ret) < 20:
            continue
        yr_nav = (1 + yr_ret).cumprod()
        yr_sharpe = calc_sharpe(yr_ret)
        yr_mdd = calc_max_drawdown(yr_nav * INITIAL_CAPITAL)
        yearly[year] = (round(yr_sharpe, 2), round(yr_mdd * 100, 1))

    # 持仓市值分布（最近6个月）
    mv_samples = []
    recent_dates = sorted(target_portfolios.keys())[-6:]
    cur = conn.cursor()
    for rd in recent_dates:
        codes = list(target_portfolios[rd].keys())
        if not codes:
            continue
        placeholders = ",".join(["%s"] * len(codes))
        cur.execute(
            f"SELECT code, total_mv FROM daily_basic WHERE trade_date = %s AND code IN ({placeholders})",
            [rd] + codes,
        )
        for code, mv in cur.fetchall():
            if mv:
                mv_samples.append(float(mv) / 10000)  # 万元→亿元

    small_pct = sum(1 for m in mv_samples if m < 100) / max(len(mv_samples), 1)
    mv_median = np.median(mv_samples) if mv_samples else 0

    # 换手率
    turnover_series = result.turnover_series
    avg_turnover = float(turnover_series.mean()) if turnover_series is not None and len(turnover_series) > 0 else 0

    return {
        "label": label,
        "n_factors": len(factor_names),
        "cagr": cagr,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "small_pct": small_pct,
        "mv_median": mv_median,
        "avg_turnover": avg_turnover,
        "yearly": yearly,
    }


# ── 报告 ─────────────────────────────────────────────
def print_report(results: list[dict]) -> None:
    print("\n" + "═" * 95)
    print("  因子扩展验证（生产级回测引擎）")
    print("  引擎: SimpleBacktester + SignalComposer + PortfolioBuilder")
    print("  成本: 佣金万0.854 + 印花税千0.5 + volume_impact滑点")
    print(f"  配置: Top-{PAPER_TRADING_CONFIG.top_n} | 等权 | 月度调仓 | 行业上限{PAPER_TRADING_CONFIG.industry_cap}")
    print(f"  期间: {START_DATE} ~ {END_DATE}")
    print("═" * 95)

    print("\n  核心结果:")
    print(
        f"  {'组':<12s}  {'因子':>4s}  {'CAGR%':>7s}  {'Sharpe':>7s}  {'MDD%':>7s}  "
        f"{'Calmar':>7s}  {'<100亿%':>7s}  {'市值中位':>8s}  {'换手率':>6s}"
    )
    print(f"  {'─'*12}  {'─'*4}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*8}  {'─'*6}")

    for r in results:
        print(
            f"  {r['label']:<12s}  {r['n_factors']:>4d}  {r['cagr']*100:>+7.1f}  "
            f"{r['sharpe']:>7.2f}  {r['mdd']*100:>+7.1f}  {r['calmar']:>7.2f}  "
            f"{r['small_pct']*100:>6.0f}%  {r['mv_median']:>7.0f}亿  {r['avg_turnover']*100:>5.0f}%"
        )

    # vs ad-hoc对比
    d_result = next((r for r in results if "15" in r["label"]), None)
    if d_result:
        print("\n  D组(15因子) 验证对比:")
        print(f"    生产引擎: Sharpe={d_result['sharpe']:.2f}, MDD={d_result['mdd']*100:.1f}%")
        print("    ad-hoc版1(factor_pool_expansion.py): Sharpe=0.78")
        print("    ad-hoc版2(factor_pool_ic_weighted.py): Sharpe=1.26")
        if abs(d_result['sharpe'] - 1.26) < abs(d_result['sharpe'] - 0.78):
            print("    → 版2(1.26)更接近生产级结果")
        else:
            print("    → 版1(0.78)更接近生产级结果")

    # 年度分解
    print("\n  年度分解:")
    header = f"  {'年':>6s}"
    for r in results:
        header += f"  │ {r['label']:>12s}"
    print(header)
    print(f"  {'─'*6}" + "  ┼ " + "  ┼ ".join(["─" * 12] * len(results)))

    for year in range(START_DATE.year, END_DATE.year + 1):
        line = f"  {year:>6d}"
        for r in results:
            s, m = r["yearly"].get(year, (0, 0))
            line += f"  │ {s:>+5.2f}/{m:>+5.1f}"
        print(line)

    # 结论
    print("\n  结论:")
    base = results[0]
    best_calmar = max(results, key=lambda r: r["calmar"])
    max(results, key=lambda r: r["mdd"])

    print("    Sharpe趋势: " + " → ".join(f"{r['n_factors']}f={r['sharpe']:.2f}" for r in results))
    print("    MDD趋势:    " + " → ".join(f"{r['n_factors']}f={r['mdd']*100:.1f}%" for r in results))

    if best_calmar["label"] != base["label"]:
        print(f"    最优Calmar: {best_calmar['label']} = {best_calmar['calmar']:.2f} (基线={base['calmar']:.2f})")
        delta_sharpe = (best_calmar["sharpe"] - base["sharpe"]) / abs(base["sharpe"]) * 100
        delta_mdd = (best_calmar["mdd"] - base["mdd"]) * 100
        print(f"    vs基线: Sharpe变化{delta_sharpe:+.0f}%, MDD改善{delta_mdd:+.1f}pp")
    else:
        print("    CORE 5仍是最优（扩展无改善）")

    print(f"\n{'═' * 95}\n")


# ── 主流程 ─────────────────────────────────────────────
def main() -> None:
    # 注入新因子方向（monkey-patch，不修改signal_engine.py源文件）
    for fname, direction in EXTRA_DIRECTIONS.items():
        if fname not in FACTOR_DIRECTION:
            FACTOR_DIRECTION[fname] = direction
            logger.info(f"  注入方向: {fname} = {direction}")

    conn = _get_sync_conn()

    # 加载共享数据（只加载一次）
    logger.info("加载共享数据...")
    t0 = time.perf_counter()
    price_data = load_price_data(conn)
    logger.info(f"  价格: {len(price_data):,}行 ({time.perf_counter()-t0:.1f}s)")

    benchmark_data = load_benchmark(conn)
    industry = load_industry(conn)
    rebalance_dates = get_rebalance_dates(START_DATE, END_DATE, freq="monthly", conn=conn)
    logger.info(f"  基准: {len(benchmark_data)}天, 行业: {len(industry)}只, 调仓日: {len(rebalance_dates)}个")

    # 串行运行4组
    results = []
    for label, factor_names in GROUPS:
        t1 = time.perf_counter()
        r = run_backtest_for_factors(
            factor_names, price_data, benchmark_data,
            industry, rebalance_dates, conn, label=label,
        )
        elapsed = time.perf_counter() - t1
        logger.info(f"[{label}] 完成: Sharpe={r['sharpe']:.2f} MDD={r['mdd']*100:.1f}% ({elapsed:.1f}s)")
        results.append(r)

    print_report(results)
    conn.close()


if __name__ == "__main__":
    main()
