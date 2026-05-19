"""Plan v8 P0-17 Phase 1: Disaster drill simulator (read-only verification).

Why Phase 1 read-only:
- Phase B-1 frozen state requires 0 mutation
- Read-only verifies: recovery code path exists for each disaster scenario
- Surface GAPs (scenarios with MISSING recovery code) → Phase J fix targets

Per P0_17_DISASTER_DRILL_DESIGN.md catalog (12 scenarios across 3 tiers).

Usage:
  python scripts/disaster_drill_simulator.py              # All tiers
  python scripts/disaster_drill_simulator.py --tier 1     # Specific tier
  python scripts/disaster_drill_simulator.py --json       # JSON output

Exit code:
  0 = all scenarios have recovery code documented
  1 = one or more GAPs detected
  2 = script error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Disaster scenario catalog (per P0_17_DISASTER_DRILL_DESIGN.md)
SCENARIOS = [
    # Tier 1: High frequency, low blast radius
    {
        "id": "tier1_servy_crash",
        "tier": 1,
        "name": "Servy service crash",
        "trigger": "Stop-Service QuantMind-FastAPI",
        "recovery_code": "scripts/service_manager.ps1",
        "expected_recovery": "AutoRestart=true picks up < 60s",
        "expected_sla_sec": 60,
    },
    {
        "id": "tier1_tushare_timeout",
        "tier": 1,
        "name": "Tushare API timeout",
        "trigger": "Mock 503 in TushareAPI client",
        "recovery_code": "backend/app/data_fetcher/tushare_api.py",
        "expected_recovery": "5 retry exhausted → DingTalk P1, fallback (P1-33 design)",
        "expected_sla_sec": 600,
    },
    {
        "id": "tier1_beat_paused",
        "tier": 1,
        "name": "Beat schedule paused",
        "trigger": "celerybeat-schedule.dat stale > 5min",
        "recovery_code": "scripts/audit_beat_heartbeat.py",
        "expected_recovery": "External probe P0 alert + Servy restart",
        "expected_sla_sec": 300,
    },
    {
        "id": "tier1_schtask_fail",
        "tier": 1,
        "name": "Schtask LastResult=1",
        "trigger": "Inject script bug → schtask fail",
        "recovery_code": "scripts/audit_schtask_freshness.py",
        "expected_recovery": "Daily probe P0 alert",
        "expected_sla_sec": 86400,
    },
    # Tier 2: Medium frequency, medium blast
    {
        "id": "tier2_pg_oom",
        "tier": 2,
        "name": "PG connection pool exhausted (LL-009 pattern)",
        "trigger": "Concurrent heavy workload",
        "recovery_code": "scripts/service_manager.ps1",
        "expected_recovery": "Servy restart FastAPI → connections clear",
        "expected_sla_sec": 60,
    },
    {
        "id": "tier2_redis_oom",
        "tier": 2,
        "name": "Redis OOM",
        "trigger": "redis-cli flushdb (drill)",
        "recovery_code": "backend/app/core/stream_bus.py",
        "expected_recovery": "StreamBus reconnect, paper-mode unaffected",
        "expected_sla_sec": 60,
    },
    {
        "id": "tier2_celery_leak",
        "tier": 2,
        "name": "Celery worker leak (LL-189)",
        "trigger": "Sustained 24h worker (no restart)",
        "recovery_code": "docs/adr/ADR-086-celery-worker-periodic-restart-and-memory-monitor.md",
        "expected_recovery": "ADR-086 schtask nightly restart",
        "expected_sla_sec": 86400,
    },
    {
        "id": "tier2_qmt_disconnect",
        "tier": 2,
        "name": "QMT disconnect (LL-180/182)",
        "trigger": "Mock xtquant.disconnect",
        "recovery_code": "backend/engines/broker_qmt.py",
        "expected_recovery": "LL-182 5-axis fix + auto-reconnect",
        "expected_sla_sec": 120,
    },
    # Tier 3: Low frequency, high blast
    {
        "id": "tier3_disk_full",
        "tier": 3,
        "name": "Disk full (D:\\)",
        "trigger": "Disk usage > 95%",
        "recovery_code": "scripts/audit_disk_space.py",
        "expected_recovery": "Hourly probe P0 alert + manual cleanup",
        "expected_sla_sec": 3600,
    },
    {
        "id": "tier3_env_corruption",
        "tier": 3,
        "name": ".env corruption (LL-188 sediment drift)",
        "trigger": "Mid-edit corruption / git revert mid-merge",
        "recovery_code": ".claude/hooks/pre_commit_validate.py",
        "expected_recovery": "Pre-commit canonical check + manual revert from .bak",
        "expected_sla_sec": 1800,
    },
    {
        "id": "tier3_broker_breach",
        "tier": 3,
        "name": "Broker API breach",
        "trigger": "xtquant returns invalid data",
        "recovery_code": "scripts/daily_reconciliation.py",
        "expected_recovery": "T+1 reconciliation flags + DingTalk P0 alert",
        "expected_sla_sec": 86400,
    },
    {
        "id": "tier3_live_disabled_false",
        "tier": 3,
        "name": "LIVE_TRADING_DISABLED accidentally false (or any 5/5 红线 field drift)",
        "trigger": ".env mutation OR Servy reload mismatch (LL-188 sediment drift)",
        "recovery_code": "scripts/audit_redline_runtime.py",
        "expected_recovery": "15-min schtask probe + DingTalk P0 alert on baseline diff",
        "expected_sla_sec": 900,
    },
]


def simulate(scenario: dict) -> dict:
    """Read-only simulate: verify recovery code path exists.

    Returns: {scenario_id, status, reason}
    status ∈ {PASS, GAP, DRIFT}
    """
    if scenario["recovery_code"] == "MISSING":
        return {
            "scenario_id": scenario["id"],
            "tier": scenario["tier"],
            "name": scenario["name"],
            "status": "GAP",
            "reason": "No recovery code documented",
            "recovery_code": None,
        }

    recovery_path = PROJECT_ROOT / scenario["recovery_code"]
    if not recovery_path.exists():
        return {
            "scenario_id": scenario["id"],
            "tier": scenario["tier"],
            "name": scenario["name"],
            "status": "DRIFT",
            "reason": f"Recovery code {scenario['recovery_code']} not found at expected path",
            "recovery_code": scenario["recovery_code"],
        }

    return {
        "scenario_id": scenario["id"],
        "tier": scenario["tier"],
        "name": scenario["name"],
        "status": "PASS",
        "reason": f"Recovery code exists at {scenario['recovery_code']}",
        "recovery_code": scenario["recovery_code"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", type=int, help="Filter by tier (1/2/3)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    target_scenarios = [s for s in SCENARIOS if args.tier is None or s["tier"] == args.tier]
    results = [simulate(s) for s in target_scenarios]

    by_status = {"PASS": 0, "GAP": 0, "DRIFT": 0}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    summary = {
        "total": len(results),
        "by_status": by_status,
        "any_issue": by_status["GAP"] + by_status["DRIFT"] > 0,
    }

    if args.json:
        print(json.dumps({"summary": summary, "scenarios": results}, indent=2, ensure_ascii=False))
    else:
        print(
            f"[disaster-drill-simulator] {summary['total']} scenarios: "
            f"PASS={by_status['PASS']} GAP={by_status['GAP']} DRIFT={by_status['DRIFT']}"
        )
        for r in results:
            sym = {"PASS": "✅", "GAP": "❌", "DRIFT": "⚠️"}.get(r["status"], "?")
            print(f"  {sym} [T{r['tier']}] {r['scenario_id']:30s} — {r['name']}")
            print(f"     reason: {r['reason']}")

    return 1 if summary["any_issue"] else 0


if __name__ == "__main__":
    sys.exit(main())
