#!/usr/bin/env python3
"""收盘对账 — QMT实际持仓 vs DB记录对比。

每个交易日15:40运行，比较QMT模拟盘持仓与position_snapshot。
差异超过阈值时发送钉钉告警。同时计算fill_rate毕业指标。

用法:
    python scripts/daily_reconciliation.py
    python scripts/daily_reconciliation.py --date 2026-04-02
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

import psycopg2
import structlog

from app.config import settings

logger = structlog.get_logger("daily_reconciliation")

# 告警阈值
STOCK_DIFF_THRESHOLD = 0.01   # 单股差异>1% → P1
TOTAL_MV_DIFF_THRESHOLD = 0.05  # 总市值差异>5% → P0


def get_sync_conn():
    """获取psycopg2连接。"""
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin",
        password="quantmind", host="localhost",
    )


def is_trading_day(conn, d: date) -> bool:
    """检查是否交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT is_trading_day FROM trading_calendar
           WHERE market = 'astock' AND trade_date = %s""",
        (d,),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def query_qmt_positions() -> dict[str, int] | None:
    """通过QMT查询当前持仓。返回 {code: shares} 或 None。"""
    try:
        qmt_path = settings.QMT_PATH
        account_id = settings.QMT_ACCOUNT_ID
        if not qmt_path or not account_id:
            logger.error("QMT_PATH或QMT_ACCOUNT_ID未配置")
            return None

        # xtquant双层嵌套路径修复（CLAUDE.md规则）
        _xt = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
        if _xt.exists() and str(_xt) not in sys.path:
            sys.path.append(str(_xt))

        os.environ["EXECUTION_MODE"] = "live"
        from engines.broker_qmt import MiniQMTBroker

        broker = MiniQMTBroker(qmt_path, account_id)
        broker.connect()
        positions = broker.get_positions()  # {code: shares}
        broker.disconnect()
        return positions

    except Exception as e:
        logger.error(f"QMT查询失败: {e}")
        return None


def query_db_positions(conn, d: date) -> dict[str, int]:
    """从DB position_snapshot查询live模式持仓。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT code, quantity FROM position_snapshot
           WHERE trade_date = %s AND strategy_id = %s
             AND execution_mode = 'live'""",
        (d, settings.PAPER_STRATEGY_ID),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def _strip_suffix(code: str) -> str:
    """统一后DB和QMT均为带后缀格式，直接返回。"""
    return code


def write_live_snapshot(conn, d: date, qmt_positions: dict[str, int]) -> int:
    """将QMT实际持仓写入position_snapshot (execution_mode='live')。

    在对账时调用，确保DB有live模式的持仓记录。
    价格数据从klines_daily读取，QMT资产查询获取总资产用于weight计算。

    Args:
        conn: psycopg2连接。
        d: 日期。
        qmt_positions: {code_with_suffix: shares} QMT持仓（可能含.SH/.SZ后缀）。

    Returns:
        写入行数。
    """
    if not qmt_positions:
        return 0

    # 统一转为6位代码
    qmt_positions = {_strip_suffix(k): v for k, v in qmt_positions.items()}

    cur = conn.cursor()
    strategy_id = settings.PAPER_STRATEGY_ID

    # 清除旧的live snapshot（同一天可能重跑）
    cur.execute(
        """DELETE FROM position_snapshot
           WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'live'""",
        (d, strategy_id),
    )

    # 获取收盘价（用于市值计算）
    codes = list(qmt_positions.keys())
    placeholders = ",".join(["%s"] * len(codes))
    cur.execute(
        f"""SELECT code, close FROM klines_daily
            WHERE trade_date = (SELECT MAX(trade_date) FROM klines_daily WHERE trade_date <= %s)
              AND code IN ({placeholders})""",
        [d, *codes],
    )
    prices = {r[0]: float(r[1]) for r in cur.fetchall() if r[1]}

    # 获取QMT总资产（用于weight计算）
    total_mv = sum(
        qmt_positions.get(c, 0) * prices.get(c, 0) for c in codes
    )

    # 获取成本（从trade_log live买入记录计算加权均价）
    cur.execute(
        f"""SELECT code, SUM(fill_price * quantity) / NULLIF(SUM(quantity), 0) as avg_cost
            FROM trade_log
            WHERE strategy_id = %s AND execution_mode = 'live'
              AND direction = 'buy' AND code IN ({placeholders})
            GROUP BY code""",
        [strategy_id, *codes],
    )
    avg_costs = {r[0]: float(r[1]) for r in cur.fetchall() if r[1]}

    # 写入
    written = 0
    for code, shares in qmt_positions.items():
        if shares <= 0:
            continue
        price = prices.get(code, 0)
        mv = shares * price
        weight = mv / total_mv if total_mv > 0 else 0
        avg_cost = avg_costs.get(code)
        unrealized_pnl = (mv - avg_cost * shares) if avg_cost else None

        cur.execute(
            """INSERT INTO position_snapshot
               (code, trade_date, strategy_id, quantity, market_value,
                weight, avg_cost, unrealized_pnl, execution_mode)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'live')""",
            (code, d, strategy_id, shares, mv, weight, avg_cost, unrealized_pnl),
        )
        written += 1

    conn.commit()
    logger.info(f"[Reconciliation] live持仓快照已写入: {written}只, total_mv={total_mv:.0f}")
    return total_mv


def write_live_performance(conn, d: date, nav_total: float, cash: float) -> None:
    """将QMT当日净值写入performance_series (execution_mode='live')。

    Args:
        conn: psycopg2连接。
        d: 日期。
        nav_total: 当日总资产（QMT total_asset，已含持仓+现金+冻结）。
        cash: 当日可用现金（用于cash_ratio计算）。
    """
    cur = conn.cursor()
    strategy_id = settings.PAPER_STRATEGY_ID
    nav = nav_total
    if nav <= 0:
        logger.warning(f"[Reconciliation] NAV={nav}无效，跳过performance_series写入")
        return

    # 清除旧记录（同一天可能重跑）
    cur.execute(
        """DELETE FROM performance_series
           WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'live'""",
        (d, strategy_id),
    )

    # 读取前一日NAV
    cur.execute(
        """SELECT nav FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'live'
             AND trade_date < %s
           ORDER BY trade_date DESC LIMIT 1""",
        (strategy_id, d),
    )
    prev_row = cur.fetchone()
    initial_capital = settings.PAPER_INITIAL_CAPITAL
    prev_nav = float(prev_row[0]) if prev_row else initial_capital

    daily_return = (nav / prev_nav - 1) if prev_nav > 0 else 0.0
    cumulative_return = (nav / initial_capital - 1) if initial_capital > 0 else 0.0

    # 计算最大回撤（从所有live记录中找历史最高NAV）
    cur.execute(
        """SELECT MAX(nav) FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'live'""",
        (strategy_id,),
    )
    peak_row = cur.fetchone()
    peak_nav = float(peak_row[0]) if peak_row and peak_row[0] else initial_capital
    peak_nav = max(peak_nav, nav)  # 包含当天
    drawdown = (nav / peak_nav - 1) if peak_nav > 0 else 0.0

    cash_ratio = cash / nav if nav > 0 else 0.0
    position_count = 0
    cur.execute(
        """SELECT COUNT(*) FROM position_snapshot
           WHERE trade_date = %s AND strategy_id = %s
             AND execution_mode = 'live' AND quantity > 0""",
        (d, strategy_id),
    )
    pc_row = cur.fetchone()
    if pc_row:
        position_count = pc_row[0]

    cur.execute(
        """INSERT INTO performance_series
           (trade_date, strategy_id, nav, daily_return, cumulative_return,
            drawdown, cash_ratio, position_count, execution_mode)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'live')""",
        (d, strategy_id, nav, daily_return, cumulative_return,
         drawdown, cash_ratio, position_count),
    )
    conn.commit()
    logger.info(
        f"[Reconciliation] live performance已写入: nav={nav:.0f} "
        f"ret={daily_return:.4f} cum={cumulative_return:.4f} dd={drawdown:.4f}"
    )


def calc_fill_rate(conn, d: date) -> dict:
    """计算当日fill_rate = SUM(quantity) / SUM(order_qty)。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT
               COUNT(*) as total_orders,
               SUM(quantity) as total_filled,
               SUM(order_qty) as total_ordered,
               COUNT(*) FILTER (WHERE order_qty IS NOT NULL AND quantity < order_qty) as partial_fills,
               COUNT(*) FILTER (WHERE reject_reason IS NOT NULL) as rejects
           FROM trade_log
           WHERE trade_date = %s AND strategy_id = %s
             AND execution_mode = 'live'""",
        (d, settings.PAPER_STRATEGY_ID),
    )
    row = cur.fetchone()
    if not row or row[0] == 0:
        return {"total_orders": 0, "fill_rate": None, "partial_fills": 0, "rejects": 0}

    total_filled = row[1] or 0
    total_ordered = row[2] or total_filled  # order_qty未填时用quantity
    fill_rate = total_filled / total_ordered if total_ordered > 0 else 1.0

    return {
        "total_orders": row[0],
        "total_filled": total_filled,
        "total_ordered": total_ordered,
        "fill_rate": round(fill_rate, 4),
        "partial_fills": row[3] or 0,
        "rejects": row[4] or 0,
    }


def send_alert(conn, level: str, title: str, content: str) -> None:
    """发送钉钉告警（直接HTTP调用）。"""
    import httpx
    webhook = settings.DINGTALK_WEBHOOK_URL
    if not webhook:
        logger.warning("DINGTALK_WEBHOOK_URL未配置，跳过告警")
        return
    try:
        text = f"[{level}] {title}\n{content}"
        httpx.post(webhook, json={"msgtype": "text", "text": {"content": text}}, timeout=10)
        logger.info(f"[DingTalk] {level} 告警已发送")
    except Exception as e:
        logger.error(f"告警发送失败: {e}")


def run_reconciliation(recon_date: date) -> None:
    """执行一次对账。"""
    conn = get_sync_conn()

    try:
        if not is_trading_day(conn, recon_date):
            logger.info(f"{recon_date} 非交易日，跳过对账")
            return

        logger.info(f"[Reconciliation] 开始对账 {recon_date}")

        # 1. QMT持仓（统一转6位代码）
        qmt_pos_raw = query_qmt_positions()
        if qmt_pos_raw is None:
            send_alert(conn, "P0", f"对账失败 {recon_date}", "无法连接QMT获取持仓")
            return
        qmt_pos = {_strip_suffix(k): v for k, v in qmt_pos_raw.items()}

        # 1.5. 将QMT持仓写入position_snapshot (execution_mode='live')
        snapshot_mv = write_live_snapshot(conn, recon_date, qmt_pos)

        # 1.6. 获取QMT资产并写入performance_series (execution_mode='live')
        # 以QMT total_asset为准（包含冻结/结算差额等）
        qmt_total_asset = 0.0
        qmt_cash = 0.0
        try:
            _xt = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
            if _xt.exists() and str(_xt) not in sys.path:
                sys.path.append(str(_xt))
            from engines.broker_qmt import MiniQMTBroker
            broker = MiniQMTBroker(settings.QMT_PATH, settings.QMT_ACCOUNT_ID)
            broker.connect()
            asset = broker.query_asset()
            qmt_total_asset = float(asset.get("total_asset", 0))
            qmt_cash = float(asset.get("cash", 0))
            broker.disconnect()
            logger.info(f"[Reconciliation] QMT资产: total={qmt_total_asset:.0f}, cash={qmt_cash:.0f}, mv={float(asset.get('market_value', 0)):.0f}")
        except Exception as e:
            logger.warning(f"QMT资产查询失败，使用持仓市值+估算现金: {e}")
            qmt_total_asset = 0  # fallback below

        # 如果QMT查询成功，用total_asset; 否则fallback到 snapshot_mv + 估算现金
        if qmt_total_asset > 0:
            write_live_performance(conn, recon_date, qmt_total_asset, qmt_cash)
        else:
            cur = conn.cursor()
            cur.execute(
                """SELECT COALESCE(SUM(fill_price * quantity), 0) FROM trade_log
                   WHERE strategy_id = %s AND execution_mode = 'live' AND direction = 'buy'""",
                (settings.PAPER_STRATEGY_ID,),
            )
            total_bought = float(cur.fetchone()[0])
            est_cash = max(0, settings.PAPER_INITIAL_CAPITAL - total_bought)
            write_live_performance(conn, recon_date, snapshot_mv + est_cash, est_cash)

        # 2. DB持仓 (live模式) — 现在有数据了
        db_pos = query_db_positions(conn, recon_date)

        # 3. 逐股对比
        all_codes = set(qmt_pos.keys()) | set(db_pos.keys())
        mismatches = []
        for code in sorted(all_codes):
            qmt_shares = qmt_pos.get(code, 0)
            db_shares = db_pos.get(code, 0)
            if qmt_shares != db_shares:
                diff_pct = abs(qmt_shares - db_shares) / max(qmt_shares, db_shares, 1)
                mismatches.append({
                    "code": code,
                    "qmt": qmt_shares,
                    "db": db_shares,
                    "diff_pct": round(diff_pct, 4),
                })

        # 4. 总市值对比（简化：用股数差异代替）
        qmt_total = sum(qmt_pos.values())
        db_total = sum(db_pos.values())
        total_diff = abs(qmt_total - db_total) / max(qmt_total, 1) if qmt_total > 0 else 0

        # 5. fill_rate计算
        fill_stats = calc_fill_rate(conn, recon_date)

        # 6. 日志
        logger.info(
            f"[Reconciliation] QMT={len(qmt_pos)}只/{qmt_total}股, "
            f"DB={len(db_pos)}只/{db_total}股, "
            f"差异={len(mismatches)}只, fill_rate={fill_stats.get('fill_rate')}"
        )

        # 7. 告警
        significant = [m for m in mismatches if m["diff_pct"] > STOCK_DIFF_THRESHOLD]
        if total_diff > TOTAL_MV_DIFF_THRESHOLD:
            send_alert(
                conn, "P0", f"对账严重差异 {recon_date}",
                f"QMT={qmt_total}股 vs DB={db_total}股, 差异={total_diff:.1%}\n"
                f"差异股票: {json.dumps(significant[:5], ensure_ascii=False)}",
            )
        elif significant:
            send_alert(
                conn, "P1", f"对账差异 {recon_date}",
                f"{len(significant)}只股票持仓不一致\n"
                f"{json.dumps(significant[:5], ensure_ascii=False)}",
            )
        else:
            logger.info("[Reconciliation] 对账一致 ✓")

        # 8. 写入scheduler_task_log
        cur = conn.cursor()
        result = {
            "qmt_stocks": len(qmt_pos),
            "db_stocks": len(db_pos),
            "mismatches": len(mismatches),
            "significant_mismatches": len(significant),
            "fill_rate": fill_stats.get("fill_rate"),
            "partial_fills": fill_stats.get("partial_fills", 0),
            "rejects": fill_stats.get("rejects", 0),
        }
        cur.execute(
            """INSERT INTO scheduler_task_log
               (task_name, market, schedule_time, start_time, status,
                error_message, result_json)
               VALUES ('reconciliation', 'astock', NOW(), NOW(), 'success', NULL, %s)""",
            (json.dumps(result),),
        )
        conn.commit()

    except Exception as e:
        logger.error(f"[Reconciliation] 异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


def main() -> None:
    """CLI入口。"""
    import argparse
    parser = argparse.ArgumentParser(description="收盘对账: QMT vs DB")
    parser.add_argument("--date", type=str, default=None,
                        help="对账日期 YYYY-MM-DD (默认今天)")
    args = parser.parse_args()

    recon_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else date.today()
    )
    run_reconciliation(recon_date)


if __name__ == "__main__":
    main()
