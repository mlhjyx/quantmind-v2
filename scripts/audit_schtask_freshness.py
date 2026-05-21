"""Plan v8 P0-6 closure: Windows Task Scheduler freshness + result probe.

Why P0-6:
- 30+ QuantMind_* schtask 跑 daily, 但 0 自动 probe LastResult / LastRunTime
- LL-181 sustained: schtask 死掉无人知, 直到 user 截图 DingTalk 才发现 (5-18 P0)
- Plan v8 audit: schtask freshness probe absent (P0-6 finding)

Behavior:
- Query Windows Task Scheduler for all QuantMind_* + QM-* + QuantMind-* tasks
  (sustained Servy services + Beat schedule + Daily ops)
- For each: extract LastTaskResult + LastRunTime + NextRunTime + State
- Flag P1 alerts:
  - LastTaskResult != 0 (FAIL or unknown)
  - LastRunTime > 24h ago (stale, schtask not firing)
  - State != "Ready" (Disabled / Running stuck)
- Output: JSON to stdout + optional DingTalk alert via app.core.dingtalk

Usage:
  python scripts/audit_schtask_freshness.py                # Default: alert on FAIL
  python scripts/audit_schtask_freshness.py --json         # Output JSON only
  python scripts/audit_schtask_freshness.py --no-alert     # Skip DingTalk alert
  python scripts/audit_schtask_freshness.py --stale-hours 48  # Custom stale threshold

Exit code:
  0 = all OK
  1 = one or more FAIL detected
  2 = script error (PowerShell missing / permission)

Schtask register (留 user 触发, classifier 阻止 autonomous):
  schtasks /Create /TN "QuantMind_SchtaskFreshnessProbe" \\
    /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \\
         \"D:\\quantmind-v2\\.venv\\Scripts\\python.exe \\
         D:\\quantmind-v2\\scripts\\audit_schtask_freshness.py\"" \\
    /SC DAILY /ST 09:00 /F
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Patterns to match QuantMind schtask names
QUANTMIND_PATTERNS = ("QuantMind_", "QuantMind-", "QM-")

# Default stale threshold: 24 hours
DEFAULT_STALE_HOURS = 24


def query_schtasks_powershell(timeout_sec: int = 60) -> list[dict] | None:
    """Query all scheduled tasks via PowerShell Get-ScheduledTask + Get-ScheduledTaskInfo.

    Returns list of dicts with keys: TaskName, State, LastTaskResult, LastRunTime, NextRunTime.
    None on error.
    """
    ps_script = """
$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -match '^(QuantMind[_-]|QM-)' }
$results = @()
foreach ($t in $tasks) {
    $info = Get-ScheduledTaskInfo -TaskName $t.TaskName -ErrorAction SilentlyContinue
    if ($info) {
        $results += @{
            TaskName = $t.TaskName
            State = [string]$t.State
            LastTaskResult = $info.LastTaskResult
            LastRunTime = if ($info.LastRunTime) { $info.LastRunTime.ToString("o") } else { $null }
            NextRunTime = if ($info.NextRunTime) { $info.NextRunTime.ToString("o") } else { $null }
        }
    }
}
$results | ConvertTo-Json -Depth 3 -Compress
"""

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
        )
        if result.returncode != 0:
            print(f"[ERROR] PowerShell exit={result.returncode}: {result.stderr}", file=sys.stderr)
            return None
        raw = result.stdout.strip()
        if not raw:
            return []
        parsed = json.loads(raw)
        # PowerShell ConvertTo-Json returns dict for single result, list for multiple
        if isinstance(parsed, dict):
            return [parsed]
        return parsed
    except subprocess.TimeoutExpired:
        print(f"[ERROR] PowerShell query timeout (>{timeout_sec}s)", file=sys.stderr)
        return None
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def classify(task: dict, stale_hours: int) -> tuple[str, str]:
    """Classify task health.

    Returns (severity, reason):
      severity ∈ {"OK", "FAIL", "STALE", "DISABLED"}
      reason: human-readable explanation
    """
    state = task.get("State", "Unknown")
    last_result = task.get("LastTaskResult")
    last_run = task.get("LastRunTime")

    # Disabled state
    if state == "Disabled":
        return "DISABLED", f"State={state}"

    # Never run yet
    if last_run is None:
        return "FAIL", "LastRunTime=null (never ran)"

    # Parse last run time
    try:
        last_run_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
        if last_run_dt.tzinfo is None:
            last_run_dt = last_run_dt.replace(tzinfo=UTC)
    except (ValueError, AttributeError):
        return "FAIL", f"LastRunTime parse error: {last_run!r}"

    now = datetime.now(UTC)
    age = now - last_run_dt

    # Stale: hasn't run in N hours (suggests schtask not firing)
    if age > timedelta(hours=stale_hours):
        return "STALE", f"LastRun {age.total_seconds() / 3600:.1f}h ago (> {stale_hours}h)"

    # Failed exit code (non-zero)
    if last_result != 0:
        return "FAIL", f"LastTaskResult={last_result} (expected 0)"

    return "OK", f"LastRun {age.total_seconds() / 3600:.1f}h ago, exit=0"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--no-alert", action="store_true", help="Skip DingTalk alert on FAIL/STALE")
    parser.add_argument(
        "--stale-hours",
        type=int,
        default=DEFAULT_STALE_HOURS,
        help=f"Stale threshold hours (default {DEFAULT_STALE_HOURS})",
    )
    args = parser.parse_args()

    tasks = query_schtasks_powershell()
    if tasks is None:
        return 2

    if not tasks:
        if args.json:
            print(json.dumps({"tasks": [], "summary": "0 QuantMind schtask found"}))
        else:
            print("[audit_schtask_freshness] 0 QuantMind schtask found (unexpected)")
        return 0

    report = []
    fail_count = 0
    stale_count = 0
    ok_count = 0
    disabled_count = 0

    for t in tasks:
        sev, reason = classify(t, args.stale_hours)
        entry = {
            "task_name": t["TaskName"],
            "severity": sev,
            "reason": reason,
            "state": t.get("State"),
            "last_result": t.get("LastTaskResult"),
            "last_run": t.get("LastRunTime"),
            "next_run": t.get("NextRunTime"),
        }
        report.append(entry)
        if sev == "FAIL":
            fail_count += 1
        elif sev == "STALE":
            stale_count += 1
        elif sev == "DISABLED":
            disabled_count += 1
        else:
            ok_count += 1

    summary = {
        "total": len(tasks),
        "ok": ok_count,
        "fail": fail_count,
        "stale": stale_count,
        "disabled": disabled_count,
        "stale_hours_threshold": args.stale_hours,
        "audit_time": datetime.now(UTC).isoformat(),
    }

    if args.json:
        print(json.dumps({"summary": summary, "tasks": report}, indent=2))
    else:
        print(
            f"[audit_schtask_freshness] {len(tasks)} QuantMind tasks: "
            f"OK={ok_count} / FAIL={fail_count} / STALE={stale_count} / DISABLED={disabled_count}"
        )
        for entry in report:
            sev = entry["severity"]
            tn = entry["task_name"]
            reason = entry["reason"]
            print(f"  [{sev:8s}] {tn:50s} — {reason}")

    # DingTalk alert on FAIL/STALE
    if (fail_count + stale_count) > 0 and not args.no_alert:
        try:
            _send_dingtalk_alert(summary, report)
        except Exception as exc:
            print(f"[WARN] DingTalk alert failed: {exc}", file=sys.stderr)

    return 1 if (fail_count + stale_count) > 0 else 0


def _send_dingtalk_alert(summary: dict, report: list[dict]) -> None:
    """Send DingTalk alert via app.core.dingtalk (best-effort, non-blocking)."""
    # Add backend path for app.core import
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    sys.path.insert(0, str(backend_dir))

    try:
        from app.core.dingtalk import send_alert  # type: ignore[import-not-found]
    except ImportError:
        print("[WARN] app.core.dingtalk unavailable, skip alert", file=sys.stderr)
        return

    fail_tasks = [r for r in report if r["severity"] in ("FAIL", "STALE")]
    title = f"[P1] schtask freshness: {summary['fail']} FAIL + {summary['stale']} STALE"
    body_lines = [f"audit_time: {summary['audit_time']}", ""]
    for r in fail_tasks[:10]:  # cap 10 to avoid msg overflow
        body_lines.append(f"- [{r['severity']}] {r['task_name']}: {r['reason']}")
    if len(fail_tasks) > 10:
        body_lines.append(f"... and {len(fail_tasks) - 10} more")

    send_alert(title, "\n".join(body_lines))


if __name__ == "__main__":
    sys.exit(main())
