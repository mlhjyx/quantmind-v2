#!/usr/bin/env python3
"""Phase 1修复隔离验证 — 逐项开关，量化每项贡献。

验证矩阵:
- A: 固定税率0.05% + gap_penalty=0  → 应≈旧基线1.24
- B: 历史税率       + gap_penalty=0  → 隔离P3
- C: 固定税率0.05% + gap_penalty=0.5 → 隔离P5
- D: 历史税率       + gap_penalty=0.5 → 应≈新基线0.94
- 加法性: (A-B)+(A-C) ≈ (A-D)
"""

import os
import sys
import time
from datetime import date
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import logging

logging.disable(logging.DEBUG)  # 抑制structlog debug输出

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger, logger_factory=structlog.stdlib.LoggerFactory()
)
logging.getLogger().setLevel(logging.WARNING)

import pandas as pd
from engines.backtest_engine import BacktestConfig, PMSConfig, SimpleBacktester
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from engines.slippage_model import SlippageConfig

from app.services.price_utils import _get_sync_conn


def load_factor_values(td, conn):
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
        conn,
        params=(td,),
    )


def load_universe(td, conn):
    return set(
        pd.read_sql(
            """SELECT k.code FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           LEFT JOIN LATERAL (
               SELECT AVG(amount) AS avg_amount_20d FROM klines_daily k2
               WHERE k2.code = k.code AND k2.trade_date <= %s
                 AND k2.trade_date >= %s - INTERVAL '30 days' AND k2.volume > 0
           ) amt ON TRUE
           WHERE k.trade_date = %s AND k.volume > 0 AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000
             AND COALESCE(amt.avg_amount_20d, 0) >= 0""",
            conn,
            params=(td, td, td, td),
        )["code"].tolist()
    )


def load_industry(conn):
    df = pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'", conn)
    return df.set_index("code")["industry_sw1"].fillna("其他")


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


def load_benchmark(start, end, conn):
    return pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start, end),
    )


def calc_sharpe(result):
    """从BacktestResult计算Sharpe/年化/MDD."""
    nav = result.daily_nav
    ret = nav.pct_change().dropna()
    ann_ret = (nav.iloc[-1] / nav.iloc[0]) ** (252 / len(ret)) - 1
    ann_vol = ret.std() * (252**0.5)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    mdd = ((nav.cummax() - nav) / nav.cummax()).max()
    return sharpe, ann_ret, mdd


def main():
    conn = _get_sync_conn()
    start, end = date(2021, 1, 1), date(2025, 12, 31)

    print("=" * 70)
    print("Phase 1 隔离验证: 逐项开关量化贡献")
    print("=" * 70)

    # 1. 信号(所有变体共享)
    print("\n[1/5] 生成信号...")
    t0 = time.time()
    sig_config = SignalConfig(
        factor_names=PAPER_TRADING_CONFIG.factor_names,
        top_n=20,
        rebalance_freq="monthly",
        weight_method="equal",
    )
    rebal_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    industry = load_industry(conn)
    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)
    target_portfolios = {}
    prev_weights = {}
    for rd in rebal_dates:
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
    print(f"  {len(target_portfolios)}个调仓日, {time.time() - t0:.0f}s")

    # 2. 数据(所有变体共享)
    print("[2/5] 加载数据...")
    price_data = load_price_data(start, end, conn)
    benchmark = load_benchmark(start, end, conn)
    print(f"  价格: {len(price_data)}行")

    # 3. 四组对比
    print("\n[3/5] 运行4组隔离测试...\n")
    variants = [
        ("A(旧:固定税+无gap)", False, 0.0),
        ("B(P3:历史税+无gap)", True, 0.0),
        ("C(P5:固定税+gap)", False, 0.5),
        ("D(新:历史税+gap)", True, 0.5),
    ]
    results = {}
    for label, hist_tax, gap_factor in variants:
        t1 = time.time()
        cfg = SlippageConfig(gap_penalty_factor=gap_factor)
        bt = BacktestConfig(
            initial_capital=1_000_000,
            top_n=20,
            rebalance_freq="monthly",
            slippage_mode="volume_impact",
            slippage_config=cfg,
            historical_stamp_tax=hist_tax,
            pms=PMSConfig(enabled=True, exec_mode="same_close"),
        )
        tester = SimpleBacktester(bt)
        result = tester.run(target_portfolios, price_data, benchmark)
        sharpe, ann_ret, mdd = calc_sharpe(result)
        elapsed = time.time() - t1
        print(
            f"  {label:30s}  Sharpe={sharpe:.3f}  年化={ann_ret:.1%}  MDD={-mdd:.1%}  ({elapsed:.0f}s)"
        )
        results[label[:1]] = sharpe

    # 4. 加法性检验
    sa, sb, sc, sd = results["A"], results["B"], results["C"], results["D"]
    p3 = sa - sb
    p5 = sa - sc
    total = sa - sd
    interaction = total - (p3 + p5)

    print("\n[4/5] 贡献分解:")
    print(f"  P3(印花税历史税率)贡献:  Sharpe -{p3:.3f}")
    print(f"  P5(overnight_gap)贡献:   Sharpe -{p5:.3f}")
    print(f"  各项之和:                Sharpe -{p3 + p5:.3f}")
    print(f"  实际总降幅:              Sharpe -{total:.3f}")
    print(
        f"  交互效应:                {interaction:+.3f} "
        f"({'可忽略(<0.05)' if abs(interaction) < 0.05 else '⚠️ 显著(>0.05)'})"
    )

    print("\n[5/5] 结论:")
    if abs(sa - 1.24) < 0.10:
        print(f"  ✅ A(旧基线)={sa:.3f} ≈ 1.24, 复现成功")
    else:
        print(f"  ⚠️ A(旧基线)={sa:.3f} vs 1.24, 差异{abs(sa - 1.24):.3f}需排查")
    if abs(sd - 0.94) < 0.05:
        print(f"  ✅ D(新基线)={sd:.3f} ≈ 0.94, 复现成功")
    else:
        print(f"  ⚠️ D(新基线)={sd:.3f} vs 0.94, 差异{abs(sd - 0.94):.3f}需排查")
    if abs(interaction) < 0.05:
        print(f"  ✅ 加法性成立, 交互效应={interaction:+.3f}")
    else:
        print(f"  ⚠️ 加法性不成立, 交互效应={interaction:+.3f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
