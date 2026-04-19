"""QMT↔DB状态同步 — 从run_paper_trading.py提取(Step 6-A)。

将QMT实际持仓写入position_snapshot和performance_series。

L1 Fail-Loud (D2-a, 2026-04-19): Session 10 发现 P1-b bug — QMT 断连/数据竞态
时 QMTClient 返 0 持仓, ``save_qmt_state`` 无校验直接 DELETE + INSERT 0 行覆盖真实
snapshot. 铁律 33 要求 production path fail-loud, 故在写前校验:
"前一交易日 live snapshot ≥ 1 持仓 + 今日 QMT 返 0 → RAISE ``QMTEmptyPositionsError``".
caller (``run_paper_trading.py:246``) 差异化 except 放行此异常到 outer log_step + sys.exit.
"""

from __future__ import annotations

import logging
from datetime import date

import psycopg2.extensions

from app.config import settings

logger = logging.getLogger("paper_trading")


class QMTEmptyPositionsError(RuntimeError):
    """FAIL-LOUD: QMT 返 0 持仓但前一交易日有记录 — 疑似 QMT 断连/数据竞态.

    D2-a L1 guard (2026-04-19, 回应 Session 10 P1-b).
    """


def _assert_positions_not_evaporated(
    cur: psycopg2.extensions.cursor,
    trade_date: date,
    strategy_id: str,
    qmt_positions: dict[str, int],
) -> None:
    """L1 fail-loud: 前一交易日有 live 持仓 + 今日 QMT 返 0 → RAISE.

    只在 ``qmt_positions`` 为空时查 DB. prev snapshot 无行 (fresh start) 或 prev 行
    全部 ``quantity=0`` 时放行 — 仅当"历史非空且今日空"触发.
    """
    if qmt_positions:
        return
    cur.execute(
        """SELECT MAX(trade_date) FROM position_snapshot
           WHERE strategy_id = %s AND execution_mode = 'live' AND trade_date < %s""",
        (strategy_id, trade_date),
    )
    row = cur.fetchone()
    prev_date = row[0] if row else None
    if prev_date is None:
        return  # fresh start, 无历史
    cur.execute(
        """SELECT COUNT(*) FROM position_snapshot
           WHERE strategy_id = %s AND execution_mode = 'live'
             AND trade_date = %s AND quantity > 0""",
        (strategy_id, prev_date),
    )
    prev_count = cur.fetchone()[0]
    if prev_count >= 1:
        raise QMTEmptyPositionsError(
            f"FAIL-LOUD: QMT 返 0 持仓但 {prev_date} 有 {prev_count} 只 live 持仓. "
            f"疑似 QMT 断连/数据竞态. trade_date={trade_date} strategy_id={strategy_id}. "
            f"手工排查: (1) Servy QMTData status; (2) redis portfolio:current; "
            f"(3) xtquant 连接; 确认后手工补 position_snapshot 或等下一交易日."
        )


def save_qmt_state(
    conn,
    trade_date: date,
    qmt_positions: dict[str, int],
    today_close: dict[str, float],
    nav: float,
    prev_nav: float,
    qmt_nav_data: dict | None,
    benchmark_close: float | None,
) -> None:
    """用QMT实际持仓写入position_snapshot和performance_series。

    2026-04-15修复: execution_mode 从 'paper' 改为 'live', 对齐
    execution_service._save_live_fills 和 daily_reconciliation.write_live_snapshot。
    avg_cost 从 trade_log 加权均值计算(原硬编码 0 导致 PMS check_protection 静默跳过)。

    .. note:: **铁律 32 Class C 例外** (Phase D D2b-4 audited 2026-04-16)

       本函数使用 ``SAVEPOINT snapshot_update`` (line 52/80/82) 实现 position_snapshot
       DELETE + INSERT 原子操作. ``SAVEPOINT`` 必须在事务模式下执行, 在 autocommit=True
       下 psycopg2 抛 ``NoActiveSqlTransaction``.

       因此本函数 **局部切回 autocommit=False**, 自管事务 (commit/rollback), 完成后
       恢复调用方原 autocommit 状态. 这是合理的 Class C 例外 (技术约束驱动).

       详见 ``docs/audit/F16_service_commit_audit.md``.
    """
    # 局部 tx 模式 (SAVEPOINT 需要), 函数末尾 finally 恢复
    prev_autocommit = conn.autocommit
    conn.autocommit = False
    try:
        _save_qmt_state_impl(
            conn,
            trade_date,
            qmt_positions,
            today_close,
            nav,
            prev_nav,
            qmt_nav_data,
            benchmark_close,
        )
        conn.commit()  # F16-classC — local tx for SAVEPOINT (see docstring)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = prev_autocommit


def _save_qmt_state_impl(
    conn,
    trade_date: date,
    qmt_positions: dict[str, int],
    today_close: dict[str, float],
    nav: float,
    prev_nav: float,
    qmt_nav_data: dict | None,
    benchmark_close: float | None,
) -> None:
    """save_qmt_state 实际实现 (autocommit=False 上下文已就位).

    保留 SAVEPOINT 原子语义, commit/rollback 由外层 wrapper 管理.
    """
    cur = conn.cursor()
    strategy_id = settings.PAPER_STRATEGY_ID

    # D2-a L1 fail-loud (Session 10 P1-b 回应, 铁律 33): 前日 ≥1 持仓 + 今日空 → RAISE
    _assert_positions_not_evaporated(cur, trade_date, strategy_id, qmt_positions)

    # 从 trade_log 批量查询加权平均成本 (P0 修复: 原硬编码 avg_cost=0 导致 PMS 全部跳过)
    avg_costs: dict[str, float] = {}
    if qmt_positions:
        codes = list(qmt_positions.keys())
        placeholders = ",".join(["%s"] * len(codes))
        cur.execute(
            f"""SELECT code,
                       SUM(fill_price * quantity) / NULLIF(SUM(quantity), 0) AS avg_cost
                FROM trade_log
                WHERE strategy_id = %s AND execution_mode = 'live'
                  AND direction = 'buy' AND code IN ({placeholders})
                GROUP BY code""",
            [strategy_id, *codes],
        )
        avg_costs = {r[0]: float(r[1]) for r in cur.fetchall() if r[1] is not None}

    # 1. position_snapshot: 删除当日旧数据 + 写入QMT持仓 (原子操作)
    cur.execute("SAVEPOINT snapshot_update")
    try:
        cur.execute(
            "DELETE FROM position_snapshot WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s",
            (trade_date, strategy_id),
        )
        for code, qty in qmt_positions.items():
            price = today_close.get(code, 0)
            mv = qty * price
            weight = mv / nav if nav > 0 else 0
            avg_cost = avg_costs.get(code)
            unrealized_pnl = (mv - avg_cost * qty) if avg_cost else 0
            cur.execute(
                """INSERT INTO position_snapshot
                   (code, trade_date, strategy_id, market, quantity, avg_cost,
                    market_value, weight, unrealized_pnl, holding_days, execution_mode)
                   VALUES (%s, %s, %s, 'astock', %s, %s, %s, %s, %s, 0, 'live')""",
                (
                    code,
                    trade_date,
                    strategy_id,
                    qty,
                    round(avg_cost, 4) if avg_cost else None,
                    round(mv, 2),
                    round(weight, 4),
                    round(unrealized_pnl, 2),
                ),
            )
        cur.execute("RELEASE SAVEPOINT snapshot_update")
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT snapshot_update")
        raise

    # 2. performance_series: UPSERT
    # DB中的numeric字段返回Decimal, 统一cast为float避免混合类型运算
    nav = float(nav)
    prev_nav = float(prev_nav) if prev_nav is not None else 0.0
    daily_return = (nav / prev_nav - 1) if prev_nav > 0 else 0
    cumulative_return = nav / float(settings.PAPER_INITIAL_CAPITAL) - 1

    cur.execute(
        "SELECT COALESCE(MAX(nav), %s) FROM performance_series "
        "WHERE execution_mode = 'live' AND strategy_id = %s",
        (settings.PAPER_INITIAL_CAPITAL, strategy_id),
    )
    peak_nav = float(cur.fetchone()[0])
    peak_nav = max(peak_nav, nav)
    drawdown = (nav / peak_nav - 1) if peak_nav > 0 else 0

    qmt_cash = qmt_nav_data.get("cash", 0) if qmt_nav_data else 0
    cash_ratio = qmt_cash / nav if nav > 0 else 0
    position_count = len(qmt_positions)
    benchmark_nav = benchmark_close if benchmark_close else None

    cur.execute(
        """INSERT INTO performance_series
           (trade_date, strategy_id, market, nav, daily_return, cumulative_return,
            drawdown, cash_ratio, cash, position_count, turnover,
            benchmark_nav, excess_return, execution_mode)
           VALUES (%s, %s, 'astock', %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, 'live')
           ON CONFLICT (trade_date, strategy_id, execution_mode)
           DO UPDATE SET nav=EXCLUDED.nav, daily_return=EXCLUDED.daily_return,
              cumulative_return=EXCLUDED.cumulative_return, drawdown=EXCLUDED.drawdown,
              cash_ratio=EXCLUDED.cash_ratio, cash=EXCLUDED.cash,
              position_count=EXCLUDED.position_count, benchmark_nav=EXCLUDED.benchmark_nav,
              excess_return=EXCLUDED.excess_return""",
        (
            trade_date,
            strategy_id,
            round(nav, 2),
            round(daily_return, 6),
            round(cumulative_return, 6),
            round(drawdown, 6),
            round(cash_ratio, 4),
            round(qmt_cash, 2),
            position_count,
            benchmark_nav,
            round(daily_return, 6),
        ),
    )
    # 铁律 32 (Phase D D2b-4): 不在此处 commit. 外层 save_qmt_state wrapper 在 try/except
    # 中 commit/rollback (因为本函数依赖 SAVEPOINT, 必须运行在 autocommit=False 的局部 tx).
    logger.info("[QMT] 状态已写入DB: %d只持仓, NAV=¥%s", position_count, f"{nav:,.0f}")
