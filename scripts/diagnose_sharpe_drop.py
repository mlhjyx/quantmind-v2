#!/usr/bin/env python3
"""诊断Sharpe暴跌: 修复后 vs 旧bug, Top-20 vs Top-15 对比。

回测A: 修复后代码 + Top-20
回测B: 修复后代码 + Top-15
回测C: 旧bug代码 + Top-20 (模拟持仓膨胀)

关键指标: 平均持仓数 — 如果回测C平均30-40只,证明膨胀是Sharpe虚高的原因。
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.config_guard import print_config_header
from engines.metrics import TRADING_DAYS_PER_YEAR, calc_max_drawdown, calc_sharpe
from engines.signal_engine import (
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


# ============================================================
# 两个版本的 turnover_cap 函数
# ============================================================

def turnover_cap_fixed(
    target: dict[str, float],
    prev: dict[str, float],
    cap: float = 0.5,
) -> dict[str, float]:
    """修复后: blend后只保留target中的股票。"""
    target_codes = set(target)
    all_codes = target_codes | set(prev)
    turnover = sum(
        abs(target.get(c, 0) - prev.get(c, 0)) for c in all_codes
    ) / 2

    if turnover <= cap:
        return target

    ratio = cap / max(turnover, 1e-12)
    blended = {}
    for c in all_codes:
        t = target.get(c, 0)
        p = prev.get(c, 0)
        blended[c] = p + ratio * (t - p)

    # 关键修复: 只保留target中的股票
    blended = {c: w for c, w in blended.items()
               if c in target_codes and w > 0.001}

    total = sum(blended.values())
    if total > 0:
        blended = {c: w / total for c, w in blended.items()}
    return blended


def turnover_cap_old_bug(
    target: dict[str, float],
    prev: dict[str, float],
    cap: float = 0.5,
) -> dict[str, float]:
    """旧bug: 保留并集, 不过滤target_codes。"""
    target_codes = set(target)
    all_codes = target_codes | set(prev)
    turnover = sum(
        abs(target.get(c, 0) - prev.get(c, 0)) for c in all_codes
    ) / 2

    if turnover <= cap:
        return target

    ratio = cap / max(turnover, 1e-12)
    blended = {}
    for c in all_codes:
        t = target.get(c, 0)
        p = prev.get(c, 0)
        blended[c] = p + ratio * (t - p)

    # 旧bug: 不过滤target_codes, 保留并集中所有权重>0的
    blended = {c: w for c, w in blended.items() if w > 0.001}

    total = sum(blended.values())
    if total > 0:
        blended = {c: w / total for c, w in blended.items()}
    return blended


# ============================================================
# 自定义 PortfolioBuilder (可注入 turnover_cap 函数)
# ============================================================

class CustomPortfolioBuilder(PortfolioBuilder):
    """可注入不同turnover_cap实现的PortfolioBuilder。"""

    def __init__(self, config: SignalConfig, turnover_cap_fn):
        super().__init__(config)
        self._turnover_cap_fn = turnover_cap_fn

    def _apply_turnover_cap(
        self,
        target: dict[str, float],
        prev: dict[str, float],
    ) -> dict[str, float]:
        return self._turnover_cap_fn(target, prev, self.config.turnover_cap)


# ============================================================
# 数据加载 (复用run_backtest.py逻辑)
# ============================================================

def load_factor_values(trade_date, conn) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
        conn, params=(trade_date,),
    )


def load_universe(trade_date, conn) -> set[str]:
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
        conn, params=(start_date, end_date),
    )


def load_benchmark(start_date, end_date, conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn, params=(start_date, end_date),
    )


# ============================================================
# 单次回测执行
# ============================================================

def run_single_backtest(
    label: str,
    top_n: int,
    turnover_cap_fn,
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
) -> dict:
    """执行单次回测, 返回关键指标。"""
    t0 = time.time()
    logger.info(f"[{label}] 开始: top_n={top_n}")

    # 5因子等权月频配置
    factor_names = [
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
    ]

    sig_config = SignalConfig(
        factor_names=factor_names,
        top_n=top_n,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )

    bt_config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=top_n,
        rebalance_freq="monthly",
        slippage_bps=10.0,
        turnover_cap=0.50,
    )

    composer = SignalComposer(sig_config)
    builder = CustomPortfolioBuilder(sig_config, turnover_cap_fn)

    target_portfolios = {}
    prev_weights = {}
    holdings_counts = []  # 每期持仓数

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values(rd, conn)
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
            holdings_counts.append(len(target))

    logger.info(f"[{label}] 信号生成完成: {len(target_portfolios)}期")

    # 运行回测
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    # 计算指标
    nav = result.daily_nav
    returns = result.daily_returns

    years = len(returns) / TRADING_DAYS_PER_YEAR
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1)
    annual_return = float((1 + total_return) ** (1 / max(years, 0.01)) - 1)
    sharpe = calc_sharpe(returns)
    mdd = calc_max_drawdown(nav)

    # 从holdings_history计算实际平均持仓数
    actual_holdings_counts = []
    for d, h in result.holdings_history.items():
        actual_holdings_counts.append(len(h))

    avg_target_holdings = np.mean(holdings_counts) if holdings_counts else 0
    avg_actual_holdings = np.mean(actual_holdings_counts) if actual_holdings_counts else 0

    elapsed = time.time() - t0
    logger.info(f"[{label}] 完成, 耗时 {elapsed:.0f}s")

    return {
        "label": label,
        "top_n": top_n,
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "total_return": round(total_return * 100, 2),
        "avg_target_holdings": round(avg_target_holdings, 1),
        "avg_actual_holdings": round(avg_actual_holdings, 1),
        "max_target_holdings": max(holdings_counts) if holdings_counts else 0,
        "num_rebalances": len(target_portfolios),
    }


# ============================================================
# Main
# ============================================================

def main():
    print_config_header()
    start = date(2021, 1, 1)
    end = date(2025, 12, 31)

    conn = _get_sync_conn()
    t_total = time.time()

    logger.info("=" * 60)
    logger.info("Sharpe暴跌诊断: 修复后 vs 旧bug, Top-20 vs Top-15")
    logger.info("=" * 60)

    # 1. 获取调仓日历 (月频)
    logger.info("获取月频调仓日历...")
    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    # 2. 加载共享数据
    logger.info("加载行业分类...")
    industry = load_industry(conn)

    logger.info("加载价格数据...")
    price_data = load_price_data(start, end, conn)
    logger.info(f"价格数据: {len(price_data)}行")

    benchmark_data = load_benchmark(start, end, conn)
    logger.info(f"基准数据: {len(benchmark_data)}行")

    # 3. 三组回测
    results = []

    # 回测A: 修复后 + Top-20
    r = run_single_backtest(
        label="A: 修复后+Top20",
        top_n=20,
        turnover_cap_fn=turnover_cap_fixed,
        rebalance_dates=rebalance_dates,
        industry=industry,
        price_data=price_data,
        benchmark_data=benchmark_data,
        conn=conn,
    )
    results.append(r)

    # 回测B: 修复后 + Top-15
    r = run_single_backtest(
        label="B: 修复后+Top15",
        top_n=15,
        turnover_cap_fn=turnover_cap_fixed,
        rebalance_dates=rebalance_dates,
        industry=industry,
        price_data=price_data,
        benchmark_data=benchmark_data,
        conn=conn,
    )
    results.append(r)

    # 回测C: 旧bug + Top-20
    r = run_single_backtest(
        label="C: 旧bug+Top20",
        top_n=20,
        turnover_cap_fn=turnover_cap_old_bug,
        rebalance_dates=rebalance_dates,
        industry=industry,
        price_data=price_data,
        benchmark_data=benchmark_data,
        conn=conn,
    )
    results.append(r)

    conn.close()

    # 4. 输出对比
    elapsed_total = time.time() - t_total
    print("\n")
    print("=" * 80)
    print("Sharpe暴跌诊断结果")
    print("=" * 80)
    print(f"{'回测':>20}  {'Sharpe':>8}  {'MDD':>8}  {'年化':>8}  {'平均持仓':>8}  {'最大持仓':>8}")
    print("-" * 80)
    for r in results:
        print(
            f"{r['label']:>20}  "
            f"{r['sharpe']:>8.4f}  "
            f"{r['mdd']:>7.2f}%  "
            f"{r['annual_return']:>7.2f}%  "
            f"{r['avg_target_holdings']:>8.1f}  "
            f"{r['max_target_holdings']:>8d}"
        )
    print("-" * 80)

    # 5. 诊断结论
    print("\n--- 诊断分析 ---")
    a = results[0]  # 修复+Top20
    b = results[1]  # 修复+Top15
    c = results[2]  # 旧bug+Top20

    print("\n1. Top-N效应 (A vs B):")
    print(f"   修复+Top20 Sharpe={a['sharpe']:.4f} vs 修复+Top15 Sharpe={b['sharpe']:.4f}")
    print(f"   差异: {a['sharpe'] - b['sharpe']:.4f}")
    if a['sharpe'] > b['sharpe'] + 0.1:
        print("   -> Top-20 明显优于 Top-15, 集中持仓(Top-15)可能过度集中风险")
    elif abs(a['sharpe'] - b['sharpe']) < 0.1:
        print("   -> Top-20 和 Top-15 差异不大")
    else:
        print("   -> Top-15 优于 Top-20")

    print("\n2. Bug效应 (A vs C, 同为Top-20):")
    print(f"   修复+Top20 Sharpe={a['sharpe']:.4f} vs 旧bug+Top20 Sharpe={c['sharpe']:.4f}")
    print(f"   差异: {c['sharpe'] - a['sharpe']:.4f}")
    print(f"   旧bug平均持仓: {c['avg_target_holdings']:.1f} (名义Top-20)")
    if c['avg_target_holdings'] > 25:
        print(f"   -> 持仓膨胀已确认! 名义Top-20实际持有{c['avg_target_holdings']:.0f}只")
        print(f"   -> Sharpe虚高 {c['sharpe'] - a['sharpe']:.4f} 来自过度分散化")
    elif c['sharpe'] > a['sharpe'] + 0.3:
        print("   -> 旧bug Sharpe明显更高, 持仓膨胀是Sharpe虚高的主因")

    print("\n3. 真实基线:")
    print(f"   修复后代码的真实Sharpe范围: {b['sharpe']:.4f} (Top-15) ~ {a['sharpe']:.4f} (Top-20)")
    print(f"   旧bug Sharpe {c['sharpe']:.4f} 的虚高幅度: +{c['sharpe'] - a['sharpe']:.4f}")

    print(f"\n总耗时: {elapsed_total:.0f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
