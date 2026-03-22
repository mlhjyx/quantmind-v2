#!/usr/bin/env python3
"""候选5(中期反转) SimBroker回测 — LL-011合规。

两个版本:
  A) 单因子: reversal_60 only
  B) 多因子: reversal_60 + reversal_20 + turnover_mean_20 (等权3因子)

配置: Top-15, 月频, 初始100万, IndCap=25%
输出: 分年度Sharpe/MDD/收益, 与基线的日收益率corr
"""

import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 确保reversal_60在FACTOR_DIRECTION中 ──
if "reversal_60" not in FACTOR_DIRECTION:
    FACTOR_DIRECTION["reversal_60"] = 1  # 已取反, 高值=过去60日跌幅大=反转机会

START = date(2021, 1, 1)
END = date(2025, 12, 31)
INITIAL_CAPITAL = 1_000_000.0
TOP_N = 15
FREQ = "monthly"


def load_factor_values(trade_date, factor_names, conn) -> pd.DataFrame:
    """加载单日因子值(指定因子)。"""
    placeholders = ",".join(["%s"] * len(factor_names))
    return pd.read_sql(
        f"""SELECT code, factor_name, neutral_value
            FROM factor_values
            WHERE trade_date = %s AND factor_name IN ({placeholders})""",
        conn,
        params=[trade_date] + list(factor_names),
    )


def load_universe(trade_date, conn) -> set[str]:
    """加载Universe（排除ST/新股/停牌/低流动性）。"""
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


def load_industry(conn) -> pd.Series:
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start_date, end_date, conn) -> pd.DataFrame:
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


def load_benchmark(start_date, end_date, conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


def run_strategy(factor_names: list[str], label: str, conn,
                 rebalance_dates, industry, price_data, benchmark_data):
    """运行一个策略变体, 返回BacktestResult。"""
    sig_config = SignalConfig(
        factor_names=factor_names,
        top_n=TOP_N,
        weight_method="equal",
        rebalance_freq=FREQ,
        industry_cap=0.25,
        turnover_cap=0.50,
    )
    bt_config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        top_n=TOP_N,
        rebalance_freq=FREQ,
        slippage_bps=10.0,
    )

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values(rd, factor_names, conn)
        if fv.empty:
            logger.warning(f"[{label}][{rd}] 无因子数据, 跳过")
            continue

        universe = load_universe(rd, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

    logger.info(f"[{label}] 信号生成完成: {len(target_portfolios)}个调仓日")

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    return result


def calc_metrics(result, label: str) -> dict:
    """从BacktestResult计算关键指标。"""
    nav = result.daily_nav
    ret = result.daily_returns

    # 过滤零收益开头
    first_nonzero = ret[ret != 0].index[0] if any(ret != 0) else ret.index[0]
    ret = ret.loc[first_nonzero:]
    nav = nav.loc[first_nonzero:]

    ann_ret = (nav.iloc[-1] / nav.iloc[0]) ** (252 / len(nav)) - 1
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cummax = nav.cummax()
    dd = (nav - cummax) / cummax
    max_dd = dd.min()

    return {
        "label": label,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "daily_returns": ret,
        "daily_nav": nav,
    }


def yearly_metrics(metrics: dict) -> pd.DataFrame:
    """分年度指标。"""
    ret = metrics["daily_returns"]
    nav = metrics["daily_nav"]
    rows = []
    for year in sorted(set(d.year for d in ret.index)):
        yr = ret[ret.index.map(lambda d: d.year == year)]
        yr_nav = nav[nav.index.map(lambda d: d.year == year)]
        if len(yr) < 20:
            continue
        ann_r = (yr_nav.iloc[-1] / yr_nav.iloc[0]) ** (252 / len(yr_nav)) - 1
        ann_v = yr.std() * np.sqrt(252)
        sh = ann_r / ann_v if ann_v > 0 else 0
        cummax = yr_nav.cummax()
        mdd = ((yr_nav - cummax) / cummax).min()
        rows.append({
            "year": year,
            "ann_return": ann_r,
            "sharpe": sh,
            "max_dd": mdd,
            "n_days": len(yr),
        })
    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    conn = _get_sync_conn()

    logger.info("加载公共数据...")
    rebalance_dates = get_rebalance_dates(START, END, freq=FREQ, conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    industry = load_industry(conn)
    price_data = load_price_data(START, END, conn)
    benchmark_data = load_benchmark(START, END, conn)
    logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

    # ── 版本A: 单因子 reversal_60 ──
    logger.info("=" * 60)
    logger.info("版本A: reversal_60 单因子")
    logger.info("=" * 60)
    result_a = run_strategy(
        ["reversal_60"], "Rev60-Only", conn,
        rebalance_dates, industry, price_data, benchmark_data,
    )
    m_a = calc_metrics(result_a, "Rev60-Only(SimBroker)")

    # ── 版本B: 三因子 reversal_60 + reversal_20 + turnover_mean_20 ──
    logger.info("=" * 60)
    logger.info("版本B: reversal_60 + reversal_20 + turnover_mean_20 三因子")
    logger.info("=" * 60)
    result_b = run_strategy(
        ["reversal_60", "reversal_20", "turnover_mean_20"], "Rev60-Multi", conn,
        rebalance_dates, industry, price_data, benchmark_data,
    )
    m_b = calc_metrics(result_b, "Rev60-Multi(SimBroker)")

    # ── 基线 (5因子) ──
    logger.info("=" * 60)
    logger.info("基线: 5因子等权")
    logger.info("=" * 60)
    baseline_factors = [
        "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio",
    ]
    result_base = run_strategy(
        baseline_factors, "Baseline-5F", conn,
        rebalance_dates, industry, price_data, benchmark_data,
    )
    m_base = calc_metrics(result_base, "Baseline-5F(SimBroker)")

    # ── 汇总输出 ──
    print("\n" + "=" * 80)
    print("候选5(中期反转) SimBroker回测结果")
    print("=" * 80)
    print(f"回测区间: {START} ~ {END}, Top-{TOP_N}, 月频, 初始{INITIAL_CAPITAL/10000:.0f}万")
    print()

    print(f"{'策略':<30} {'年化收益':>10} {'Sharpe':>8} {'Max DD':>10} {'年化波动':>10}")
    print("-" * 70)
    for m in [m_a, m_b, m_base]:
        print(f"{m['label']:<30} {m['ann_return']:>9.2%} {m['sharpe']:>8.3f} {m['max_dd']:>9.2%} {m['ann_vol']:>9.2%}")

    # ── 与基线日收益率相关性 ──
    print("\n--- 与基线的日收益率相关性 ---")
    common_idx = m_a["daily_returns"].index.intersection(m_base["daily_returns"].index)
    corr_a = m_a["daily_returns"].loc[common_idx].corr(m_base["daily_returns"].loc[common_idx])
    corr_b = m_b["daily_returns"].loc[common_idx].corr(m_base["daily_returns"].loc[common_idx])
    print(f"  Rev60-Only  vs Baseline:  corr = {corr_a:.3f}")
    print(f"  Rev60-Multi vs Baseline:  corr = {corr_b:.3f}")

    # ── 分年度相关性 ──
    print("\n--- 分年度相关性(Rev60-Only vs Baseline) ---")
    for year in sorted(set(d.year for d in common_idx)):
        yr_idx = [d for d in common_idx if d.year == year]
        if len(yr_idx) < 20:
            continue
        c = m_a["daily_returns"].loc[yr_idx].corr(m_base["daily_returns"].loc[yr_idx])
        print(f"  {year}: corr = {c:.3f}")

    print("\n--- 分年度相关性(Rev60-Multi vs Baseline) ---")
    for year in sorted(set(d.year for d in common_idx)):
        yr_idx = [d for d in common_idx if d.year == year]
        if len(yr_idx) < 20:
            continue
        c = m_b["daily_returns"].loc[yr_idx].corr(m_base["daily_returns"].loc[yr_idx])
        print(f"  {year}: corr = {c:.3f}")

    # ── 分年度指标 ──
    for m in [m_a, m_b, m_base]:
        print(f"\n--- {m['label']} 分年度 ---")
        yr = yearly_metrics(m)
        for _, row in yr.iterrows():
            print(f"  {int(row['year'])}: 年化={row['ann_return']:+.2%}  Sharpe={row['sharpe']:.3f}  MDD={row['max_dd']:.2%}")

    # ── 50/50组合分析 ──
    print("\n--- 50/50组合分析 ---")
    for m_cand, cand_label in [(m_a, "Rev60-Only"), (m_b, "Rev60-Multi")]:
        common = m_cand["daily_nav"].index.intersection(m_base["daily_nav"].index)
        combo_nav = (m_cand["daily_nav"].loc[common] + m_base["daily_nav"].loc[common]) / 2
        combo_ret = combo_nav.pct_change().dropna()
        combo_ret = combo_ret[combo_ret.index >= combo_ret[combo_ret != 0].index[0]]
        combo_nav_clean = combo_nav.loc[combo_ret.index]

        ann_r = (combo_nav_clean.iloc[-1] / combo_nav_clean.iloc[0]) ** (252 / len(combo_nav_clean)) - 1
        ann_v = combo_ret.std() * np.sqrt(252)
        sh = ann_r / ann_v if ann_v > 0 else 0
        cummax = combo_nav_clean.cummax()
        mdd = ((combo_nav_clean - cummax) / cummax).min()
        print(f"\n  50/50 Baseline + {cand_label}:")
        print(f"    年化收益={ann_r:.2%}  Sharpe={sh:.3f}  MDD={mdd:.2%}  波动={ann_v:.2%}")

        # 分年度
        for year in sorted(set(d.year for d in combo_ret.index)):
            yr_nav = combo_nav_clean[combo_nav_clean.index.map(lambda d: d.year == year)]
            if len(yr_nav) < 20:
                continue
            yr_r = (yr_nav.iloc[-1] / yr_nav.iloc[0]) ** (252 / len(yr_nav)) - 1
            print(f"    {year}: {yr_r:+.2%}")

    # ── 交易统计 ──
    print("\n--- 交易统计 ---")
    for res, label in [(result_a, "Rev60-Only"), (result_b, "Rev60-Multi"), (result_base, "Baseline")]:
        n_trades = len(res.trades)
        buys = sum(1 for t in res.trades if t.direction == "buy")
        sells = sum(1 for t in res.trades if t.direction == "sell")
        total_cost = sum(t.total_cost + t.slippage for t in res.trades)
        print(f"  {label}: {n_trades}笔({buys}买+{sells}卖), 总成本={total_cost:,.0f}元")

    elapsed = time.time() - t0
    logger.info(f"\n总耗时: {elapsed:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
