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

Phase 2 — execute（T+1日 09:00 cron触发）:
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
from datetime import date, datetime, timedelta
from pathlib import Path

# Windows UTF-8 输出修复（兼容Git Bash管道模式）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from app.config import settings
from app.services.db import get_sync_conn
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.paper_trading_service import PaperTradingService
from app.services.risk_control_service import check_circuit_breaker_sync
from app.services.signal_service import SignalService
from app.services.trading_calendar import (
    acquire_lock,
    get_next_trading_day,
    get_prev_trading_day,
    is_trading_day,
)
from engines.factor_engine import compute_daily_factors, save_daily_factors
from engines.paper_broker import PaperBroker
from engines.signal_engine import PAPER_TRADING_CONFIG
from health_check import run_health_check
from run_backtest import load_factor_values, load_industry, load_universe

# ── 日志配置 ──
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_log_handlers = [
    logging.FileHandler(LOG_DIR / "paper_trading.log", encoding="utf-8"),
]
if sys.stdout and not getattr(sys.stdout, "closed", True) and sys.stderr and not getattr(sys.stderr, "closed", True):
    try:
        _log_handlers.insert(0, logging.StreamHandler(sys.stderr))
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
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
        try:
            conn.rollback()
        except Exception:
            pass


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

    if y <= 2022:
        fold_id = 1
    elif y == 2023 and m <= 6:
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
    import numpy as np  # noqa: F811

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
        logger.info(f"[SHADOW] dry-run模式，不写DB")


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
    logger.info(f"[SHADOW] Raw LGB影子选股完成")


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
        logger.info(f"[SHADOW] 无历史持仓，Inertia等同于Raw LGB（首次运行）")
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
        logger.info(f"[SHADOW] 首次建仓，换手率: 100%")

    _write_shadow_portfolio(df_top, SHADOW_STRATEGY, trade_date, top_n, conn, dry_run)
    logger.info(f"[SHADOW] Inertia(0.7σ)影子选股完成")


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
                raise AssertionError("因子集与v1.1基线不一致")
            logger.info("[Step0.5] config_guard: v1.1配置一致 ✓")
        except (AssertionError, Exception) as e:
            logger.error(f"[Step0.5] P0 配置漂移! {e}")
            if not dry_run:
                log_step(conn, "config_guard", "failed", str(e))
                notif_svc.send_sync(conn, "P0", "pipeline",
                                    f"配置漂移 {trade_date}", str(e))
                conn.commit()
            conn.close()
            sys.exit(1)

        # ── Step 1: 拉取数据（尚未Service化）──
        if skip_fetch:
            logger.info("[Step1] 跳过数据拉取")
        else:
            from app.data_fetcher.tushare_fetcher import TushareFetcher
            from app.data_fetcher.data_loader import upsert_klines_daily, upsert_daily_basic

            fetcher = TushareFetcher()
            td_str = trade_date.strftime("%Y%m%d")

            t1 = time.time()
            logger.info(f"[Step1] 拉取 {td_str}...")
            df_klines = fetcher.merge_daily_data(td_str)
            if df_klines.empty:
                logger.error(f"[Step1] {td_str} 无行情数据")
                log_step(conn, "data_fetch", "failed", "无数据返回")
                conn.close()
                sys.exit(1)
            upsert_klines_daily(df_klines, conn)

            df_basic = fetcher.fetch_daily_basic_by_date(td_str)
            if not df_basic.empty:
                upsert_daily_basic(df_basic, conn)

            # 增量拉取index_daily
            idx_codes = ["000300.SH", "000905.SH", "000852.SH"]
            start_5d = (trade_date - timedelta(days=10)).strftime("%Y%m%d")
            idx_total = 0
            for idx_code in idx_codes:
                try:
                    df_idx = fetcher.fetch_index_daily(idx_code, start_5d, td_str)
                    if df_idx is not None and not df_idx.empty:
                        cur = conn.cursor()
                        for _, r in df_idx.iterrows():
                            cur.execute(
                                """INSERT INTO index_daily
                                       (index_code, trade_date, open, high, low, close,
                                        pre_close, pct_change, volume, amount)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        conn.commit()
                        idx_total += len(df_idx)
                except Exception as e:
                    logger.warning(f"[Step1] index_daily拉取失败({idx_code}): {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            logger.info(f"[Step1] index_daily增量拉取: {idx_total}行")

            logger.info(f"[Step1] 完成 ({time.time()-t1:.0f}s): klines={len(df_klines)}, basic={len(df_basic)}, index={idx_total}")
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
            today_close_t = dict(zip(price_data_t["code"], price_data_t["close"]))
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

        # ── Step 2: 因子计算 ──
        if skip_factors:
            logger.info("[Step2] 跳过因子计算")
        else:
            t2 = time.time()
            logger.info(f"[Step2] 计算因子 {trade_date}...")
            factor_df = compute_daily_factors(trade_date, factor_set="full", conn=conn)
            if factor_df.empty:
                logger.error(f"[Step2] 因子计算结果为空")
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

        # ── Step 3 前置: 波动率Regime缩放（Sprint 1.1）──
        vol_regime_scale = 1.0
        try:
            from engines.vol_regime import calc_vol_regime
            csi300_closes = pd.read_sql(
                """SELECT trade_date, close FROM index_daily
                   WHERE index_code = '000300.SH'
                     AND trade_date <= %s
                   ORDER BY trade_date DESC LIMIT 260""",
                conn,
                params=(trade_date,),
            )
            if len(csi300_closes) >= 22:
                csi300_series = csi300_closes.set_index("trade_date")["close"].sort_index()
                vol_regime_scale = calc_vol_regime(csi300_series)
                logger.info(f"[Step3-VolRegime] scale={vol_regime_scale:.4f}")
            else:
                logger.warning(
                    f"[Step3-VolRegime] CSI300数据不足({len(csi300_closes)}条)，"
                    "跳过Regime缩放"
                )
        except Exception as e:
            logger.warning(f"[Step3-VolRegime] 计算异常，使用scale=1.0: {e}")

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
        try:
            log_step(conn, "signal_phase", "failed", str(e))
        except Exception:
            pass
        sys.exit(1)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# Phase 2: EXECUTE — T+1日盘前 09:00
# ════════════════════════════════════════════════════════════

def run_execute_phase(exec_date: date, dry_run: bool, skip_fetch: bool):
    """T+1日盘前：读昨日信号 → 用今日open价格执行 → 保存状态。"""
    logger.info(f"{'='*60}")
    logger.info(f"[EXECUTE PHASE] exec_date={exec_date}")
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
                from app.data_fetcher.tushare_fetcher import TushareFetcher
                from app.data_fetcher.data_loader import upsert_klines_daily, upsert_daily_basic

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
            logger.error(f"[Execute] {exec_date} 无价格数据")
            log_step(conn, "execute_phase", "failed", "T+1无价格数据")
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
                logger.info(f"[DELAYED REBALANCE] L1已恢复，执行延迟月度调仓")
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
            )
            fills = pending_fills + exec_result.fills
            logger.info(f"[Step6] 调仓完成: {len(exec_result.fills)}笔成交")

            if not dry_run:
                log_step(conn, "execute_phase", "success",
                         result={"fills": len(fills), "is_rebalance": True})
        else:
            fills = pending_fills
            logger.info("[Step6] 非调仓日，无订单执行")
            if not dry_run:
                log_step(conn, "execute_phase", "success",
                         result={"fills": len(fills), "is_rebalance": False})

        # ── Step 7.5: 回填executed_at时间戳(gap_hours毕业指标) ──
        if not dry_run and fills:
            from datetime import datetime as dt_mod, timezone as tz_mod
            now_utc = dt_mod.now(tz_mod.utc)
            cur = conn.cursor()
            cur.execute(
                """UPDATE trade_log
                   SET executed_at = %s
                   WHERE trade_date = %s AND strategy_id = %s
                     AND execution_mode = 'paper' AND executed_at IS NULL""",
                (now_utc, exec_date, settings.PAPER_STRATEGY_ID),
            )
            conn.commit()
            logger.info(f"[Step7.5] executed_at已更新: {cur.rowcount}行")

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
        try:
            log_step(conn, "execute_phase", "failed", str(e))
        except Exception:
            pass
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
        run_execute_phase(trade_date, args.dry_run, args.skip_fetch)


if __name__ == "__main__":
    main()
