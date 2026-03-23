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
from engines.backtest_engine import Fill, PendingOrder
from engines.beta_hedge import calc_portfolio_beta  # apply_beta_hedge removed: A股无做空工具
from engines.factor_engine import compute_daily_factors, save_daily_factors
from engines.paper_broker import PaperBroker
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
)
from app.services.notification_service import send_alert, send_daily_report
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


def check_circuit_breaker(
    conn, strategy_id: str, exec_date: date, initial_capital: float
) -> dict:
    """4级熔断检查（DESIGN_V5 §8.1 + risk评审方案）。

    L1: 单策略日亏>3% → 暂停1天(次日自动恢复)
    L2: 总组合日亏>5% → 全部暂停+P0告警
    L3: 月亏>10% → 降仓50%
    L4: 累计亏损>25%(NAV<750k) → 停止所有交易+人工审批
    阈值来源: DESIGN_V5 §8.1，用户确认不要过于敏感

    Returns:
        {"level": 0-4, "action": str, "reason": str}
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT trade_date, nav::float, daily_return::float
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date DESC LIMIT 20""",
        (strategy_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return {"level": 0, "action": "normal", "reason": "无历史数据(首次运行)"}

    latest_nav = rows[0][1]
    latest_ret = rows[0][2]

    # L4: 累计亏损 > 25%
    cum_loss = (latest_nav / initial_capital) - 1
    if cum_loss < -0.25:
        return {"level": 4, "action": "halt",
                "reason": f"累计亏损{cum_loss:.1%}, NAV={latest_nav:.0f}"}

    # L3: 滚动5日亏>7% OR 滚动20日亏>10%（OR条件, 任一触发即降仓）
    # 滚动5日（日频响应: 短窗口快速检测急跌）
    rolling_5d_loss = None
    if len(rows) >= 5:
        rolling_5d = 1.0
        for r in rows[:5]:
            rolling_5d *= (1 + r[2])
        rolling_5d_loss = rolling_5d - 1

    # 滚动20日
    rolling_20d_loss = None
    if len(rows) >= 5:
        rolling_20d = 1.0
        for r in rows[:20]:
            rolling_20d *= (1 + r[2])
        rolling_20d_loss = rolling_20d - 1

    l3_reasons = []
    if rolling_5d_loss is not None and rolling_5d_loss < -0.07:
        l3_reasons.append(f"5日累计{rolling_5d_loss:.1%}")
    if rolling_20d_loss is not None and rolling_20d_loss < -0.10:
        l3_reasons.append(f"20日累计{rolling_20d_loss:.1%}")
    if l3_reasons:
        return {"level": 3, "action": "reduce",
                "reason": " + ".join(l3_reasons)}

    # L2: 单日亏损 > 5%
    if latest_ret < -0.05:
        return {"level": 2, "action": "pause",
                "reason": f"昨日亏损{latest_ret:.1%}"}

    # L1: 单日亏损 > 3%
    if latest_ret < -0.03:
        return {"level": 1, "action": "skip_rebalance",
                "reason": f"昨日亏损{latest_ret:.1%}"}

    return {"level": 0, "action": "normal", "reason": "正常"}


def run_daily_risk_check(broker, today_close: dict, nav: float, fills: list) -> list[str]:
    """风控日检（risk评审blocking要求#2）。

    检查: 单股权重/现金比例/持仓数量/调仓拒绝率。
    返回异常列表（空=全部正常）。
    """
    warnings = []

    # 单股最大权重 > 15%
    if broker.holdings and nav > 0:
        max_weight = max(
            shares * today_close.get(code, 0) / nav
            for code, shares in broker.holdings.items()
        )
        if max_weight > 0.15:
            warnings.append(f"单股权重超限: {max_weight:.1%} > 15%")

    # 现金比例异常
    cash_ratio = broker.cash / nav if nav > 0 else 1
    if cash_ratio > 0.15:
        warnings.append(f"现金比例过高: {cash_ratio:.1%}")
    elif cash_ratio < 0.005 and broker.holdings:
        warnings.append(f"现金比例过低: {cash_ratio:.1%}")

    # 持仓数量异常
    pos_count = len(broker.holdings)
    if pos_count < 15 and pos_count > 0:
        warnings.append(f"持仓不足: {pos_count}只 < 15")
    elif pos_count > 25:
        warnings.append(f"持仓过多: {pos_count}只 > 25")

    return warnings


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

        # ── 因子完整性硬性检查（防止静默降级）──
        # 如果配置要求5因子但实际只拿到<5因子，阻塞并告警
        available_factors = set(fv.columns) if hasattr(fv, 'columns') else set()
        if 'factor_name' in fv.columns:
            available_factors = set(fv['factor_name'].unique())
        required_factors = set(config.factor_names)
        missing_factors = required_factors - available_factors
        if missing_factors:
            msg = f"因子缺失: {missing_factors}。配置要求{len(required_factors)}因子，实际只有{len(required_factors - missing_factors)}。不允许静默降级。"
            logger.error(f"[Step3] P0 {msg}")
            if not dry_run:
                log_step(conn, "signal_gen", "failed", msg)
                send_alert("P0", f"因子缺失 {trade_date}", msg,
                           settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)
            conn.close()
            sys.exit(1)

        # ── 检查2: 因子截面覆盖率（每个因子当日覆盖股票数）──
        for fname in config.factor_names:
            if 'factor_name' in fv.columns:
                count = fv[fv['factor_name'] == fname].shape[0]
            else:
                count = len(fv)
            if count < 1000:
                msg = (f"因子 {fname} 截面覆盖率严重不足: {count}只 < 1000。"
                       f"可能数据源故障或拉取异常，阻塞信号生成。")
                logger.error(f"[Step3] P0 {msg}")
                if not dry_run:
                    log_step(conn, "signal_gen", "failed", msg)
                    send_alert("P0", f"因子覆盖率严重不足 {trade_date}", msg,
                               settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)
                conn.close()
                sys.exit(1)
            elif count < 3000:
                msg = (f"因子 {fname} 截面覆盖率偏低: {count}只 < 3000。"
                       f"信号生成继续，但请排查数据完整性。")
                logger.warning(f"[Step3] P1 {msg}")
                if not dry_run:
                    send_alert("P1", f"因子覆盖率偏低 {trade_date}", msg,
                               settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)
            else:
                logger.info(f"[Step3] 因子 {fname} 覆盖率正常: {count}只")

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

        # Beta监控（只记录，不缩放权重）
        # A股无做空工具，Beta对冲=纯减仓，三方讨论共识：去掉
        beta = calc_portfolio_beta(
            trade_date, settings.PAPER_STRATEGY_ID, lookback_days=60, conn=conn
        )
        hedged_target = target  # 不缩放，直接使用原始权重
        logger.info(f"[Step3] Beta={beta:.3f}(监控), 总权重={sum(hedged_target.values()):.3f}")

        # ── 检查3: Top20行业集中度（最大行业权重<25%）──
        if hedged_target:
            top20_codes = sorted(hedged_target, key=lambda c: hedged_target[c], reverse=True)[:20]
            top20_weights = {c: hedged_target[c] for c in top20_codes}
            # join symbols.industry_sw1 获取行业
            if top20_codes:
                cur = conn.cursor()
                placeholders = ','.join(['%s'] * len(top20_codes))
                cur.execute(
                    f"""SELECT code, industry_sw1 FROM symbols
                        WHERE code IN ({placeholders})""",
                    tuple(top20_codes),
                )
                code_industry = dict(cur.fetchall())
                # 按行业汇总权重
                industry_weights: dict[str, float] = {}
                for code in top20_codes:
                    ind = code_industry.get(code, "未知")
                    industry_weights[ind] = industry_weights.get(ind, 0) + top20_weights[code]
                max_ind = max(industry_weights, key=industry_weights.get) if industry_weights else "N/A"
                max_ind_weight = industry_weights.get(max_ind, 0)
                logger.info(f"[Step3] 行业集中度: 最大行业={max_ind} 权重={max_ind_weight:.1%}")
                if max_ind_weight > 0.25:
                    msg = (f"Top20持仓行业集中度过高: {max_ind} 权重={max_ind_weight:.1%} > 25%。"
                           f"行业分布: {', '.join(f'{k}={v:.1%}' for k, v in sorted(industry_weights.items(), key=lambda x: -x[1])[:5])}")
                    logger.warning(f"[Step3] P1 {msg}")
                    if not dry_run:
                        send_alert("P1", f"行业集中度超标 {trade_date}", msg,
                                   settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)

        # ── 检查4: 持仓重合度（与上期持仓比较，<30%重合→P1告警）──
        if hedged_target and prev_weights:
            current_top = set(sorted(hedged_target, key=lambda c: hedged_target[c], reverse=True)[:20])
            prev_top = set(sorted(prev_weights, key=lambda c: prev_weights[c], reverse=True)[:20])
            if prev_top:
                overlap = len(current_top & prev_top)
                overlap_ratio = overlap / max(len(prev_top), 1)
                logger.info(f"[Step3] 持仓重合度: {overlap}/{len(prev_top)} = {overlap_ratio:.0%}")
                if overlap_ratio < 0.30:
                    msg = (f"持仓重合度过低: {overlap}/{len(prev_top)} = {overlap_ratio:.0%} < 30%。"
                           f"换手剧烈，建议人工确认信号合理性。"
                           f"\n新进: {', '.join(sorted(current_top - prev_top)[:10])}"
                           f"\n退出: {', '.join(sorted(prev_top - current_top)[:10])}")
                    logger.warning(f"[Step3] P1 {msg}")
                    if not dry_run:
                        send_alert("P1", f"持仓换手剧烈 {trade_date}", msg,
                                   settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)

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
            hedged_target = {}
            is_rebalance = False
        else:
            hedged_target = {r[0]: float(r[1]) for r in signal_rows}
            signal_action = signal_rows[0][2]
            logger.info(f"[Step5] 读取{len(hedged_target)}只信号, signal_action={signal_action}")

        # ── Step 5.6: 信号调仓标记验证 ──
        # 正常流程：T日signal标记rebalance → T+1日execute执行。
        # signal的rebalance判断是在T日（月末）做的，T+1日不是月末是正常的。
        # 所以execute应该信任signal的action标记。
        #
        # 独立验证只在以下异常场景覆盖：
        # 1. signal标记rebalance但execute发现已无持仓需要清仓（不应该发生）
        # 2. 信号日期与exec_date间隔超过3天（信号已过时）
        if signal_rows:
            # 用交易日间隔而非自然日（A股有国庆9天、五一6天长假）
            cur.execute(
                """SELECT COUNT(*) FROM trading_calendar
                   WHERE market='astock' AND is_trading_day=TRUE
                     AND trade_date > %s AND trade_date < %s""",
                (signal_date, exec_date),
            )
            trading_days_between = cur.fetchone()[0]

            if trading_days_between > 2:
                # 信号过时（中间超过2个交易日=不正常，正常T→T+1间隔0个中间交易日）
                logger.warning(f"[Step5.6] 信号日{signal_date}距执行日{exec_date}中间有{trading_days_between}个交易日，信号过时")
                is_rebalance = False
            elif signal_action == "rebalance":
                is_rebalance = True
                logger.info(f"[Step5.6] 信任信号rebalance标记（T日={signal_date} → T+1={exec_date}，间隔{trading_days_between}交易日）")
            else:
                is_rebalance = False

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

                fetcher = TushareFetcher()
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

        # ── Step 5.9: 熔断检查（risk评审blocking要求）──
        cb = check_circuit_breaker(conn, settings.PAPER_STRATEGY_ID,
                                   exec_date, settings.PAPER_INITIAL_CAPITAL)
        logger.info(f"[Step5.9] 熔断检查: L{cb['level']} - {cb['reason']}")

        if cb["level"] >= 4:
            logger.error(f"[L4 HALT] {cb['reason']}")
            if not dry_run:
                log_step(conn, "circuit_breaker", "halt", cb["reason"])
                send_alert("P0", f"L4熔断 {exec_date}", cb["reason"],
                           settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)
            conn.close()
            sys.exit(1)

        if cb["level"] == 3:
            logger.warning(f"[L3 REDUCE] 降仓50%: {cb['reason']}")
            hedged_target = {k: v * 0.5 for k, v in hedged_target.items()}
            is_rebalance = True  # 强制调仓（减仓）
            if not dry_run:
                log_step(conn, "circuit_breaker", "reduce", cb["reason"])
                send_alert("P0", f"L3降仓 {exec_date}", cb["reason"],
                           settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)

        if cb["level"] == 2:
            logger.warning(f"[L2 PAUSE] 暂停交易: {cb['reason']}")
            is_rebalance = False
            if not dry_run:
                log_step(conn, "circuit_breaker", "pause", cb["reason"])
                send_alert("P0", f"L2暂停 {exec_date}", cb["reason"],
                           settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)

        if cb["level"] == 1:
            if is_rebalance:
                # 方案C：延迟月度调仓到L1恢复后
                logger.info(f"[L1 DELAY] {cb['reason']}，月度调仓延迟到L1恢复后执行")
                is_rebalance = False  # 今天不执行
                if not dry_run:
                    log_step(conn, "pending_monthly_rebalance", "pending",
                             f"L1触发延迟月度调仓 signal_date={signal_date}",
                             result={"signal_date": str(signal_date),
                                     "target": {k: round(v, 6) for k, v in hedged_target.items()}})
                    log_step(conn, "circuit_breaker", "l1_delay", cb["reason"])
            else:
                logger.info(f"[L1 SKIP] {cb['reason']}")
                is_rebalance = False
                if not dry_run:
                    log_step(conn, "circuit_breaker", "skip", cb["reason"])

        # ── Step 5.95: 检查延迟调仓（L1恢复后执行pending月度调仓）──
        if cb["level"] == 0 and not is_rebalance:  # 当前NORMAL且不是调仓日
            cur.execute(
                """SELECT result_json FROM scheduler_task_log
                   WHERE task_name = 'pending_monthly_rebalance' AND status = 'pending'
                   ORDER BY created_at DESC LIMIT 1""")
            pending = cur.fetchone()
            if pending and pending[0]:
                pending_data = json.loads(pending[0]) if isinstance(pending[0], str) else pending[0]
                pending_signal_date = pending_data.get("signal_date")
                pending_target = pending_data.get("target", {})

                if pending_signal_date:
                    p_date = datetime.strptime(pending_signal_date, "%Y-%m-%d").date()
                    # risk附加条件2: 延迟只存在有限交易日内
                    cur.execute(
                        """SELECT COUNT(*) FROM trading_calendar
                           WHERE market='astock' AND is_trading_day=TRUE
                           AND trade_date > %s AND trade_date < %s""",
                        (p_date, exec_date))
                    gap = cur.fetchone()[0]

                    if gap <= 2 and pending_target:  # 2个交易日内且有target
                        logger.info(f"[DELAYED REBALANCE] L1已恢复，执行延迟月度调仓(signal={pending_signal_date})")
                        hedged_target = {k: float(v) for k, v in pending_target.items()}
                        is_rebalance = True
                        # 标记pending为已执行
                        if not dry_run:
                            cur.execute(
                                """UPDATE scheduler_task_log SET status='executed'
                                   WHERE task_name='pending_monthly_rebalance' AND status='pending'""")
                            conn.commit()
                    else:
                        logger.info(f"[DELAYED REBALANCE EXPIRED] pending过期(gap={gap}交易日)，放弃")
                        if not dry_run:
                            cur.execute(
                                """UPDATE scheduler_task_log SET status='expired'
                                   WHERE task_name='pending_monthly_rebalance' AND status='pending'""")
                            conn.commit()

        # ── Step 5.96: 补单检查（封板未成交T+1日补单）──
        # 读取pending_orders（scheduler_task_log中status='pending'的封板记录）
        cur = conn.cursor()
        cur.execute(
            """SELECT result_json FROM scheduler_task_log
               WHERE task_name = 'pending_buy_orders' AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1"""
        )
        pending_row = cur.fetchone()
        saved_pending: list[PendingOrder] = []
        if pending_row and pending_row[0]:
            pending_data = json.loads(pending_row[0]) if isinstance(pending_row[0], str) else pending_row[0]
            for po_dict in pending_data.get("orders", []):
                saved_pending.append(PendingOrder(
                    code=po_dict["code"],
                    signal_date=datetime.strptime(po_dict["signal_date"], "%Y-%m-%d").date(),
                    exec_date=datetime.strptime(po_dict["exec_date"], "%Y-%m-%d").date(),
                    target_weight=po_dict["target_weight"],
                    original_score=po_dict.get("original_score", 0),
                ))
            logger.info(f"[Step5.96] 发现{len(saved_pending)}只封板待补单")

        # ── Step 6: 执行调仓 ──
        paper_broker = PaperBroker(
            strategy_id=settings.PAPER_STRATEGY_ID,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        paper_broker.load_state(conn)

        fills: list[Fill] = []
        new_pending: list[PendingOrder] = []
        beta = 0.0

        # 先处理补单（在调仓之前，用闲置现金）
        if saved_pending:
            # 获取下次调仓日用于距离检查
            cur = conn.cursor()
            cur.execute(
                """SELECT MIN(trade_date) FROM trading_calendar
                   WHERE market = 'astock' AND is_trading_day = TRUE
                     AND trade_date > %s
                     AND trade_date = (
                         SELECT MAX(trade_date) FROM trading_calendar
                         WHERE market = 'astock' AND is_trading_day = TRUE
                           AND DATE_TRUNC('month', trade_date) = DATE_TRUNC('month',
                               (SELECT MIN(trade_date) FROM trading_calendar
                                WHERE market='astock' AND is_trading_day=TRUE
                                AND trade_date > %s))
                     )""",
                (exec_date, exec_date),
            )
            next_rebal_row = cur.fetchone()
            next_rebal_date = next_rebal_row[0] if next_rebal_row else None

            retry_fills, updated_pending = paper_broker.process_pending_orders(
                saved_pending, exec_date, price_data,
                next_rebal_date=next_rebal_date, conn=conn,
            )
            fills.extend(retry_fills)

            filled = [po for po in updated_pending if po.status == "filled"]
            cancelled = [po for po in updated_pending if po.status == "cancelled"]
            logger.info(
                f"[Step5.96] 补单结果: {len(filled)}成功, {len(cancelled)}取消"
            )
            for po in cancelled:
                logger.info(f"  取消: {po.code} 原因={po.cancel_reason}")

            # 更新pending状态
            if not dry_run:
                cur.execute(
                    """UPDATE scheduler_task_log SET status='executed'
                       WHERE task_name='pending_buy_orders' AND status='pending'"""
                )
                conn.commit()

        if is_rebalance and hedged_target:
            logger.info(f"[Step6] 执行调仓 (T+1 open价格)...")
            # R1 fix: 使用exec_date的价格数据（T+1日open价格）
            rebal_fills, new_pending = paper_broker.execute_rebalance(
                hedged_target, exec_date, price_data, signal_date=signal_date,
            )
            fills.extend(rebal_fills)
            logger.info(f"[Step6] 调仓完成: {len(rebal_fills)}笔成交, {len(new_pending)}只封板")

            # 保存封板补单记录（供T+2日处理）
            if new_pending and not dry_run:
                pending_data = {
                    "orders": [
                        {
                            "code": po.code,
                            "signal_date": po.signal_date.isoformat(),
                            "exec_date": po.exec_date.isoformat(),
                            "target_weight": po.target_weight,
                            "original_score": po.original_score,
                        }
                        for po in new_pending
                    ]
                }
                log_step(conn, "pending_buy_orders", "pending",
                         result=pending_data)
                logger.info(
                    f"[Step6] 封板补单已保存: "
                    f"{', '.join(po.code for po in new_pending)}"
                )

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

        # ── Step 8.5: 风控日检 ──
        risk_warnings = run_daily_risk_check(
            paper_broker.broker, today_close, nav, fills
        )
        if risk_warnings:
            warn_msg = "\n".join(risk_warnings)
            logger.warning(f"[Step8.5] 风控日检异常:\n{warn_msg}")
            if not dry_run:
                send_alert("P1", f"风控日检 {exec_date}", warn_msg,
                           settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)
        else:
            logger.info("[Step8.5] 风控日检: 全部正常")

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
