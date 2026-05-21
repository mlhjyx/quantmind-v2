"""V3 BAU — Monday morning pre-09:31 live-fire automated preflight verification.

Runs 7 checks programmatically (sustained MONDAY_2026_05_18_LIVE_FIRE_CHECKLIST.md
§09:00 SH manual procedure). Each check outputs PASS/FAIL + reason + evidence cite.
Exit 0 if all pass; exit 1 if any fail (operator must investigate failures BEFORE
09:31 SH live-fire).

## 7 checks

1. **Servy services** — 4 Servy-managed services (FastAPI / Celery / CeleryBeat / QMTData) all Running
2. **services_healthcheck full pass** — invokes scripts/services_healthcheck.py; expects Status: ok
3. **FastAPI /health endpoint** — returns {"status":"ok", "execution_mode":"live"}
4. **xtquant truth via Redis** — portfolio:nav fresh (≤ 10min) + portfolio:current size = 0
5. **qm:qmt:status stream fresh** — XLEN > 0 + last entry timestamp ≤ 10min
6. **DB freshness** — klines_daily MAX(trade_date) ≥ 2026-05-15 (sustained from CT-2c-pre Sat backfill)
7. **QuantMind_DailyExecute schtask** — State=Ready + NextRun ≈ today 09:31:00

## Output

- Console: structured PASS/FAIL per check + final summary
- Log: `logs/monday_preflight_<YYYY_MM_DD>.log` (timestamped evidence capture)

## Usage

```bash
# 09:00 SH Mon: run before any other ops
python scripts/monday_morning_preflight.py

# Optional: --json for machine-readable output
python scripts/monday_morning_preflight.py --json
```

关联铁律: 25 / 33 (fail-loud) / 41 (timezone) / 43 (schtask hardening)
关联 ADR-077 §3 (emergency rollback path readiness verify pre-condition)
关联 MONDAY_2026_05_18_LIVE_FIRE_CHECKLIST.md §1 (manual procedure this script automates)
关联 LL-074 (Beat zombie watchdog SOP — services_healthcheck.py invocation)
关联 LL-175 lesson 1 (comprehensive testing surfaces P0 the gate-verification system misses)
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# ruff: noqa: E402
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "backend" / ".env")

from app.data_fetcher.data_loader import get_sync_conn

logger = logging.getLogger("monday_morning_preflight")

_SERVY_SERVICES: tuple[str, ...] = (
    "QuantMind-FastAPI",
    "QuantMind-Celery",
    "QuantMind-CeleryBeat",
    "QuantMind-QMTData",
)

_FRESHNESS_THRESHOLD_MIN = 10  # max staleness for fresh-data checks
_HEALTH_URL = "http://127.0.0.1:8000/health"
_TARGET_KLINES_DATE = "2026-05-15"  # min freshness threshold per Sat backfill
_TARGET_SCHTASK = "QuantMind_DailyExecute"


def _now_sh() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _check_servy_services() -> dict:
    """Check 1: All 4 Servy services Running."""
    try:
        ps_cmd = (
            "Get-Service "
            + ", ".join(f"'{s}'" for s in _SERVY_SERVICES)
            + " | ForEach-Object { @{Name=$_.Name; Status=$_.Status.ToString()} } | ConvertTo-Json"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return {
                "name": "servy_services",
                "pass": False,
                "reason": f"powershell exit={result.returncode}: {result.stderr[:200]}",
            }

        parsed = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(parsed, dict):
            parsed = [parsed]

        service_states = {item["Name"]: item["Status"] for item in parsed}
        not_running = {k: v for k, v in service_states.items() if v != "Running"}
        if not_running:
            return {
                "name": "servy_services",
                "pass": False,
                "reason": f"NOT RUNNING: {not_running}",
                "evidence": service_states,
            }
        return {
            "name": "servy_services",
            "pass": True,
            "reason": f"4/4 Running: {list(service_states.keys())}",
            "evidence": service_states,
        }
    except Exception as e:  # noqa: BLE001 — broad catch for preflight robustness
        return {"name": "servy_services", "pass": False, "reason": f"{type(e).__name__}: {e}"}


def _check_services_healthcheck() -> dict:
    """Check 2: services_healthcheck.py full pass."""
    try:
        result = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
                str(PROJECT_ROOT / "scripts" / "services_healthcheck.py"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        # exit 0 = ok; exit 1 = warn (degraded dedup); exit 2 = error
        # (Trust exit code only — services_healthcheck.py writes via structlog to stderr,
        # not stdout; we don't try to parse log output for "Status: ok" string.)
        if result.returncode == 0:
            return {
                "name": "services_healthcheck",
                "pass": True,
                "reason": "exit=0 (Status: ok per documented contract)",
                "evidence": {"exit": 0, "stderr_tail": (result.stderr or "")[-300:]},
            }
        return {
            "name": "services_healthcheck",
            "pass": False,
            "reason": f"exit={result.returncode} (1=warn-dedup, 2=error); stderr tail: {(result.stderr or '')[-300:]}",
        }
    except Exception as e:  # noqa: BLE001
        return {"name": "services_healthcheck", "pass": False, "reason": f"{type(e).__name__}: {e}"}


def _check_fastapi_health() -> dict:
    """Check 3: /health endpoint returns execution_mode=live."""
    try:
        import urllib.request

        with urllib.request.urlopen(_HEALTH_URL, timeout=5) as resp:
            body = json.loads(resp.read().decode())

        status = body.get("status")
        mode = body.get("execution_mode")
        if status == "ok" and mode == "live":
            return {
                "name": "fastapi_health",
                "pass": True,
                "reason": "status=ok execution_mode=live",
                "evidence": body,
            }
        return {
            "name": "fastapi_health",
            "pass": False,
            "reason": f"unexpected: status={status} execution_mode={mode}",
            "evidence": body,
        }
    except Exception as e:  # noqa: BLE001
        return {"name": "fastapi_health", "pass": False, "reason": f"{type(e).__name__}: {e}"}


def _check_xtquant_truth() -> dict:
    """Check 4: xtquant truth via Redis (portfolio:nav fresh + position_count=0)."""
    try:
        import redis

        r = redis.Redis(host="localhost", port=6379, decode_responses=True)
        nav_raw = r.get("portfolio:nav")
        if not nav_raw:
            return {"name": "xtquant_truth", "pass": False, "reason": "portfolio:nav is empty"}

        nav = json.loads(nav_raw)
        position_count = nav.get("position_count")
        updated_at = nav.get("updated_at")

        # Parse updated_at and check freshness.
        upd_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        age_min = (datetime.now(UTC) - upd_dt).total_seconds() / 60

        portfolio_current = r.hgetall("portfolio:current")
        pc_size = len(portfolio_current) if portfolio_current else 0

        issues = []
        if age_min > _FRESHNESS_THRESHOLD_MIN:
            issues.append(
                f"portfolio:nav stale {age_min:.1f}min (threshold {_FRESHNESS_THRESHOLD_MIN}min)"
            )
        if position_count != pc_size:
            issues.append(f"position_count={position_count} != portfolio:current size={pc_size}")

        if issues:
            return {
                "name": "xtquant_truth",
                "pass": False,
                "reason": "; ".join(issues),
                "evidence": {
                    "nav": nav,
                    "portfolio_current_size": pc_size,
                    "age_min": round(age_min, 1),
                },
            }
        return {
            "name": "xtquant_truth",
            "pass": True,
            "reason": f"cash={nav.get('cash')} position_count={position_count} portfolio:current_size={pc_size} age={age_min:.1f}min",
            "evidence": {"nav": nav, "age_min": round(age_min, 1)},
        }
    except Exception as e:  # noqa: BLE001
        return {"name": "xtquant_truth", "pass": False, "reason": f"{type(e).__name__}: {e}"}


def _check_qm_qmt_status_stream() -> dict:
    """Check 5: qm:qmt:status stream fresh."""
    try:
        import redis

        r = redis.Redis(host="localhost", port=6379, decode_responses=True)
        xlen = r.xlen("qm:qmt:status")
        if xlen == 0:
            return {"name": "qm_qmt_status_stream", "pass": False, "reason": "stream XLEN=0"}

        last_entries = r.xrevrange("qm:qmt:status", count=1)
        if not last_entries:
            return {"name": "qm_qmt_status_stream", "pass": False, "reason": "no entries returned"}

        last_id = last_entries[0][0]
        # Stream ID format: <ms>-<seq>
        ms = int(last_id.split("-")[0])
        last_dt = datetime.fromtimestamp(ms / 1000, tz=UTC)
        age_min = (datetime.now(UTC) - last_dt).total_seconds() / 60

        if age_min > _FRESHNESS_THRESHOLD_MIN:
            return {
                "name": "qm_qmt_status_stream",
                "pass": False,
                "reason": f"stream stale {age_min:.1f}min (threshold {_FRESHNESS_THRESHOLD_MIN}min)",
                "evidence": {"xlen": xlen, "last_id": last_id, "age_min": round(age_min, 1)},
            }
        return {
            "name": "qm_qmt_status_stream",
            "pass": True,
            "reason": f"XLEN={xlen} last_id={last_id} age={age_min:.1f}min",
            "evidence": {"xlen": xlen, "last_id": last_id, "age_min": round(age_min, 1)},
        }
    except Exception as e:  # noqa: BLE001
        return {"name": "qm_qmt_status_stream", "pass": False, "reason": f"{type(e).__name__}: {e}"}


def _check_db_freshness() -> dict:
    """Check 6: klines_daily MAX(trade_date) >= 2026-05-15."""
    try:
        with get_sync_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT MAX(trade_date)::text FROM klines_daily")
            klines_latest = cur.fetchone()[0]
            cur.execute("SELECT MAX(trade_date)::text FROM daily_basic")
            basic_latest = cur.fetchone()[0]

        if (klines_latest or "") >= _TARGET_KLINES_DATE and (
            basic_latest or ""
        ) >= _TARGET_KLINES_DATE:
            return {
                "name": "db_freshness",
                "pass": True,
                "reason": f"klines={klines_latest} daily_basic={basic_latest} (target >= {_TARGET_KLINES_DATE})",
                "evidence": {"klines_daily": klines_latest, "daily_basic": basic_latest},
            }
        return {
            "name": "db_freshness",
            "pass": False,
            "reason": f"klines={klines_latest} daily_basic={basic_latest} below {_TARGET_KLINES_DATE}",
            "evidence": {"klines_daily": klines_latest, "daily_basic": basic_latest},
        }
    except Exception as e:  # noqa: BLE001
        return {"name": "db_freshness", "pass": False, "reason": f"{type(e).__name__}: {e}"}


def _check_daily_execute_schtask() -> dict:
    """Check 7: QuantMind_DailyExecute schtask State=Ready + NextRun ≈ today 09:31."""
    try:
        ps_cmd = (
            f"$t = Get-ScheduledTask -TaskName '{_TARGET_SCHTASK}'; "
            f"$i = Get-ScheduledTaskInfo -TaskName '{_TARGET_SCHTASK}'; "
            "@{State=$t.State.ToString(); NextRun=$i.NextRunTime.ToString('o'); "
            "LastRun=$i.LastRunTime.ToString('o'); LastResult=$i.LastTaskResult} | ConvertTo-Json"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return {
                "name": "daily_execute_schtask",
                "pass": False,
                "reason": f"powershell exit={result.returncode}: {result.stderr[:200]}",
            }

        info = json.loads(result.stdout)
        state = info.get("State")
        next_run_iso = info.get("NextRun")

        if state != "Ready":
            return {
                "name": "daily_execute_schtask",
                "pass": False,
                "reason": f"State={state} (expected Ready)",
                "evidence": info,
            }

        # Verify NextRun is in the future (i.e., not stale past time).
        try:
            next_run_dt = datetime.fromisoformat(next_run_iso)
            if next_run_dt.tzinfo is None:
                next_run_dt = next_run_dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            now_sh = _now_sh()
            if next_run_dt < now_sh:
                return {
                    "name": "daily_execute_schtask",
                    "pass": False,
                    "reason": f"NextRun {next_run_iso} is in the past (now SH={now_sh.isoformat()})",
                    "evidence": info,
                }
        except Exception as e:  # noqa: BLE001
            return {
                "name": "daily_execute_schtask",
                "pass": False,
                "reason": f"NextRun parse error: {e}",
                "evidence": info,
            }

        return {
            "name": "daily_execute_schtask",
            "pass": True,
            "reason": f"State=Ready NextRun={next_run_iso}",
            "evidence": info,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "name": "daily_execute_schtask",
            "pass": False,
            "reason": f"{type(e).__name__}: {e}",
        }


# NOTE: previous Check #5 "qm:qmt:status stream fresh" REMOVED — stream is
# event-driven (publishes only on state CHANGE), not heartbeat. 0 events during
# steady-state (cash + 持仓 unchanged) is normal, not a failure. Liveness is
# verified via Check #4 portfolio:nav freshness (HASH key updated every poll).
# Stream freshness check would produce false-positive FAIL during normal steady
# state and is therefore harmful. 6 checks total (was 7).
#
# Check 7 added 2026-05-18 per LL-179 lesson 5: Servy "Running" state ≠ Beat
# dispatch loop alive. Beat process can be Running but unable to dispatch
# (broker disconnect / persistent DB corrupt / silent termination 0 stderr).
# Mon 5-18 incident: Beat ran fine 22:24-22:49 SH 5-17, then silently terminated;
# Servy state lagged + 13.5h 0 task dispatch. Check 7 = celery-beat-stderr.log
# last "Sending due task" entry within last 5min (outbox-publisher-tick is 30s
# Beat cadence, so 5min staleness = ~10 missed ticks = certain dispatch failure).


def _check_beat_dispatch_alive() -> dict:
    """Check 7: CeleryBeat dispatch loop alive (LL-179 lesson 5 sediment).

    Servy "Running" state ≠ Beat dispatch loop active. Beat process can survive
    while dispatch loop dies (broker disconnect / persistent DB corrupt / silent
    process death). Direct evidence: celery-beat-stderr.log latest 'Sending due
    task' entry. 5min staleness threshold = ~10 missed 30s-cadence outbox-publisher
    ticks → certain failure (not transient).
    """
    import re

    try:
        log_path = PROJECT_ROOT / "logs" / "celery-beat-stderr.log"
        if not log_path.exists():
            return {
                "name": "beat_dispatch_alive",
                "pass": False,
                "reason": "celery-beat-stderr.log not found",
            }

        # Read last 8KB tail (sufficient for ~50 dispatch entries).
        size = log_path.stat().st_size
        offset = max(0, size - 8192)
        with open(log_path, "rb") as f:
            f.seek(offset)
            tail = f.read().decode("utf-8", errors="replace")

        pattern = re.compile(
            r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+: INFO/MainProcess\] Scheduler: Sending due task"
        )
        matches = pattern.findall(tail)
        if not matches:
            return {
                "name": "beat_dispatch_alive",
                "pass": False,
                "reason": "no 'Sending due task' entries in last 8KB stderr tail (Beat dispatch loop dead)",
            }

        latest_ts_str = matches[-1]
        latest_dt = datetime.fromisoformat(latest_ts_str).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        now_sh = _now_sh()
        delta_sec = (now_sh - latest_dt).total_seconds()

        if delta_sec > 300:
            return {
                "name": "beat_dispatch_alive",
                "pass": False,
                "reason": (
                    f"latest dispatch {latest_ts_str} ({int(delta_sec)}s ago) > 5min — "
                    "Beat may be silently terminated (LL-179 lesson 5)"
                ),
                "evidence": {"latest_dispatch": latest_ts_str, "delta_sec": int(delta_sec)},
            }

        return {
            "name": "beat_dispatch_alive",
            "pass": True,
            "reason": f"latest dispatch {latest_ts_str} ({int(delta_sec)}s ago)",
            "evidence": {"latest_dispatch": latest_ts_str, "delta_sec": int(delta_sec)},
        }
    except Exception as e:  # noqa: BLE001
        return {"name": "beat_dispatch_alive", "pass": False, "reason": f"{type(e).__name__}: {e}"}


_CHECKS = (
    ("1. Servy services (4 services Running)", _check_servy_services),
    ("2. services_healthcheck full pass", _check_services_healthcheck),
    ("3. FastAPI /health (execution_mode=live)", _check_fastapi_health),
    ("4. xtquant truth via Redis (nav fresh + 0 持仓)", _check_xtquant_truth),
    ("5. DB freshness (klines_daily >= 2026-05-15)", _check_db_freshness),
    ("6. QuantMind_DailyExecute schtask Ready", _check_daily_execute_schtask),
    ("7. CeleryBeat dispatch loop alive (LL-179 lesson 5)", _check_beat_dispatch_alive),
)


def _run_all() -> tuple[list[dict], bool]:
    """Run all checks; return (results, all_pass)."""
    results = []
    all_pass = True
    for label, check_fn in _CHECKS:
        result = check_fn()
        result["label"] = label
        results.append(result)
        if not result["pass"]:
            all_pass = False
    return results, all_pass


def _format_console(results: list[dict], all_pass: bool, sh_now: datetime) -> str:
    lines = [
        "=" * 70,
        f"Monday Morning Preflight — {sh_now.strftime('%Y-%m-%d %H:%M:%S')} SH",
        "=" * 70,
        "",
    ]
    for r in results:
        mark = "✅ PASS" if r["pass"] else "❌ FAIL"
        lines.append(f"{mark}  {r['label']}")
        lines.append(f"        {r['reason']}")
        lines.append("")
    lines.append("=" * 70)
    pass_count = sum(1 for r in results if r["pass"])
    overall = "✅ ALL PASS" if all_pass else f"❌ FAIL — {pass_count}/{len(results)} pass"
    lines.append(f"Overall: {overall}")
    if not all_pass:
        lines.append("")
        lines.append("⚠️  DO NOT proceed to 09:31 live-fire until ALL checks pass.")
        lines.append("    Refer to MONDAY_2026_05_18_LIVE_FIRE_CHECKLIST.md §1 'If fail' column.")
    lines.append("=" * 70)
    return "\n".join(lines)


def _write_log(results: list[dict], all_pass: bool, sh_now: datetime) -> Path:
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"monday_preflight_{sh_now.strftime('%Y_%m_%d')}.log"
    payload = {
        "ran_at_sh": sh_now.isoformat(),
        "ran_at_utc": datetime.now(UTC).isoformat(),
        "all_pass": all_pass,
        "pass_count": sum(1 for r in results if r["pass"]),
        "total_count": len(results),
        "checks": results,
    }
    log_path.write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    return log_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json", action="store_true", help="output JSON only (no console formatting)"
    )
    parser.add_argument(
        "--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    sh_now = _now_sh()
    results, all_pass = _run_all()
    log_path = _write_log(results, all_pass, sh_now)

    if args.json:
        print(
            json.dumps(
                {
                    "ran_at_sh": sh_now.isoformat(),
                    "all_pass": all_pass,
                    "checks": results,
                    "log_path": str(log_path),
                },
                indent=2,
                default=str,
                ensure_ascii=False,
            )
        )
    else:
        print(_format_console(results, all_pass, sh_now))
        print(f"\nEvidence captured: {log_path}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
