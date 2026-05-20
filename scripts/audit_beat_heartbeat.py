"""Plan v8 P0-5 closure: Celery Beat death heartbeat probe.

Why P0-5:
- LL-181 sustained (5-18): Celery Beat process 仍存活 (Servy running) 但内部 deadlock
  导致 Beat 不 fire schtask, schedule 真死. 5-18 incident: M3 mitigation 后 4h stress test
- 0 自动 detect — 直到 user 截图 DingTalk 才发现
- Plan v8 audit: Beat death no heartbeat probe (P0-5 finding)

Strategy (外部 probe, 不修改 Beat process):
- celerybeat-schedule.dat is updated on EVERY Beat fire (30s outbox / 60s Beat tick)
- mtime > threshold = Beat dead/deadlocked
- 不依赖 Beat 自身写 Redis heartbeat (反 LL-181: Beat 死时它就不写)
- 外部 file mtime 检测 = robust to internal Beat deadlock

Probe logic:
- Read celerybeat-schedule.dat mtime
- if (now - mtime) > stale_seconds: ALERT (Beat death detected)
- else: OK

Usage:
  python scripts/audit_beat_heartbeat.py                  # Default: 120s stale threshold
  python scripts/audit_beat_heartbeat.py --stale-seconds 60  # Custom (60s)
  python scripts/audit_beat_heartbeat.py --no-alert       # Skip DingTalk alert
  python scripts/audit_beat_heartbeat.py --json           # JSON output

Exit code:
  0 = Beat alive (mtime fresh)
  1 = Beat death detected (mtime stale OR file missing)
  2 = script error

Schtask register (留 user 触发, classifier 阻止 autonomous):
  schtasks /Create /TN "QuantMind_BeatHeartbeatProbe" ^
    /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
         \"D:\\quantmind-v2\\.venv\\Scripts\\python.exe ^
         D:\\quantmind-v2\\scripts\\audit_beat_heartbeat.py\"" ^
    /SC MINUTE /MO 5 /F  # Every 5 minutes
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# celerybeat-schedule.dat 真 path (project root, sustained 4-17 default)
BEAT_SCHEDULE_FILE = Path(__file__).resolve().parent.parent / "celerybeat-schedule.dat"

# Default stale threshold: 300s (5min, conservative for production tick gaps)
# 反 false alarm: Beat tick can lag up to a few minutes during heavy task queue
# (e.g. pre-cleanup 28GB memory leak Session 58+1 morning, LL-189).
# 反 silent miss: LL-181 incident was 1+ hour deadlock, 300s catches that easily.
DEFAULT_STALE_SECONDS = 300


def probe_beat(stale_seconds: int) -> tuple[str, str, dict]:
    """Probe Celery Beat liveness via celerybeat-schedule.dat mtime.

    Returns (severity, reason, data):
      severity ∈ {"OK", "DEAD", "MISSING"}
      reason: human-readable
      data: dict with file_path, mtime, age_seconds, threshold
    """
    if not BEAT_SCHEDULE_FILE.exists():
        return (
            "MISSING",
            f"celerybeat-schedule.dat not found at {BEAT_SCHEDULE_FILE}",
            {"file_path": str(BEAT_SCHEDULE_FILE), "mtime": None},
        )

    mtime_ts = BEAT_SCHEDULE_FILE.stat().st_mtime
    mtime_dt = datetime.fromtimestamp(mtime_ts, tz=UTC)
    now = datetime.now(UTC)
    age_seconds = (now - mtime_dt).total_seconds()

    data = {
        "file_path": str(BEAT_SCHEDULE_FILE),
        "mtime_utc": mtime_dt.isoformat(),
        "now_utc": now.isoformat(),
        "age_seconds": round(age_seconds, 1),
        "stale_threshold_seconds": stale_seconds,
    }

    if age_seconds > stale_seconds:
        return (
            "DEAD",
            f"Beat schedule file mtime {age_seconds:.1f}s ago (> {stale_seconds}s threshold)",
            data,
        )

    return "OK", f"Beat schedule file mtime {age_seconds:.1f}s ago (fresh)", data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stale-seconds",
        type=int,
        default=DEFAULT_STALE_SECONDS,
        help=f"Stale threshold in seconds (default {DEFAULT_STALE_SECONDS})",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    parser.add_argument("--no-alert", action="store_true", help="Skip DingTalk alert on DEAD")
    args = parser.parse_args()

    severity, reason, data = probe_beat(args.stale_seconds)

    if args.json:
        print(
            json.dumps(
                {"severity": severity, "reason": reason, "data": data},
                indent=2,
            )
        )
    else:
        prefix = {
            "OK": "[BEAT-OK]",
            "DEAD": "[BEAT-DEAD]",
            "MISSING": "[BEAT-MISSING]",
        }.get(severity, "[BEAT-?]")
        print(f"{prefix} {reason}")
        if data.get("file_path"):
            print(f"  file: {data['file_path']}")
        if data.get("mtime_utc"):
            print(f"  mtime: {data['mtime_utc']}")
            print(f"  age_seconds: {data['age_seconds']}")
            print(f"  threshold: {data['stale_threshold_seconds']}")

    # DingTalk alert on DEAD/MISSING (LL-181 lesson)
    if severity in ("DEAD", "MISSING") and not args.no_alert:
        try:
            _send_dingtalk_alert(severity, reason, data)
        except Exception as exc:
            print(f"[WARN] DingTalk alert failed: {exc}", file=sys.stderr)

    return 0 if severity == "OK" else 1


def _send_dingtalk_alert(severity: str, reason: str, data: dict) -> None:
    """Send DingTalk alert via app.core.dingtalk (P0 severity, LL-181 sediment)."""
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    sys.path.insert(0, str(backend_dir))

    try:
        from app.core.dingtalk import send_alert  # type: ignore[import-not-found]
    except ImportError:
        print("[WARN] app.core.dingtalk unavailable, skip alert", file=sys.stderr)
        return

    title = f"[P0] Celery Beat {severity} detected — LL-181 类 silent failure"
    body_lines = [
        f"severity: {severity}",
        f"reason: {reason}",
        f"file: {data.get('file_path')}",
        f"mtime: {data.get('mtime_utc') or 'N/A'}",
        f"age: {data.get('age_seconds') or 'N/A'}s (threshold {data.get('stale_threshold_seconds')}s)",
        "",
        "Required action: 检查 Celery Beat Servy service status, 必要时 servy-cli restart QuantMind-CeleryBeat",
    ]
    send_alert(title, "\n".join(body_lines))


if __name__ == "__main__":
    sys.exit(main())
