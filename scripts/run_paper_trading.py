#!/usr/bin/env python3
"""Paper Trading 两阶段管道。

R1 fix: 拆分为信号阶段(T日盘后) + 执行阶段(T+1日盘前)，
与CLAUDE.md调度时序完全一致。

Phase 1 — signal（T日 16:30 cron触发）:
  Step 0: 健康预检
  Step 1: 拉取T日行情数据
  Step 2: 计算T日因子
  Step 3: 生成信号 + Beta对冲 → 存signals表
  Step 4: 通知（调仓预告）

Phase 2 — execute（T+1日 09:00 cron触发）:
  Step 5: 读取昨日信号
  Step 6: 用T+1日open价格执行调仓
  Step 7: 保存状态（trade_log, position_snapshot, performance_series）
  Step 8: 通知（执行结果）

用法:
    # T日盘后: 生成信号
    python scripts/run_paper_trading.py signal --date 2026-03-21

    # T+1日盘前: 执行调仓
    python scripts/run_paper_trading.py execute --date 2026-03-24

    # 非调仓日NAV更新（T+1执行阶段会自动判断）
    python scripts/run_paper_trading.py execute --date 2026-03-24

    # 调试
    python scripts/run_paper_trading.py signal --date 2026-03-21 --dry-run
"""

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from app.config import settings
from app.services.price_utils import _get_sync_conn
from engines.backtest_engine import Fill
from engines.beta_hedge import apply_beta_hedge, calc_portfolio_beta
from engines.factor_engine import compute_daily_factors, save_daily_factors
from engines.paper_broker import PaperBroker
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
)
from services.notification_service import send_alert, send_daily_report
from health_check import run_health_check
from run_backtest import load_factor_values, load_industry, load_universe

# ── 日志配置 ──
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "paper_trading.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("paper_trading")


# ════════════════════════════════════════════════════════════
# 共用工具函数
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


def is_trading_day(trade_date: date, conn) -> bool:
    """检查是否为交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT is_trading_day FROM trading_calendar
           WHERE trade_date = %s AND market = 'astock'""",
        (trade_date,),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def get_next_trading_day(trade_date: date, conn) -> date:
    """获取trade_date之后的下一个交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT MIN(trade_date) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date > %s""",
        (trade_date,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_prev_trading_day(trade_date: date, conn) -> date:
    """获取trade_date之前的上一个交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT MAX(trade_date) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date < %s""",
        (trade_date,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def acquire_lock(conn) -> bool:
    """R7 fix: pg_advisory_lock 并发保护。"""
    cur = conn.cursor()
    cur.execute("SELECT pg_try_advisory_lock(202603210001)")
    got = cur.fetchone()[0]
    if not got:
        logger.error("另一实例正在运行，退出")
    return got


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


# ════════════════════════════════════════════════════════════
# Phase 1: SIGNAL — T日盘后 16:30
# ════════════════════════════════════════════════════════════

def run_signal_phase(trade_date: date, dry_run: bool, skip_fetch: bool, skip_factors: bool):
    """T日盘后：拉数据 → 算因子 → 生成信号存库。

    信号存入signals表，次日执行阶段读取。
    """
    logger.info(f"{'='*60}")
    logger.info(f"[SIGNAL PHASE] T日={trade_date}")
    logger.info(f"{'='*60}")

    conn = _get_sync_conn()
    t_total = time.time()

    try:
        if not acquire_lock(conn):
            conn.close()
            sys.exit(1)

        if not is_trading_day(trade_date, conn):
            logger.info(f"{trade_date} 非交易日，退出")
            conn.close()
            return

        # ── Step 0: 健康预检 ──
        logger.info("[Step0] 健康预检...")
        health = run_health_check(trade_date, conn, write_db=not dry_run)
        if not health["all_pass"]:
            logger.error("[Step0] 预检失败，管道停止")
            if not dry_run:
                log_step(conn, "signal_phase", "failed", "健康预检失败")
                failed = [k for k, v in health.items() if not v and k != "all_pass"]
                send_alert(
                    "P0", f"健康预检失败 {trade_date}",
                    f"失败项: {', '.join(failed)}",
                    settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn,
                )
            conn.close()
            sys.exit(1)

        # ── Step 1: 拉取数据 ──
        if skip_fetch:
            logger.info("[Step1] 跳过数据拉取")
        else:
            from app.data_fetcher.tushare_fetcher import TushareFetcher
            from app.data_fetcher.data_loader import upsert_klines_daily, upsert_daily_basic

            fetcher = TushareFetcher(settings.TUSHARE_TOKEN)
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

            logger.info(f"[Step1] 完成 ({time.time()-t1:.0f}s): klines={len(df_klines)}, basic={len(df_basic)}")
            if not dry_run:
                log_step(conn, "data_fetch", "success")

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

        # ── Step 3: 信号生成 + Beta对冲 ──
        t3 = time.time()
        config = PAPER_TRADING_CONFIG

        fv = load_factor_values(trade_date, conn)
        if fv.empty:
            logger.error(f"[Step3] {trade_date} 无因子数据")
            log_step(conn, "signal_gen", "failed", "无因子")
            conn.close()
            sys.exit(1)

        universe = load_universe(trade_date, conn)
        industry = load_industry(conn)

        composer = SignalComposer(config)
        builder = PortfolioBuilder(config)

        scores = composer.compose(fv, universe)
        if scores.empty:
            logger.error(f"[Step3] 信号为空")
            log_step(conn, "signal_gen", "failed", "scores为空")
            conn.close()
            sys.exit(1)

        # 读取当前持仓
        cur = conn.cursor()
        cur.execute(
            """SELECT code, weight FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = 'paper'
                 AND trade_date = (
                   SELECT MAX(trade_date) FROM position_snapshot
                   WHERE strategy_id = %s AND execution_mode = 'paper'
                 )""",
            (settings.PAPER_STRATEGY_ID, settings.PAPER_STRATEGY_ID),
        )
        prev_weights = {r[0]: float(r[1] or 0) for r in cur.fetchall()}

        target = builder.build(scores, industry, prev_weights)
        logger.info(f"[Step3] 目标持仓: {len(target)}只, 总权重={sum(target.values()):.3f}")

        # Beta对冲
        beta = calc_portfolio_beta(
            trade_date, settings.PAPER_STRATEGY_ID, lookback_days=60, conn=conn
        )
        hedged_target = apply_beta_hedge(target, beta)
        logger.info(f"[Step3] Beta={beta:.3f}, 对冲后总权重={sum(hedged_target.values()):.3f}")

        # 检查是否需要调仓
        paper_broker = PaperBroker(
            strategy_id=settings.PAPER_STRATEGY_ID,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        paper_broker.load_state(conn)
        is_rebalance = paper_broker.needs_rebalance(trade_date, conn)

        # ── 存入signals表（含hedged权重）──
        if not dry_run:
            cur = conn.cursor()
            # 清除当日旧信号
            cur.execute(
                """DELETE FROM signals
                   WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'paper'""",
                (trade_date, settings.PAPER_STRATEGY_ID),
            )
            sorted_codes = sorted(hedged_target.keys(), key=lambda c: hedged_target[c], reverse=True)
            for rank, code in enumerate(sorted_codes, 1):
                score = float(scores.get(code, 0)) if not scores.empty else 0
                action = "rebalance" if is_rebalance else "hold"
                cur.execute(
                    """INSERT INTO signals
                       (code, trade_date, strategy_id, alpha_score, rank,
                        target_weight, action, execution_mode)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'paper')""",
                    (code, trade_date, settings.PAPER_STRATEGY_ID,
                     score, rank, hedged_target[code], action),
                )
            conn.commit()
            log_step(conn, "signal_gen", "success",
                     result={"n_stocks": len(hedged_target), "is_rebalance": is_rebalance,
                             "beta": round(beta, 3)})

        logger.info(f"[Step3] 完成 ({time.time()-t3:.0f}s)")

        # ── Step 4: 信号预告通知 ──
        next_td = get_next_trading_day(trade_date, conn)
        msg = (f"[信号预告] {trade_date}\n"
               f"调仓: {'是（月度）' if is_rebalance else '否'}\n"
               f"目标: {len(hedged_target)}只, Beta={beta:.3f}\n"
               f"执行日: {next_td}\n"
               f"Top5: {', '.join(sorted_codes[:5]) if not dry_run else 'dry-run'}")
        logger.info(msg)

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
    """T+1日盘前：读昨日信号 → 用今日open价格执行 → 保存状态。

    Args:
        exec_date: 执行日（T+1日，当天）
        dry_run: 不写DB
        skip_fetch: 跳过T+1日数据拉取（如果已有）
    """
    logger.info(f"{'='*60}")
    logger.info(f"[EXECUTE PHASE] exec_date={exec_date}")
    logger.info(f"{'='*60}")

    conn = _get_sync_conn()
    t_total = time.time()

    try:
        if not acquire_lock(conn):
            conn.close()
            sys.exit(1)

        if not is_trading_day(exec_date, conn):
            logger.info(f"{exec_date} 非交易日，退出")
            conn.close()
            return

        # ── 查找信号日（上一个交易日）──
        signal_date = get_prev_trading_day(exec_date, conn)
        if not signal_date:
            logger.error("找不到上一交易日")
            conn.close()
            sys.exit(1)
        logger.info(f"[Execute] 信号日={signal_date}, 执行日={exec_date}")

        # ── Step 5: 读取信号 ──
        cur = conn.cursor()
        cur.execute(
            """SELECT code, target_weight, action
               FROM signals
               WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'paper'
               ORDER BY rank""",
            (signal_date, settings.PAPER_STRATEGY_ID),
        )
        signal_rows = cur.fetchall()

        if not signal_rows:
            logger.warning(f"[Step5] {signal_date} 无信号记录。可能信号阶段未运行。")
            # 仍然继续——需要更新非调仓日的NAV
            hedged_target = {}
            is_rebalance = False
        else:
            hedged_target = {r[0]: float(r[1]) for r in signal_rows}
            is_rebalance = signal_rows[0][2] == "rebalance"
            logger.info(f"[Step5] 读取{len(hedged_target)}只信号, action={signal_rows[0][2]}")

        # ── Step 5.5: 拉取T+1日数据（如果还没有）──
        if not skip_fetch:
            cur.execute(
                "SELECT COUNT(*) FROM klines_daily WHERE trade_date = %s",
                (exec_date,),
            )
            existing = cur.fetchone()[0]
            if existing < 100:
                logger.info(f"[Step5.5] T+1日数据不足({existing}行), 拉取...")
                from app.data_fetcher.tushare_fetcher import TushareFetcher
                from app.data_fetcher.data_loader import upsert_klines_daily, upsert_daily_basic

                fetcher = TushareFetcher(settings.TUSHARE_TOKEN)
                td_str = exec_date.strftime("%Y%m%d")
                df_k = fetcher.merge_daily_data(td_str)
                if not df_k.empty:
                    upsert_klines_daily(df_k, conn)
                df_b = fetcher.fetch_daily_basic_by_date(td_str)
                if not df_b.empty:
                    upsert_daily_basic(df_b, conn)
                logger.info(f"[Step5.5] T+1数据拉取完成: {len(df_k)}行")

        # ── 加载T+1日价格（open用于执行，close用于NAV）──
        price_data = load_today_prices(exec_date, conn)
        if price_data.empty:
            logger.error(f"[Execute] {exec_date} 无价格数据")
            log_step(conn, "execute_phase", "failed", "T+1无价格数据")
            conn.close()
            sys.exit(1)
        today_close = dict(zip(price_data["code"], price_data["close"]))
        benchmark_close = get_benchmark_close(exec_date, conn)

        # ── Step 6: 执行调仓 ──
        paper_broker = PaperBroker(
            strategy_id=settings.PAPER_STRATEGY_ID,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        paper_broker.load_state(conn)

        fills: list[Fill] = []
        beta = 0.0

        if is_rebalance and hedged_target:
            logger.info(f"[Step6] 执行调仓 (T+1 open价格)...")
            # R1 fix: 使用exec_date的价格数据（T+1日open价格）
            fills = paper_broker.execute_rebalance(
                hedged_target, exec_date, price_data
            )
            logger.info(f"[Step6] 调仓完成: {len(fills)}笔成交")

            # 从信号日读取beta
            cur.execute(
                """SELECT result_json->>'beta'
                   FROM scheduler_task_log
                   WHERE task_name = 'signal_gen'
                   ORDER BY created_at DESC LIMIT 1""",
            )
            beta_row = cur.fetchone()
            if beta_row and beta_row[0]:
                beta = float(beta_row[0])
        else:
            logger.info("[Step6] 非调仓日，仅更新NAV")
            paper_broker.broker.new_day()

        # ── Step 7: 保存状态 ──
        nav = paper_broker.get_current_nav(today_close)
        prev_nav = paper_broker.state.nav if paper_broker.state else settings.PAPER_INITIAL_CAPITAL
        daily_ret = (nav / prev_nav - 1) if prev_nav > 0 else 0
        cum_ret = (nav / settings.PAPER_INITIAL_CAPITAL - 1)

        if not dry_run:
            paper_broker.save_state(
                exec_date, fills, today_close, benchmark_close, conn
            )
            log_step(conn, "execute_phase", "success",
                     result={"nav": round(nav, 2), "fills": len(fills),
                             "daily_return": round(daily_ret, 6)})

        # ── Step 8: 通知 ──
        report_lines = [
            f"[QuantMind Paper] {exec_date} 执行报告",
            "─" * 40,
            f"信号日: {signal_date} | 执行日: {exec_date}",
            f"调仓: {'是' if is_rebalance else '否'}",
            f"持仓: {len(paper_broker.broker.holdings)}只 | NAV: ¥{nav:,.0f}",
            f"日收益: {daily_ret:+.2%} | 累计: {cum_ret:+.2%}",
        ]
        if fills:
            buy_list = [f.code for f in fills if f.direction == "buy"]
            sell_list = [f.code for f in fills if f.direction == "sell"]
            if buy_list:
                report_lines.append(f"买入({len(buy_list)}): {', '.join(buy_list[:5])}")
            if sell_list:
                report_lines.append(f"卖出({len(sell_list)}): {', '.join(sell_list[:5])}")

        report = "\n".join(report_lines)
        print("\n" + report)

        if not dry_run:
            buys = [f.code for f in fills if f.direction == "buy"]
            sells = [f.code for f in fills if f.direction == "sell"]
            send_daily_report(
                trade_date=exec_date,
                nav=nav, daily_return=daily_ret, cum_return=cum_ret,
                position_count=len(paper_broker.broker.holdings),
                is_rebalance=is_rebalance, beta=beta,
                buys=buys, sells=sells, rejected=[],
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                webhook_url=settings.DINGTALK_WEBHOOK_URL,
                secret=settings.DINGTALK_SECRET, conn=conn,
            )

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
