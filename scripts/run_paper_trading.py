#!/usr/bin/env python3
"""Paper Trading 两阶段管道 — V2: Service层架构。

业务逻辑已迁移至Service层，本脚本仅为薄壳调度入口。

Phase 1 — signal（T日 16:30 cron触发）:
  Step 0: 健康预检
  Step 1: 拉取T日行情数据
  Step 1.5: 用T日收盘价更新NAV + position_snapshot + performance_series
  Step 2: 计算T日因子
  Step 3: 生成信号 + Beta对冲 → 存signals表
  Step 3.5: 影子选股（LightGBM Raw + Inertia）
  Step 4: 通知（调仓预告 + PT日报）

Phase 2 — execute（T+1日触发）:
  调度: miniQMT模式→09:00 / SimBroker(paper)模式→17:05(收盘数据可用后)
  09:00无数据时SimBroker模式正常退出(exit 0)，不报错
  Step 5: 读取昨日信号
  Step 5.5: 拉取T+1数据
  Step 5.9: 熔断检查
  Step 5.95: 延迟调仓恢复
  Step 5.96: 封板补单
  Step 6: 执行调仓
  Step 7: 保存成交记录
  Step 8: 通知（执行确认）

用法:
    python scripts/run_paper_trading.py signal --date 2026-03-21
    python scripts/run_paper_trading.py execute --date 2026-03-24
    python scripts/run_paper_trading.py signal --date 2026-03-21 --dry-run
"""

import argparse
import json
import logging
import os
import sys
import time
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Windows UTF-8 输出修复（兼容Git Bash管道模式）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib

import pandas as pd
from engines.factor_engine import compute_daily_factors, save_daily_factors
from engines.paper_broker import PaperBroker
from engines.signal_engine import PAPER_TRADING_CONFIG
from health_check import run_health_check
from run_backtest import load_factor_values, load_industry, load_universe

from app.config import settings
from app.services.db import get_sync_conn
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.risk_control_service import check_circuit_breaker_sync
from app.services.signal_service import SignalService
from app.services.trading_calendar import (
    acquire_lock,
    get_next_trading_day,
    get_prev_trading_day,
    is_trading_day,
)

# ── 日志配置 ──
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_log_handlers = [
    logging.FileHandler(LOG_DIR / "paper_trading.log", encoding="utf-8"),
]
if sys.stdout and not getattr(sys.stdout, "closed", True) and sys.stderr and not getattr(sys.stderr, "closed", True):
    with contextlib.suppress(Exception):
        _log_handlers.insert(0, logging.StreamHandler(sys.stderr))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
    force=True,  # 确保覆盖structlog的root handler配置
)
logger = logging.getLogger("paper_trading")


# ════════════════════════════════════════════════════════════
# 共用工具函数（尚未Service化）
# ════════════════════════════════════════════════════════════

def log_step(conn, task_name: str, status: str, error: str = None, result: dict = None):
    """写入scheduler_task_log。"""
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO scheduler_task_log
               (task_name, market, schedule_time, start_time, status,
                error_message, result_json)
               VALUES (%s, 'astock', NOW(), NOW(), %s, %s, %s)""",
            (task_name, status, error, json.dumps(result) if result else None),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"写入scheduler_task_log失败: {e}")
        with contextlib.suppress(Exception):
            conn.rollback()


def load_today_prices(trade_date: date, conn) -> pd.DataFrame:
    """加载当日价格数据。"""
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s AND k.volume > 0
           ORDER BY k.code""",
        conn,
        params=(trade_date,),
    )


def get_benchmark_close(trade_date: date, conn) -> float:
    """获取CSI300当日收盘价。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date = %s""",
        (trade_date,),
    )
    row = cur.fetchone()
    return float(row[0]) if row else 0.0


def _get_notif_service() -> NotificationService:
    """创建NotificationService实例（sync方法不使用async session）。"""
    return NotificationService(session=None)  # type: ignore[arg-type]


def _check_opening_gap(
    exec_date: date,
    price_data: pd.DataFrame,
    conn,
    notif_svc: NotificationService,
    dry_run: bool,
    single_stock_gap_threshold: float = 0.05,
    portfolio_gap_threshold: float = 0.03,
) -> None:
    """开盘跳空预检 — 在execute阶段执行调仓前检测跳空风险。

    用DB数据（klines_daily）计算 open vs pre_close 的偏差。
    PT阶段：只告警，不暂停执行（实盘阶段可升级为暂停）。

    Args:
        exec_date: 执行日（T+1）。
        price_data: load_today_prices()返回的DataFrame，含open/pre_close列。
        conn: psycopg2连接。
        notif_svc: 通知服务。
        dry_run: 不发通知。
        single_stock_gap_threshold: 单股跳空告警阈值（默认5%）。
        portfolio_gap_threshold: 组合加权跳空告警阈值（默认3%）。
    """
    if price_data.empty:
        logger.warning("[Step5.8] 无价格数据，跳过开盘跳空预检")
        return

    # 计算跳空率: (open - pre_close) / pre_close
    df = price_data[["code", "open", "pre_close"]].copy()
    df = df[df["pre_close"] > 0]
    df["gap"] = (df["open"] - df["pre_close"]) / df["pre_close"]

    # ── 单股跳空 >5% 告警（P1）──
    large_gaps = df[df["gap"].abs() > single_stock_gap_threshold].copy()
    large_gaps = large_gaps.sort_values("gap", key=abs, ascending=False)

    if not large_gaps.empty:
        gap_summary = ", ".join(
            f"{row['code']}({row['gap']:+.1%})"
            for _, row in large_gaps.head(5).iterrows()
        )
        msg = (
            f"开盘跳空预警 {exec_date}\n"
            f"单股跳空>5%的股票: {len(large_gaps)}只\n"
            f"Top5: {gap_summary}"
        )
        logger.warning(f"[Step5.8] P1 {msg}")
        if not dry_run:
            notif_svc.send_sync(
                conn, "P1", "risk",
                f"开盘跳空P1 {exec_date}",
                msg,
            )

    # ── 组合加权平均跳空（读当前持仓权重）──
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT code, weight FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = 'paper'
               ORDER BY trade_date DESC, weight DESC
               LIMIT 50""",
            (settings.PAPER_STRATEGY_ID,),
        )
        rows = cur.fetchall()
        if rows:
            weights = {r[0]: float(r[1]) for r in rows}
            total_w = sum(weights.values())
            if total_w > 0:
                # 用当前持仓计算组合加权跳空
                gap_map = df.set_index("code")["gap"].to_dict()
                portfolio_gap = sum(
                    weights.get(code, 0) * gap_map.get(code, 0)
                    for code in weights
                ) / total_w

                logger.info(
                    f"[Step5.8] 组合加权跳空={portfolio_gap:+.2%} "
                    f"(阈值>{portfolio_gap_threshold:.0%}告P0)"
                )

                if abs(portfolio_gap) > portfolio_gap_threshold:
                    msg = (
                        f"组合开盘跳空告警 {exec_date}\n"
                        f"持仓加权平均跳空={portfolio_gap:+.2%}(阈值{portfolio_gap_threshold:.0%})\n"
                        f"PT阶段继续执行，请人工复核"
                    )
                    logger.error(f"[Step5.8] P0 {msg}")
                    if not dry_run:
                        notif_svc.send_sync(
                            conn, "P0", "risk",
                            f"组合跳空P0 {exec_date}",
                            msg,
                        )
                        conn.commit()
    except Exception as e:
        logger.warning(f"[Step5.8] 组合跳空计算失败（不影响执行）: {e}")


# ════════════════════════════════════════════════════════════
# Shadow LightGBM Portfolio (影子选股 — 暂未Service化)
# ════════════════════════════════════════════════════════════

def _ensure_shadow_portfolio_table(conn) -> None:
    """确保shadow_portfolio表存在（幂等）。"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shadow_portfolio (
            id SERIAL PRIMARY KEY,
            strategy_name VARCHAR(50) NOT NULL,
            trade_date DATE NOT NULL,
            rebalance_date DATE NOT NULL,
            symbol_code VARCHAR(10) NOT NULL,
            predicted_score FLOAT,
            weight FLOAT NOT NULL,
            rank_in_portfolio INT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(strategy_name, trade_date, symbol_code)
        );
        CREATE INDEX IF NOT EXISTS idx_shadow_portfolio_date
            ON shadow_portfolio(trade_date);
    """)
    conn.commit()


def _select_fold_model(trade_date: date) -> str:
    """根据trade_date选择对应的fold模型文件。"""
    import numpy as np  # noqa: F401 — kept for shadow functions below

    model_dir = Path(__file__).resolve().parent.parent / "models" / "lgbm_walkforward"
    y, m = trade_date.year, trade_date.month

    if y <= 2022 or y == 2023 and m <= 6:
        fold_id = 1
    elif y == 2023 and m >= 7:
        fold_id = 2
    elif y == 2024 and m <= 6:
        fold_id = 3
    elif y == 2024 and m >= 7:
        fold_id = 4
    elif y == 2025 and m <= 6:
        fold_id = 5
    elif y == 2025 and m >= 7:
        fold_id = 6
    else:
        fold_id = 7

    return str(model_dir / f"fold_{fold_id}.txt")


def _get_lgbm_scored_universe(
    trade_date: date, conn,
) -> tuple[pd.DataFrame | None, int]:
    """LightGBM预测+Universe过滤。"""
    import lightgbm as lgb

    SHADOW_TOP_N = 15
    FEATURE_NAMES = [
        "turnover_mean_20", "volatility_20", "reversal_20",
        "amihud_20", "bp_ratio",
    ]

    model_path = _select_fold_model(trade_date)
    if not Path(model_path).exists():
        logger.warning(f"[SHADOW] 模型文件不存在: {model_path}，跳过")
        return None, SHADOW_TOP_N

    model = lgb.Booster(model_file=model_path)
    logger.info(f"[SHADOW] 加载模型: {model_path}")

    placeholders = ",".join(["%s"] * len(FEATURE_NAMES))
    df_factors = pd.read_sql(
        f"""SELECT code, factor_name, neutral_value
            FROM factor_values
            WHERE trade_date = %s
              AND factor_name IN ({placeholders})
              AND neutral_value IS NOT NULL""",
        conn,
        params=[trade_date] + FEATURE_NAMES,
    )

    if df_factors.empty:
        logger.warning(f"[SHADOW] {trade_date} 无因子数据，跳过")
        return None, SHADOW_TOP_N

    df_wide = df_factors.pivot_table(
        index="code", columns="factor_name", values="neutral_value", aggfunc="first",
    ).reset_index()
    df_wide.columns.name = None

    missing = [f for f in FEATURE_NAMES if f not in df_wide.columns]
    if missing:
        logger.warning(f"[SHADOW] 缺少因子列: {missing}，跳过")
        return None, SHADOW_TOP_N

    logger.info(f"[SHADOW] 因子矩阵: {len(df_wide)}只股票, {len(FEATURE_NAMES)}因子")

    from engines.ml_engine import FeaturePreprocessor
    preprocessor = FeaturePreprocessor()
    preprocessor.fit(df_wide, FEATURE_NAMES)
    df_processed = preprocessor.transform(df_wide)

    X = df_processed[FEATURE_NAMES].values.astype("float32")
    scores = model.predict(X)
    df_processed["predicted_score"] = scores

    universe_df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           WHERE k.trade_date = %s
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'""",
        conn,
        params=(trade_date,),
    )
    universe_codes = set(universe_df["code"])
    df_eligible = df_processed[df_processed["code"].isin(universe_codes)].copy()

    if len(df_eligible) < SHADOW_TOP_N:
        logger.warning(f"[SHADOW] 可选股票不足: {len(df_eligible)} < {SHADOW_TOP_N}，跳过")
        return None, SHADOW_TOP_N

    return df_eligible, SHADOW_TOP_N


def _write_shadow_portfolio(
    df_top: pd.DataFrame, strategy_name: str, trade_date: date,
    top_n: int, conn, dry_run: bool,
) -> None:
    """将Top-N写入shadow_portfolio表。"""
    top_codes = df_top["code"].tolist()
    logger.info(f"[SHADOW] {strategy_name} Top-{top_n}: {','.join(top_codes)}")

    if not dry_run:
        _ensure_shadow_portfolio_table(conn)
        next_td = get_next_trading_day(conn, trade_date)
        rebalance_date = next_td if next_td else trade_date

        cur = conn.cursor()
        for _, row in df_top.iterrows():
            cur.execute(
                """INSERT INTO shadow_portfolio
                       (strategy_name, trade_date, rebalance_date,
                        symbol_code, predicted_score, weight, rank_in_portfolio)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (strategy_name, trade_date, symbol_code)
                   DO UPDATE SET
                       predicted_score = EXCLUDED.predicted_score,
                       weight = EXCLUDED.weight,
                       rank_in_portfolio = EXCLUDED.rank_in_portfolio,
                       rebalance_date = EXCLUDED.rebalance_date,
                       created_at = NOW()""",
                (strategy_name, trade_date, rebalance_date,
                 row["code"], float(row["predicted_score"]),
                 float(row["weight"]), int(row["rank_in_portfolio"])),
            )
        conn.commit()
        logger.info(f"[SHADOW] 写入shadow_portfolio({strategy_name}): {len(df_top)}行")
    else:
        logger.info("[SHADOW] dry-run模式，不写DB")


def generate_shadow_lgbm_signals(trade_date: date, conn, dry_run: bool = False) -> None:
    """影子LightGBM选股（Raw）。"""
    SHADOW_STRATEGY = "lgbm_5feat_default"
    logger.info(f"[SHADOW] 开始Raw LightGBM影子选股 {trade_date}")

    df_eligible, top_n = _get_lgbm_scored_universe(trade_date, conn)
    if df_eligible is None:
        return

    df_top = df_eligible.nlargest(top_n, "predicted_score").copy()
    df_top["rank_in_portfolio"] = range(1, top_n + 1)
    df_top["weight"] = 1.0 / top_n

    _write_shadow_portfolio(df_top, SHADOW_STRATEGY, trade_date, top_n, conn, dry_run)
    logger.info("[SHADOW] Raw LGB影子选股完成")


def generate_shadow_lgbm_inertia(trade_date: date, conn, dry_run: bool = False) -> None:
    """影子LightGBM+Inertia(0.7σ)选股。"""
    import numpy as np

    SHADOW_STRATEGY = "lgbm_inertia_07"
    BONUS_STD = 0.7
    logger.info(f"[SHADOW] 开始Inertia(0.7σ)影子选股 {trade_date}")

    df_eligible, top_n = _get_lgbm_scored_universe(trade_date, conn)
    if df_eligible is None:
        return

    prev_holdings_df = pd.read_sql(
        """SELECT symbol_code FROM shadow_portfolio
           WHERE strategy_name = %s AND trade_date < %s
           ORDER BY trade_date DESC
           LIMIT %s""",
        conn,
        params=(SHADOW_STRATEGY, trade_date, top_n),
    )
    prev_holdings = set(prev_holdings_df["symbol_code"]) if not prev_holdings_df.empty else set()

    if not prev_holdings:
        logger.info("[SHADOW] 无历史持仓，Inertia等同于Raw LGB（首次运行）")
    else:
        logger.info(f"[SHADOW] 上期持仓: {len(prev_holdings)}只 — "
                    f"{','.join(sorted(prev_holdings))}")

    scores = df_eligible["predicted_score"].values.copy()
    cs_std = np.std(scores) if len(scores) > 1 else 1.0
    codes = df_eligible["code"].values
    bonus_count = 0
    for i, code in enumerate(codes):
        if code in prev_holdings:
            scores[i] += BONUS_STD * cs_std
            bonus_count += 1
    df_eligible = df_eligible.copy()
    df_eligible["predicted_score"] = scores

    logger.info(f"[SHADOW] Inertia bonus: {bonus_count}只加分 "
                f"(0.7×σ={BONUS_STD * cs_std:.4f})")

    df_top = df_eligible.nlargest(top_n, "predicted_score").copy()
    df_top["rank_in_portfolio"] = range(1, top_n + 1)
    df_top["weight"] = 1.0 / top_n

    new_holdings = set(df_top["code"])
    if prev_holdings:
        retained = new_holdings & prev_holdings
        turnover = len(new_holdings.symmetric_difference(prev_holdings)) / (2 * top_n)
        logger.info(f"[SHADOW] 换手率: {turnover:.1%}, 留存: {len(retained)}/{top_n}")
    else:
        logger.info("[SHADOW] 首次建仓，换手率: 100%")

    _write_shadow_portfolio(df_top, SHADOW_STRATEGY, trade_date, top_n, conn, dry_run)
    logger.info("[SHADOW] Inertia(0.7σ)影子选股完成")


# ════════════════════════════════════════════════════════════
# Phase 1: SIGNAL — T日盘后 16:30
# ════════════════════════════════════════════════════════════

def run_signal_phase(trade_date: date, dry_run: bool, skip_fetch: bool, skip_factors: bool):
    """T日盘后：拉数据 → 算因子 → 生成信号存库。"""
    logger.info(f"{'='*60}")
    logger.info(f"[SIGNAL PHASE] T日={trade_date}")
    logger.info(f"{'='*60}")

    conn = get_sync_conn()
    t_total = time.time()

    try:
        if not acquire_lock(conn):
            conn.close()
            sys.exit(1)

        if not is_trading_day(conn, trade_date):
            logger.info(f"{trade_date} 非交易日，退出")
            conn.close()
            return

        notif_svc = _get_notif_service()

        # ── Step 0: 健康预检 ──
        logger.info("[Step0] 健康预检...")
        health = run_health_check(trade_date, conn, write_db=not dry_run)
        if not health["all_pass"]:
            logger.error("[Step0] 预检失败，管道停止")
            if not dry_run:
                log_step(conn, "signal_phase", "failed", "健康预检失败")
                failed = [k for k, v in health.items() if not v and k != "all_pass"]
                notif_svc.send_sync(
                    conn, "P0", "pipeline",
                    f"健康预检失败 {trade_date}",
                    f"失败项: {', '.join(failed)}",
                )
                conn.commit()
            conn.close()
            sys.exit(1)

        # ── Step 0.5: 配置一致性守卫 ──
        try:
            from engines.config_guard import assert_baseline_config
            config_ok = assert_baseline_config(
                PAPER_TRADING_CONFIG.factor_names,
                config_source="run_paper_trading.py",
            )
            if not config_ok:
                raise AssertionError("因子集与v1.2基线不一致")
            logger.info("[Step0.5] config_guard: v1.2配置一致 ✓")
        except (AssertionError, Exception) as e:
            logger.error(f"[Step0.5] P0 配置漂移! {e}")
            if not dry_run:
                log_step(conn, "config_guard", "failed", str(e))
                notif_svc.send_sync(conn, "P0", "pipeline",
                                    f"配置漂移 {trade_date}", str(e))
                conn.commit()
            conn.close()
            sys.exit(1)

        # ── Step 1: 拉取数据（并行化：klines + daily_basic + index_daily）──
        if skip_fetch:
            logger.info("[Step1] 跳过数据拉取")
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            from app.data_fetcher.data_loader import upsert_daily_basic, upsert_klines_daily
            from app.data_fetcher.tushare_fetcher import TushareFetcher

            fetcher = TushareFetcher()
            td_str = trade_date.strftime("%Y%m%d")
            t1 = time.time()
            logger.info(f"[Step1] 并行拉取 {td_str}...")

            # 各拉取任务用独立DB连接（避免线程共享连接）
            fetch_results = {}
            fetch_errors = []

            def _fetch_klines():
                _conn = get_sync_conn()
                try:
                    df = fetcher.merge_daily_data(td_str)
                    if not df.empty:
                        upsert_klines_daily(df, _conn)
                    return "klines", len(df)
                finally:
                    _conn.close()

            def _fetch_basic():
                _conn = get_sync_conn()
                try:
                    df = fetcher.fetch_daily_basic_by_date(td_str)
                    if not df.empty:
                        upsert_daily_basic(df, _conn)
                    return "basic", len(df)
                finally:
                    _conn.close()

            def _fetch_index():
                _conn = get_sync_conn()
                try:
                    idx_codes = ["000300.SH", "000905.SH", "000852.SH"]
                    start_5d = (trade_date - timedelta(days=10)).strftime("%Y%m%d")
                    total = 0
                    for idx_code in idx_codes:
                        try:
                            df_idx = fetcher.fetch_index_daily(idx_code, start_5d, td_str)
                            if df_idx is not None and not df_idx.empty:
                                _cur = _conn.cursor()
                                for _, r in df_idx.iterrows():
                                    _cur.execute(
                                        """INSERT INTO index_daily
                                               (index_code, trade_date, open, high, low, close,
                                                pre_close, pct_change, volume, amount)
                                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                           ON CONFLICT (index_code, trade_date) DO UPDATE SET
                                               close = EXCLUDED.close,
                                               pre_close = EXCLUDED.pre_close""",
                                        (
                                            str(r.get("ts_code", idx_code)),
                                            pd.to_datetime(r["trade_date"]).date(),
                                            float(r["open"]) if pd.notna(r.get("open")) else None,
                                            float(r["high"]) if pd.notna(r.get("high")) else None,
                                            float(r["low"]) if pd.notna(r.get("low")) else None,
                                            float(r["close"]) if pd.notna(r.get("close")) else None,
                                            float(r["pre_close"]) if pd.notna(r.get("pre_close")) else None,
                                            float(r["pct_chg"]) if pd.notna(r.get("pct_chg")) else None,
                                            int(r["vol"]) if pd.notna(r.get("vol")) else None,
                                            float(r["amount"]) if pd.notna(r.get("amount")) else None,
                                        ),
                                    )
                                _conn.commit()
                                total += len(df_idx)
                        except Exception as e:
                            logger.warning(f"[Step1] index_daily({idx_code}): {e}")
                            with contextlib.suppress(Exception):
                                _conn.rollback()
                    return "index", total
                finally:
                    _conn.close()

            # 并行执行3个拉取任务（各自独立连接，无锁竞争）
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="fetch") as pool:
                futures = [
                    pool.submit(_fetch_klines),
                    pool.submit(_fetch_basic),
                    pool.submit(_fetch_index),
                ]
                for f in as_completed(futures):
                    try:
                        name, count = f.result()
                        fetch_results[name] = count
                        logger.info(f"[Step1] {name}: {count}行 ✓")
                    except Exception as e:
                        fetch_errors.append(str(e))
                        logger.error(f"[Step1] 拉取失败: {e}")

            if fetch_results.get("klines", 0) == 0 and not fetch_errors:
                logger.error(f"[Step1] {td_str} 无行情数据")
                log_step(conn, "data_fetch", "failed", "无数据返回")
                conn.close()
                sys.exit(1)

            logger.info(
                f"[Step1] 完成 ({time.time()-t1:.0f}s): "
                f"klines={fetch_results.get('klines',0)}, "
                f"basic={fetch_results.get('basic',0)}, "
                f"index={fetch_results.get('index',0)}"
            )
            if not dry_run:
                log_step(conn, "data_fetch", "success")

        # ── Step 1.5: 更新T日NAV ──
        nav = settings.PAPER_INITIAL_CAPITAL
        daily_ret = 0.0
        cum_ret = 0.0
        t15 = time.time()
        logger.info(f"[Step1.5] 更新T日NAV ({trade_date})...")
        price_data_t = load_today_prices(trade_date, conn)
        if not price_data_t.empty:
            today_close_t = dict(zip(price_data_t["code"], price_data_t["close"], strict=False))
            benchmark_close_t = get_benchmark_close(trade_date, conn)

            paper_broker_nav = PaperBroker(
                strategy_id=settings.PAPER_STRATEGY_ID,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
            )
            paper_broker_nav.load_state(conn)

            nav = paper_broker_nav.get_current_nav(today_close_t)
            prev_nav = paper_broker_nav.state.nav if paper_broker_nav.state else settings.PAPER_INITIAL_CAPITAL
            daily_ret = (nav / prev_nav - 1) if prev_nav > 0 else 0
            cum_ret = (nav / settings.PAPER_INITIAL_CAPITAL - 1)

            if not dry_run:
                paper_broker_nav.save_state(
                    trade_date, [], today_close_t, benchmark_close_t, conn
                )
                log_step(conn, "nav_update", "success",
                         result={"nav": round(nav, 2), "daily_return": round(daily_ret, 6)})

            logger.info(f"[Step1.5] 完成 ({time.time()-t15:.0f}s): NAV=¥{nav:,.0f}, 日收益={daily_ret:+.2%}")
        else:
            logger.warning(f"[Step1.5] {trade_date} 无价格数据，跳过NAV更新")

        # ── Step 1.6: 每日风控评估 (L1-L4每日运行，非仅调仓日) ──
        # 目的: 确保CB状态机每个交易日都更新，L3触发时非调仓日也能记录
        # 并在下一个execute阶段生效（减仓指令）
        t16 = time.time()
        logger.info(f"[Step1.6] 每日风控评估 ({trade_date})...")
        try:
            if not dry_run:
                cb_daily = check_circuit_breaker_sync(
                    conn, settings.PAPER_STRATEGY_ID, trade_date,
                    settings.PAPER_INITIAL_CAPITAL
                )
                logger.info(
                    f"[Step1.6] 完成 ({time.time()-t16:.0f}s): "
                    f"L{cb_daily['level']} - {cb_daily['reason']}"
                )
                if cb_daily["level"] >= 3:
                    notif_svc.send_sync(
                        conn, "P0", "risk",
                        f"风控告警 L{cb_daily['level']} {trade_date}",
                        f"{cb_daily['reason']}\n"
                        f"仓位系数: {cb_daily['position_multiplier']:.0%}\n"
                        f"次日执行将应用降仓指令",
                    )
                    conn.commit()
            else:
                logger.info("[Step1.6] dry-run，跳过风控评估写入")
        except Exception as e:
            logger.warning(f"[Step1.6] 风控评估异常（不影响主流程）: {e}")

        # ── Step 1.7: 数据完整性预检 ──
        logger.info("[Step1.7] 数据完整性预检...")
        td_str_check = trade_date.strftime("%Y%m%d")
        _data_ok = True
        _data_cur = conn.cursor()
        for _tbl, _label in [("klines_daily", "日线行情"), ("daily_basic", "每日指标")]:
            _data_cur.execute(
                f"SELECT MAX(trade_date) FROM {_tbl}"
            )
            _max = _data_cur.fetchone()[0]
            _max_str = _max.strftime("%Y%m%d") if _max else "NULL"
            if _max_str < td_str_check:
                logger.error(f"[Step1.7] {_label}({_tbl})数据未就绪: 最新={_max_str}, 需要={td_str_check}")
                _data_ok = False
            else:
                logger.info(f"[Step1.7] {_label}: {_max_str} ✓")
        if not _data_ok:
            msg = f"信号生成阻塞: 核心数据未就绪({td_str_check})"
            logger.error(f"[Step1.7] {msg}")
            if not dry_run:
                log_step(conn, "data_readiness_check", "failed", msg)
                notif_svc.send_sync(
                    conn, "P0", "system", "数据预检失败", msg,
                )
                conn.commit()
            conn.close()
            sys.exit(1)

        # ── Step 2: 因子计算 ──
        if skip_factors:
            logger.info("[Step2] 跳过因子计算")
        else:
            t2 = time.time()
            logger.info(f"[Step2] 计算因子 {trade_date}...")
            factor_df = compute_daily_factors(trade_date, factor_set="full", conn=conn)
            if factor_df.empty:
                logger.error("[Step2] 因子计算结果为空")
                log_step(conn, "factor_calc", "failed", "因子为空")
                conn.close()
                sys.exit(1)
            rows = save_daily_factors(trade_date, factor_df, conn=conn)
            logger.info(f"[Step2] 完成 ({time.time()-t2:.0f}s): {rows}行")
            if not dry_run:
                log_step(conn, "factor_calc", "success")

        # ── Step 3: 信号生成（SignalService）──
        t3 = time.time()
        config = PAPER_TRADING_CONFIG
        fv = load_factor_values(trade_date, conn)
        universe = load_universe(trade_date, conn)
        industry = load_industry(conn)

        # ── Step 3 前置: Regime缩放（vol_regime 启发式 或 hmm_regime HMM）──
        vol_regime_scale = 1.0
        regime_mode = getattr(PAPER_TRADING_CONFIG, "regime_mode", "vol_regime")
        try:
            csi300_df = pd.read_sql(
                """SELECT trade_date, close FROM index_daily
                   WHERE index_code = '000300.SH'
                     AND trade_date <= %s
                   ORDER BY trade_date ASC LIMIT 500""",
                conn,
                params=(trade_date,),
            )
            if len(csi300_df) >= 22:
                csi300_closes = csi300_df.set_index("trade_date")["close"]

                if regime_mode == "hmm_regime":
                    from engines.regime_detector import HMMRegimeDetector
                    hmm_detector = HMMRegimeDetector()
                    regime_result = hmm_detector.fit_predict(csi300_closes)
                    vol_regime_scale = regime_result.scale
                    logger.info(
                        f"[Step3-HMMRegime] state={regime_result.state}, "
                        f"scale={vol_regime_scale:.4f}, "
                        f"bear_prob={regime_result.bear_prob:.3f}, "
                        f"source={regime_result.source}"
                    )
                else:
                    from engines.vol_regime import calc_vol_regime
                    vol_regime_scale = calc_vol_regime(csi300_closes)
                    logger.info(f"[Step3-VolRegime] scale={vol_regime_scale:.4f}")
            else:
                logger.warning(
                    f"[Step3-Regime] CSI300数据不足({len(csi300_df)}条)，"
                    "跳过Regime缩放"
                )
        except Exception as e:
            logger.warning(f"[Step3-Regime] 计算异常，使用scale=1.0: {e}")

        signal_svc = SignalService()
        try:
            signal_result = signal_svc.generate_signals(
                conn=conn,
                strategy_id=settings.PAPER_STRATEGY_ID,
                trade_date=trade_date,
                factor_df=fv,
                universe=universe,
                industry=industry,
                config=config,
                dry_run=dry_run,
                vol_regime_scale=vol_regime_scale,
            )
        except ValueError as e:
            logger.error(f"[Step3] P0 {e}")
            if not dry_run:
                log_step(conn, "signal_gen", "failed", str(e))
                notif_svc.send_sync(conn, "P0", "pipeline", f"信号生成失败 {trade_date}", str(e))
                conn.commit()
            conn.close()
            sys.exit(1)

        if not dry_run:
            log_step(conn, "signal_gen", "success",
                     result={"n_stocks": len(signal_result.target_weights),
                             "is_rebalance": signal_result.is_rebalance,
                             "beta": round(signal_result.beta, 3)})

        for w in signal_result.warnings:
            logger.warning(f"[Step3] {w}")

        logger.info(f"[Step3] 完成 ({time.time()-t3:.0f}s)")

        # ── Step 3.5: 影子选股（仅调仓日，失败不影响主策略）──
        if signal_result.is_rebalance:
            try:
                generate_shadow_lgbm_signals(trade_date, conn, dry_run=dry_run)
            except Exception as e:
                logger.warning(f"[SHADOW] Raw LGB影子选股失败（不影响主策略）: {e}")
                traceback.print_exc()
            try:
                generate_shadow_lgbm_inertia(trade_date, conn, dry_run=dry_run)
            except Exception as e:
                logger.warning(f"[SHADOW] Inertia(0.7σ)影子选股失败（不影响主策略）: {e}")
                traceback.print_exc()
        else:
            logger.info("[SHADOW] 非调仓日，跳过影子选股")

        # ── Step 4: 通知（NotificationService）──
        sorted_codes = sorted(
            signal_result.target_weights,
            key=lambda c: signal_result.target_weights[c],
            reverse=True,
        )
        next_td = get_next_trading_day(conn, trade_date)
        msg = (f"[信号预告] {trade_date}\n"
               f"调仓: {'是（月度）' if signal_result.is_rebalance else '否'}\n"
               f"目标: {len(signal_result.target_weights)}只, Beta={signal_result.beta:.3f}\n"
               f"执行日: {next_td}\n"
               f"Top5: {', '.join(sorted_codes[:5]) if not dry_run else 'dry-run'}")
        logger.info(msg)

        if not dry_run:
            try:
                notif_svc.send_daily_report_sync(
                    conn=conn,
                    trade_date=trade_date,
                    nav=nav,
                    daily_return=daily_ret,
                    holdings_count=len(signal_result.target_weights),
                    signals_summary={
                        "cum_return": cum_ret,
                        "beta": signal_result.beta,
                        "buys": sorted_codes[:15] if signal_result.is_rebalance else [],
                        "sells": [],
                        "rejected": [],
                    },
                    is_rebalance=signal_result.is_rebalance,
                )
                conn.commit()
                logger.info("[Step4] PT日报已发送钉钉")
            except Exception as e:
                logger.warning(f"[Step4] PT日报发送失败（不影响主流程）: {e}")

        # ── Step 5: 收尾任务（并行：Parquet缓存导出 + 因子衰减检测）──
        if not dry_run:
            from concurrent.futures import ThreadPoolExecutor

            t5 = time.time()
            logger.info("[Step5] 并行收尾任务...")

            def _export_parquet_cache():
                """导出Parquet缓存（研究脚本用，避免DB锁竞争）。"""
                try:
                    import subprocess
                    result = subprocess.run(
                        [sys.executable, "scripts/precompute_cache.py", "--quick"],
                        capture_output=True, text=True, timeout=300,
                        cwd="D:/quantmind-v2",
                    )
                    if result.returncode == 0:
                        logger.info("[Step5] Parquet缓存导出 ✓")
                    else:
                        logger.warning(f"[Step5] Parquet导出异常: {result.stderr[:200]}")
                except Exception as e:
                    logger.warning(f"[Step5] Parquet导出失败: {e}")

            def _run_factor_decay():
                """因子衰减检测。"""
                try:
                    _dconn = get_sync_conn()
                    from engines.factor_decay import check_factor_decay
                    decay_result = check_factor_decay(trade_date, _dconn)
                    if decay_result:
                        logger.info(f"[Step5] 因子衰减检测 ✓: {len(decay_result)}个因子")
                    _dconn.close()
                except Exception as e:
                    logger.warning(f"[Step5] 因子衰减检测失败（不影响主流程）: {e}")

            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cleanup") as pool:
                pool.submit(_export_parquet_cache)
                pool.submit(_run_factor_decay)

            logger.info(f"[Step5] 收尾完成 ({time.time()-t5:.0f}s)")

        # ── 心跳记录（PT watchdog用）──
        try:
            import json as _json
            heartbeat_file = Path("D:/quantmind-v2/logs/pt_heartbeat.json")
            heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
            heartbeat_file.write_text(_json.dumps({
                "trade_date": str(trade_date),
                "completed_at": datetime.now().isoformat(),
                "phase": "signal",
                "status": "ok",
            }))
            logger.info(f"[Heartbeat] written: {trade_date}")
        except Exception as e_hb:
            logger.warning(f"[Heartbeat] write failed: {e_hb}")

        elapsed = time.time() - t_total
        logger.info(f"[SIGNAL PHASE] 完成: {elapsed:.0f}s")

    except Exception as e:
        logger.error(f"[SIGNAL PHASE] 异常: {e}")
        traceback.print_exc()
        with contextlib.suppress(Exception):
            log_step(conn, "signal_phase", "failed", str(e))
        sys.exit(1)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# Phase 2: EXECUTE — T+1日盘前 09:00
# ════════════════════════════════════════════════════════════

def run_execute_phase(exec_date: date, dry_run: bool, skip_fetch: bool,
                      execution_mode: str = "paper"):
    """T+1日盘前：读昨日信号 → 用今日open价格执行 → 保存状态。

    Args:
        execution_mode: "paper"=SimBroker, "live"=miniQMT。
    """
    exec_mode = execution_mode  # 简写

    # live模式: 覆盖settings + xtquant路径 + 初始化qmt_manager连接
    if exec_mode == "live":
        os.environ["EXECUTION_MODE"] = "live"
        settings.EXECUTION_MODE = "live"  # type: ignore[misc]
        # xtquant双层嵌套路径修复（append不insert，避免其旧numpy覆盖venv版本）
        _xt = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
        if _xt.exists() and str(_xt) not in sys.path:
            sys.path.append(str(_xt))
        # qmt_manager是单例，需要手动startup（.env是paper，不会自动启动）
        from app.services.qmt_connection_manager import qmt_manager
        if qmt_manager.state == "disabled":
            qmt_manager.startup()

    logger.info(f"{'='*60}")
    logger.info(f"[EXECUTE PHASE] exec_date={exec_date}, mode={exec_mode}")
    logger.info(f"{'='*60}")

    conn = get_sync_conn()
    t_total = time.time()

    try:
        if not acquire_lock(conn):
            conn.close()
            sys.exit(1)

        if not is_trading_day(conn, exec_date):
            logger.info(f"{exec_date} 非交易日，退出")
            conn.close()
            return

        # ── QMT进程检查+自启动（live模式）──
        if exec_mode == "live":
            import subprocess as _sp
            qmt_exe = getattr(settings, "QMT_EXE_PATH", "")

            def _qmt_is_running() -> bool:
                """检查XtMiniQmt.exe进程是否存在。"""
                try:
                    r = _sp.run(
                        ["tasklist"], capture_output=True, timeout=10,
                        encoding="gbk", errors="ignore",
                    )
                    return "XtMiniQmt.exe" in (r.stdout or "")
                except Exception:
                    return False

            qmt_running = _qmt_is_running()

            if not qmt_running and qmt_exe:
                logger.info(f"[QMT] 进程未运行, 尝试启动: {qmt_exe}")
                try:
                    _sp.Popen([qmt_exe], cwd=str(Path(qmt_exe).parent))
                    time.sleep(10)  # 等待QMT启动
                    qmt_running = _qmt_is_running()
                except Exception as e:
                    logger.error(f"[QMT] 自启动失败: {e}")

            if not qmt_running:
                logger.error("[QMT] 进程未运行且无法启动, 跳过live执行")
                try:
                    notif_svc = _get_notif_service()
                    notif_svc.send_sync(
                        conn, "P0", f"QMT进程未运行 {exec_date}",
                        "miniQMT进程不存在, live执行已跳过, 17:05 SimBroker兜底",
                    )
                except Exception:
                    pass
                log_step(conn, f"execute_phase_{exec_mode}", "failed", "QMT进程未运行")
                conn.close()
                return  # exit 0, SimBroker 17:05兜底

        # ── 防止重复执行（paper和live独立判断）──
        guard_task = f"execute_phase_{exec_mode}"
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM scheduler_task_log
               WHERE task_name = %s AND status = 'success'
                 AND start_time::date = %s""",
            (guard_task, exec_date),
        )
        if cur.fetchone()[0] > 0:
            logger.info(f"[Execute] {exec_date} {exec_mode}模式已成功执行，跳过")
            conn.close()
            return

        notif_svc = _get_notif_service()
        signal_svc = SignalService()
        exec_svc = ExecutionService()

        # ── 查找信号日（上一个交易日）──
        signal_date = get_prev_trading_day(conn, exec_date)
        if not signal_date:
            logger.error("找不到上一交易日")
            conn.close()
            sys.exit(1)
        logger.info(f"[Execute] 信号日={signal_date}, 执行日={exec_date}")

        # ── Step 5: 读取信号（SignalService）──
        signal_rows = signal_svc.get_latest_signals(conn, settings.PAPER_STRATEGY_ID, signal_date)

        if not signal_rows:
            logger.warning(f"[Step5] {signal_date} 无信号记录。可能信号阶段未运行。")
            hedged_target = {}
            is_rebalance = False
        else:
            hedged_target = {r["code"]: r["target_weight"] for r in signal_rows}
            signal_action = signal_rows[0]["action"]
            logger.info(f"[Step5] 读取{len(hedged_target)}只信号, signal_action={signal_action}")

        # ── Step 5.6: 信号调仓标记验证 ──
        if signal_rows:
            cur = conn.cursor()
            cur.execute(
                """SELECT COUNT(*) FROM trading_calendar
                   WHERE market='astock' AND is_trading_day=TRUE
                     AND trade_date > %s AND trade_date < %s""",
                (signal_date, exec_date),
            )
            trading_days_between = cur.fetchone()[0]

            if trading_days_between > 2:
                logger.warning(f"[Step5.6] 信号日{signal_date}距执行日{exec_date}中间有{trading_days_between}个交易日，信号过时")
                is_rebalance = False
            elif signal_action == "rebalance":
                is_rebalance = True
                logger.info(f"[Step5.6] 信任信号rebalance标记（T日={signal_date} → T+1={exec_date}，间隔{trading_days_between}交易日）")
            else:
                is_rebalance = False

        # ── Step 5.7: QMT持仓偏差检测（live模式）──
        # 检测3种情况: 首次建仓 / 超买修复 / 缺失补买
        # adapter内部自动处理差额（sell overweight + buy missing）
        DRIFT_OVERWEIGHT_RATIO = 1.3  # 超买阈值: 实际 > 目标×130%
        DRIFT_MAX_SELL_PCT = 0.30     # 单日修复最多卖总市值30%

        if exec_mode == "live" and hedged_target and not is_rebalance:
            try:
                from app.services.qmt_connection_manager import qmt_manager
                qmt_manager.ensure_connected()
                broker = qmt_manager.broker
                qmt_pos = broker.query_positions()
                qmt_asset = broker.query_asset()
                total_value = qmt_asset.get("total_asset", 0)

                # 转为 {code: shares} 去后缀
                actual_holdings: dict[str, int] = {}
                for p in qmt_pos:
                    code = p.get("stock_code", "").split(".")[0]
                    if code and p.get("market_value", 0) > 1000:
                        actual_holdings[code] = p["volume"]

                # 计算目标股数
                target_shares: dict[str, int] = {}
                for code, weight in hedged_target.items():
                    # 用xtdata实时价或klines close估算
                    px = 0.0
                    try:
                        from engines.qmt_execution_adapter import _get_realtime_tick, _to_qmt_code
                        tick = _get_realtime_tick(_to_qmt_code(code))
                        if tick and tick.get("lastPrice", 0) > 0:
                            px = tick["lastPrice"]
                    except Exception:
                        pass
                    if px <= 0:
                        # fallback: klines_daily close
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT close FROM klines_daily WHERE code=%s ORDER BY trade_date DESC LIMIT 1",
                            (code,),
                        )
                        row = cur.fetchone()
                        if row and row[0]:
                            px = float(row[0])
                    if px > 0 and total_value > 0:
                        target_shares[code] = int(total_value * float(weight) / px / 100) * 100

                # 偏差分析
                overweight = {}  # code → excess shares
                missing = {}    # code → target shares
                for code, target_s in target_shares.items():
                    actual_s = actual_holdings.get(code, 0)
                    if actual_s == 0 and target_s > 0:
                        missing[code] = target_s
                    elif target_s > 0 and actual_s > target_s * DRIFT_OVERWEIGHT_RATIO:
                        overweight[code] = actual_s - target_s

                effective_count = len(actual_holdings)
                target_count = len(hedged_target)

                if target_count > 0 and effective_count < target_count * 0.5:
                    # 首次建仓（空仓或极少持仓）
                    is_rebalance = True
                    logger.info(
                        f"[Step5.7] QMT首次建仓: "
                        f"当前{effective_count}只, 目标{target_count}只"
                    )
                elif overweight or missing:
                    # 持仓偏差修复
                    # 安全检查: 卖出不超过总市值30%
                    # 估算卖出金额: excess_shares × 参考价格
                    def _est_price(code: str) -> float:
                        """获取估价（xtdata或klines）。"""
                        try:
                            from engines.qmt_execution_adapter import (
                                _get_realtime_tick,
                                _to_qmt_code,
                            )
                            t = _get_realtime_tick(_to_qmt_code(code))
                            if t and t.get("lastPrice", 0) > 0:
                                return t["lastPrice"]
                        except Exception:
                            pass
                        c2 = conn.cursor()
                        c2.execute("SELECT close FROM klines_daily WHERE code=%s ORDER BY trade_date DESC LIMIT 1", (code,))
                        r2 = c2.fetchone()
                        return float(r2[0]) if r2 and r2[0] else 0

                    sell_value = sum(
                        overweight[c] * _est_price(c) for c in overweight
                    )
                    if total_value > 0 and sell_value > total_value * DRIFT_MAX_SELL_PCT:
                        logger.warning(
                            f"[Step5.7] 偏差修复卖出额¥{sell_value:,.0f} > "
                            f"总市值{DRIFT_MAX_SELL_PCT:.0%}，跳过（防意外清仓）"
                        )
                    else:
                        # 检查超买部分是否可卖（T+1约束）
                        # can_use从query_positions获取
                        can_use_map: dict[str, int] = {}
                        for p in qmt_pos:
                            pc = p.get("stock_code", "").split(".")[0]
                            can_use_map[pc] = p.get("can_use_volume", 0)

                        actually_sellable = {
                            c: min(excess, can_use_map.get(c, 0))
                            for c, excess in overweight.items()
                        }
                        sellable_count = sum(1 for v in actually_sellable.values() if v >= 100)

                        if sellable_count == 0 and overweight:
                            logger.info(
                                f"[Step5.7] 超买{len(overweight)}只但可卖=0(T+1), "
                                "跳过偏差修复"
                            )
                        else:
                            is_rebalance = True

                            # 节前保护: 下一交易日距今>2天 → 买入仓位降至70%
                            next_td = get_next_trading_day(conn, exec_date)
                            holiday_gap = (next_td - exec_date).days if next_td else 1
                            if holiday_gap > 2:
                                buy_scale = 0.7
                                logger.info(
                                    f"[Step5.7] 节前保护: 假期{holiday_gap}天, "
                                    "买入仓位降至70%"
                                )
                                # 缩放缺失股票的目标权重
                                for c in missing:
                                    hedged_target[c] = float(hedged_target.get(c, 0)) * buy_scale

                            logger.info(
                                f"[Step5.7] 持仓偏差修复: "
                                f"超买{len(overweight)}只(可卖{sellable_count}只), "
                                f"缺失{len(missing)}只"
                            )
                            for c, excess in overweight.items():
                                can = can_use_map.get(c, 0)
                                logger.info(
                                    f"  超买 {c}: 实际{actual_holdings[c]} "
                                    f"目标{target_shares[c]} 超{excess}股 "
                                    f"可卖{can}股"
                                )
                            for c, target_s in missing.items():
                                logger.info(f"  缺失 {c}: 目标{target_s}股")
                else:
                    logger.info(
                        f"[Step5.7] QMT持仓正常: "
                        f"{effective_count}只 (目标{target_count}只), 无偏差"
                    )
            except Exception as e:
                logger.warning(f"[Step5.7] QMT持仓检查失败: {e}")

        # ── Step 5.5: 拉取T+1日数据 ──
        if not skip_fetch:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM klines_daily WHERE trade_date = %s",
                (exec_date,),
            )
            existing = cur.fetchone()[0]
            if existing < 100:
                logger.info(f"[Step5.5] T+1日数据不足({existing}行), 拉取...")
                from app.data_fetcher.data_loader import upsert_daily_basic, upsert_klines_daily
                from app.data_fetcher.tushare_fetcher import TushareFetcher

                fetcher = TushareFetcher()
                td_str = exec_date.strftime("%Y%m%d")
                df_k = fetcher.merge_daily_data(td_str)
                if not df_k.empty:
                    upsert_klines_daily(df_k, conn)
                df_b = fetcher.fetch_daily_basic_by_date(td_str)
                if not df_b.empty:
                    upsert_daily_basic(df_b, conn)
                logger.info(f"[Step5.5] T+1数据拉取完成: {len(df_k)}行")

        # ── 加载T+1日价格 ──
        price_data = load_today_prices(exec_date, conn)
        if price_data.empty:
            if exec_mode == "live":
                # live模式: klines_daily盘中无数据是正常的(收盘后才更新)
                # adapter内部通过xtdata获取实时价格，不依赖klines
                logger.info(
                    f"[Execute] {exec_date} klines无数据 — live模式使用xtdata实时价格"
                )
                # 构造空DataFrame让后续代码不报错
                price_data = pd.DataFrame(
                    columns=["code", "trade_date", "open", "close", "high",
                             "low", "volume", "amount", "pre_close",
                             "up_limit", "down_limit"]
                )
            elif exec_mode == "paper":
                logger.info(
                    f"[Execute] {exec_date} 无价格数据 — SimBroker模式等待收盘数据，"
                    "将由17:05调度重试"
                )
                log_step(conn, guard_task, "skipped", "SimBroker等待收盘数据")
                conn.close()
                return
            else:
                logger.error(f"[Execute] {exec_date} 无价格数据")
                log_step(conn, guard_task, "failed", "T+1无价格数据")
                conn.close()
                sys.exit(1)

        # ── Step 5.8: 开盘跳空预检（PT阶段：只告警，不暂停执行）──
        try:
            _check_opening_gap(
                exec_date=exec_date,
                price_data=price_data,
                conn=conn,
                notif_svc=notif_svc,
                dry_run=dry_run,
            )
        except Exception as e:
            logger.warning(f"[Step5.8] 开盘跳空预检异常（不影响主流程）: {e}")

        # ── Step 5.9: 熔断检查（RiskControlService）──
        cb = check_circuit_breaker_sync(
            conn, settings.PAPER_STRATEGY_ID, exec_date, settings.PAPER_INITIAL_CAPITAL
        )
        logger.info(f"[Step5.9] 熔断检查: L{cb['level']} - {cb['reason']}")
        if cb.get("recovery_info"):
            logger.info(f"[Step5.9] 恢复信息: {cb['recovery_info']}")

        # ── Step 5.95: 延迟调仓恢复（ExecutionService）──
        if cb["level"] == 0 and not is_rebalance:
            should_resume, resume_target = exec_svc.resume_pending_rebalance(
                conn, settings.PAPER_STRATEGY_ID, exec_date,
                cb_level=cb["level"], dry_run=dry_run,
            )
            if should_resume and resume_target:
                logger.info("[DELAYED REBALANCE] L1已恢复，执行延迟月度调仓")
                hedged_target = resume_target
                is_rebalance = True

        # ── Step 5.96: 封板补单（ExecutionService）──
        pending_fills = exec_svc.process_pending_orders(
            conn, settings.PAPER_STRATEGY_ID, exec_date, price_data,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
            cb_level=cb["level"], dry_run=dry_run,
        )

        # ── Step 6: 执行调仓（ExecutionService）──
        if is_rebalance and hedged_target:
            exec_result = exec_svc.execute_rebalance(
                conn=conn,
                strategy_id=settings.PAPER_STRATEGY_ID,
                exec_date=exec_date,
                target_weights=hedged_target,
                cb_level=cb["level"],
                position_multiplier=cb["position_multiplier"],
                price_data=price_data,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                signal_date=signal_date,
                dry_run=dry_run,
                execution_mode=exec_mode,
            )
            fills = pending_fills + exec_result.fills
            logger.info(f"[Step6] 调仓完成: {len(exec_result.fills)}笔成交")

            if not dry_run:
                log_step(conn, guard_task, "success",
                         result={"fills": len(fills), "is_rebalance": True})
        else:
            fills = pending_fills
            logger.info("[Step6] 非调仓日，无订单执行")
            if not dry_run:
                log_step(conn, guard_task, "success",
                         result={"fills": len(fills), "is_rebalance": False})

        # ── Step 7.5: 回填executed_at + signal_price(gap_hours/slippage毕业指标) ──
        if not dry_run and fills:
            from datetime import datetime as dt_mod
            now_utc = dt_mod.now(UTC)
            cur = conn.cursor()
            # 回填executed_at
            cur.execute(
                """UPDATE trade_log
                   SET executed_at = %s
                   WHERE trade_date = %s AND strategy_id = %s
                     AND execution_mode = %s AND executed_at IS NULL""",
                (now_utc, exec_date, settings.PAPER_STRATEGY_ID, exec_mode),
            )
            conn.commit()
            logger.info(f"[Step7.5] executed_at已更新: {cur.rowcount}行")

            # 回填signal_price（信号日收盘价，用于滑点计算）
            if signal_date:
                codes = [f.code for f in fills]
                cur.execute(
                    """SELECT code, close FROM klines_daily
                       WHERE trade_date = %s AND code = ANY(%s)""",
                    (signal_date, codes),
                )
                for code, close_px in cur.fetchall():
                    cur.execute(
                        """UPDATE trade_log SET signal_price = %s
                           WHERE trade_date = %s AND code = %s
                             AND strategy_id = %s AND execution_mode = %s
                             AND signal_price IS NULL""",
                        (float(close_px), exec_date, code,
                         settings.PAPER_STRATEGY_ID, exec_mode),
                    )
                conn.commit()
                logger.info(f"[Step7.5] signal_price已回填: {len(codes)}只")

        # ── Step 8: 执行结果通知 ──
        report_lines = [
            f"[QuantMind Paper] {exec_date} 执行确认",
            "─" * 40,
            f"信号日: {signal_date} | 执行日: {exec_date}",
            f"调仓: {'是' if is_rebalance else '否'}",
            f"成交: {len(fills)}笔",
        ]
        if fills:
            buy_list = [f.code for f in fills if f.direction == "buy"]
            sell_list = [f.code for f in fills if f.direction == "sell"]
            if buy_list:
                report_lines.append(f"买入({len(buy_list)}): {', '.join(buy_list[:5])}")
            if sell_list:
                report_lines.append(f"卖出({len(sell_list)}): {', '.join(sell_list[:5])}")

        report = "\n".join(report_lines)
        print("\n" + report.encode('utf-8', errors='replace').decode('utf-8'))

        if not dry_run and fills:
            try:
                notif_svc.send_execute_report_sync(
                    conn=conn,
                    exec_date=exec_date,
                    fills_count=len(fills),
                    nav=exec_result.nav if is_rebalance else 0.0,
                    cb_level=cb["level"],
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"[Step8] 执行确认通知发送失败: {e}")

        elapsed = time.time() - t_total
        logger.info(f"[EXECUTE PHASE] 完成: {elapsed:.0f}s")

    except Exception as e:
        logger.error(f"[EXECUTE PHASE] 异常: {e}")
        traceback.print_exc()
        with contextlib.suppress(Exception):
            log_step(conn, f"execute_phase_{exec_mode}", "failed", str(e))
        sys.exit(1)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="QuantMind Paper Trading 两阶段管道",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # T日盘后生成信号
  python scripts/run_paper_trading.py signal --date 2026-03-21

  # T+1日盘前执行
  python scripts/run_paper_trading.py execute --date 2026-03-24

  # dry-run
  python scripts/run_paper_trading.py signal --date 2026-03-21 --dry-run
        """,
    )

    parser.add_argument("phase", choices=["signal", "execute"],
                        help="signal=T日盘后生成信号, execute=T+1日执行调仓")
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD (默认今天)")
    parser.add_argument("--dry-run", action="store_true", help="仅模拟，不写DB")
    parser.add_argument("--skip-fetch", action="store_true", help="跳过数据拉取")
    parser.add_argument("--skip-factors", action="store_true", help="跳过因子计算(仅signal阶段)")
    parser.add_argument("--execution-mode", type=str, default=None,
                        choices=["paper", "live"],
                        help="覆盖执行模式: paper=SimBroker, live=miniQMT")
    args = parser.parse_args()

    if not settings.PAPER_STRATEGY_ID:
        logger.error("PAPER_STRATEGY_ID未配置！请先运行 setup_paper_trading.py")
        sys.exit(1)

    trade_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else date.today()
    )

    if args.phase == "signal":
        run_signal_phase(trade_date, args.dry_run, args.skip_fetch, args.skip_factors)
    elif args.phase == "execute":
        exec_mode = args.execution_mode or settings.EXECUTION_MODE
        run_execute_phase(trade_date, args.dry_run, args.skip_fetch,
                          execution_mode=exec_mode)


if __name__ == "__main__":
    main()
