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
from datetime import date, datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

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


def load_universe(trade_date: date, conn, min_avg_amount: float = 0.0) -> set[str]:
    """加载 Universe（排除 ST/新股/停牌/BJ/退市/低流动性）。

    Step 6-C 修复: 之前只过滤 volume>0, 导致 BJ 股全部进入信号。
    现在正确 JOIN stock_status_daily + symbols 做完整过滤。

    PR-B 修复 (2026-04-20, ADR-008 阶段 2, 关闭 Session 10 P0-ε):
      根因: 2026-04-14 "fix" 用 INNER JOIN + status_date 回退 →
            status_date lag 时 (live PT 16:30 预检失败, pt_data_service 未及时
            入 stock_status_daily), 用旧状态过滤. 688184.SH 4-14 已是 ST 但
            status_date=4-13 记录 is_st=false → 错买 → 4-15 更新后错卖.
      修法: LEFT JOIN + ss.trade_date = k.trade_date (correlated 实际日) +
            COALESCE(is_st/is_suspended/is_new_stock, TRUE) = false
            (缺记录保守当 ST/停牌/新股排除, 铁律 33 fail-safe 精神).
      backward compat: historical backtest status_date==trade_date,
            语义完全等价 → regression max_diff=0 保持.
      移除: 原 status_date 预计算 + 回退 + warning log 已删 (3 reviewer 一致 P1:
            新 COALESCE(TRUE) 保守排除已完全守门, 原 status_date 查询是 dead
            code + misleading warning. live 路径 stock_status_daily 未入
            当日行时, LEFT JOIN 使所有 code 被 COALESCE 排除 → universe 空
            → 下游信号失败 (铁律 33 fail-loud, 优于 silent lag bug).

    调用方: run_paper_trading.py Step 3
    """
    df = pd.read_sql(
        """SELECT DISTINCT k.code
           FROM klines_daily k
           LEFT JOIN stock_status_daily ss
             ON k.code = ss.code AND ss.trade_date = k.trade_date
           LEFT JOIN symbols s ON k.code = s.code
           WHERE k.trade_date = %s
             AND k.volume > 0
             AND COALESCE(ss.is_st, TRUE) = false
             AND COALESCE(ss.is_suspended, TRUE) = false
             AND COALESCE(ss.is_new_stock, TRUE) = false
             AND COALESCE(ss.board, '') != 'bse'
             AND k.code NOT LIKE '%%.BJ'
             AND COALESCE(s.list_status, 'L') = 'L'""",
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
    """加载行业分类(SW1一级29组)。"""
    from app.services.industry_utils import apply_sw2_to_sw1

    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE industry_sw1 IS NOT NULL",
        conn,
    )
    sw2_series = df.set_index("code")["industry_sw1"]
    return apply_sw2_to_sw1(sw2_series, conn)


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
    """YAML配置驱动的回测 — MVP 2.3 Sub1 PR C3 迁 Platform SDK.

    走 PlatformBacktestRunner + InMemoryBacktestRegistry + LIVE_PT mode (ad-hoc
    场景借 LIVE_PT 不 override start/end + 不 cache 语义, Sub3 真 LIVE_PT 实现评估新
    AD_HOC mode 替代).

    数据加载: closure cache 优先 + DB fallback (保原 run_with_yaml 行为).
    Engine/Signal config: 走 builder callable 注入 Runner 完整 YAML 14+8 字段
    (消除 PR B SN=0 bug + PMS 失效 bug — Runner fallback 只映 5 字段).
    消费者从 `result.engine_artifacts` 取 engine_result / price_data 走 generate_report.

    关联铁律 15 (config_hash 复现) / 16 (信号路径唯一 SignalComposer) / 34 (配置 SSOT YAML).
    """
    from engines.metrics import generate_report, print_report

    from app.services.config_loader import (
        config_hash,
        get_data_range,
        get_directions,
        load_config,
        to_backtest_config,
        to_signal_config,
    )
    from backend.qm_platform._types import BacktestMode
    from backend.qm_platform.backtest import BacktestConfig as PlatformCfg
    from backend.qm_platform.backtest import InMemoryBacktestRegistry
    from backend.qm_platform.backtest.runner import PlatformBacktestRunner

    cfg = load_config(config_path)
    # Engine BacktestConfig / SignalConfig 从 YAML 全字段构造 (14/8 字段), 走 builder 注入
    # Runner → 避绕 PR B fallback 只映 5 字段导致 SN=0 + PMS 失效 bug.
    bt_config_engine = to_backtest_config(cfg)
    sig_config = to_signal_config(cfg)
    directions = get_directions(cfg)
    # PR C3 review L1 fix: empty directions 早暴露 (pre-existing 问题被迁移顺便修)
    if not directions:
        raise ValueError(
            f"YAML 配置 {config_path} strategy.factors 为空 — 无因子无法跑回测. "
            f"检查 YAML `strategy.factors` 列表非空."
        )
    start_str, end_str = get_data_range(cfg)
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_str, "%Y-%m-%d").date()
    c_hash = config_hash(cfg)

    logger.info(
        "Config: %s (hash=%s), %s~%s, top_n=%d, %d factors [Platform SDK]",
        Path(config_path).name,
        c_hash,
        start,
        end,
        bt_config_engine.top_n,
        len(directions),
    )

    t0 = time.time()

    # 数据加载 closure: cache 优先, DB fallback — 作为 Runner.data_loader 注入.
    # PR C1 BacktestCacheLoader 对 invalid cache 直接 raise, 不匹配本场景 "cache miss → DB"
    # 回退策略, 因此本处用 closure 显式组合 (单次使用, 不值新建通用 loader 类).
    def _cache_or_db_loader(_platform_cfg, _start, _end):
        from data.parquet_cache import BacktestDataCache

        cache = BacktestDataCache()
        if cache.is_valid(_start, _end):
            logger.info("从Parquet缓存加载数据...")
            data = cache.load(_start, _end)
            factor_df = data["factor_data"]
            price_data = data["price_data"]
            benchmark = data.get("benchmark")  # 可选 (老 parquet 可能无)
            logger.info(
                "缓存加载: factor=%d行, price=%d行, benchmark=%s",
                len(factor_df),
                len(price_data),
                f"{len(benchmark)}行" if benchmark is not None else "无",
            )
            return factor_df, price_data, benchmark

        logger.info("缓存不可用, 从DB加载...")
        _conn = _get_sync_conn()
        try:
            factor_df = pd.read_sql(
                """SELECT code, trade_date, factor_name,
                          COALESCE(neutral_value, raw_value) as raw_value
                   FROM factor_values
                   WHERE factor_name IN %s AND trade_date BETWEEN %s AND %s""",
                _conn,
                params=(tuple(directions.keys()), _start, _end),
            )
            price_data = load_price_data(_start, _end, _conn)
            benchmark = load_benchmark(_start, _end, _conn)
            logger.info(
                "DB加载: factor=%d行, price=%d行, benchmark=%d行",
                len(factor_df),
                len(price_data),
                len(benchmark),
            )
            return factor_df, price_data, benchmark
        finally:
            _conn.close()

    # Runner conn: engine 内 size_neutral 加载 ln_mcap pivot 要 DB. 独立于 loader closure
    # (后者 DB fallback 用完就 close, 生命周期不重叠, 共享会 cursor 争用). PR C3 review M4
    # 显式注释: 未来 refactor 不要误合为一 (双调用者重叠生命周期不安全).
    runner_conn = _get_sync_conn()
    try:
        # Platform BacktestConfig — 核心字段对齐 PR B 设计, 完整 Engine/Signal config 走 builder
        strategy_cfg = cfg.get("strategy", {})
        backtest_cfg = cfg.get("backtest", {})
        execution_cfg = cfg.get("execution", {})
        stamp_tax_mode = execution_cfg.get("costs", {}).get("stamp_tax", "historical")

        platform_cfg = PlatformCfg(
            start=start,
            end=end,
            universe="all_a",  # YAML universe 节是排除开关集, 非 universe 名, 给 Platform placeholder
            factor_pool=tuple(directions.keys()),
            rebalance_freq=strategy_cfg.get("rebalance_freq", "monthly"),
            top_n=int(strategy_cfg.get("top_n", 20)),
            industry_cap=float(strategy_cfg.get("industry_cap", 1.0)),
            size_neutral_beta=float(strategy_cfg.get("size_neutral_beta", 0.0)),
            cost_model="full" if stamp_tax_mode == "historical" else "simplified",
            capital=str(backtest_cfg.get("initial_capital", 1_000_000)),
            benchmark="csi300"
            if backtest_cfg.get("benchmark") == "000300.SH"
            else "none",
            extra={},
        )

        runner = PlatformBacktestRunner(
            registry=InMemoryBacktestRegistry(),
            data_loader=_cache_or_db_loader,
            conn=runner_conn,
            direction_provider=lambda pool: {n: directions[n] for n in pool},
            engine_config_builder=lambda _p: bt_config_engine,  # 完整 14 字段 Engine config
            signal_config_builder=lambda _p: sig_config,  # 完整 8 字段 SignalConfig
        )

        logger.info("运行回测 (Platform SDK)...")
        t1 = time.time()
        # TODO(mvp-2.3-sub3): BacktestMode.AD_HOC 目前未实现, 借 LIVE_PT 语义
        # (不 override config.start/end + 跳过 cache 强制真跑). 配 InMemoryBacktestRegistry
        # get_by_hash 恒 None 双重保真跑. Sub3 真 LIVE_PT 实盘实现时, 评估新 AD_HOC mode
        # 替代借用避免语义混淆.
        result = runner.run(mode=BacktestMode.LIVE_PT, config=platform_cfg)
        t_engine_done = time.time()  # PR C3 review M2 fix: 精准测 engine 耗时, 排除 report

        # PR C2 契约: cache-miss 真跑 → engine_artifacts 必塞; LIVE_PT 强制 always re-run
        # 配 InMemory get_by_hash 恒 None, artifacts 永不为 None.
        if result.engine_artifacts is None:
            raise RuntimeError(
                "engine_artifacts=None — 违反 PR C2 契约 (LIVE_PT always re-run), "
                "Runner 可能未走 cache-miss 路径. 检查 PlatformBacktestRunner.run() 实现."
            )
        engine_result = result.engine_artifacts["engine_result"]
        price_data_for_report = result.engine_artifacts["price_data"]

        report = generate_report(engine_result, price_data_for_report)
        print_report(report)

        elapsed = time.time() - t0
        logger.info(
            "回测完成, 总耗时 %.0fs (信号+执行 %.0fs, 报告 %.0fs)",
            elapsed,
            t_engine_done - t1,  # 纯 engine 时间 (不含 generate_report + print_report)
            time.time() - t_engine_done,
        )
    finally:
        runner_conn.close()


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
