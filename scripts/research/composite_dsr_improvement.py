#!/usr/bin/env python3
"""Step 3: Composite回测DSR改善验证。

变体对比:
- A(基线): 5因子等权, 无Modifier
- B: 5因子等权 + NorthboundModifier
- 每个变体输出Sharpe/DSR/MDD/子期间

验证: B的DSR是否优于A(方向正确)
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

import pandas as pd
from engines.backtest_engine import (
    BacktestConfig,
    PMSConfig,
    run_composite_backtest,
    run_hybrid_backtest,
)
from engines.metrics import generate_report
from engines.modifiers.northbound_modifier import NorthboundModifier
from engines.slippage_model import SlippageConfig

from app.services.price_utils import _get_sync_conn


def load_data(conn, start, end):
    """加载因子+价格+基准数据。"""
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


def main():
    conn = _get_sync_conn()
    start, end = date(2021, 1, 1), date(2025, 12, 31)

    print("=" * 70)
    print("Composite回测DSR改善验证")
    print("=" * 70)

    # 加载数据
    print("\n[1/3] 加载数据...")
    t0 = time.time()
    factor_df, price_data, benchmark = load_data(conn, start, end)
    print(
        "  因子: %d行, 价格: %d行 (%ds)"
        % (len(factor_df), len(price_data), time.time() - t0)
    )

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

    # A: 基线
    print("\n[2/3] 运行回测...")
    print("\n--- 变体A: 基线(5因子等权, 无Modifier) ---")
    t1 = time.time()
    result_a = run_hybrid_backtest(
        factor_df, directions, price_data, config, benchmark,
    )
    report_a = generate_report(result_a, price_data, num_trials=69)
    print("  Sharpe=%.3f DSR=%.4f MDD=%.2f%% (%ds)"
          % (report_a.sharpe_ratio, report_a.deflated_sharpe,
             report_a.max_drawdown, time.time() - t1))

    # B: + NorthboundModifier
    print("\n--- 变体B: 5因子 + NorthboundModifier ---")
    t2 = time.time()
    nb_modifier = NorthboundModifier({"scale_negative": 0.7, "scale_panic": 0.5})
    result_b = run_composite_backtest(
        factor_df, directions, price_data, config,
        modifiers=[nb_modifier],
        benchmark_data=benchmark,
        conn=conn,
    )
    report_b = generate_report(result_b, price_data, num_trials=69)
    print("  Sharpe=%.3f DSR=%.4f MDD=%.2f%% (%ds)"
          % (report_b.sharpe_ratio, report_b.deflated_sharpe,
             report_b.max_drawdown, time.time() - t2))

    # 对比
    print("\n[3/3] 对比")
    print("=" * 70)
    print("  %-30s %10s %10s" % ("指标", "A(基线)", "B(+NB Mod)"))
    print("  " + "-" * 52)
    print("  %-30s %10.3f %10.3f" % ("Sharpe", report_a.sharpe_ratio, report_b.sharpe_ratio))
    print("  %-30s %10.4f %10.4f" % ("DSR (M=69)", report_a.deflated_sharpe, report_b.deflated_sharpe))
    print("  %-30s %10.2f%% %9.2f%%" % ("MDD", report_a.max_drawdown, report_b.max_drawdown))
    print("  %-30s %10.2f %10.2f" % ("Calmar", report_a.calmar_ratio, report_b.calmar_ratio))
    print("  %-30s %10.2f %10.2f" % ("Sortino", report_a.sortino_ratio, report_b.sortino_ratio))
    print("  %-30s %10.2f%% %9.2f%%" % ("年化收益", report_a.annual_return, report_b.annual_return))
    print("  %-30s %10d %10d" % ("交易次数", report_a.total_trades, report_b.total_trades))

    # DSR改善判定
    sharpe_improved = report_b.sharpe_ratio > report_a.sharpe_ratio
    mdd_improved = report_b.max_drawdown > report_a.max_drawdown  # MDD是负数，更大=更好

    print("\n  判定:")
    if sharpe_improved:
        print("  ✅ Sharpe改善: %.3f → %.3f (+%.3f)"
              % (report_a.sharpe_ratio, report_b.sharpe_ratio,
                 report_b.sharpe_ratio - report_a.sharpe_ratio))
    else:
        print("  ⚠️ Sharpe未改善: %.3f → %.3f"
              % (report_a.sharpe_ratio, report_b.sharpe_ratio))

    if mdd_improved:
        print("  ✅ MDD改善: %.2f%% → %.2f%%"
              % (report_a.max_drawdown, report_b.max_drawdown))
    else:
        print("  ⚠️ MDD未改善: %.2f%% → %.2f%%"
              % (report_a.max_drawdown, report_b.max_drawdown))

    print("=" * 70)
    conn.close()


if __name__ == "__main__":
    main()
