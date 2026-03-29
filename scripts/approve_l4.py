#!/usr/bin/env python3
"""L4熔断人工审批恢复脚本。

L4触发后所有交易停止，需人工审批才能恢复。
本脚本更新approval_queue状态为approved，下次Paper Trading执行时
check_circuit_breaker会检测到审批通过并自动恢复到NORMAL。

用法:
    # 查看待审批的L4请求
    python scripts/approve_l4.py --list

    # 批准恢复
    python scripts/approve_l4.py --approve --approval-id <UUID>

    # 拒绝（保持L4）
    python scripts/approve_l4.py --reject --approval-id <UUID>

    # 强制重置到NORMAL（紧急运维，跳过审批流程）
    python scripts/approve_l4.py --force-reset --reason "紧急运维: xxx"
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.services.notification_service import send_alert
from app.services.price_utils import _get_sync_conn


def list_pending(conn) -> None:
    """列出所有待审批的L4请求。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT aq.id, aq.reference_id, aq.notes, aq.created_at,
                  cbs.current_level, cbs.entered_date, cbs.trigger_reason
           FROM approval_queue aq
           LEFT JOIN circuit_breaker_state cbs
             ON aq.reference_id::uuid = cbs.strategy_id
             AND cbs.execution_mode = 'paper'
           WHERE aq.approval_type = 'circuit_breaker_l4_recovery'
             AND aq.status = 'pending'
           ORDER BY aq.created_at DESC"""
    )
    rows = cur.fetchall()
    if not rows:
        print("No pending L4 approval requests.")
        return

    print(f"\n{'='*80}")
    print(f"  Pending L4 Approval Requests ({len(rows)})")
    print(f"{'='*80}")
    for row in rows:
        print(f"\n  Approval ID:   {row[0]}")
        print(f"  Strategy ID:   {row[1]}")
        print(f"  Notes:         {row[2]}")
        print(f"  Created At:    {row[3]}")
        print(f"  CB Level:      L{row[4]}")
        print(f"  CB Since:      {row[5]}")
        print(f"  CB Reason:     {row[6]}")
        print(f"  {'-'*60}")
    print()


def approve_request(conn, approval_id: str) -> None:
    """批准L4恢复请求。"""
    cur = conn.cursor()

    # 验证请求存在且pending
    cur.execute(
        "SELECT status, reference_id FROM approval_queue WHERE id = %s",
        (approval_id,),
    )
    row = cur.fetchone()
    if not row:
        print(f"ERROR: Approval ID {approval_id} not found.")
        sys.exit(1)
    if row[0] != "pending":
        print(f"ERROR: Approval ID {approval_id} is already '{row[0]}'.")
        sys.exit(1)

    strategy_id = row[1]

    # 更新审批状态
    cur.execute(
        """UPDATE approval_queue
           SET status = 'approved', reviewed_at = NOW(),
               reviewer_notes = 'Manual approval via approve_l4.py'
           WHERE id = %s""",
        (approval_id,),
    )
    conn.commit()

    print(f"Approved: {approval_id}")
    print(f"Strategy {strategy_id} will recover to NORMAL on next execution.")

    send_alert("P1", "L4审批已通过",
               f"策略{strategy_id} L4恢复审批已通过。\n"
               f"审批ID: {approval_id}\n"
               f"下次执行时将自动恢复到NORMAL状态。",
               settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)


def reject_request(conn, approval_id: str) -> None:
    """拒绝L4恢复请求。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT status FROM approval_queue WHERE id = %s",
        (approval_id,),
    )
    row = cur.fetchone()
    if not row:
        print(f"ERROR: Approval ID {approval_id} not found.")
        sys.exit(1)
    if row[0] != "pending":
        print(f"ERROR: Approval ID {approval_id} is already '{row[0]}'.")
        sys.exit(1)

    cur.execute(
        """UPDATE approval_queue
           SET status = 'rejected', reviewed_at = NOW(),
               reviewer_notes = 'Rejected via approve_l4.py'
           WHERE id = %s""",
        (approval_id,),
    )
    conn.commit()
    print(f"Rejected: {approval_id}. L4 will remain active.")


def force_reset(conn, reason: str) -> None:
    """强制重置到NORMAL（紧急运维）。"""
    if not reason.strip():
        print("ERROR: --reason is required for force-reset.")
        sys.exit(1)

    strategy_id = settings.PAPER_STRATEGY_ID
    cur = conn.cursor()

    # 读取当前状态
    cur.execute(
        """SELECT current_level FROM circuit_breaker_state
           WHERE strategy_id = %s AND execution_mode = 'paper'""",
        (strategy_id,),
    )
    row = cur.fetchone()
    prev_level = row[0] if row else 0

    today = date.today()

    # 写log
    cur.execute(
        """INSERT INTO circuit_breaker_log
               (strategy_id, execution_mode, trade_date,
                prev_level, new_level, transition_type, reason, metrics)
           VALUES (%s, 'paper', %s, %s, 0, 'manual', %s, NULL)""",
        (strategy_id, today, prev_level, f"FORCE RESET: {reason}"),
    )

    # 更新state
    cur.execute(
        """UPDATE circuit_breaker_state
           SET current_level = 0, entered_date = %s,
               trigger_reason = %s,
               recovery_streak_days = 0, recovery_streak_return = 0,
               position_multiplier = 1.0, approval_id = NULL,
               updated_at = NOW()
           WHERE strategy_id = %s AND execution_mode = 'paper'""",
        (today, f"FORCE RESET: {reason}", strategy_id),
    )

    # 清理pending审批
    cur.execute(
        """UPDATE approval_queue
           SET status = 'cancelled', reviewed_at = NOW(),
               reviewer_notes = %s
           WHERE approval_type = 'circuit_breaker_l4_recovery'
             AND reference_id = %s AND status = 'pending'""",
        (f"Force reset: {reason}", strategy_id),
    )
    conn.commit()

    print(f"Force reset: L{prev_level} -> NORMAL")
    print(f"Reason: {reason}")

    send_alert("P0", "L4强制重置",
               f"策略{strategy_id}从L{prev_level}强制重置到NORMAL。\n原因: {reason}",
               settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn)


def main():
    parser = argparse.ArgumentParser(description="L4 Circuit Breaker Approval Management")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List pending L4 approvals")
    group.add_argument("--approve", action="store_true", help="Approve a L4 recovery request")
    group.add_argument("--reject", action="store_true", help="Reject a L4 recovery request")
    group.add_argument("--force-reset", action="store_true", help="Force reset to NORMAL (emergency)")

    parser.add_argument("--approval-id", type=str, help="Approval UUID (for --approve/--reject)")
    parser.add_argument("--reason", type=str, default="", help="Reason (required for --force-reset)")

    args = parser.parse_args()

    conn = _get_sync_conn()
    try:
        if args.list:
            list_pending(conn)
        elif args.approve:
            if not args.approval_id:
                print("ERROR: --approval-id required for --approve")
                sys.exit(1)
            approve_request(conn, args.approval_id)
        elif args.reject:
            if not args.approval_id:
                print("ERROR: --approval-id required for --reject")
                sys.exit(1)
            reject_request(conn, args.approval_id)
        elif args.force_reset:
            force_reset(conn, args.reason)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
