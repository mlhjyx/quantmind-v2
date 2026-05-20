"""Plan v8 P0-17 Tier 3 gap closure: 5/5 红线 runtime guard probe.

Why P0-17 Tier 3 GAP:
- Disaster drill scenario "tier3_live_disabled_false" had 0 runtime recovery code
- LL-188 sediment drift sustained pattern: .env can drift between Servy reload + actual file
- Pre-commit hook prevents commit-time drift but NOT runtime drift
- Need: periodic runtime probe to detect & alert on 5/5 红线 field changes

Strategy:
- Read backend/.env current values for 5/5 红线 fields
- Compare with persisted baseline (logs/.redline-baseline.json)
- On mismatch: compute drift summary + DingTalk P0 alert
- First run: persist baseline if no baseline exists yet

Usage:
  python scripts/audit_redline_runtime.py                # Probe + alert on drift
  python scripts/audit_redline_runtime.py --json         # JSON output
  python scripts/audit_redline_runtime.py --no-alert     # Skip DingTalk
  python scripts/audit_redline_runtime.py --reset        # Reset baseline (post user-trigger flip)

Exit code:
  0 = no drift OR first-run baseline persisted
  1 = drift detected (5/5 红线 field changed since baseline)
  2 = script error

Schtask register (留 user 触发):
  schtasks /Create /TN "QuantMind_RedlineRuntimeProbe" /TR "...audit_redline_runtime.py" /SC MINUTE /MO 15 /F
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / "backend" / ".env"
BASELINE_FILE = PROJECT_ROOT / "logs" / ".redline-baseline.json"

# 5/5 红线 fields (canonical per ADR-027 §7 + V3 spec)
REDLINE_FIELDS = (
    "EXECUTION_MODE",
    "LIVE_TRADING_DISABLED",
    "QMT_ACCOUNT_ID",
    "DINGTALK_ALERTS_ENABLED",
    "L4_AUTO_MODE_ENABLED",
)


def read_env_field(name: str) -> str:
    """Read field value from .env. Returns MISSING if not found.

    Plan v8 code review MEDIUM fix (5-20): strip surrounding quotes to prevent
    false-positive drift when .env uses EXECUTION_MODE="paper" syntax.
    L4_AUTO_MODE_ENABLED default per backend/app/config.py:Settings (default=False).
    """
    if not ENV_FILE.exists():
        return "MISSING"
    try:
        text = ENV_FILE.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "MISSING"
    m = re.search(rf"^{re.escape(name)}=(.+)$", text, re.MULTILINE)
    if m is None:
        # Default fallback per backend/app/config.py:Settings (sustained 5-20)
        if name == "L4_AUTO_MODE_ENABLED":
            return "false"  # default per config.py L4_AUTO_MODE_ENABLED: bool = False
        return "MISSING"
    # Strip surrounding quotes (single or double) — prevents quote-vs-no-quote false drift.
    return m.group(1).strip().strip('"').strip("'")


def read_current_redline() -> dict[str, str]:
    """Read current 5/5 红线 field values."""
    return {field: read_env_field(field) for field in REDLINE_FIELDS}


class BaselineCorruptedError(Exception):
    """Baseline file exists but JSON parse failed (LL-188 anti-pattern防).

    Plan v8 code review MEDIUM fix (5-20): distinguish "file missing" (first run OK)
    from "file corrupted" (silent re-baseline DANGER — drift detection anchor lost).
    Raise on corruption so main() can exit code 2 + alert, NOT silently re-baseline.
    """


def load_baseline() -> dict[str, str] | None:
    """Load persisted baseline.

    Returns None if file truly absent (first run).
    Raises BaselineCorruptedError if file exists but JSON parse failed.
    """
    if not BASELINE_FILE.exists():
        return None
    try:
        text = BASELINE_FILE.read_text(encoding="utf-8")
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # CORRUPTED — do NOT silently re-baseline (would reset drift anchor).
        raise BaselineCorruptedError(
            f"Baseline file {BASELINE_FILE} corrupted: {exc}. "
            f"Manual review required — review .env mutation history before --reset."
        ) from exc


def persist_baseline(values: dict[str, str]) -> None:
    """Persist baseline to disk (first run OR reset)."""
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "redline_fields": values,
    }
    BASELINE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def diff_baseline(current: dict[str, str], baseline: dict[str, str]) -> list[dict]:
    """Compare current vs baseline, return list of drift entries."""
    drift = []
    baseline_redline = baseline.get("redline_fields", baseline)  # support old/new format
    for field in REDLINE_FIELDS:
        current_val = current.get(field, "MISSING")
        baseline_val = baseline_redline.get(field, "MISSING")
        if current_val != baseline_val:
            drift.append(
                {
                    "field": field,
                    "baseline": baseline_val,
                    "current": current_val,
                }
            )
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-alert", action="store_true", help="Skip DingTalk alert")
    parser.add_argument("--reset", action="store_true", help="Reset baseline (post user-trigger)")
    args = parser.parse_args()

    current = read_current_redline()

    if args.reset:
        persist_baseline(current)
        msg = "[redline-runtime] Baseline RESET captured"
        if args.json:
            print(json.dumps({"reset": True, "current": current}, indent=2, ensure_ascii=False))
        else:
            print(msg)
            for field, val in current.items():
                print(f"  {field} = {val}")
        return 0

    try:
        baseline = load_baseline()
    except BaselineCorruptedError as exc:
        # CORRUPTED baseline — alert + exit 2, NOT silent re-baseline.
        print(f"[redline-runtime] 🔴 BASELINE CORRUPTED: {exc}", file=sys.stderr)
        if not args.no_alert:
            try:
                _send_corruption_alert(str(exc))
            except Exception as alert_exc:
                print(f"[WARN] DingTalk alert failed: {alert_exc}", file=sys.stderr)
        return 2

    if baseline is None:
        # First run (file truly absent): persist baseline
        persist_baseline(current)
        msg = f"[redline-runtime] FIRST RUN — baseline persisted at {BASELINE_FILE}"
        if args.json:
            print(json.dumps({"first_run": True, "current": current}, indent=2, ensure_ascii=False))
        else:
            print(msg)
            for field, val in current.items():
                print(f"  {field} = {val}")
        return 0

    drift = diff_baseline(current, baseline)

    summary = {
        "audit_time": datetime.now(UTC).isoformat(),
        "baseline_captured_at": baseline.get("captured_at"),
        "drift_count": len(drift),
        "drift": drift,
        "current": current,
    }

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        if drift:
            print(f"[redline-runtime] 🔴 P0 DRIFT detected: {len(drift)} field(s)")
            for d in drift:
                print(f"  {d['field']}: baseline={d['baseline']!r} → current={d['current']!r}")
            print(f"  baseline captured: {baseline.get('captured_at')}")
        else:
            print("[redline-runtime] ✅ All 5/5 红线 fields sustained vs baseline")
            for field, val in current.items():
                print(f"  {field} = {val}")

    # DingTalk P0 alert on drift
    if drift and not args.no_alert:
        try:
            _send_dingtalk_alert(summary)
        except Exception as exc:
            print(f"[WARN] DingTalk alert failed: {exc}", file=sys.stderr)

    return 1 if drift else 0


def _send_dingtalk_alert(summary: dict) -> None:
    """Send DingTalk P0 alert on red-line drift (LL-188 anti-pattern recurrence防).

    Plan v8 code review HIGH fix (5-20): real send_alert at
    notification_service.send_alert(level, title, content), not app.core.dingtalk.
    """
    backend_dir = PROJECT_ROOT / "backend"
    sys.path.insert(0, str(backend_dir))

    try:
        from app.services.notification_service import send_alert  # type: ignore[import-not-found]
    except ImportError:
        print("[WARN] notification_service unavailable, skip alert", file=sys.stderr)
        return

    title = f"[P0] 红线 runtime drift: {summary['drift_count']} field(s) changed"
    body_lines = [
        f"audit_time: {summary['audit_time']}",
        f"baseline: {summary['baseline_captured_at']}",
        "",
        "Drift detected:",
    ]
    for d in summary["drift"]:
        body_lines.append(f"- {d['field']}: {d['baseline']!r} → {d['current']!r}")
    body_lines.append("")
    body_lines.append(
        "Required action: IMMEDIATE — verify .env mutation source. If unauthorized, ROLLBACK from .env-backup-*.bak. Reset baseline post-verify via --reset."
    )

    send_alert("P0", title, "\n".join(body_lines))


def _send_corruption_alert(reason: str) -> None:
    """Send DingTalk P0 alert on baseline corruption (drift detection anchor lost)."""
    backend_dir = PROJECT_ROOT / "backend"
    sys.path.insert(0, str(backend_dir))

    try:
        from app.services.notification_service import send_alert  # type: ignore[import-not-found]
    except ImportError:
        print("[WARN] notification_service unavailable, skip alert", file=sys.stderr)
        return

    title = "[P0] 红线 baseline CORRUPTED — drift detection anchor LOST"
    body = (
        f"Baseline file: {BASELINE_FILE}\n"
        f"Reason: {reason}\n\n"
        "Required action: MANUAL review .env mutation history before --reset. "
        "Corrupted baseline ≠ first-run; DO NOT auto-recreate (LL-188 防drift)."
    )
    send_alert("P0", title, body)


if __name__ == "__main__":
    sys.exit(main())
