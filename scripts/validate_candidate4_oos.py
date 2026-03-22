#!/usr/bin/env python3
"""候选4 (大盘低波) WF-OOS验证。

候选4配置:
- 选股池: 市值Top30%大盘股 (daily_basic.total_mv前30%)
- 因子: volatility_20 (低波排序, 方向-1)
- Top-10等权, 月频调仓
- 初始资金: 50万

验证内容:
1. 2021-2025全期回测 (SimpleBacktester)
2. 风格逆风检查 (2024 Q3-Q4 AI行情)
3. 50/50组合 (候选4 50万 + 基线5因子50万)
4. Bootstrap Sharpe CI

用法:
    cd /Users/xin/Documents/quantmind-v2 && python scripts/validate_candidate4_oos.py
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn
from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import (
    TRADING_DAYS_PER_YEAR,
    bootstrap_sharpe_ci,
    calc_max_drawdown,
    calc_sharpe,
)
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# 数据加载
# ============================================================

def load_large_cap_universe(trade_date: date, conn, top_pct: float = 0.30) -> set[str]:
    """加载市值Top30%大盘股宇宙。

    从daily_basic取total_mv(万元), 排名取前30%。
    同时过滤: 正常上市、非ST、上市满60天、有成交量。
    """
    df = pd.read_sql(
        """SELECT db.code, db.total_mv
           FROM daily_basic db
           JOIN symbols s ON db.code = s.code
           JOIN klines_daily k ON db.code = k.code AND db.trade_date = k.trade_date
           WHERE db.trade_date = %s
             AND db.total_mv IS NOT NULL
             AND db.total_mv > 0
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
        """,
        conn,
        params=(trade_date, trade_date),
    )
    if df.empty:
        return set()

    # Top 30% by market cap
    cutoff = df["total_mv"].quantile(1 - top_pct)
    large = df[df["total_mv"] >= cutoff]
    return set(large["code"].tolist())


def load_full_universe(trade_date: date, conn) -> set[str]:
    """加载全A宇宙（基线用，与diagnose脚本一致）。"""
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


def load_factor_values(trade_date: date, conn) -> pd.DataFrame:
    """加载单日全部因子值。"""
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
        conn,
        params=(trade_date,),
    )


def load_single_factor(trade_date: date, factor_name: str, conn) -> pd.DataFrame:
    """加载单日单因子，返回与compose兼容的DataFrame。"""
    df = pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s AND factor_name = %s""",
        conn,
        params=(trade_date, factor_name),
    )
    return df


def load_industry(conn) -> pd.Series:
    """加载行业分类。"""
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载价格数据。"""
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
        conn,
        params=(start_date, end_date),
    )


def load_benchmark(start_date: date, end_date: date, conn) -> pd.DataFrame:
    """加载基准指数数据。"""
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


# ============================================================
# 候选4: 单因子volatility_20选股 (大盘股宇宙)
# ============================================================

def generate_candidate4_signals(
    rebalance_dates: list[date],
    industry: pd.Series,
    conn,
) -> dict[date, dict[str, float]]:
    """候选4信号生成: 大盘股宇宙内volatility_20 Top10等权。"""
    config = SignalConfig(
        factor_names=["volatility_20"],
        top_n=10,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.30,  # 单因子放宽行业约束到30%
        turnover_cap=0.50,
    )
    composer = SignalComposer(config)
    builder = PortfolioBuilder(config)

    target_portfolios: dict[date, dict[str, float]] = {}
    prev_weights: dict[str, float] = {}

    for rd in rebalance_dates:
        # 加载大盘股宇宙
        universe = load_large_cap_universe(rd, conn)
        if len(universe) < 50:
            logger.warning(f"[候选4] {rd}: 大盘股宇宙太小 ({len(universe)}), 跳过")
            continue

        # 加载单因子
        fv = load_single_factor(rd, "volatility_20", conn)
        if fv.empty:
            continue

        # compose在大盘股宇宙内排序
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    return target_portfolios


# ============================================================
# 基线: 5因子Top15等权 (全A宇宙)
# ============================================================

def generate_baseline_signals(
    rebalance_dates: list[date],
    industry: pd.Series,
    conn,
) -> dict[date, dict[str, float]]:
    """基线信号: 5因子等权Top15月频。"""
    config = SignalConfig(
        factor_names=[
            "turnover_mean_20",
            "volatility_20",
            "reversal_20",
            "amihud_20",
            "bp_ratio",
        ],
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    composer = SignalComposer(config)
    builder = PortfolioBuilder(config)

    target_portfolios: dict[date, dict[str, float]] = {}
    prev_weights: dict[str, float] = {}

    for rd in rebalance_dates:
        universe = load_full_universe(rd, conn)
        if len(universe) < 100:
            continue

        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue

        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    return target_portfolios


# ============================================================
# 回测执行
# ============================================================

def run_backtest(
    label: str,
    target_portfolios: dict[date, dict[str, float]],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    initial_capital: float = 500_000.0,
    top_n: int = 10,
) -> dict:
    """执行回测并返回结果字典。"""
    t0 = time.time()
    logger.info(f"[{label}] 开始回测, {len(target_portfolios)}期信号, 初始资金={initial_capital:,.0f}")

    bt_config = BacktestConfig(
        initial_capital=initial_capital,
        top_n=top_n,
        rebalance_freq="monthly",
        slippage_bps=10.0,
        turnover_cap=0.50,
    )

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    nav = result.daily_nav
    returns = result.daily_returns

    years = len(returns) / TRADING_DAYS_PER_YEAR
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (1 / max(years, 0.01)) - 1)
    sharpe = calc_sharpe(returns)
    mdd = calc_max_drawdown(nav)

    elapsed = time.time() - t0
    logger.info(f"[{label}] 完成, 耗时 {elapsed:.0f}s, Sharpe={sharpe:.4f}")

    return {
        "label": label,
        "nav": nav,
        "returns": returns,
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "mdd": mdd,
        "result": result,
    }


def calc_annual_stats(nav: pd.Series) -> dict[int, dict]:
    """分年度计算收益和MDD。"""
    stats = {}
    for year in sorted(set(d.year for d in nav.index)):
        mask = [d.year == year for d in nav.index]
        year_nav = nav[mask]
        if len(year_nav) < 10:
            continue
        year_ret = float(year_nav.iloc[-1] / year_nav.iloc[0] - 1)
        year_mdd = calc_max_drawdown(year_nav)
        year_returns = year_nav.pct_change().fillna(0)
        year_sharpe = calc_sharpe(year_returns)
        stats[year] = {
            "return": year_ret,
            "mdd": year_mdd,
            "sharpe": year_sharpe,
        }
    return stats


def calc_quarterly_returns(nav: pd.Series) -> dict[str, float]:
    """按季度计算收益率。"""
    results = {}
    for d in nav.index:
        q = f"{d.year}Q{(d.month - 1) // 3 + 1}"
        if q not in results:
            results[q] = {"first": nav[d], "last": nav[d]}
        results[q]["last"] = nav[d]

    return {q: v["last"] / v["first"] - 1 for q, v in results.items()}


def calc_monthly_returns(nav: pd.Series) -> dict[str, float]:
    """按月计算收益率。"""
    results = {}
    for d in nav.index:
        key = f"{d.year}-{d.month:02d}"
        if key not in results:
            results[key] = {"first": nav[d], "last": nav[d]}
        results[key]["last"] = nav[d]

    return {k: v["last"] / v["first"] - 1 for k, v in results.items()}


# ============================================================
# Main
# ============================================================

def main():
    START = date(2021, 1, 1)
    END = date(2025, 12, 31)
    CAPITAL_EACH = 500_000.0

    conn = _get_sync_conn()
    t_total = time.time()

    print("=" * 70)
    print("候选4 (大盘低波) WF-OOS验证")
    print("=" * 70)

    # 1. 获取月频调仓日
    logger.info("获取月频调仓日...")
    rebalance_dates = get_rebalance_dates(START, END, freq="monthly", conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    # 2. 加载共享数据
    logger.info("加载行业分类...")
    industry = load_industry(conn)

    logger.info("加载价格数据 (2021-2025)...")
    price_data = load_price_data(START, END, conn)
    logger.info(f"价格数据: {len(price_data):,}行")

    benchmark_data = load_benchmark(START, END, conn)
    logger.info(f"基准数据: {len(benchmark_data)}行")

    # ============================================================
    # 3. 候选4信号生成
    # ============================================================
    logger.info("\n[Step 1] 生成候选4信号 (大盘低波Top10)...")
    c4_signals = generate_candidate4_signals(rebalance_dates, industry, conn)
    logger.info(f"候选4信号: {len(c4_signals)}期")

    # 打印每期持仓样本
    if c4_signals:
        sample_date = sorted(c4_signals.keys())[-1]
        sample = c4_signals[sample_date]
        logger.info(f"最新一期 ({sample_date}): {len(sample)}只, 权重范围 [{min(sample.values()):.3f}, {max(sample.values()):.3f}]")

    # ============================================================
    # 4. 基线信号生成
    # ============================================================
    logger.info("\n[Step 2] 生成基线信号 (5因子Top15)...")
    baseline_signals = generate_baseline_signals(rebalance_dates, industry, conn)
    logger.info(f"基线信号: {len(baseline_signals)}期")

    conn.close()

    # ============================================================
    # 5. 回测
    # ============================================================
    logger.info("\n[Step 3] 执行回测...")

    # 候选4回测 (50万)
    c4_result = run_backtest(
        "候选4(大盘低波)",
        c4_signals,
        price_data,
        benchmark_data,
        initial_capital=CAPITAL_EACH,
        top_n=10,
    )

    # 基线回测 (50万)
    bl_result = run_backtest(
        "基线(5因子Top15)",
        baseline_signals,
        price_data,
        benchmark_data,
        initial_capital=CAPITAL_EACH,
        top_n=15,
    )

    # ============================================================
    # 6. 50/50组合
    # ============================================================
    logger.info("\n[Step 4] 计算50/50组合...")

    # 对齐两条NAV曲线的日期
    common_dates = c4_result["nav"].index.intersection(bl_result["nav"].index)
    c4_nav_aligned = c4_result["nav"].loc[common_dates]
    bl_nav_aligned = bl_result["nav"].loc[common_dates]

    # 组合NAV = 候选4 NAV + 基线 NAV (各自50万起步)
    combo_nav = c4_nav_aligned + bl_nav_aligned
    combo_returns = combo_nav.pct_change().fillna(0)

    combo_years = len(combo_returns) / TRADING_DAYS_PER_YEAR
    combo_total_ret = float(combo_nav.iloc[-1] / combo_nav.iloc[0] - 1)
    combo_annual_ret = float((1 + combo_total_ret) ** (1 / max(combo_years, 0.01)) - 1)
    combo_sharpe = calc_sharpe(combo_returns)
    combo_mdd = calc_max_drawdown(combo_nav)

    # ============================================================
    # 7. Bootstrap CI
    # ============================================================
    logger.info("\n[Step 5] Bootstrap Sharpe CI...")
    c4_ci = bootstrap_sharpe_ci(c4_result["returns"], n_bootstrap=2000)
    combo_ci = bootstrap_sharpe_ci(combo_returns, n_bootstrap=2000)

    # ============================================================
    # 8. 分年度统计
    # ============================================================
    c4_annual = calc_annual_stats(c4_result["nav"])
    bl_annual = calc_annual_stats(bl_result["nav"])
    combo_annual = calc_annual_stats(combo_nav)

    # ============================================================
    # 9. 风格逆风检查
    # ============================================================
    c4_monthly = calc_monthly_returns(c4_result["nav"])
    c4_quarterly = calc_quarterly_returns(c4_result["nav"])

    # ============================================================
    # 输出
    # ============================================================
    elapsed_total = time.time() - t_total

    print("\n")
    print("=" * 70)
    print("候选4 OOS验证结果")
    print("=" * 70)

    # --- 候选4单独 ---
    print("\n--- 候选4单独 (大盘低波Top10, 50万) ---")
    print(f"  总收益:    {c4_result['total_return']*100:>+8.2f}%")
    print(f"  年化收益:  {c4_result['annual_return']*100:>+8.2f}%")
    print(f"  Sharpe:    {c4_result['sharpe']:>8.4f}")
    print(f"  MDD:       {c4_result['mdd']*100:>8.2f}%")
    print(f"  Bootstrap CI: Sharpe={c4_ci[0]:.2f} [{c4_ci[1]:.2f}, {c4_ci[2]:.2f}] (95% CI)")
    if c4_ci[1] < 0:
        print("  *** 警告: CI下界 < 0, 策略可能不赚钱! ***")
    else:
        print(f"  CI下界 > 0: 通过")

    # --- 基线单独 ---
    print("\n--- 基线单独 (5因子Top15, 50万) ---")
    print(f"  总收益:    {bl_result['total_return']*100:>+8.2f}%")
    print(f"  年化收益:  {bl_result['annual_return']*100:>+8.2f}%")
    print(f"  Sharpe:    {bl_result['sharpe']:>8.4f}")
    print(f"  MDD:       {bl_result['mdd']*100:>8.2f}%")

    # --- 50/50组合 ---
    print("\n--- 50/50组合 (候选4 50万 + 基线 50万) ---")
    print(f"  总收益:    {combo_total_ret*100:>+8.2f}%")
    print(f"  年化收益:  {combo_annual_ret*100:>+8.2f}%")
    print(f"  Sharpe:    {combo_sharpe:>8.4f}")
    print(f"  MDD:       {combo_mdd*100:>8.2f}%")
    print(f"  Bootstrap CI: Sharpe={combo_ci[0]:.2f} [{combo_ci[1]:.2f}, {combo_ci[2]:.2f}] (95% CI)")

    # --- 分年度 ---
    print("\n--- 分年度统计 ---")
    print(f"{'年份':>6}  {'候选4收益':>10}  {'候选4MDD':>10}  {'候选4Sharpe':>12}  "
          f"{'基线收益':>10}  {'基线MDD':>10}  {'组合收益':>10}  {'组合MDD':>10}  {'组合Sharpe':>12}")
    print("-" * 120)

    worst_combo_year_mdd = 0
    for year in sorted(set(list(c4_annual.keys()) + list(bl_annual.keys()) + list(combo_annual.keys()))):
        c4y = c4_annual.get(year, {})
        bly = bl_annual.get(year, {})
        cby = combo_annual.get(year, {})

        c4_ret = c4y.get("return", float("nan"))
        c4_mdd = c4y.get("mdd", float("nan"))
        c4_sh = c4y.get("sharpe", float("nan"))
        bl_ret = bly.get("return", float("nan"))
        bl_mdd = bly.get("mdd", float("nan"))
        cb_ret = cby.get("return", float("nan"))
        cb_mdd = cby.get("mdd", float("nan"))
        cb_sh = cby.get("sharpe", float("nan"))

        if not np.isnan(cb_mdd) and cb_mdd < worst_combo_year_mdd:
            worst_combo_year_mdd = cb_mdd

        flag = ""
        if not np.isnan(cb_ret) and cb_ret < -0.15:
            flag = " *** 年亏>15%!"
        if not np.isnan(cb_mdd) and cb_mdd < -0.20:
            flag += " *** 年MDD>20%!"

        print(
            f"{year:>6}  "
            f"{c4_ret*100:>+9.2f}%  {c4_mdd*100:>9.2f}%  {c4_sh:>11.3f}   "
            f"{bl_ret*100:>+9.2f}%  {bl_mdd*100:>9.2f}%  "
            f"{cb_ret*100:>+9.2f}%  {cb_mdd*100:>9.2f}%  {cb_sh:>11.3f}"
            f"{flag}"
        )

    # --- 风格逆风: 2024 Q3-Q4 (AI行情) ---
    print("\n--- 风格逆风检查: 2024 Q3-Q4 (AI行情) ---")
    ai_months = [f"2024-{m:02d}" for m in [7, 8, 9, 10, 11, 12]]
    print(f"  {'月份':>10}  {'候选4月收益':>14}")
    for m in ai_months:
        ret = c4_monthly.get(m, float("nan"))
        if not np.isnan(ret):
            flag = " *** 亏损" if ret < 0 else ""
            print(f"  {m:>10}  {ret*100:>+13.2f}%{flag}")
        else:
            print(f"  {m:>10}  {'N/A':>14}")

    # 季度汇总
    for q in ["2024Q3", "2024Q4"]:
        ret = c4_quarterly.get(q, float("nan"))
        if not np.isnan(ret):
            print(f"  {q:>10}  {ret*100:>+13.2f}% (季度)")

    # 如果有更早数据, 检查2020H2 (成长牛末期)
    print("\n--- 补充: 成长牛尾期 (2021Q1因子数据从2020.7开始) ---")
    for q in ["2021Q1", "2021Q2"]:
        ret = c4_quarterly.get(q, float("nan"))
        if not np.isnan(ret):
            print(f"  {q:>10}  {ret*100:>+13.2f}% (季度)")

    # --- 单因子风格衰减分析 ---
    print("\n--- 单因子风格衰减度分析 ---")
    c4_ann = c4_annual
    if c4_ann:
        sharpes = [s.get("sharpe", 0) for s in c4_ann.values()]
        returns_list = [s.get("return", 0) for s in c4_ann.values()]
        best_yr = max(c4_ann.items(), key=lambda x: x[1].get("sharpe", 0))
        worst_yr = min(c4_ann.items(), key=lambda x: x[1].get("sharpe", 0))
        print(f"  最优年: {best_yr[0]} Sharpe={best_yr[1]['sharpe']:.3f} 收益={best_yr[1]['return']*100:+.1f}%")
        print(f"  最差年: {worst_yr[0]} Sharpe={worst_yr[1]['sharpe']:.3f} 收益={worst_yr[1]['return']*100:+.1f}%")
        print(f"  Sharpe极差: {max(sharpes) - min(sharpes):.3f}")
        print(f"  收益极差: {(max(returns_list) - min(returns_list))*100:.1f}pp")
        if max(sharpes) - min(sharpes) > 1.5:
            print("  *** 风格波动大, 单因子在逆风期衰减严重 ***")

    # --- 汇总结论 ---
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    print(f"  候选4单独:  Sharpe={c4_result['sharpe']:.4f}, MDD={c4_result['mdd']*100:.2f}%, CI=[{c4_ci[1]:.2f}, {c4_ci[2]:.2f}]")
    print(f"  基线单独:   Sharpe={bl_result['sharpe']:.4f}, MDD={bl_result['mdd']*100:.2f}%")
    print(f"  50/50组合:  Sharpe={combo_sharpe:.4f}, MDD={combo_mdd*100:.2f}%, CI=[{combo_ci[1]:.2f}, {combo_ci[2]:.2f}]")

    # Gate checks
    gates_passed = 0
    total_gates = 4

    # Gate 1: CI下界>0
    if c4_ci[1] > 0:
        gates_passed += 1
        print(f"\n  [PASS] Gate 1: Bootstrap CI下界 > 0 ({c4_ci[1]:.2f})")
    else:
        print(f"\n  [FAIL] Gate 1: Bootstrap CI下界 <= 0 ({c4_ci[1]:.2f})")

    # Gate 2: 全期Sharpe > 0.3
    if c4_result["sharpe"] > 0.3:
        gates_passed += 1
        print(f"  [PASS] Gate 2: 全期Sharpe > 0.3 ({c4_result['sharpe']:.4f})")
    else:
        print(f"  [FAIL] Gate 2: 全期Sharpe <= 0.3 ({c4_result['sharpe']:.4f})")

    # Gate 3: 组合无单年亏损>20%
    any_bad_year = False
    for year, stats in combo_annual.items():
        if stats["return"] < -0.20:
            any_bad_year = True
            print(f"  [FAIL] Gate 3: 组合{year}年亏损{stats['return']*100:.1f}% > 20%")
    if not any_bad_year:
        gates_passed += 1
        print(f"  [PASS] Gate 3: 组合无单年亏损>20%")

    # Gate 4: 组合Sharpe > 基线Sharpe (候选4有增益)
    if combo_sharpe > bl_result["sharpe"]:
        gates_passed += 1
        print(f"  [PASS] Gate 4: 组合Sharpe ({combo_sharpe:.4f}) > 基线Sharpe ({bl_result['sharpe']:.4f})")
    else:
        print(f"  [FAIL] Gate 4: 组合Sharpe ({combo_sharpe:.4f}) <= 基线Sharpe ({bl_result['sharpe']:.4f})")

    print(f"\n  Gate通过: {gates_passed}/{total_gates}")
    if gates_passed == total_gates:
        print("  VERDICT: 候选4通过全部Gate, 可加入组合")
    elif gates_passed >= 3:
        print("  VERDICT: 候选4基本可用, 需关注未通过的Gate")
    else:
        print("  VERDICT: 候选4未通过足够Gate, 不建议加入组合")

    print(f"\n总耗时: {elapsed_total:.0f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
