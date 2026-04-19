"""D2-c Session 15 — 一次性修复 4-17 position_snapshot (live).

Session 10 P1-b 根因链:
  4-17 15:40 ``daily_reconciliation.write_live_snapshot`` 正确写 19 行.
  4-17 16:30 或 20:58 ``save_qmt_state`` 被调用, QMTClient 读 Redis 返空,
  _save_qmt_state_impl 在 D2-a (PR #25) 合并前无守卫, 执行 DELETE live rows +
  INSERT 0 → 蒸发 19 行.
  D2-a 已根除类似 bug (未来不会重现), 但 4-17 数据仍需手工补.

重构逻辑:
  ground truth = 4-16 live snapshot (22 行, reconciliation 直查 QMT 写入) +
                 4-17 live trade_log (20 行 frozen fills).
  apply fills (buy 加仓更新 avg_cost 加权 / sell 减仓保留 avg_cost / sell 全平 qty=0 丢弃),
  得到 24 codes qty>0 (含 2 BJ 遗留 avg_cost=0 反映真实 DB 状态, 不掩盖).

输入: 无 CLI 参数 (date hardcoded), 可选 ``--apply`` / ``--strategy-id``.
输出: dry-run 默认, print precondition + diff + 24 行 INSERT preview.

铁律:
  17 DataPipeline 入库: 本脚本是 one-shot 修复, 不走 DataPipeline, 但写入前
    4 precondition fail-loud + tx atomic 保证, 等效风控
  33 fail-loud: precondition 失败 raise, 拒绝 silent skip
  15 可复现: reconstruction 从 frozen data 确定性计算, 可单测

回滚 (已 --apply 后如需 undo, 必含 execution_mode + strategy_id 过滤):

    DELETE FROM position_snapshot
    WHERE trade_date = '2026-04-17'
      AND execution_mode = 'live'
      AND strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0';

(缺 execution_mode 过滤将误删 paper 命名空间, 缺 strategy_id 误删其他策略.)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import TypedDict

import psycopg2
import psycopg2.extensions


class _PositionEntry(TypedDict):
    """Typed structure for reconstruct_positions entries. qty=int, avg_cost=float."""

    qty: int
    avg_cost: float

# .env 加载 DATABASE_URL / PAPER_STRATEGY_ID
_BACKEND = Path(__file__).resolve().parent.parent.parent / "backend"
_ENV = _BACKEND / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("restore_snapshot_20260417")

# Hard-coded 修复参数 (one-shot, 不可改)
REPAIR_DATE = date(2026, 4, 17)
REF_DATE = date(2026, 4, 16)
DEFAULT_STRATEGY_ID = os.environ.get(
    "PAPER_STRATEGY_ID", "28fc37e5-2d32-4ada-92e0-41c11a5103d0"
)


class PreconditionError(RuntimeError):
    """D2-c precondition 守卫失败 (铁律 33 fail-loud)."""


def get_sync_conn():
    """Return psycopg2 connection with autocommit=False (本脚本需显式 tx).

    铁律 35: DATABASE_URL 未设置 → RAISE (不允许硬编码 fallback credential).
    通常 .env loader 已 populate DATABASE_URL. 缺失即真配置错误 → fail-loud.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. Configure backend/.env or export env var "
            "before running this script (铁律 35 禁硬编码 credential)."
        )
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


def assert_preconditions(
    cur: psycopg2.extensions.cursor,
    strategy_id: str,
    repair_date: date,
    ref_date: date,
) -> None:
    """3 upfront precondition 守卫 — 任一失败 raise PreconditionError (铁律 33).

    1. target_count == 0   (防重复 apply)
    2. baseline_count >= 1 (必需 4-16 snapshot 作 ground truth)
    3. fills_count >= 1    (必需 4-17 trade_log 作 transition)

    第 4 项 (klines 100% 覆盖) 在 fetch_closes 中守卫 (mid-execution guard),
    因 codes 需 reconstruct_positions 之后才知. fetch_closes 亦 raise PreconditionError.
    """
    cur.execute(
        """SELECT COUNT(*) FROM position_snapshot
           WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s""",
        (repair_date, strategy_id),
    )
    target = cur.fetchone()[0]
    if target != 0:
        raise PreconditionError(
            f"target {repair_date} live snapshot 已有 {target} 行 (应为 0). "
            f"拒绝 apply (防重复). 如需重跑 → 先手工 DELETE (人工审查)."
        )

    cur.execute(
        """SELECT COUNT(*) FROM position_snapshot
           WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s
             AND quantity > 0""",
        (ref_date, strategy_id),
    )
    baseline = cur.fetchone()[0]
    if baseline < 1:
        raise PreconditionError(
            f"baseline {ref_date} live snapshot 0 行 (应 ≥ 1). 无 ground truth, 拒绝 apply."
        )

    cur.execute(
        """SELECT COUNT(*) FROM trade_log
           WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s""",
        (repair_date, strategy_id),
    )
    fills = cur.fetchone()[0]
    if fills < 1:
        raise PreconditionError(
            f"{repair_date} live trade_log 0 行 (应 ≥ 1). 无 transition, 拒绝 apply."
        )

    logger.info(
        "[precondition] target=%d(=0) ✓  baseline=%d(≥1) ✓  fills=%d(≥1) ✓",
        target,
        baseline,
        fills,
    )


def reconstruct_positions(
    cur: psycopg2.extensions.cursor,
    strategy_id: str,
    repair_date: date,
    ref_date: date,
) -> dict[str, _PositionEntry]:
    """从 ref_date snapshot + repair_date trade_log 重算 repair_date 持仓.

    假设: ref_date snapshot 的 ``avg_cost`` 是真正的 all-time 加权均价 (由
    ``daily_reconciliation.write_live_snapshot`` 写入, 从 trade_log live buy 历史
    加权得出). 本函数只 incremental 叠加 repair_date 当日 fills, 保持该不变量.

    Returns:
        {code: {'qty': int, 'avg_cost': float}} 仅含 qty > 0 的 codes.
    """
    cur.execute(
        """SELECT code, quantity, avg_cost FROM position_snapshot
           WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s""",
        (ref_date, strategy_id),
    )
    positions: dict[str, _PositionEntry] = {
        r[0]: _PositionEntry(qty=int(r[1]), avg_cost=float(r[2] or 0))
        for r in cur.fetchall()
    }

    cur.execute(
        """SELECT code, direction, quantity, fill_price FROM trade_log
           WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s
           ORDER BY executed_at""",
        (repair_date, strategy_id),
    )
    for code, direction, qty, price in cur.fetchall():
        qty = int(qty)
        price = float(price)
        pos = positions.setdefault(code, _PositionEntry(qty=0, avg_cost=0.0))
        prev_qty = pos["qty"]
        prev_cost = pos["avg_cost"]
        if direction == "buy":
            new_qty = prev_qty + qty
            new_cost = (prev_qty * prev_cost + qty * price) / new_qty if new_qty > 0 else 0.0
            pos["qty"] = new_qty
            pos["avg_cost"] = new_cost
        elif direction == "sell":
            new_qty = prev_qty - qty
            if new_qty < 0:
                # 数据完整性异常 — 卖出量超持仓. 不 silent drop, fail-loud warning.
                logger.warning(
                    "[reconstruction] %s sell qty=%d > prev_qty=%d (oversell) → 视为全平 qty=0. "
                    "数据完整性问题, 需审查 trade_log vs snapshot 一致性.",
                    code, qty, prev_qty,
                )
                new_qty = 0
            pos["qty"] = new_qty
            pos["avg_cost"] = prev_cost if new_qty > 0 else 0.0
        # silent_ok: unknown direction (非 buy/sell) 不改 position — trade_log DDL CHECK
        # 约束 direction IN ('buy','sell'), 本分支数据上不可达

    return {c: v for c, v in positions.items() if v["qty"] > 0}


def fetch_closes(
    cur: psycopg2.extensions.cursor,
    codes: list[str],
    repair_date: date,
) -> dict[str, float]:
    """取 repair_date klines_daily close. 缺任一 code → RAISE (铁律 33).

    (缺 close 无法算 market_value, 必须补数据后重试.)
    """
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    cur.execute(
        f"""SELECT code, close FROM klines_daily
            WHERE trade_date = %s AND code IN ({placeholders})""",
        [repair_date, *codes],
    )
    closes = {r[0]: float(r[1]) for r in cur.fetchall()}
    missing = [c for c in codes if c not in closes]
    if missing:
        raise PreconditionError(
            f"klines_daily {repair_date} 缺 {len(missing)} code close: {missing}. "
            f"拒绝 apply. 请补数据后重试."
        )
    logger.info("[klines_daily] %d/%d codes close 覆盖 ✓", len(closes), len(codes))
    return closes


def build_rows(
    positions: dict[str, dict[str, float]],
    closes: dict[str, float],
    strategy_id: str,
    repair_date: date,
) -> list[tuple]:
    """生成 INSERT rows (仿 daily_reconciliation.write_live_snapshot 字段)."""
    total_mv = sum(v["qty"] * closes[c] for c, v in positions.items())
    rows: list[tuple] = []
    for code in sorted(positions.keys()):
        v = positions[code]
        qty = v["qty"]
        avg_cost = v["avg_cost"]
        close = closes[code]
        mv = qty * close
        weight = mv / total_mv if total_mv > 0 else 0.0
        unrealized_pnl = (mv - avg_cost * qty) if avg_cost > 0 else None
        rows.append(
            (
                code,
                repair_date,
                strategy_id,
                "astock",
                qty,
                round(avg_cost, 4) if avg_cost > 0 else None,
                round(mv, 2),
                round(weight, 4),
                round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                0,  # holding_days
                "live",
            )
        )
    return rows


def apply_rows(cur: psycopg2.extensions.cursor, rows: list[tuple]) -> None:
    """Batch INSERT (执行在调用方打开的 tx 内, 失败由调用方 rollback)."""
    cur.executemany(
        """INSERT INTO position_snapshot
             (code, trade_date, strategy_id, market, quantity, avg_cost,
              market_value, weight, unrealized_pnl, holding_days, execution_mode)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        rows,
    )


def run(strategy_id: str, apply: bool) -> int:
    """Main. Returns exit code (0 = success, 1 = precondition fail)."""
    conn = get_sync_conn()
    try:
        cur = conn.cursor()
        assert_preconditions(cur, strategy_id, REPAIR_DATE, REF_DATE)
        positions = reconstruct_positions(cur, strategy_id, REPAIR_DATE, REF_DATE)
        closes = fetch_closes(cur, list(positions.keys()), REPAIR_DATE)
        rows = build_rows(positions, closes, strategy_id, REPAIR_DATE)

        total_mv = sum(r[6] for r in rows)
        logger.info("[reconstruction] %d rows, total_mv=%.2f", len(rows), total_mv)
        for r in rows:
            logger.info(
                "  %s qty=%d mv=%.2f weight=%.4f avg_cost=%s",
                r[0], r[4], r[6], r[7], r[5] if r[5] is not None else "NULL",
            )

        if not apply:
            logger.info("[dry-run] no changes made (rerun with --apply to write)")
            conn.rollback()
            return 0

        apply_rows(cur, rows)
        conn.commit()
        logger.info("[apply] COMMIT ✓ %d rows inserted into position_snapshot", len(rows))
        return 0
    except PreconditionError as e:
        conn.rollback()
        logger.error("[precondition-fail] %s", e)
        return 1
    except Exception:
        conn.rollback()
        logger.exception("[unexpected] rolled back")
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="D2-c Session 15: restore 4-17 position_snapshot (live) (one-shot)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute INSERT (default: dry-run, no DB write)",
    )
    parser.add_argument(
        "--strategy-id",
        default=DEFAULT_STRATEGY_ID,
        help=f"Strategy id (default from env PAPER_STRATEGY_ID or {DEFAULT_STRATEGY_ID})",
    )
    args = parser.parse_args()
    sys.exit(run(args.strategy_id, args.apply))


if __name__ == "__main__":
    main()
