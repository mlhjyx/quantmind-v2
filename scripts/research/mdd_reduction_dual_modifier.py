#!/usr/bin/env python3
"""MDD优化: RegimeModifier + NorthboundModifier双层叠加测试。

目标: MDD从-50%降到<25%，同时Sharpe不大幅下降。

变体矩阵:
- A: 基线(无Modifier)
- B: NorthboundModifier(保守: 70%/50%)
- C: NorthboundModifier(激进: 50%/30%, 阈值-0.3)
- D: RegimeModifier(risk_off=0.3)
- E: RegimeModifier + NorthboundModifier(激进)双层
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

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import pandas as pd
from engines.backtest_engine import (
    BacktestConfig,
    PMSConfig,
    run_composite_backtest,
    run_hybrid_backtest,
)
from engines.metrics import calc_max_drawdown, calc_sharpe, calc_sortino, deflated_sharpe_ratio
from engines.modifiers.northbound_modifier import NorthboundModifier
from engines.modifiers.regime_modifier import RegimeModifier
from engines.slippage_model import SlippageConfig

from app.services.price_utils import _get_sync_conn


def load_data(conn, start, end):
    factor_df = pd.read_sql(
        """SELECT code, trade_date, factor_name, neutral_value as raw_value
           FROM factor_values
           WHERE factor_name IN ('turnover_mean_20','volatility_20','reversal_20','amihud_20','bp_ratio')
             AND trade_date BETWEEN %s AND %s""",
        conn,
        params=(start, end),
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


def calc_metrics(result):
    nav = result.daily_nav
    ret = result.daily_returns
    sharpe = calc_sharpe(ret)
    mdd = calc_max_drawdown(nav) * 100
    sortino = calc_sortino(ret)
    ann_ret = float((nav.iloc[-1] / nav.iloc[0]) ** (252 / len(ret)) - 1) * 100
    T = len(ret)
    skew = float(ret.skew()) if T > 10 else 0.0
    kurt = float(ret.kurtosis() + 3) if T > 10 else 3.0
    dsr = deflated_sharpe_ratio(sharpe, 69, T, skew, kurt)
    return {
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd, 2),
        "sortino": round(sortino, 2),
        "ann_ret": round(ann_ret, 2),
        "dsr": round(dsr, 4),
    }


def main():
    conn = _get_sync_conn()
    start, end = date(2021, 1, 1), date(2025, 12, 31)

    print("=" * 70)
    print("MDD优化: 双层Modifier回撤控制测试")
    print("=" * 70)

    print("\n[1/3] 加载数据...")
    t0 = time.time()
    factor_df, price_data, benchmark = load_data(conn, start, end)
    print("  因子: %d行, 价格: %d行 (%ds)" % (len(factor_df), len(price_data), time.time() - t0))

    directions = {
        "turnover_mean_20": -1,
        "volatility_20": -1,
        "reversal_20": 1,
        "amihud_20": 1,
        "bp_ratio": 1,
    }
    config = BacktestConfig(
        initial_capital=1_000_000,
        top_n=20,
        rebalance_freq="monthly",
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
        historical_stamp_tax=True,
        pms=PMSConfig(enabled=True, exec_mode="same_close"),
    )

    variants = [
        ("A: 基线(无Modifier)", []),
        ("B: NB保守(70%/50%)", [NorthboundModifier({"scale_negative": 0.7, "scale_panic": 0.5})]),
        (
            "C: NB激进(50%/30%,阈值-0.3)",
            [
                NorthboundModifier(
                    {
                        "scale_negative": 0.5,
                        "scale_panic": 0.3,
                        "negative_threshold": -0.3,
                        "panic_threshold": -1.5,
                    }
                )
            ],
        ),
        (
            "D: Regime(risk_off=0.3)",
            [RegimeModifier({"scale_risk_on": 1.0, "scale_neutral": 0.7, "scale_risk_off": 0.3})],
        ),
        (
            "E: Regime+NB激进(双层)",
            [
                RegimeModifier({"scale_risk_on": 1.0, "scale_neutral": 0.7, "scale_risk_off": 0.3}),
                NorthboundModifier(
                    {
                        "scale_negative": 0.5,
                        "scale_panic": 0.3,
                        "negative_threshold": -0.3,
                        "panic_threshold": -1.5,
                    }
                ),
            ],
        ),
    ]

    print("\n[2/3] 运行%d个变体..." % len(variants))
    print("\n  %-35s %8s %8s %8s %8s %8s" % ("变体", "Sharpe", "MDD%", "Sortino", "年化%", "DSR"))
    print("  " + "-" * 73)

    results = {}
    for label, modifiers in variants:
        t1 = time.time()
        if modifiers:
            result = run_composite_backtest(
                factor_df,
                directions,
                price_data,
                config,
                modifiers=modifiers,
                benchmark_data=benchmark,
                conn=conn,
            )
        else:
            result = run_hybrid_backtest(factor_df, directions, price_data, config, benchmark)
        m = calc_metrics(result)
        elapsed = time.time() - t1
        print(
            "  %-35s %8.3f %8.2f %8.2f %8.2f %8.4f (%ds)"
            % (label, m["sharpe"], m["mdd"], m["sortino"], m["ann_ret"], m["dsr"], elapsed)
        )
        results[label] = m

    # 对比
    print("\n[3/3] 对比分析")
    print("=" * 70)
    base = results["A: 基线(无Modifier)"]
    for label, m in results.items():
        if label.startswith("A:"):
            continue
        mdd_improve = base["mdd"] - m["mdd"]  # 正=改善(MDD是负数,减少绝对值)
        sharpe_cost = m["sharpe"] - base["sharpe"]
        print(
            "  %-35s MDD改善%+.1fpp  Sharpe%+.3f  效率=%.2f"
            % (label, mdd_improve, sharpe_cost, mdd_improve / max(abs(sharpe_cost), 0.001))
        )

    # 判定
    best = min(results.items(), key=lambda x: -x[1]["mdd"] if x[1]["sharpe"] > 0.5 else 999)
    print("\n  最优(Sharpe>0.5前提下MDD最小): %s" % best[0])
    print("  Sharpe=%.3f MDD=%.2f%%" % (best[1]["sharpe"], best[1]["mdd"]))
    if best[1]["mdd"] > -25:
        print("  ✅ MDD < 25% 目标达成")
    elif best[1]["mdd"] > -35:
        print("  🟡 MDD < 35% 可接受")
    else:
        print("  ⚠️ MDD > 35% 仍需进一步优化")
    print("=" * 70)

    conn.close()


if __name__ == "__main__":
    main()
