"""Plan v8 P0-17 gap surface: Disk space monitor (Tier 3 disaster drill, was MISSING).

Why P0-17 sub-gap:
- Disaster drill catalog Tier 3 scenario "disk_full" had 0 recovery code documented
- Critical: PG WAL / klines_daily growth / backup files can fill D:\\ silently
- LL-009 cross-domain pattern (PG OOM 4-03 sustained)
- No probe = no DingTalk alert until pg_dump fails OR Servy crash

Strategy:
- Cross-platform disk usage probe (Windows wmic logical disk OR Python shutil.disk_usage)
- Tier thresholds: WARN 80% / ALERT 90% / P0 95%
- Check key dirs: D:\\ (project + PG + backups) + C:\\ (Windows + Python tools)
- DingTalk alert on threshold breach via app.core.dingtalk

Usage:
  python scripts/audit_disk_space.py                # Default thresholds
  python scripts/audit_disk_space.py --json         # JSON output
  python scripts/audit_disk_space.py --no-alert     # Skip DingTalk

Exit code:
  0 = all OK
  1 = WARN+ threshold breached
  2 = script error

Schtask register (留 user 触发, classifier 阻止 autonomous):
  schtasks /Create /TN "QuantMind_DiskSpaceProbe" /TR "...audit_disk_space.py" /SC HOURLY /F
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Default thresholds (% of capacity used)
WARN_PCT = 80.0
ALERT_PCT = 90.0
P0_PCT = 95.0

# Directories to monitor (each maps to its filesystem root)
MONITORED_PATHS = [
    PROJECT_ROOT,  # D:\quantmind-v2
    Path("D:\\pgsql"),  # PG bin + WAL
    Path("D:\\pgdata16"),  # PG data
    Path("D:\\quantmind-v2\\backups"),  # backup files
    Path("C:\\Users") if Path("C:\\Users").exists() else None,  # User profile
]


def get_disk_usage(path: Path, warn_pct: float, alert_pct: float, p0_pct: float) -> dict | None:
    """Get disk usage for path's filesystem.

    Returns dict with total_gb / used_gb / free_gb / used_pct / severity.
    None if path doesn't exist.
    """
    if path is None or not path.exists():
        return None

    try:
        usage = shutil.disk_usage(str(path))
    except OSError as exc:
        return {"error": str(exc), "path": str(path)}

    total_gb = usage.total / 1024**3
    used_gb = usage.used / 1024**3
    free_gb = usage.free / 1024**3
    used_pct = (usage.used / usage.total * 100) if usage.total > 0 else 0

    severity = "OK"
    if used_pct >= p0_pct:
        severity = "P0"
    elif used_pct >= alert_pct:
        severity = "ALERT"
    elif used_pct >= warn_pct:
        severity = "WARN"

    return {
        "path": str(path),
        "total_gb": round(total_gb, 1),
        "used_gb": round(used_gb, 1),
        "free_gb": round(free_gb, 1),
        "used_pct": round(used_pct, 1),
        "severity": severity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-alert", action="store_true", help="Skip DingTalk alert")
    parser.add_argument(
        "--warn-pct", type=float, default=WARN_PCT, help=f"WARN threshold (default {WARN_PCT}%%)"
    )
    parser.add_argument(
        "--alert-pct",
        type=float,
        default=ALERT_PCT,
        help=f"ALERT threshold (default {ALERT_PCT}%%)",
    )
    parser.add_argument(
        "--p0-pct", type=float, default=P0_PCT, help=f"P0 threshold (default {P0_PCT}%%)"
    )
    args = parser.parse_args()

    warn_pct, alert_pct, p0_pct = args.warn_pct, args.alert_pct, args.p0_pct

    results = []
    for path in MONITORED_PATHS:
        if path is None:
            continue
        result = get_disk_usage(path, warn_pct, alert_pct, p0_pct)
        if result is None:
            results.append({"path": str(path), "severity": "MISSING", "reason": "path not found"})
        else:
            results.append(result)

    # Aggregate
    by_severity = {"OK": 0, "WARN": 0, "ALERT": 0, "P0": 0, "MISSING": 0}
    for r in results:
        sev = r.get("severity", "MISSING")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    summary = {
        "audit_time": datetime.now(UTC).isoformat(),
        "thresholds": {"warn_pct": warn_pct, "alert_pct": alert_pct, "p0_pct": p0_pct},
        "by_severity": by_severity,
        "any_breach": by_severity["WARN"] + by_severity["ALERT"] + by_severity["P0"] > 0,
    }

    if args.json:
        print(json.dumps({"summary": summary, "paths": results}, indent=2, ensure_ascii=False))
    else:
        print(
            f"[disk-space] {len(results)} paths probed: "
            f"OK={by_severity['OK']} WARN={by_severity['WARN']} "
            f"ALERT={by_severity['ALERT']} P0={by_severity['P0']} MISSING={by_severity['MISSING']}"
        )
        for r in results:
            sev = r.get("severity", "?")
            sym = {"OK": "  ", "WARN": "⚠️", "ALERT": "🚨", "P0": "🔴", "MISSING": "❓"}.get(
                sev, "?"
            )
            if "error" in r:
                print(f"  {sym} {sev:8s} {r['path']:60s} — ERROR: {r['error']}")
            elif "reason" in r:
                print(f"  {sym} {sev:8s} {r['path']:60s} — {r['reason']}")
            else:
                print(
                    f"  {sym} {sev:8s} {r['path']:60s} — used {r['used_pct']}% "
                    f"({r['used_gb']:.1f}/{r['total_gb']:.1f} GB)"
                )

    # DingTalk alert on threshold breach
    if summary["any_breach"] and not args.no_alert:
        try:
            _send_dingtalk_alert(summary, results)
        except Exception as exc:
            print(f"[WARN] DingTalk alert failed: {exc}", file=sys.stderr)

    return 1 if summary["any_breach"] else 0


def _send_dingtalk_alert(summary: dict, results: list[dict]) -> None:
    """Send DingTalk alert on threshold breach (P0/ALERT/WARN escalation)."""
    backend_dir = PROJECT_ROOT / "backend"
    sys.path.insert(0, str(backend_dir))

    # Plan v8 code review HIGH fix (5-20): real send_alert lives at
    # backend/app/services/notification_service.py with signature
    # send_alert(level, title, content, ...). Was using non-existent app.core.dingtalk.
    try:
        from app.services.notification_service import send_alert  # type: ignore[import-not-found]
    except ImportError:
        print("[WARN] notification_service unavailable, skip alert", file=sys.stderr)
        return

    p0 = summary["by_severity"]["P0"]
    alert = summary["by_severity"]["ALERT"]
    warn = summary["by_severity"]["WARN"]

    severity_word = "P0" if p0 > 0 else "ALERT" if alert > 0 else "WARN"
    title = f"[{severity_word}] Disk space probe: P0={p0} ALERT={alert} WARN={warn}"
    body_lines = [f"audit_time: {summary['audit_time']}", "", "Breached paths:"]
    for r in results:
        if r.get("severity") in ("WARN", "ALERT", "P0"):
            body_lines.append(
                f"- [{r['severity']}] {r['path']}: used {r['used_pct']}% "
                f"({r['used_gb']:.1f}/{r['total_gb']:.1f} GB)"
            )
    send_alert(severity_word, title, "\n".join(body_lines))


if __name__ == "__main__":
    sys.exit(main())
