#!/usr/bin/env python3
"""回测运行脚本 — 端到端因子→信号→回测→报告。

用法:
    # YAML配置驱动(推荐):
    python scripts/run_backtest.py --config configs/backtest_5yr.yaml
    python scripts/run_backtest.py --config configs/backtest_12yr.yaml

    # 传统参数(向后兼容):
    python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31
    python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31 --top-n 30
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_factor_values(trade_date, conn) -> pd.DataFrame:
    """加载单日因子值。"""
    return pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values WHERE trade_date = %s""",
        conn,
        params=(trade_date,),
    )


def load_universe(trade_date, conn, min_avg_amount: float = 0.0) -> set[str]:
    """加载Universe（排除ST/新股/停牌/低流动性）。

    调用方: run_paper_trading.py Step 3
    """
    df = pd.read_sql(
        """SELECT DISTINCT code FROM klines_daily
           WHERE trade_date = %s AND volume > 0""",
        conn,
        params=(trade_date,),
    )
    codes = set(df["code"].tolist())
    if min_avg_amount > 0:
        df2 = pd.read_sql(
            """SELECT code, AVG(amount) as avg_amount
               FROM klines_daily
               WHERE trade_date <= %s
               GROUP BY code
               HAVING AVG(amount) >= %s""",
            conn,
            params=(trade_date, min_avg_amount),
        )
        codes &= set(df2["code"].tolist())
    return codes


def load_industry(conn) -> pd.Series:
    """加载行业分类。"""
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE industry_sw1 IS NOT NULL",
        conn,
    )
    return df.set_index("code")["industry_sw1"]


def load_price_data(start_date, end_date, conn) -> pd.DataFrame:
    """加载回测价格数据(含adj_close/is_st/board)。"""
    return pd.read_sql(
        """WITH latest_af AS (
               SELECT DISTINCT ON (code) code, adj_factor AS latest_adj_factor
               FROM klines_daily WHERE adj_factor IS NOT NULL AND adj_factor > 0
               ORDER BY code, trade_date DESC
           )
           SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit,
                  COALESCE(k.adj_factor, 1.0) AS adj_factor,
                  CASE WHEN laf.latest_adj_factor > 0
                       THEN k.close * COALESCE(k.adj_factor, 1.0) / laf.latest_adj_factor
                       ELSE k.close END AS adj_close,
                  db.turnover_rate,
                  COALESCE(ss.is_st, FALSE) AS is_st,
                  COALESCE(ss.is_suspended, FALSE) AS is_suspended,
                  COALESCE(ss.is_new_stock, FALSE) AS is_new_stock,
                  ss.board
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           LEFT JOIN latest_af laf ON k.code = laf.code
           LEFT JOIN stock_status_daily ss ON k.code = ss.code AND k.trade_date = ss.trade_date
           WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(start_date, end_date),
    )


def load_benchmark(start_date, end_date, conn) -> pd.DataFrame:
    """加载基准数据(CSI300)。"""
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


def run_with_yaml(config_path: str):
    """YAML配置驱动的回测(推荐路径)。"""
    from engines.backtest.runner import run_hybrid_backtest
    from engines.metrics import generate_report, print_report

    from app.services.config_loader import (
        config_hash,
        get_data_range,
        get_directions,
        load_config,
        to_backtest_config,
    )

    cfg = load_config(config_path)
    bt_config = to_backtest_config(cfg)
    directions = get_directions(cfg)
    start_str, end_str = get_data_range(cfg)
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()
    c_hash = config_hash(cfg)

    logger.info(
        "Config: %s (hash=%s), %s~%s, top_n=%d, %d factors",
        Path(config_path).name,
        c_hash,
        start,
        end,
        bt_config.top_n,
        len(directions),
    )

    t0 = time.time()

    # 加载数据: Parquet缓存优先, DB回退
    from data.parquet_cache import BacktestDataCache

    cache = BacktestDataCache()
    if cache.is_valid(start, end):
        logger.info("从Parquet缓存加载数据...")
        data = cache.load(start, end)
        factor_df = data["factor_data"]
        price_data = data["price_data"]
        benchmark = data["benchmark"]
        logger.info(
            "缓存加载: factor=%d行, price=%d行, benchmark=%d行 (%.1fs)",
            len(factor_df), len(price_data), len(benchmark), time.time() - t0,
        )
    else:
        logger.info("缓存不可用, 从DB加载...")
        conn = _get_sync_conn()
        factor_df = pd.read_sql(
            """SELECT code, trade_date, factor_name,
                      COALESCE(neutral_value, raw_value) as raw_value
               FROM factor_values
               WHERE factor_name IN %s AND trade_date BETWEEN %s AND %s""",
            conn,
            params=(tuple(directions.keys()), start, end),
        )
        price_data = load_price_data(start, end, conn)
        benchmark = load_benchmark(start, end, conn)
        conn.close()
        logger.info(
            "DB加载: factor=%d行, price=%d行, benchmark=%d行 (%.0fs)",
            len(factor_df), len(price_data), len(benchmark), time.time() - t0,
        )

    # 运行回测(统一信号路径)
    logger.info("运行回测...")
    t1 = time.time()
    result = run_hybrid_backtest(
        factor_df, directions, price_data, bt_config, benchmark,
    )

    # 报告
    report = generate_report(result, price_data)
    print_report(report)

    elapsed = time.time() - t0
    logger.info("回测完成, 总耗时 %.0fs (信号+执行 %.0fs)", elapsed, time.time() - t1)


def run_with_args(args):
    """传统参数驱动的回测(向后兼容)。"""
    from engines.backtest.config import BacktestConfig, PMSConfig
    from engines.backtest.engine import SimpleBacktester
    from engines.config_guard import assert_baseline_config, print_config_header
    from engines.metrics import generate_report, print_report
    from engines.signal_engine import (
        PAPER_TRADING_CONFIG,
        PortfolioBuilder,
        SignalComposer,
        SignalConfig,
        get_rebalance_dates,
    )
    from engines.slippage_model import SlippageConfig

    print_config_header()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    conn = _get_sync_conn()
    t0 = time.time()

    sig_config = SignalConfig(
        factor_names=PAPER_TRADING_CONFIG.factor_names,
        top_n=args.top_n,
        rebalance_freq=args.freq,
        weight_method=args.weight_method,
    )
    assert_baseline_config(sig_config.factor_names, config_source="run_backtest.py")
    need_vol = args.weight_method in ("risk_parity", "min_variance")

    pms_cfg = PMSConfig(enabled=False)
    if args.pms == "tiered":
        pms_cfg = PMSConfig(enabled=True, exec_mode="next_open")
    elif args.pms == "tiered_close":
        pms_cfg = PMSConfig(enabled=True, exec_mode="same_close")

    bt_config = BacktestConfig(
        initial_capital=args.capital,
        top_n=args.top_n,
        rebalance_freq=args.freq,
        slippage_bps=args.slippage,
        slippage_mode=args.slippage_mode,
        slippage_config=SlippageConfig(),
        pms=pms_cfg,
    )

    rebalance_dates = get_rebalance_dates(start, end, freq=args.freq, conn=conn)
    logger.info("调仓日: %d个", len(rebalance_dates))

    industry = load_industry(conn)
    vol_regime_scale = 1.0
    csi300_closes = None
    if args.vol_regime:
        from engines.vol_regime import calc_vol_regime

        csi300_df = load_benchmark(start, end, conn)
        csi300_closes = csi300_df.set_index("trade_date")["close"]

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)
    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        vol_map = None
        if need_vol:
            vol_df = pd.read_sql(
                "SELECT code, raw_value FROM factor_values "
                "WHERE trade_date = %s AND factor_name = %s",
                conn,
                params=(rd, args.vol_factor),
            )
            vol_map = dict(zip(vol_df["code"], vol_df["raw_value"].astype(float), strict=False))

        if args.vol_regime and csi300_closes is not None:
            closes_up_to = csi300_closes[csi300_closes.index <= rd]
            if len(closes_up_to) >= 21:
                vol_regime_scale = calc_vol_regime(closes_up_to)

        target = builder.build(scores, industry, prev_weights, vol_regime_scale=vol_regime_scale, volatility_map=vol_map)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 20 == 0:
            logger.info("  信号 [%d/%d] %s: %d只", i + 1, len(rebalance_dates), rd, len(target))

    logger.info("信号完成: %d个调仓日", len(target_portfolios))

    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    report = generate_report(result, price_data)
    print_report(report)

    logger.info("回测完成, 总耗时 %.0fs", time.time() - t0)
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="QuantMind V2 回测")
    parser.add_argument("--config", type=str, help="YAML配置文件路径(推荐)")
    parser.add_argument("--start", type=str, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--freq", choices=["weekly", "biweekly", "monthly"], default="monthly")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--slippage", type=float, default=10.0)
    parser.add_argument("--slippage-mode", choices=["volume_impact", "fixed"], default="volume_impact")
    parser.add_argument("--weight-method", choices=["equal", "risk_parity", "min_variance"], default="equal")
    parser.add_argument("--vol-regime", action="store_true")
    parser.add_argument("--vol-factor", default="volatility_20")
    parser.add_argument("--pms", choices=["off", "tiered", "tiered_close"], default="off")
    args = parser.parse_args()

    if args.config:
        run_with_yaml(args.config)
    elif args.start and args.end:
        run_with_args(args)
    else:
        parser.error("需要 --config 或 --start + --end")


if __name__ == "__main__":
    main()
