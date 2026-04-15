#!/usr/bin/env python3
"""Paper Trading 两阶段管道 — V3编排器。

Step 6-A重构: 从1734行缩减为编排器。
具体逻辑在:
  - app.services.pt_data_service: 并行数据拉取
  - app.services.pt_monitor_service: 开盘跳空+风险检测
  - app.services.pt_qmt_state: QMT↔DB状态同步
  - app.services.shadow_portfolio: LightGBM影子选股

用法:
  python scripts/run_paper_trading.py signal --date 2026-04-08
  python scripts/run_paper_trading.py execute --date 2026-04-09
  python scripts/run_paper_trading.py signal --date 2026-04-08 --dry-run
"""

import argparse
import contextlib
import json
import logging
import os
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from engines.factor_engine import compute_daily_factors, save_daily_factors
from engines.signal_engine import PAPER_TRADING_CONFIG
from health_check import run_health_check
from run_backtest import load_factor_values, load_industry, load_universe

from app.config import settings
from app.core.qmt_client import QMTClient
from app.services.db import get_sync_conn
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.pt_data_service import fetch_daily_data
from app.services.pt_monitor_service import check_opening_gap
from app.services.pt_qmt_state import save_qmt_state
from app.services.risk_control_service import check_circuit_breaker_sync
from app.services.shadow_portfolio import (
    generate_shadow_lgbm_inertia,
    generate_shadow_lgbm_signals,
)
from app.services.signal_service import SignalService
from app.services.trading_calendar import (
    acquire_lock,
    get_prev_trading_day,
    is_trading_day,
)

# ── 日志配置 ──
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
_log_handlers = [logging.FileHandler(LOG_DIR / "paper_trading.log", encoding="utf-8")]
if sys.stdout and not getattr(sys.stdout, "closed", True):
    with contextlib.suppress(Exception):
        _log_handlers.insert(0, logging.StreamHandler(sys.stderr))
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S", handlers=_log_handlers, force=True,
)
logger = logging.getLogger("paper_trading")


def log_step(conn, task_name: str, status: str, error: str = None, result: dict = None):
    """写入 scheduler_task_log。schedule_time 用 now() 代替 (实际执行时间)。"""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scheduler_task_log "
        "(task_name, status, error_message, result_json, schedule_time, start_time, end_time, market) "
        "VALUES (%s, %s, %s, %s, NOW(), NOW(), NOW(), 'astock')",
        (task_name, status, error, json.dumps(result) if result else None),
    )
    conn.commit()


def load_today_prices(trade_date: date, conn) -> pd.DataFrame:
    """加载当日价格数据。"""
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close, k.volume, k.amount,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s AND k.volume > 0
           ORDER BY k.code""",
        conn, params=(trade_date,),
    )


def get_benchmark_close(trade_date: date, conn) -> float:
    """获取CSI300当日收盘价。"""
    cur = conn.cursor()
    cur.execute("SELECT close FROM index_daily WHERE index_code='000300.SH' AND trade_date=%s", (trade_date,))
    r = cur.fetchone()
    return float(r[0]) if r else 0.0


def _get_notif_service() -> NotificationService:
    return NotificationService(session=None)


# ════════════════════════════════════════════════════════════
# Signal Phase — T日盘后 16:30
# ════════════════════════════════════════════════════════════


def run_signal_phase(trade_date: date, dry_run: bool, skip_fetch: bool, skip_factors: bool, force_rebalance: bool = False):
    """T日信号生成编排: 健康检查→拉数据→NAV→风控→因子→信号→影子→通知。"""
    logger.info("=" * 60)
    logger.info("[SIGNAL PHASE] T日=%s", trade_date)
    conn = get_sync_conn()
    t_total = time.time()

    try:
        if not acquire_lock(conn) or not is_trading_day(conn, trade_date):
            logger.info("%s 非交易日或锁冲突，退出", trade_date)
            return

        notif_svc = _get_notif_service()  # noqa: F841

        # Step 0: 健康预检
        health = run_health_check(trade_date, conn, write_db=not dry_run)
        if not health["all_pass"]:
            logger.error("[Step0] 预检失败")
            if not dry_run:
                log_step(conn, "signal_phase", "failed", "健康预检失败")
            sys.exit(1)

        # Step 0.5: 配置守卫
        from engines.config_guard import assert_baseline_config
        if not assert_baseline_config(PAPER_TRADING_CONFIG.factor_names, "run_paper_trading.py"):
            logger.error("[Step0.5] 配置漂移!")
            sys.exit(1)

        # Step 1: 数据拉取(委托pt_data_service)
        fetch_result = fetch_daily_data(trade_date, skip_fetch=skip_fetch)
        logger.info("[Step1] 数据: klines=%d, basic=%d (%.1fs)",
                     fetch_result["klines_rows"], fetch_result["basic_rows"], fetch_result["elapsed"])

        # Step 1.5: NAV更新(QMT→DB)
        try:
            qmt = QMTClient()
            qmt_positions = qmt.get_positions() or {}
            qmt_nav_data = qmt.get_nav()
            price_data_t = load_today_prices(trade_date, conn)
            today_close = dict(zip(price_data_t["code"], price_data_t["close"], strict=False)) if not price_data_t.empty else {}

            nav = qmt_nav_data.get("total_value", 0) if qmt_nav_data else 0
            if nav <= 0:
                nav = sum(qty * today_close.get(code, 0) for code, qty in qmt_positions.items())
                nav += qmt_nav_data.get("cash", 0) if qmt_nav_data else 0

            cur = conn.cursor()
            cur.execute("SELECT nav FROM performance_series WHERE execution_mode='paper' AND strategy_id=%s ORDER BY trade_date DESC LIMIT 1",
                        (settings.PAPER_STRATEGY_ID,))
            r = cur.fetchone()
            prev_nav = float(r[0]) if r else settings.PAPER_INITIAL_CAPITAL

            benchmark_close = get_benchmark_close(trade_date, conn)
            if not dry_run and nav > 0:
                save_qmt_state(conn, trade_date, qmt_positions, today_close, nav, prev_nav, qmt_nav_data, benchmark_close)
        except Exception as e:
            logger.warning("[Step1.5] NAV更新失败(不影响信号): %s", e)

        # Step 1.6: 风控评估
        cb = check_circuit_breaker_sync(
            conn=conn,
            strategy_id=settings.PAPER_STRATEGY_ID,
            exec_date=trade_date,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        logger.info("[Step1.6] 熔断: L%s - %s", cb.get("level", 0), cb.get("reason", ""))

        # Step 2: 因子计算
        if not skip_factors:
            logger.info("[Step2] 因子计算...")
            factor_df = compute_daily_factors(trade_date, factor_set="full", conn=conn)
            save_daily_factors(trade_date, factor_df, conn=conn)

        # Step 3: 信号生成
        fv = load_factor_values(trade_date, conn)
        universe = load_universe(trade_date, conn)
        industry = load_industry(conn)

        signal_svc = SignalService()
        signal_result = signal_svc.generate_signals(
            conn=conn, strategy_id=settings.PAPER_STRATEGY_ID,
            trade_date=trade_date, factor_df=fv,
            universe=universe, industry=industry,
            config=PAPER_TRADING_CONFIG, dry_run=dry_run,
        )
        if force_rebalance and not signal_result.is_rebalance:
            signal_result.is_rebalance = True
            if not dry_run:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE signals SET action='rebalance' "
                    "WHERE trade_date=%s AND strategy_id=%s AND execution_mode='paper'",
                    (trade_date, settings.PAPER_STRATEGY_ID),
                )
                conn.commit()
                logger.info("[Step3] --force-rebalance: 已更新%d条信号为rebalance", cur.rowcount)
            else:
                logger.info("[Step3] --force-rebalance: dry-run模式，跳过DB更新")
        logger.info("[Step3] 信号: %d只目标, rebalance=%s",
                     len(signal_result.target_weights), signal_result.is_rebalance)

        # Step 3.5: 影子选股(可选,失败不阻塞)
        if signal_result.is_rebalance:
            for shadow_fn in [generate_shadow_lgbm_signals, generate_shadow_lgbm_inertia]:
                try:
                    shadow_fn(trade_date, conn, dry_run)
                except Exception as e:
                    logger.warning("[Shadow] %s失败: %s", shadow_fn.__name__, e)

        # Step 5: 收尾
        if not dry_run:
            log_step(conn, "signal_phase", "success")

        elapsed = time.time() - t_total
        logger.info("[SIGNAL PHASE] 完成: %.0fs", elapsed)

    except Exception as e:
        logger.error("[SIGNAL PHASE] 失败: %s\n%s", e, traceback.format_exc())
        if not dry_run:
            log_step(conn, "signal_phase", "failed", str(e))
        sys.exit(1)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# Execute Phase — T+1日 09:31
# ════════════════════════════════════════════════════════════


def run_execute_phase(exec_date: date, dry_run: bool, skip_fetch: bool, execution_mode: str = "paper"):
    """T+1日执行编排: QMT连接→读信号→风控→执行→对账→通知。"""
    logger.info("=" * 60)
    logger.info("[EXECUTE PHASE] exec_date=%s, mode=%s", exec_date, execution_mode)
    exec_mode = execution_mode

    # Live模式: 启动QMT
    if exec_mode == "live":
        settings.EXECUTION_MODE = "live"
        try:
            from app.services.qmt_connection_manager import qmt_manager
            qmt_manager.startup()
        except Exception as e:
            logger.error("[Execute] QMT启动失败: %s", e)

    conn = get_sync_conn()
    t_total = time.time()

    try:
        if not acquire_lock(conn) or not is_trading_day(conn, exec_date):
            return

        notif_svc = _get_notif_service()

        # Step 5: 读信号
        signal_svc = SignalService()
        signal_date = get_prev_trading_day(conn, exec_date)
        signals_list = signal_svc.get_latest_signals(conn=conn, strategy_id=settings.PAPER_STRATEGY_ID, signal_date=signal_date)
        hedged_target = {s["code"]: s["target_weight"] for s in signals_list}
        is_rebalance = any(s["action"] == "rebalance" for s in signals_list) if signals_list else False
        logger.info("[Step5] 信号日=%s, 目标=%d只, rebalance=%s", signal_date, len(hedged_target), is_rebalance)

        # Step 5.5: 数据拉取(如需)
        if not skip_fetch:
            fetch_daily_data(exec_date, skip_fetch=False)

        # Step 5.7: QMT drift检测(live模式)
        if exec_mode == "live" and hedged_target:
            try:
                from app.services.qmt_connection_manager import qmt_manager
                qmt_pos = qmt_manager.broker.query_positions() if qmt_manager.broker else []
                actual_holdings = {p.get("stock_code", ""): p["volume"] for p in qmt_pos if p.get("market_value", 0) > 1000}
                target_count = len(hedged_target)
                if len(actual_holdings) < target_count * 0.5:
                    is_rebalance = True
                    logger.info("[Step5.7] 首次建仓检测: actual=%d < target×0.5=%d",
                                len(actual_holdings), target_count * 0.5)
            except Exception as e:
                logger.warning("[Step5.7] Drift检测失败: %s", e)

        # Step 5.8: 开盘跳空预检
        price_data_t = load_today_prices(exec_date, conn)

        # Step 5.8.1: 价格数据校验 (2026-04-14新增)
        if price_data_t.empty:
            if exec_mode == "live":
                logger.warning("[Step5.8] price_data为空，live模式继续(依赖QMT实时价)")
            else:
                logger.error("[Step5.8] price_data为空，paper模式中止执行")
                if not dry_run:
                    log_step(conn, f"execute_phase_{exec_mode}", "failed", "price_data为空")
                return

        check_opening_gap(exec_date, price_data_t, conn, notif_svc, dry_run)

        # Step 5.9: 熔断检查
        cb = check_circuit_breaker_sync(
            conn=conn,
            strategy_id=settings.PAPER_STRATEGY_ID,
            exec_date=exec_date,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        logger.info("[Step5.9] 熔断: L%s", cb.get("level", 0))

        # Step 6: 执行调仓
        exec_svc = ExecutionService()
        exec_result = None

        if is_rebalance and hedged_target:
            exec_svc.process_pending_orders(
                conn=conn, strategy_id=settings.PAPER_STRATEGY_ID,
                exec_date=exec_date, price_data=price_data_t,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                cb_level=cb.get("level", 0),
            )
            exec_result = exec_svc.execute_rebalance(
                conn=conn, strategy_id=settings.PAPER_STRATEGY_ID,
                exec_date=exec_date, target_weights=hedged_target,
                cb_level=cb.get("level", 0), position_multiplier=0.5,
                price_data=price_data_t,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                signal_date=signal_date, execution_mode=exec_mode,
            )
            fill_count = len(exec_result.fills) if exec_result and hasattr(exec_result, "fills") else 0
            logger.info("[Step6] 执行: %d笔成交", fill_count)
        else:
            logger.info("[Step6] 无调仓")

        if not dry_run:
            log_step(conn, f"execute_phase_{exec_mode}", "success")

        elapsed = time.time() - t_total
        logger.info("[EXECUTE PHASE] 完成: %.0fs", elapsed)

    except Exception as e:
        logger.error("[EXECUTE PHASE] 失败: %s\n%s", e, traceback.format_exc())
        if not dry_run:
            log_step(conn, f"execute_phase_{exec_mode}", "failed", str(e))
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# CLI入口
# ════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="QuantMind Paper Trading 两阶段管道")
    parser.add_argument("phase", choices=["signal", "execute"])
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--skip-factors", action="store_true")
    parser.add_argument("--force-rebalance", action="store_true", help="Force rebalance regardless of schedule")
    parser.add_argument("--execution-mode", choices=["paper", "live"], default=None)
    args = parser.parse_args()

    if not settings.PAPER_STRATEGY_ID:
        logger.error("PAPER_STRATEGY_ID未配置!")
        sys.exit(1)

    trade_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    if args.phase == "signal":
        run_signal_phase(trade_date, args.dry_run, args.skip_fetch, args.skip_factors, args.force_rebalance)
    elif args.phase == "execute":
        exec_mode = args.execution_mode or settings.EXECUTION_MODE
        run_execute_phase(trade_date, args.dry_run, args.skip_fetch, execution_mode=exec_mode)


if __name__ == "__main__":
    main()
