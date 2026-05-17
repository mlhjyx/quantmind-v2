"""V3 CT-2c-pre — klines + daily_basic backfill 2026-05-08 ~ 2026-05-15.

Scope (6 A-share trading days × 4 Tushare endpoints):
  - 2026-05-08 (Fri)
  - 2026-05-11 (Mon) ~ 2026-05-15 (Fri) — 5 days
  - 5-09 (Sat) + 5-10 (Sun) excluded (non-trading)

Per-day pipeline:
  1. merge_daily_data(date) -> klines_daily upsert  (daily + adj_factor + stk_limit merged)
  2. fetch_daily_basic_by_date(date) -> daily_basic upsert

Idempotent: ON CONFLICT (code, trade_date) DO UPDATE (DataPipeline-managed).

Modes (sustained CT-1a/CT-2b 3-mode runner体例):
  --dry-run  (default): preflight verify (current MAX trade_date) + print plan, 0 mutation
  --apply              : execute backfill with per-day commit + per-day verify
  --verify             : post-apply state verify (MAX trade_date >= 2026-05-15)

关联铁律: 17 (DataPipeline upsert) / 25 (改什么读什么) / 33 (fail-loud) / 41 (timezone)
关联 Plan: V3 PT Cutover Plan v0.4 §A CT-2c-pre operational health remediation
关联 ADR-082 (reserved) §3 candidate: post-cutover data ingestion automation
关联 Finding #15/#17/#23/#25 (CT-2c kickoff Phase 0)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# ruff: noqa: E402
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "backend" / ".env")

from app.data_fetcher.data_loader import (
    get_sync_conn,
    upsert_daily_basic,
    upsert_klines_daily,
)
from app.data_fetcher.tushare_api import TushareAPI

logger = logging.getLogger("backfill_klines_2026_05")

# 6 A-share trading days to backfill (verified via trading_calendar at Phase 0 prep).
_TARGET_DATES: tuple[str, ...] = (
    "20260508",  # Friday
    "20260511",  # Monday
    "20260512",
    "20260513",
    "20260514",
    "20260515",  # Friday (latest)
)

# Sustained CT-1a/CT-2b — strict env-check before --apply
_REQUIRED_ENV_FOR_APPLY: tuple[str, ...] = ("TUSHARE_TOKEN",)


def _now_iso() -> tuple[str, str]:
    """Return (utc_iso, shanghai_iso) sustained 铁律 41."""
    now_utc = datetime.now(UTC)
    return (
        now_utc.isoformat(),
        now_utc.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
    )


def _check_apply_env() -> list[str]:
    """Strict env gate sustained CT-1a P2 fix体例."""
    failures = []
    for k in _REQUIRED_ENV_FOR_APPLY:
        v = os.environ.get(k, "")
        if not v:
            failures.append(f"{k} not set or empty")
    return failures


def _read_db_state() -> dict[str, str]:
    """Read MAX(trade_date) for klines_daily + daily_basic."""
    with get_sync_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(trade_date)::text FROM klines_daily")
        klines_latest = cur.fetchone()[0]
        cur.execute("SELECT MAX(trade_date)::text FROM daily_basic")
        basic_latest = cur.fetchone()[0]
    return {"klines_daily": klines_latest, "daily_basic": basic_latest}


def _preflight_summary(state: dict[str, str]) -> str:
    """Render preflight summary."""
    target_latest = "2026-05-15"
    lines = [
        "=== Preflight ===",
        f"  klines_daily latest: {state['klines_daily']}  (target: >= {target_latest})",
        f"  daily_basic  latest: {state['daily_basic']}  (target: >= {target_latest})",
        f"  Target dates ({len(_TARGET_DATES)}): {', '.join(_TARGET_DATES)}",
    ]
    return "\n".join(lines)


def _dry_run() -> int:
    """Preflight + plan print, 0 mutation."""
    state = _read_db_state()
    print(_preflight_summary(state))
    print()
    print("=== Plan ===")
    print("  Per date (× 6):")
    print("    1. TushareAPI.merge_daily_data(date) -> klines_daily upsert")
    print("    2. TushareAPI.fetch_daily_basic_by_date(date) -> daily_basic upsert")
    print("  Atomic per-day commit. Idempotent upsert (ON CONFLICT DO UPDATE).")
    print("  Sustained 铁律 17 (DataPipeline) + 41 (UTC) + LL-098 X10.")
    print()
    print("=== DRY RUN COMPLETE — re-run with --apply to execute ===")
    return 0


def _apply_one_date(api: TushareAPI, trade_date_str: str) -> dict[str, int]:
    """Backfill single date — returns row counts."""
    t0 = time.time()

    # Step 1: klines (merged daily + adj_factor + stk_limit).
    logger.info("[%s] fetching merged daily data...", trade_date_str)
    df_klines = api.merge_daily_data(trade_date_str)
    if df_klines is None or len(df_klines) == 0:
        raise RuntimeError(f"merge_daily_data returned empty for {trade_date_str}")
    n_klines = upsert_klines_daily(df_klines)
    logger.info("[%s] klines_daily upserted: %d rows", trade_date_str, n_klines)

    # Step 2: daily_basic.
    logger.info("[%s] fetching daily_basic...", trade_date_str)
    df_basic = api.fetch_daily_basic_by_date(trade_date_str)
    if df_basic is None or len(df_basic) == 0:
        raise RuntimeError(f"fetch_daily_basic_by_date returned empty for {trade_date_str}")
    n_basic = upsert_daily_basic(df_basic)
    logger.info("[%s] daily_basic upserted: %d rows", trade_date_str, n_basic)

    elapsed = time.time() - t0
    logger.info(
        "[%s] done in %.1fs — klines=%d daily_basic=%d",
        trade_date_str,
        elapsed,
        n_klines,
        n_basic,
    )
    return {"klines": n_klines, "daily_basic": n_basic, "elapsed_sec": int(elapsed)}


def _apply() -> int:
    """Execute backfill with per-day commit + per-day verify."""
    # Strict env-check gate sustained CT-1a P2 fix体例.
    env_failures = _check_apply_env()
    if env_failures:
        print("❌ apply BLOCKED — env-check failed:")
        for f in env_failures:
            print(f"  - {f}")
        return 1

    state_pre = _read_db_state()
    print(_preflight_summary(state_pre))
    print()

    utc_iso, sh_iso = _now_iso()
    print(f"=== APPLY started — UTC={utc_iso} SH={sh_iso} ===")
    print()

    api = TushareAPI()
    summary = []
    for trade_date_str in _TARGET_DATES:
        try:
            r = _apply_one_date(api, trade_date_str)
            summary.append((trade_date_str, "ok", r))
        except Exception as e:  # noqa: BLE001 — broad except by design: continue with remaining dates per partial-backfill体例
            logger.exception("[%s] FAILED", trade_date_str)
            summary.append((trade_date_str, "fail", {"error": str(e)}))
            # Continue with remaining dates — partial backfill better than total fail.
            # NOTE: idempotent ON CONFLICT DO UPDATE makes re-run safe per code-reviewer P1 fix.

    print()
    print("=== APPLY summary ===")
    for date_str, status, r in summary:
        if status == "ok":
            print(f"  {date_str} ✅ klines={r['klines']} daily_basic={r['daily_basic']} ({r['elapsed_sec']}s)")
        else:
            print(f"  {date_str} ❌ {r.get('error', 'unknown')}")

    state_post = _read_db_state()
    print()
    print("=== Post-apply state ===")
    print(_preflight_summary(state_post))

    # Verdict.
    ok = all(s == "ok" for _, s, _ in summary)
    klines_ok = (state_post["klines_daily"] or "") >= "2026-05-15"
    basic_ok = (state_post["daily_basic"] or "") >= "2026-05-15"
    if ok and klines_ok and basic_ok:
        print()
        print("✅✅✅ BACKFILL SUCCESS — klines_daily + daily_basic both fresh through 2026-05-15 ✅✅✅")
        return 0

    print()
    print("⚠️ BACKFILL PARTIAL OR FAILED — review summary above")
    return 1


def _verify() -> int:
    """Post-apply verify."""
    state = _read_db_state()
    print(_preflight_summary(state))
    print()
    ok_klines = (state["klines_daily"] or "") >= "2026-05-15"
    ok_basic = (state["daily_basic"] or "") >= "2026-05-15"
    if ok_klines and ok_basic:
        print("✅ Verify PASS — both tables fresh through 2026-05-15")
        return 0
    print("❌ Verify FAIL — one or both tables still stale:")
    if not ok_klines:
        print(f"  klines_daily: {state['klines_daily']} (expected >= 2026-05-15)")
    if not ok_basic:
        print(f"  daily_basic: {state['daily_basic']} (expected >= 2026-05-15)")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = parser.add_mutually_exclusive_group()
    # NOTE: --dry-run is the default behavior via fallthrough dispatch (line ~244),
    # NOT via default=True (which is ignored by argparse inside mutex groups per
    # convergent reviewer P1/P2 finding — code-rev P2 + python-rev P1-2).
    g.add_argument("--dry-run", action="store_true", help="(default when no flag) preflight + plan, 0 mutation")
    g.add_argument("--apply", action="store_true", help="EXECUTE backfill")
    g.add_argument("--verify", action="store_true", help="post-apply state verify only")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if args.apply:
        return _apply()
    if args.verify:
        return _verify()
    return _dry_run()


if __name__ == "__main__":
    sys.exit(main())
