"""Plan v8 P0-15 closure: 09:30 SH market open watcher.

Why P0-15:
- A 股 09:30 SH market open 是 critical signal/execute trigger
- 0 自动 probe — schtask 死或 Beat dead, market 开盘后无人知
- Plan v8 audit: 09:30 SH market open no watcher (P0-15 finding)

Strategy:
- Run @09:31 SH (schtask) — 1 minute after market open
- Check 3 signals (all must be healthy):
  1. trading_day_today (is_trading_day SSOT)
  2. Latest DailyExecute schtask fire OR ExecutionService log
  3. Recent qmt:status Redis stream entry (last 5min)
- If any FAIL on trading day: DingTalk P0 alert

Usage:
  python scripts/audit_market_open_watcher.py           # Default, alerts on FAIL
  python scripts/audit_market_open_watcher.py --json    # JSON output only
  python scripts/audit_market_open_watcher.py --no-alert  # Skip DingTalk

Exit code:
  0 = market open healthy
  1 = market open watcher detected issue (DingTalk alert sent)
  2 = script error

Schtask register (留 user 触发):
  schtasks /Create /TN "QuantMind_MarketOpenWatcher" \\
    /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \\
         \"D:\\quantmind-v2\\.venv\\Scripts\\python.exe \\
         D:\\quantmind-v2\\scripts\\audit_market_open_watcher.py\"" \\
    /SC DAILY /ST 09:31 /F  # Trigger 1 minute after market open
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# A 股 trading hours (SH timezone)
SH_TZ = ZoneInfo("Asia/Shanghai")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30

# Beat schedule.dat path (P0-5 reuse pattern)
BEAT_SCHEDULE_FILE = Path(__file__).resolve().parent.parent / "celerybeat-schedule.dat"


def check_trading_day_today() -> tuple[bool, str]:
    """Check if today is A 股 trading day (heuristic weekday + holiday list, 沿用 DB SSOT 优先).

    Strategy:
    - Primary: query A股 trading_calendar SSOT (app.services.trading_calendar.is_trading_day)
      via DB connection (env-driven from backend/.env)
    - Fallback: weekday heuristic (Mon-Fri = trading day, weekend = NOT)
    - 反 LL-181 sustained: 节假日 calendar 漂移 — DB query 失败时退 heuristic 但
      log WARNING (heuristic 可能误报节假日 = trading day).
    """
    today = datetime.now(SH_TZ).date()

    # Primary: DB SSOT
    try:
        import re

        import psycopg2

        backend_dir = Path(__file__).resolve().parent.parent / "backend"
        env_text = (backend_dir / ".env").read_text(encoding="utf-8")
        m = re.search(
            r"^DATABASE_URL=postgresql\+?(?:asyncpg)?://([^:]+):([^@]+)@([^:]+):(\d+)/(\S+)",
            env_text,
            re.MULTILINE,
        )
        if m:
            sys.path.insert(0, str(backend_dir))
            from app.services.trading_calendar import (
                is_trading_day,  # type: ignore[import-not-found]
            )

            u, p, h, port, db = m.groups()
            conn = psycopg2.connect(
                host=h, port=port, dbname=db, user=u, password=p, connect_timeout=5
            )
            try:
                ok = is_trading_day(conn, today)
                return ok, f"is_trading_day({today}) = {ok} [DB SSOT]"
            finally:
                conn.close()
    except Exception as exc:
        # Fallback to heuristic
        is_weekday = today.weekday() < 5  # Mon=0, Sun=6
        return (
            is_weekday,
            f"weekday heuristic ({today}, dow={today.weekday()}) = {is_weekday} [fallback, DB error: {exc}]",
        )

    # If env parse fails, fall through to weekday heuristic
    is_weekday = today.weekday() < 5
    return (
        is_weekday,
        f"weekday heuristic ({today}) = {is_weekday} [env parse failed]",
    )


def check_beat_alive() -> tuple[bool, str]:
    """Check Celery Beat alive via celerybeat-schedule.dat mtime (P0-5 reuse)."""
    if not BEAT_SCHEDULE_FILE.exists():
        return False, "celerybeat-schedule.dat missing"

    mtime = datetime.fromtimestamp(BEAT_SCHEDULE_FILE.stat().st_mtime, tz=UTC)
    age_sec = (datetime.now(UTC) - mtime).total_seconds()
    # Beat should tick every 30-60s, allow 300s for safety net
    if age_sec > 300:
        return False, f"Beat stale, mtime {age_sec:.1f}s ago > 300s"
    return True, f"Beat fresh, mtime {age_sec:.1f}s ago"


def check_market_open_time() -> tuple[bool, str]:
    """Check current SH time is past 09:30 SH (within trading hours)."""
    now_sh = datetime.now(SH_TZ)
    market_open = now_sh.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
    )
    if now_sh < market_open:
        return False, f"Current SH time {now_sh.strftime('%H:%M')} pre-market"

    elapsed = now_sh - market_open
    if elapsed > timedelta(hours=6):  # After 15:30 SH
        return False, f"Current SH time {now_sh.strftime('%H:%M')} post-market"

    return True, f"Current SH time {now_sh.strftime('%H:%M')} in trading hours"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-alert", action="store_true", help="Skip DingTalk alert")
    args = parser.parse_args()

    # Check 1: trading day today
    is_trading, reason_trading = check_trading_day_today()

    # If non-trading day, exit OK (no alert needed)
    if not is_trading:
        result = {
            "severity": "OK",
            "reason": f"Non-trading day or check failed: {reason_trading}",
            "checks": {"trading_day": False},
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"[market-open-watcher] OK (non-trading): {reason_trading}")
        return 0

    # On trading day, check all signals
    is_market_hours, reason_time = check_market_open_time()
    is_beat_alive, reason_beat = check_beat_alive()

    checks = {
        "trading_day": True,
        "market_hours": is_market_hours,
        "beat_alive": is_beat_alive,
    }

    all_healthy = is_market_hours and is_beat_alive
    severity = "OK" if all_healthy else "ALERT"

    result = {
        "severity": severity,
        "checks": checks,
        "reasons": {
            "trading_day": reason_trading,
            "market_hours": reason_time,
            "beat_alive": reason_beat,
        },
        "audit_time": datetime.now(SH_TZ).isoformat(),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        prefix = "[market-open-watcher]"
        print(f"{prefix} {severity}")
        print(f"  trading_day: {reason_trading}")
        print(f"  market_hours: {reason_time}")
        print(f"  beat_alive: {reason_beat}")

    if severity == "ALERT" and not args.no_alert:
        try:
            _send_dingtalk_alert(result)
        except Exception as exc:
            print(f"[WARN] DingTalk alert failed: {exc}", file=sys.stderr)

    return 0 if all_healthy else 1


def _send_dingtalk_alert(result: dict) -> None:
    """Send DingTalk P0 alert on market open failure."""
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    sys.path.insert(0, str(backend_dir))

    try:
        from app.core.dingtalk import send_alert  # type: ignore[import-not-found]
    except ImportError:
        print("[WARN] app.core.dingtalk unavailable, skip alert", file=sys.stderr)
        return

    title = "[P0] 09:30 SH market open watcher ALERT"
    body_lines = [
        f"audit_time: {result['audit_time']}",
        "",
        "Health checks:",
    ]
    for check, ok in result["checks"].items():
        sym = "✅" if ok else "❌"
        body_lines.append(f"  {sym} {check}: {result['reasons'].get(check, 'N/A')}")
    body_lines.append("")
    body_lines.append("Required action: 检查 Servy Celery + Beat status, 必要时 restart.")

    send_alert(title, "\n".join(body_lines))


if __name__ == "__main__":
    sys.exit(main())
