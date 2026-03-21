#!/usr/bin/env python3
"""Paper Trading 每日管道 — T日盘后自动运行。

流程:
  Step 0: 健康预检
  Step 1: 拉取T日行情数据
  Step 2: 计算T日因子
  Step 3: 生成信号+目标持仓
  Step 4: Beta对冲权重调整
  Step 5: 执行调仓（SimBroker）
  Step 6: 保存状态（trade_log, position_snapshot, performance_series）
  Step 7: 发送通知

CLAUDE.md调度时序:
  T日 16:30  拉取T日收盘数据
  T日 17:00  因子计算
  T日 17:20  信号生成 + 调仓
  T日 17:30  通知推送

用法:
    python scripts/run_paper_trading.py --date 2026-03-21
    python scripts/run_paper_trading.py  # 默认今天
    python scripts/run_paper_trading.py --dry-run  # 不写DB
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
        conn.rollback()


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


def fetch_daily_data(trade_date: date, conn) -> bool:
    """Step 1: 拉取T日行情。"""
    from app.data_fetcher.tushare_fetcher import TushareFetcher
    from app.data_fetcher.data_loader import upsert_klines_daily, upsert_daily_basic

    fetcher = TushareFetcher(settings.TUSHARE_TOKEN)
    td_str = trade_date.strftime("%Y%m%d")

    # klines + adj + limits
    logger.info(f"[Step1] 拉取 klines_daily {td_str}...")
    df_klines = fetcher.merge_daily_data(td_str)
    if df_klines.empty:
        logger.warning(f"[Step1] {td_str} 无行情数据")
        return False
    upsert_klines_daily(df_klines, conn)

    # daily_basic
    logger.info(f"[Step1] 拉取 daily_basic {td_str}...")
    df_basic = fetcher.fetch_daily_basic_by_date(td_str)
    if not df_basic.empty:
        upsert_daily_basic(df_basic, conn)

    logger.info(f"[Step1] 数据拉取完成: klines={len(df_klines)}, basic={len(df_basic)}")
    return True


def compute_factors(trade_date: date, conn) -> bool:
    """Step 2: 计算T日因子。"""
    logger.info(f"[Step2] 计算因子 {trade_date}...")
    factor_df = compute_daily_factors(trade_date, factor_set="full", conn=conn)
    if factor_df.empty:
        logger.warning(f"[Step2] {trade_date} 因子计算结果为空")
        return False

    rows = save_daily_factors(trade_date, factor_df, conn=conn)
    logger.info(f"[Step2] 因子写入完成: {rows}行")
    return True


def build_signals(
    trade_date: date, conn
) -> tuple[dict[str, float], pd.Series]:
    """Step 3: 生成信号和目标持仓。

    Returns:
        (target_weights, scores) — 目标权重字典和原始分数
    """
    logger.info(f"[Step3] 生成信号 {trade_date}...")
    config = PAPER_TRADING_CONFIG

    fv = load_factor_values(trade_date, conn)
    if fv.empty:
        logger.warning(f"[Step3] {trade_date} 无因子数据")
        return {}, pd.Series()

    universe = load_universe(trade_date, conn)
    industry = load_industry(conn)

    composer = SignalComposer(config)
    builder = PortfolioBuilder(config)

    scores = composer.compose(fv, universe)
    if scores.empty:
        logger.warning(f"[Step3] {trade_date} 信号为空")
        return {}, scores

    # 读取当前持仓作为prev_weights
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

    return target, scores


def save_signals(
    trade_date: date,
    target: dict[str, float],
    scores: pd.Series,
    conn,
):
    """将信号写入signals表。"""
    if not target:
        return
    cur = conn.cursor()
    sorted_codes = sorted(target.keys(), key=lambda c: target[c], reverse=True)
    for rank, code in enumerate(sorted_codes, 1):
        score = float(scores.get(code, 0)) if not scores.empty else 0
        cur.execute(
            """INSERT INTO signals
               (code, trade_date, strategy_id, alpha_score, rank,
                target_weight, action, execution_mode)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'paper')
               ON CONFLICT (code, trade_date, strategy_id) DO UPDATE SET
                alpha_score=EXCLUDED.alpha_score, rank=EXCLUDED.rank,
                target_weight=EXCLUDED.target_weight, action=EXCLUDED.action""",
            (
                code,
                trade_date,
                settings.PAPER_STRATEGY_ID,
                score,
                rank,
                target[code],
                "buy",
            ),
        )
    conn.commit()


def load_today_prices(trade_date: date, conn) -> pd.DataFrame:
    """加载当日价格数据（用于调仓执行）。"""
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


def format_report(
    trade_date: date,
    fills: list[Fill],
    nav: float,
    daily_ret: float,
    cum_ret: float,
    position_count: int,
    is_rebalance: bool,
    beta: float,
) -> str:
    """格式化每日报告。"""
    buys = [f for f in fills if f.direction == "buy"]
    sells = [f for f in fills if f.direction == "sell"]

    lines = [
        f"[QuantMind Paper] {trade_date} 盘后报告",
        "─" * 40,
        f"调仓: {'是（月度调仓）' if is_rebalance else '否'}",
        f"持仓: {position_count}只 | NAV: ¥{nav:,.0f}",
        f"日收益: {daily_ret:+.2%} | 累计: {cum_ret:+.2%}",
        f"Beta: {beta:.3f}",
    ]

    if fills:
        lines.append("─" * 40)
        if buys:
            buy_codes = ", ".join(f.code for f in buys[:5])
            if len(buys) > 5:
                buy_codes += f" +{len(buys)-5}"
            lines.append(f"买入({len(buys)}): {buy_codes}")
        if sells:
            sell_codes = ", ".join(f.code for f in sells[:5])
            if len(sells) > 5:
                sell_codes += f" +{len(sells)-5}"
            lines.append(f"卖出({len(sells)}): {sell_codes}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="QuantMind Paper Trading 每日管道")
    parser.add_argument("--date", type=str, help="交易日期 YYYY-MM-DD (默认今天)")
    parser.add_argument("--dry-run", action="store_true", help="仅模拟，不写DB")
    parser.add_argument("--skip-fetch", action="store_true", help="跳过数据拉取（数据已就绪）")
    parser.add_argument("--skip-factors", action="store_true", help="跳过因子计算（因子已就绪）")
    args = parser.parse_args()

    trade_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else date.today()
    )

    logger.info(f"{'='*60}")
    logger.info(f"Paper Trading 管道启动: {trade_date}")
    logger.info(f"策略: {settings.PAPER_STRATEGY_ID}")
    logger.info(f"模式: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    logger.info(f"{'='*60}")

    if not settings.PAPER_STRATEGY_ID:
        logger.error("PAPER_STRATEGY_ID未配置！请先运行 setup_paper_trading.py")
        sys.exit(1)

    conn = _get_sync_conn()
    t_total = time.time()

    try:
        # ── Step 0: 交易日检查 + 健康预检 ──
        if not is_trading_day(trade_date, conn):
            logger.info(f"{trade_date} 非交易日，退出")
            conn.close()
            return

        logger.info("[Step0] 健康预检...")
        health = run_health_check(trade_date, conn, write_db=not args.dry_run)
        if not health["all_pass"]:
            logger.error("[Step0] 预检失败，管道停止")
            log_step(conn, "paper_pipeline", "failed", "健康预检失败")
            failed = [k for k, v in health.items() if not v and k != "all_pass"]
            send_alert(
                "P0", f"健康预检失败 {trade_date}",
                f"失败项: {', '.join(failed)}",
                settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn,
            )
            conn.close()
            sys.exit(1)

        # ── Step 1: 拉取数据 ──
        if args.skip_fetch:
            logger.info("[Step1] 跳过数据拉取")
        else:
            t1 = time.time()
            ok = fetch_daily_data(trade_date, conn)
            if not ok:
                logger.error("[Step1] 数据拉取失败")
                log_step(conn, "data_fetch", "failed", "无数据返回")
                conn.close()
                sys.exit(1)
            logger.info(f"[Step1] 完成 ({time.time()-t1:.0f}s)")
            if not args.dry_run:
                log_step(conn, "data_fetch", "success")

        # ── Step 2: 因子计算 ──
        if args.skip_factors:
            logger.info("[Step2] 跳过因子计算")
        else:
            t2 = time.time()
            ok = compute_factors(trade_date, conn)
            if not ok:
                logger.error("[Step2] 因子计算失败")
                log_step(conn, "factor_calc", "failed", "因子为空")
                conn.close()
                sys.exit(1)
            logger.info(f"[Step2] 完成 ({time.time()-t2:.0f}s)")
            if not args.dry_run:
                log_step(conn, "factor_calc", "success")

        # ── Step 3: 信号生成 ──
        t3 = time.time()
        target_weights, scores = build_signals(trade_date, conn)
        if not target_weights:
            logger.error("[Step3] 信号生成失败")
            log_step(conn, "signal_gen", "failed", "无目标持仓")
            conn.close()
            sys.exit(1)
        logger.info(f"[Step3] 完成 ({time.time()-t3:.0f}s)")

        if not args.dry_run:
            save_signals(trade_date, target_weights, scores, conn)
            log_step(conn, "signal_gen", "success",
                     result={"n_stocks": len(target_weights)})

        # ── Step 4: Beta对冲 ──
        beta = calc_portfolio_beta(
            trade_date, settings.PAPER_STRATEGY_ID, lookback_days=60, conn=conn
        )
        hedged_weights = apply_beta_hedge(target_weights, beta)
        logger.info(f"[Step4] Beta={beta:.3f}, 权重缩放后总权重={sum(hedged_weights.values()):.3f}")

        # ── Step 5+6: 加载状态 + 执行调仓 ──
        paper_broker = PaperBroker(
            strategy_id=settings.PAPER_STRATEGY_ID,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        paper_broker.load_state(conn)

        is_rebalance = paper_broker.needs_rebalance(trade_date, conn)
        fills: list[Fill] = []

        price_data = load_today_prices(trade_date, conn)
        today_close = dict(zip(price_data["code"], price_data["close"]))
        benchmark_close = get_benchmark_close(trade_date, conn)

        if is_rebalance:
            logger.info("[Step5] 执行月度调仓...")
            fills = paper_broker.execute_rebalance(
                hedged_weights, trade_date, price_data
            )
            logger.info(f"[Step5] 调仓完成: {len(fills)}笔成交")
        else:
            logger.info("[Step5] 非调仓日，仅更新NAV")
            paper_broker.broker.new_day()

        # ── Step 6: 保存状态 ──
        nav = paper_broker.get_current_nav(today_close)
        prev_nav = paper_broker.state.nav if paper_broker.state else settings.PAPER_INITIAL_CAPITAL
        daily_ret = (nav / prev_nav - 1) if prev_nav > 0 else 0
        cum_ret = (nav / settings.PAPER_INITIAL_CAPITAL - 1)

        if not args.dry_run:
            paper_broker.save_state(
                trade_date, fills, today_close, benchmark_close, conn
            )
            log_step(conn, "state_save", "success",
                     result={"nav": round(nav, 2), "fills": len(fills)})
        else:
            logger.info(f"[DRY-RUN] NAV={nav:.0f}, 跳过DB写入")

        # ── Step 7: 报告 ──
        report = format_report(
            trade_date, fills, nav, daily_ret, cum_ret,
            len(paper_broker.broker.holdings), is_rebalance, beta
        )
        print("\n" + report)

        # ── Step 7: 通知 ──
        if not args.dry_run:
            buys = [f.code for f in fills if f.direction == "buy"]
            sells = [f.code for f in fills if f.direction == "sell"]
            send_daily_report(
                trade_date=trade_date,
                nav=nav,
                daily_return=daily_ret,
                cum_return=cum_ret,
                position_count=len(paper_broker.broker.holdings),
                is_rebalance=is_rebalance,
                beta=beta,
                buys=buys,
                sells=sells,
                rejected=[],
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                webhook_url=settings.DINGTALK_WEBHOOK_URL,
                secret=settings.DINGTALK_SECRET,
                conn=conn,
            )

        elapsed = time.time() - t_total
        logger.info(f"管道完成: {elapsed:.0f}s")
        if not args.dry_run:
            log_step(conn, "paper_pipeline", "success",
                     result={"elapsed_sec": round(elapsed), "nav": round(nav, 2)})

    except Exception as e:
        logger.error(f"管道异常: {e}")
        traceback.print_exc()
        log_step(conn, "paper_pipeline", "failed", str(e))
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
