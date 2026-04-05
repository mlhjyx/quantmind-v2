"""A7 回填脚本 — 补充 position_snapshot 中 avg_cost / unrealized_pnl。

用途:
  历史快照中 avg_cost / unrealized_pnl 为 NULL（写入时未传入 avg_costs）。
  本脚本从 trade_log 计算每只股票的加权平均成本，回填到 position_snapshot。

计算方法:
  avg_cost = 累计买入金额 / 累计买入股数  (仅计算 trade_date <= 快照日期的买入)
  unrealized_pnl = (market_value - avg_cost * quantity)
  cost_basis = 0 时 unrealized_pnl = NULL（避免除零）

运行方式:
  python scripts/fix_unrealized_pnl_backfill.py [--strategy-id <uuid>] [--dry-run]

约束:
  - 不修改 PT 保护文件
  - 读取 trade_log，写入 position_snapshot（avg_cost + unrealized_pnl 两列）
  - 幂等: 重复运行结果相同
"""

import argparse
import logging
import sys
from pathlib import Path

# 添加 backend/ 到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import psycopg2
from psycopg2.extras import execute_values

from app.config import settings  # type: ignore[import]

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def compute_avg_costs(
    cur: psycopg2.extensions.cursor,
    strategy_id: str,
    snapshot_date: object,
) -> dict[str, float]:
    """从 trade_log 计算截至 snapshot_date 的加权平均买入成本。

    Args:
        cur: psycopg2 游标。
        strategy_id: 策略ID。
        snapshot_date: 快照日期（计算该日期及之前的买入记录）。

    Returns:
        {code: avg_cost_per_share}
    """
    cur.execute(
        """
        SELECT code,
               SUM(price * shares) AS total_buy_amount,
               SUM(shares)         AS total_buy_shares
        FROM trade_log
        WHERE strategy_id = %s
          AND direction = 'buy'
          AND trade_date <= %s
          AND execution_mode = 'paper'
        GROUP BY code
        HAVING SUM(shares) > 0
        """,
        (strategy_id, snapshot_date),
    )
    rows = cur.fetchall()
    avg_costs: dict[str, float] = {}
    for code, total_buy_amount, total_buy_shares in rows:
        if total_buy_shares > 0:
            avg_costs[code] = float(total_buy_amount) / float(total_buy_shares)
    return avg_costs


def backfill_strategy(
    conn: psycopg2.extensions.connection,
    strategy_id: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    """回填单个策略的所有快照记录。

    Returns:
        (updated_rows, skipped_rows)
    """
    cur = conn.cursor()

    # 获取所有待更新的快照日期（avg_cost IS NULL 的记录）
    cur.execute(
        """
        SELECT DISTINCT trade_date
        FROM position_snapshot
        WHERE strategy_id = %s
          AND execution_mode = 'paper'
          AND avg_cost IS NULL
          AND quantity > 0
        ORDER BY trade_date
        """,
        (strategy_id,),
    )
    snapshot_dates = [row[0] for row in cur.fetchall()]
    logger.info("策略 %s: 找到 %d 个待回填快照日期", strategy_id, len(snapshot_dates))

    total_updated = 0
    total_skipped = 0

    for snap_date in snapshot_dates:
        avg_costs = compute_avg_costs(cur, strategy_id, snap_date)

        # 获取该日快照所有持仓
        cur.execute(
            """
            SELECT code, quantity, market_value
            FROM position_snapshot
            WHERE strategy_id = %s
              AND execution_mode = 'paper'
              AND trade_date = %s
              AND quantity > 0
            """,
            (strategy_id, snap_date),
        )
        snapshot_rows = cur.fetchall()

        updates = []
        for code, quantity, market_value in snapshot_rows:
            ac = avg_costs.get(code)
            if ac is None or ac <= 0:
                total_skipped += 1
                continue

            cost_basis = float(ac) * int(quantity)
            unrealized_pnl = float(market_value) - cost_basis if cost_basis > 0 else None

            updates.append((float(ac), unrealized_pnl, code, strategy_id, snap_date))
            total_updated += 1

        if updates and not dry_run:
            execute_values(
                cur,
                """
                UPDATE position_snapshot
                SET avg_cost = data.avg_cost,
                    unrealized_pnl = data.unrealized_pnl
                FROM (VALUES %s) AS data(avg_cost, unrealized_pnl, code, strategy_id, trade_date)
                WHERE position_snapshot.code = data.code
                  AND position_snapshot.strategy_id = CAST(data.strategy_id AS uuid)
                  AND position_snapshot.trade_date = CAST(data.trade_date AS date)
                  AND position_snapshot.execution_mode = 'paper'
                """,
                updates,
            )
            logger.info("  %s: 更新 %d 条", snap_date, len(updates))
        elif updates and dry_run:
            logger.info("  [dry-run] %s: 将更新 %d 条", snap_date, len(updates))

    return total_updated, total_skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 position_snapshot.avg_cost/unrealized_pnl")
    parser.add_argument("--strategy-id", type=str, help="指定策略ID（不填则回填全部策略）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入")
    args = parser.parse_args()

    conn = psycopg2.connect(settings.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+", "postgresql://", 1))
    conn.autocommit = False

    try:
        cur = conn.cursor()

        if args.strategy_id:
            strategy_ids = [args.strategy_id]
        else:
            cur.execute(
                """SELECT DISTINCT CAST(strategy_id AS text)
                   FROM position_snapshot
                   WHERE execution_mode = 'paper' AND avg_cost IS NULL AND quantity > 0"""
            )
            strategy_ids = [row[0] for row in cur.fetchall()]

        logger.info("共 %d 个策略需要回填", len(strategy_ids))
        total_updated = total_skipped = 0

        for sid in strategy_ids:
            u, s = backfill_strategy(conn, sid, dry_run=args.dry_run)
            total_updated += u
            total_skipped += s

        if not args.dry_run:
            conn.commit()
            logger.info("✅ 回填完成: 更新=%d 跳过=%d", total_updated, total_skipped)
        else:
            logger.info("[dry-run] 预计更新=%d 跳过=%d", total_updated, total_skipped)

    except Exception:
        conn.rollback()
        logger.exception("回填失败，已回滚")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
