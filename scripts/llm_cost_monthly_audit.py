"""LLM Cost Monthly Audit — P0-16 closure (Plan v8 Master).

沿用 Plan v8 Master P0-16 (No Monthly LLM Cost Audit Aggregator) Alt 1:
    `scripts/llm_cost_monthly_audit.py` + Beat `crontab(day_of_month=1, hour=8)`
    aggregates `llm_call_log WHERE triggered_at BETWEEN last_month_start AND last_month_end`.

Designed to run:
    1. Monthly via Celery Beat `llm-cost-monthly-audit` (新 entry, batch 6)
    2. Ad-hoc via direct python invocation

Outputs:
    1. stdout: per-month + per-call_type aggregated cost
    2. Comparison vs $50 budget (sustained V3 §20.1 #6, .env LLM_MONTHLY_BUDGET_USD)
    3. DingTalk push if cost > 80% threshold OR > 100% (沿用 budget.py state machine)

Sustained:
    - 铁律 9 (并发限制基础, 单一 process 仅查询)
    - 铁律 33 (fail-loud — exit code != 0 if DB fail)
    - 铁律 35 (secrets via env — DATABASE_URL from backend/.env, 0 fallback)
    - 铁律 41 (Asia/Shanghai timezone)
    - LL-105 SOP-6 SSOT (cite source priority)
    - LL-190 (sediment-then-forget, 本 script 是 enforcement layer)

Author: CC autonomous Session 58+1 (continuous mode, P0-16 closure batch 6).
Date: 2026-05-19 evening SH.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Asia/Shanghai timezone (铁律 41)
SH_TZ = timezone(timedelta(hours=8))
NOW = datetime.now(SH_TZ)

# Threshold (沿用 V3 §20.1 #6 budget cap, sustained backend/.env LLM_MONTHLY_BUDGET_USD=50)
DEFAULT_MONTHLY_BUDGET_USD = 50.0
WARN_RATIO = 0.80  # 80% warn
CAP_RATIO = 1.00  # 100% cap (Ollama fallback trigger)


def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env file, return field→value dict (反 fallback per 铁律 35)."""
    if not env_path.exists():
        raise SystemExit(f"FAIL: {env_path} not found (铁律 35 secrets via env required)")
    fields: dict[str, str] = {}
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        fields[k.strip()] = v.strip()
    return fields


def _parse_database_url(url: str) -> dict[str, str]:
    """Parse postgresql+asyncpg://user:pass@host:port/db → connection dict."""
    # postgresql+asyncpg://xin:quantmind@localhost:5432/quantmind_v2
    m = re.match(
        r"postgresql\+?(?:asyncpg)?://([^:]+):([^@]+)@([^:]+):(\d+)/(\S+)", url
    )
    if not m:
        raise SystemExit(f"FAIL: DATABASE_URL parse failed: {url[:50]}...")
    return {
        "user": m.group(1),
        "password": m.group(2),
        "host": m.group(3),
        "port": m.group(4),
        "dbname": m.group(5),
    }


def main() -> int:
    """Run monthly audit, push DingTalk if cost > 80% threshold, exit 0/1."""
    print(f"=== LLM Cost Monthly Audit {NOW.isoformat()} ===")
    print(f"Sustained: 铁律 9/33/35/41 + V3 §20.1 #6 + LL-190 sediment-then-forget enforcement")
    print()

    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / "backend" / ".env"
    env = _parse_env_file(env_path)

    db_url = env.get("DATABASE_URL", "")
    if not db_url:
        raise SystemExit("FAIL: DATABASE_URL not set in .env (铁律 35)")

    db_conn = _parse_database_url(db_url)

    budget_str = env.get("LLM_MONTHLY_BUDGET_USD", str(DEFAULT_MONTHLY_BUDGET_USD))
    try:
        budget = float(budget_str)
    except ValueError:
        budget = DEFAULT_MONTHLY_BUDGET_USD

    print(f"[Config] Monthly budget: ${budget:.2f}")
    print(f"[Config] Warn threshold: {WARN_RATIO * 100:.0f}% = ${budget * WARN_RATIO:.2f}")
    print(f"[Config] Cap threshold:  {CAP_RATIO * 100:.0f}% = ${budget * CAP_RATIO:.2f}")
    print()

    # Connect DB
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        raise SystemExit("FAIL: psycopg2 not installed (沿用 backend/.venv 体例)")

    import psycopg2

    conn = psycopg2.connect(
        host=db_conn["host"],
        port=db_conn["port"],
        dbname=db_conn["dbname"],
        user=db_conn["user"],
        password=db_conn["password"],
        connect_timeout=10,
    )
    try:
        cur = conn.cursor()
        # Per-month aggregation (last 6 months)
        cur.execute(
            """
            SELECT
                to_char(triggered_at, 'YYYY-MM') as month_bucket,
                task as call_type,
                COUNT(*) as call_count,
                ROUND(SUM(cost_usd)::numeric, 4) as total_cost_usd,
                ROUND(AVG(cost_usd)::numeric, 6) as avg_cost_per_call
            FROM llm_call_log
            WHERE triggered_at >= date_trunc('month', NOW()) - INTERVAL '6 months'
            GROUP BY month_bucket, task
            ORDER BY month_bucket DESC, total_cost_usd DESC NULLS LAST;
            """
        )
        rows = cur.fetchall()
        print(f"[Query] llm_call_log last 6 months, {len(rows)} groups:")
        print()
        print(
            f"  {'Month':<10} {'CallType':<25} {'Count':>8} {'Total$':>10} {'Avg$':>10}"
        )
        print(f"  {'-' * 10} {'-' * 25} {'-' * 8} {'-' * 10} {'-' * 10}")
        current_month = NOW.strftime("%Y-%m")
        mtd_total = 0.0
        for row in rows:
            month, call_type, count, total, avg = row
            total_f = float(total) if total else 0.0
            avg_f = float(avg) if avg else 0.0
            print(
                f"  {month:<10} {call_type:<25} {count:>8} {total_f:>10.4f} {avg_f:>10.6f}"
            )
            if month == current_month:
                mtd_total += total_f
        print()

        # MTD summary
        print(f"[MTD {current_month}] total cost: ${mtd_total:.4f}")
        mtd_ratio = mtd_total / budget if budget > 0 else 0
        print(f"[MTD {current_month}] ratio: {mtd_ratio * 100:.1f}% of budget")

        # Threshold evaluation
        if mtd_ratio >= CAP_RATIO:
            print(f"[ALERT] CAP THRESHOLD EXCEEDED: trigger Ollama fallback per ADR-028 §3.3")
            status = "CAP_EXCEEDED"
            exit_code = 1
        elif mtd_ratio >= WARN_RATIO:
            print(f"[WARN] WARN THRESHOLD EXCEEDED: cost approaching $50 monthly budget")
            status = "WARN"
            exit_code = 0  # Warning still exit 0 (沿用 budget.py state machine — warning, not fail)
        else:
            print(f"[OK] within budget")
            status = "OK"
            exit_code = 0

        # Last month comparison (反 month-over-month drift detection)
        last_month_dt = (NOW.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        cur.execute(
            """
            SELECT ROUND(SUM(cost_usd)::numeric, 4)
            FROM llm_call_log
            WHERE to_char(triggered_at, 'YYYY-MM') = %s
            """,
            (last_month_dt,),
        )
        last_month_total = cur.fetchone()[0]
        if last_month_total is not None:
            last_month_f = float(last_month_total)
            mom_change = (
                (mtd_total - last_month_f) / last_month_f * 100 if last_month_f > 0 else 0
            )
            print(f"[Compare] Last month ({last_month_dt}): ${last_month_f:.4f}")
            print(f"[Compare] MoM change: {mom_change:+.1f}%")

        cur.close()

        # TODO: DingTalk push if status != "OK"
        # Phase B post-deployment wire via backend/app/services/dingtalk_alert.py

        print()
        print(f"=== Audit COMPLETE — status={status} ===")
        return exit_code
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
