#!/usr/bin/env python3
"""Layer 3: 随机信号统计检验 — 检测回测引擎是否存在系统性正偏。

优化: 预构建price_idx/daily_close一次, 复用200次trial, 避免iterrows重建。
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
    wrapper_class=structlog.stdlib.BoundLogger, logger_factory=structlog.stdlib.LoggerFactory()
)
logging.getLogger().setLevel(logging.WARNING)

import numpy as np
import pandas as pd
from engines.backtest_engine import BacktestConfig, PMSConfig, SimBroker
from engines.signal_engine import get_rebalance_dates
from engines.slippage_model import SlippageConfig
from scipy import stats

from app.services.price_utils import _get_sync_conn


def load_price_data(start, end, conn):
    return pd.read_sql(
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


def precompute_indexes(price_data):
    """一次性构建price_idx和daily_close(避免每次trial重建iterrows)。"""
    price_data = price_data.sort_values(["trade_date", "code"], kind="mergesort")
    all_dates = sorted(price_data["trade_date"].unique())

    # price_idx: (code, date) → row
    price_idx = {}
    for _, row in price_data.iterrows():
        price_idx[(row["code"], row["trade_date"])] = row

    # daily_close: date → {code: close}
    daily_close = {}
    for d in all_dates:
        day_data = price_data[price_data["trade_date"] == d]
        daily_close[d] = dict(zip(day_data["code"], day_data["close"], strict=False))

    return all_dates, price_idx, daily_close


def run_single_trial(
    config: BacktestConfig,
    target_portfolios: dict,
    all_dates: list,
    price_idx: dict,
    daily_close: dict,
) -> float:
    """运行一次回测(复用预构建数据), 返回Sharpe。"""
    broker = SimBroker(config)
    signal_dates = sorted(target_portfolios.keys())

    # 构建exec_map
    exec_map = {}
    for sd in signal_dates:
        future = [d for d in all_dates if d > sd]
        if future:
            exec_map[future[0]] = sd

    # 简化日循环(无PMS, 无pending orders)
    nav_series = {}
    trades = []

    for td in all_dates:
        broker.new_day()

        # 调仓
        if td in exec_map:
            signal_date = exec_map[td]
            target = target_portfolios.get(signal_date, {})
            portfolio_value = broker.get_portfolio_value(daily_close.get(td, {}))

            # 先卖
            for code in list(broker.holdings.keys()):
                if code not in target:
                    row = price_idx.get((code, td))
                    if row is not None and broker.can_trade(code, "sell", row):
                        shares = broker.holdings.get(code, 0)
                        if shares > 0:
                            fill = broker.execute_sell(code, shares, row)
                            if fill:
                                trades.append(fill)

            # 后买
            for code, weight in sorted(target.items(), key=lambda x: -x[1]):
                if code in broker.holdings:
                    continue
                row = price_idx.get((code, td))
                if row is None or not broker.can_trade(code, "buy", row):
                    continue
                buy_amount = portfolio_value * weight
                if broker.cash < buy_amount * 0.1:
                    break
                fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
                if fill:
                    trades.append(fill)

        # NAV
        prices = daily_close.get(td, {})
        nav_series[td] = broker.get_portfolio_value(prices)

    # 计算Sharpe
    nav = pd.Series(nav_series).sort_index()
    if len(nav) < 20:
        return 0.0
    ret = nav.pct_change().dropna()
    ann_ret = (nav.iloc[-1] / nav.iloc[0]) ** (252 / len(ret)) - 1
    ann_vol = ret.std() * (252**0.5)
    return ann_ret / ann_vol if ann_vol > 0 else 0.0


def main():
    N_TRIALS = 200
    TOP_N = 20

    conn = _get_sync_conn()
    start, end = date(2023, 1, 1), date(2025, 12, 31)

    print("=" * 60)
    print(f"Layer 3: 随机信号偏差检验 ({N_TRIALS}次)")
    print("=" * 60)

    # 1. 加载+预构建(只做一次)
    print("\n[1/4] 加载数据+预构建索引...")
    t0 = time.time()
    price_data = load_price_data(start, end, conn)
    print(f"  价格: {len(price_data)}行 ({time.time() - t0:.0f}s)")

    t1 = time.time()
    all_dates, price_idx, daily_close = precompute_indexes(price_data)
    print(f"  索引构建: {time.time() - t1:.0f}s")

    # 获取调仓日历+universe
    rebal_dates_raw = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    rebal_dates = [d for d in rebal_dates_raw if d in set(all_dates)]
    print(f"  调仓日: {len(rebal_dates)}个")

    # Universe: 每个调仓日有数据的股票
    universe_by_date = {}
    for d in rebal_dates:
        universe_by_date[d] = list(daily_close.get(d, {}).keys())
    print(f"  Universe: ~{np.mean([len(v) for v in universe_by_date.values()]):.0f}只/日")

    # 2. 配置
    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=TOP_N,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=False),
    )

    # 3. 运行trials
    print(f"\n[2/4] 运行{N_TRIALS}次随机回测...")
    sharpes = []
    t2 = time.time()

    for i in range(N_TRIALS):
        rng = np.random.default_rng(seed=i)

        # 生成随机目标
        targets = {}
        for rd in rebal_dates:
            codes = universe_by_date.get(rd, [])
            if len(codes) < TOP_N:
                continue
            selected = rng.choice(codes, size=TOP_N, replace=False)
            w = 1.0 / TOP_N
            targets[rd] = {c: w for c in selected}

        if not targets:
            continue

        s = run_single_trial(config, targets, all_dates, price_idx, daily_close)
        sharpes.append(s)

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t2
            eta = elapsed / (i + 1) * (N_TRIALS - i - 1)
            print(
                f"  [{i + 1}/{N_TRIALS}] mean={np.mean(sharpes):.3f} "
                f"std={np.std(sharpes):.3f} ({elapsed:.0f}s, ETA {eta:.0f}s)"
            )

    elapsed = time.time() - t2
    print(f"  完成: {elapsed:.0f}s ({elapsed / N_TRIALS:.1f}s/trial)")

    # 4. 统计检验
    sharpes = np.array(sharpes)
    mean_s = np.mean(sharpes)
    std_s = np.std(sharpes)
    median_s = np.median(sharpes)

    t_stat, p_two = stats.ttest_1samp(sharpes, 0)
    p_one = p_two / 2 if t_stat > 0 else 1 - p_two / 2

    print("\n[3/4] 统计结果:")
    print(f"  N         = {len(sharpes)}")
    print(f"  Mean      = {mean_s:.4f}")
    print(f"  Median    = {median_s:.4f}")
    print(f"  Std       = {std_s:.4f}")
    print(f"  Min/Max   = {sharpes.min():.3f} / {sharpes.max():.3f}")
    print(f"  t-stat    = {t_stat:.3f}")
    print(f"  p(>0)     = {p_one:.4f}")

    pcts = [5, 25, 50, 75, 95]
    pct_vals = np.percentile(sharpes, pcts)
    print("  分位数: " + " | ".join(f"P{p}={v:.3f}" for p, v in zip(pcts, pct_vals, strict=False)))

    print("\n[4/4] 判定:")
    if mean_s > 0.3:
        print(f"  ❌ FAIL: mean(Sharpe)={mean_s:.3f} > 0.3, 严重前瞻偏差!")
    elif mean_s > 0.1 and p_one < 0.05:
        print(f"  ⚠️ WARNING: mean(Sharpe)={mean_s:.3f} > 0.1 且 p={p_one:.4f}<0.05, 可能有正偏")
    elif -0.3 <= mean_s <= 0.1:
        print(f"  ✅ PASS: mean(Sharpe)={mean_s:.3f} ∈ [-0.3, 0.1], 无系统性偏差")
    else:
        print(f"  🟡 INFO: mean(Sharpe)={mean_s:.3f} < -0.3, 成本可能偏高(不影响严谨性)")

    if abs(mean_s) < 0.15:
        print("  ✅ 回测引擎无前瞻偏差(随机信号无法系统性获利)")
    print("=" * 60)


if __name__ == "__main__":
    main()
