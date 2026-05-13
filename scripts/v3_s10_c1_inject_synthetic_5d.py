"""C1 synthetic injection — V3 §13.2 5d operational kickoff non-zero data fixture.

Purpose: 5-7 → 5-13 真生产源表全 0,导致 risk_metrics_daily 5d 验收 trivially
pass 但没真意义。本脚本注入轻量合成数据 (5 days × varying alerts + STAGED plans),
让 aggregator + verify_report 全链路用非零数据走一遍。

Tag convention (for cleanup):
  - risk_event_log.rule_id LIKE 'c1_synthetic_%'
  - execution_plans.risk_reason LIKE 'c1_synthetic_%'

Run:
  python scripts/v3_s10_c1_inject_synthetic_5d.py

Cleanup (post-verify):
  DELETE FROM risk_event_log WHERE rule_id LIKE 'c1_synthetic_%';
  DELETE FROM execution_plans WHERE risk_reason LIKE 'c1_synthetic_%';

红线 sustained: 0 broker / 0 .env / 0 trade. 仅 INSERT 测试 row + 立即可逆.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.db import get_sync_conn

TZ = ZoneInfo("Asia/Shanghai")

# Per-day plan: (date, [(severity, count)], [(status, count)] for STAGED, AUTO count)
PLAN = [
    (date(2026, 5, 7), [("p0", 1), ("p1", 2), ("p2", 1)],
     [("EXECUTED", 1), ("CANCELLED", 1)], 0),
    (date(2026, 5, 8), [("p0", 2), ("p1", 1)],
     [("EXECUTED", 1)], 0),
    (date(2026, 5, 11), [("p0", 1), ("p1", 3), ("p2", 2)],
     [("EXECUTED", 1), ("CANCELLED", 1), ("TIMEOUT_EXECUTED", 1)], 0),
    (date(2026, 5, 12), [("p1", 2), ("p2", 1)],
     [("EXECUTED", 2)], 1),
    (date(2026, 5, 13), [("p0", 1), ("p2", 1)],
     [("TIMEOUT_EXECUTED", 1)], 0),
]


def _ts(d: date, hour: int = 10, minute: int = 0) -> datetime:
    """Convert date → Asia/Shanghai tz-aware datetime at given local time."""
    return datetime.combine(d, time(hour, minute), tzinfo=TZ)


def inject_risk_events(cur, d: date, severities: list[tuple[str, int]]) -> int:
    """INSERT risk_event_log rows for the day; return total inserted."""
    inserted = 0
    for sev, count in severities:
        for i in range(count):
            triggered = _ts(d, 10 + (inserted % 6), inserted * 7 % 60)
            cur.execute(
                """INSERT INTO risk_event_log
                   (strategy_id, execution_mode, rule_id, severity, code,
                    shares, reason, context_snapshot, action_taken,
                    triggered_at, created_at, priority)
                   VALUES (gen_random_uuid(), 'paper', %s, %s, %s,
                           %s, %s, '{}'::jsonb, 'alert_only',
                           %s, %s, %s)""",
                (
                    f"c1_synthetic_{sev}_{d.isoformat()}_{i}",
                    sev,
                    f"60{i:04d}",  # synthetic symbol_id 600000..
                    100 * (i + 1),
                    f"C1 synthetic {sev} alert #{i} on {d.isoformat()}",
                    triggered,
                    triggered,
                    sev.upper(),  # priority column uppercase
                ),
            )
            inserted += 1
    return inserted


def inject_execution_plans(
    cur, d: date, statuses: list[tuple[str, int]], auto_count: int
) -> int:
    """INSERT execution_plans rows; STAGED with varying status + AUTO."""
    inserted = 0
    base = _ts(d, 14, 0)  # 14:00 trigger
    for status, count in statuses:
        for i in range(count):
            scheduled = base + timedelta(minutes=i * 5)
            cancel_deadline = scheduled + timedelta(minutes=30)
            cur.execute(
                """INSERT INTO execution_plans
                   (mode, symbol_id, action, qty, scheduled_at, cancel_deadline,
                    status, created_at, risk_reason)
                   VALUES ('STAGED', %s, 'SELL', %s, %s, %s, %s, %s, %s)""",
                (
                    f"60{inserted:04d}",
                    1000 * (i + 1),
                    scheduled,
                    cancel_deadline,
                    status,
                    scheduled,
                    f"c1_synthetic_STAGED_{status}_{d.isoformat()}_{i}",
                ),
            )
            inserted += 1
    for i in range(auto_count):
        scheduled = base + timedelta(minutes=30 + i * 5)
        cancel_deadline = scheduled + timedelta(minutes=5)
        cur.execute(
            """INSERT INTO execution_plans
               (mode, symbol_id, action, qty, scheduled_at, cancel_deadline,
                status, created_at, risk_reason)
               VALUES ('AUTO', %s, 'SELL', %s, %s, %s, 'EXECUTED', %s, %s)""",
            (
                f"60{inserted:04d}",
                500,
                scheduled,
                cancel_deadline,
                scheduled,
                f"c1_synthetic_AUTO_{d.isoformat()}_{i}",
            ),
        )
        inserted += 1
    return inserted


def main() -> None:
    conn = get_sync_conn()
    try:
        cur = conn.cursor()
        total_re = 0
        total_ep = 0
        try:
            for d, sevs, statuses, auto_n in PLAN:
                re_n = inject_risk_events(cur, d, sevs)
                ep_n = inject_execution_plans(cur, d, statuses, auto_n)
                total_re += re_n
                total_ep += ep_n
                print(f"{d.isoformat()}: +{re_n} risk_event_log / +{ep_n} execution_plans")
            conn.commit()
        finally:
            cur.close()
        print(f"DONE — total {total_re} risk_event_log + {total_ep} execution_plans inserted")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
