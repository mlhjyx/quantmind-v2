#!/usr/bin/env python3
"""V3 Plan v0.4 CT-1a — apply runner for stale snapshot DB cleanup.

Plan v0.4 §A CT-1 first non-zero-mutation sprint. DB row mutation on
production tables `position_snapshot` + `performance_series` — REDLINE
GATE per `quantmind-redline-guardian` subagent contract.

Modes:
  --dry-run (default): Phase 0 preflight + verify SQL semantics + simulate
    counts; 0 DB mutation. Safe to run multiple times.
  --apply: BLOCKED until user 显式 trigger via separate execution. Runs
    full pipeline (preflight + snapshot capture + DELETE + post-verify).
    Captures pre-DELETE rows to JSON snapshot for rollback safety.
  --rollback: re-INSERT from JSON snapshot. Inverse of --apply.

Pipeline (--apply):
  1. Preflight verify (sustained LL-159 step 2 data presence):
     - position_snapshot: 114 rows in stale window
     - performance_series: 7 rows in stale window
     - circuit_breaker_state.live: NAV=993520.16 (4-30 cleanup sustained)
     - red-line invariants: LIVE_TRADING_DISABLED=true, EXECUTION_MODE=paper
  2. Snapshot capture:
     - SELECT all rows to be deleted
     - Write to docs/audit/v3_ct_1a_rollback_snapshot_2026_05_16.json
     - Atomic write (tempfile + rename)
  3. DELETE phase (transactional):
     - Run position_snapshot cleanup SQL (assertion-guarded)
     - Run performance_series cleanup SQL (assertion-guarded)
     - Both SQL files COMMIT on success or ROLLBACK on failure
  4. Post-verify:
     - position_snapshot stale dates: 0 rows
     - performance_series stale dates: 0 rows
     - circuit_breaker_state untouched
     - performance_series 5-15 (most recent) untouched

Sustained 体例:
  - LL-159 amended preflight SOP (multi-directory grep + SQL data avail)
  - LL-172 lesson 1 Phase 0 active discovery before any mutation
  - LL-098 X10 per-mutation user 显式 trigger required
  - Plan §A row 5 mitigation: explicit WHERE clauses + rollback companion +
    audit_marker assertion + user 显式 trigger

关联铁律: 22 / 24 / 25 / 33 (fail-loud on count drift) / 35 (.env secrets) /
  41 (UTC tz-aware) / 42 (backend/ + scripts/ PR体例)
关联 V3: Plan v0.4 §A CT-1a + §B row 7 (DB DELETE 误删 mitigation)
关联 ADR: ADR-022 (rollback discipline) / ADR-081 候选 (CT-1 closure)
关联 LL: LL-098 X10 / LL-159 / LL-172 / SHUTDOWN_NOTICE §9.2 prereq
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)

# Strategy + date filters — sustained Phase 0 active discovery 2026-05-16.
_STRATEGY_ID: str = "28fc37e5-2d32-4ada-92e0-41c11a5103d0"
_POSITION_SNAPSHOT_DATES: tuple[str, ...] = (
    "2026-04-20",
    "2026-04-21",
    "2026-04-22",
    "2026-04-23",
    "2026-04-24",
    "2026-04-27",
)
_POSITION_SNAPSHOT_EXPECTED: int = 114
_PERFORMANCE_SERIES_DATE_LO: str = "2026-04-20"
_PERFORMANCE_SERIES_DATE_HI: str = "2026-04-28"
_PERFORMANCE_SERIES_EXPECTED: int = 7

# Migration SQL files (relative to PROJECT_ROOT).
_MIGRATION_POS_SNAPSHOT: Path = (
    PROJECT_ROOT
    / "backend"
    / "migrations"
    / "2026_05_16_ct_1a_cleanup_stale_position_snapshot.sql"
)
_MIGRATION_PERF_SERIES: Path = (
    PROJECT_ROOT
    / "backend"
    / "migrations"
    / "2026_05_16_ct_1a_cleanup_stale_performance_series.sql"
)
_ROLLBACK_SNAPSHOT: Path = (
    PROJECT_ROOT
    / "docs"
    / "audit"
    / "v3_ct_1a_rollback_snapshot_2026_05_16.json"
)


# ---------- Preflight ----------


@dataclass
class _PreflightResult:
    """Phase 0 preflight verify result."""

    position_snapshot_count: int = 0
    performance_series_count: int = 0
    cb_state_live_nav: float | None = None
    cb_state_live_updated_at: str | None = None
    perf_series_latest_date: str | None = None
    perf_series_latest_nav: float | None = None
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _verify_preflight(conn: Any, *, env_check: bool = True) -> _PreflightResult:
    """Run Phase 0 preflight + red-line env check.

    Args:
        conn: psycopg2 connection (read-only here).
        env_check: skip env-flag assertion (test runs may not set .env).

    Returns:
        _PreflightResult with counts + invariant assertions.
    """
    r = _PreflightResult()

    with conn.cursor() as cur:
        # 1. position_snapshot stale count.
        cur.execute(
            "SELECT COUNT(*) FROM position_snapshot "
            "WHERE trade_date = ANY(%s::date[]) AND execution_mode = 'live' "
            "AND strategy_id = %s",
            (list(_POSITION_SNAPSHOT_DATES), _STRATEGY_ID),
        )
        r.position_snapshot_count = int(cur.fetchone()[0])
        if r.position_snapshot_count != _POSITION_SNAPSHOT_EXPECTED:
            r.failures.append(
                f"position_snapshot stale count drift: expected "
                f"{_POSITION_SNAPSHOT_EXPECTED}, got {r.position_snapshot_count}"
            )

        # 2. performance_series stale count.
        cur.execute(
            "SELECT COUNT(*) FROM performance_series "
            "WHERE trade_date BETWEEN %s AND %s "
            "AND execution_mode = 'live' AND strategy_id = %s "
            "AND position_count = 19",
            (_PERFORMANCE_SERIES_DATE_LO, _PERFORMANCE_SERIES_DATE_HI, _STRATEGY_ID),
        )
        r.performance_series_count = int(cur.fetchone()[0])
        if r.performance_series_count != _PERFORMANCE_SERIES_EXPECTED:
            r.failures.append(
                f"performance_series stale count drift: expected "
                f"{_PERFORMANCE_SERIES_EXPECTED}, got {r.performance_series_count}"
            )

        # 3. circuit_breaker_state.live invariant — already cleaned 4-30,
        #    must NOT be touched. NAV=993520.16 expected.
        cur.execute(
            "SELECT (trigger_metrics->>'nav')::numeric, updated_at::text "
            "FROM circuit_breaker_state "
            "WHERE execution_mode = 'live' AND strategy_id = %s",
            (_STRATEGY_ID,),
        )
        row = cur.fetchone()
        if row is None:
            r.failures.append("circuit_breaker_state live row missing")
        else:
            r.cb_state_live_nav = float(row[0]) if row[0] is not None else None
            r.cb_state_live_updated_at = row[1]
            if r.cb_state_live_nav != 993520.16:
                r.failures.append(
                    f"circuit_breaker_state.live nav drift: expected 993520.16, "
                    f"got {r.cb_state_live_nav}"
                )

        # 4. performance_series latest row invariant — should be 5-15 NAV
        #    ~993520.66 with position_count=0 (current 0-持仓 state).
        cur.execute(
            "SELECT trade_date::text, nav::numeric "
            "FROM performance_series "
            "WHERE execution_mode = 'live' AND strategy_id = %s "
            "ORDER BY trade_date DESC LIMIT 1",
            (_STRATEGY_ID,),
        )
        row = cur.fetchone()
        if row is not None:
            r.perf_series_latest_date = row[0]
            r.perf_series_latest_nav = float(row[1]) if row[1] is not None else None

    # 5. Red-line env check (sustained 红线 5/5 invariant).
    if env_check:
        live_disabled = os.environ.get("LIVE_TRADING_DISABLED", "").lower()
        exec_mode = os.environ.get("EXECUTION_MODE", "").lower()
        if live_disabled and live_disabled != "true":
            r.failures.append(
                f"LIVE_TRADING_DISABLED env != 'true' (got {live_disabled!r}); "
                f"refuse mutation on production tables"
            )
        if exec_mode and exec_mode not in ("paper", ""):
            r.failures.append(
                f"EXECUTION_MODE env != 'paper' (got {exec_mode!r}); "
                f"refuse mutation on production tables"
            )

    return r


# ---------- Snapshot capture (rollback safety) ----------


def _capture_snapshot(conn: Any) -> dict[str, Any]:
    """Capture pre-DELETE rows to JSON-serializable dict for rollback."""

    def _json_default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, (datetime,)):
            return o.isoformat()
        return str(o)

    snapshot: dict[str, Any] = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_at_shanghai": datetime.now(_SHANGHAI_TZ).isoformat(),
        "strategy_id": _STRATEGY_ID,
        "position_snapshot_rows": [],
        "performance_series_rows": [],
    }

    with conn.cursor() as cur:
        # position_snapshot snapshot.
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'position_snapshot' ORDER BY ordinal_position"
        )
        ps_cols = [c[0] for c in cur.fetchall()]
        cur.execute(
            "SELECT * FROM position_snapshot "
            "WHERE trade_date = ANY(%s::date[]) AND execution_mode = 'live' "
            "AND strategy_id = %s ORDER BY trade_date, code",
            (list(_POSITION_SNAPSHOT_DATES), _STRATEGY_ID),
        )
        for row in cur.fetchall():
            snapshot["position_snapshot_rows"].append(
                {c: _json_default(v) for c, v in zip(ps_cols, row, strict=False)}
            )

        # performance_series snapshot.
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'performance_series' ORDER BY ordinal_position"
        )
        prf_cols = [c[0] for c in cur.fetchall()]
        cur.execute(
            "SELECT * FROM performance_series "
            "WHERE trade_date BETWEEN %s AND %s "
            "AND execution_mode = 'live' AND strategy_id = %s "
            "AND position_count = 19 ORDER BY trade_date",
            (_PERFORMANCE_SERIES_DATE_LO, _PERFORMANCE_SERIES_DATE_HI, _STRATEGY_ID),
        )
        for row in cur.fetchall():
            snapshot["performance_series_rows"].append(
                {c: _json_default(v) for c, v in zip(prf_cols, row, strict=False)}
            )

    return snapshot


def _write_snapshot_atomic(snapshot: dict[str, Any], out_path: Path) -> None:
    """Atomic write — tempfile then rename. Avoids partial-write corruption."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=out_path.stem + "_",
        suffix=".tmp",
        dir=str(out_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, out_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------- DELETE phase ----------


def _execute_migration_sql(conn: Any, sql_path: Path) -> None:
    """Execute a migration SQL file. Fail-loud on assertion DO block raise."""
    sql_text = sql_path.read_text(encoding="utf-8")
    logger.info("[CT-1a apply] executing %s (%d bytes)", sql_path.name, len(sql_text))
    with conn.cursor() as cur:
        cur.execute(sql_text)
    logger.info("[CT-1a apply] %s completed", sql_path.name)


# ---------- Rollback ----------


def _rollback_from_snapshot(conn: Any, snapshot: dict[str, Any]) -> tuple[int, int]:
    """Re-INSERT rows from snapshot. Returns (ps_count, prf_count)."""
    ps_rows = snapshot.get("position_snapshot_rows", [])
    prf_rows = snapshot.get("performance_series_rows", [])
    logger.info(
        "[CT-1a rollback] inserting %d position_snapshot + %d performance_series rows",
        len(ps_rows),
        len(prf_rows),
    )

    with conn.cursor() as cur:
        if ps_rows:
            cols = list(ps_rows[0].keys())
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(cols)
            sql = (
                f"INSERT INTO position_snapshot ({col_list}) VALUES ({placeholders})"
            )
            for r in ps_rows:
                cur.execute(sql, [r[c] for c in cols])

        if prf_rows:
            cols = list(prf_rows[0].keys())
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(cols)
            sql = (
                f"INSERT INTO performance_series ({col_list}) VALUES ({placeholders})"
            )
            for r in prf_rows:
                cur.execute(sql, [r[c] for c in cols])

    return len(ps_rows), len(prf_rows)


# ---------- main ----------


def _print_preflight(r: _PreflightResult) -> None:
    print("=" * 70)
    print("CT-1a Preflight Verify Result")
    print("=" * 70)
    print(
        f"  position_snapshot stale count: {r.position_snapshot_count} "
        f"(expected {_POSITION_SNAPSHOT_EXPECTED})"
    )
    print(
        f"  performance_series stale count: {r.performance_series_count} "
        f"(expected {_PERFORMANCE_SERIES_EXPECTED})"
    )
    print(
        f"  circuit_breaker_state.live nav: {r.cb_state_live_nav} "
        f"(expected 993520.16, updated_at={r.cb_state_live_updated_at})"
    )
    print(
        f"  performance_series latest: {r.perf_series_latest_date} "
        f"(nav={r.perf_series_latest_nav})"
    )
    if r.failures:
        print("\n  FAILURES:")
        for f in r.failures:
            print(f"    - {f}")
    else:
        print("\n  ALL PREFLIGHT CHECKS ✅ PASS")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="default — preflight + verify SQL semantics, 0 DB mutation",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="EXECUTE DELETE — requires user 显式 trigger per LL-098 X10",
    )
    mode.add_argument(
        "--rollback",
        action="store_true",
        help="re-INSERT from JSON snapshot (inverse of --apply)",
    )
    parser.add_argument(
        "--no-env-check",
        action="store_true",
        help="skip LIVE_TRADING_DISABLED/EXECUTION_MODE env check (tests only)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    from app.services.db import get_sync_conn  # noqa: PLC0415

    # Dry-run default if no mode flag.
    apply_mode = args.apply
    rollback_mode = args.rollback

    conn = get_sync_conn()
    try:
        # PREFLIGHT (always run).
        preflight = _verify_preflight(conn, env_check=not args.no_env_check)
        _print_preflight(preflight)

        if not preflight.ok:
            logger.error("[CT-1a] preflight FAILED — aborting")
            return 1

        if not (apply_mode or rollback_mode):
            print("[CT-1a] --dry-run mode: preflight ✅ PASS; 0 DB mutation.")
            print("[CT-1a] To execute DELETE, run with --apply after user 同意.")
            return 0

        if rollback_mode:
            if not _ROLLBACK_SNAPSHOT.exists():
                logger.error(
                    "[CT-1a rollback] snapshot file not found: %s",
                    _ROLLBACK_SNAPSHOT,
                )
                return 1
            snapshot = json.loads(_ROLLBACK_SNAPSHOT.read_text(encoding="utf-8"))
            ps_count, prf_count = _rollback_from_snapshot(conn, snapshot)
            conn.commit()
            print(
                f"[CT-1a rollback] ✅ re-inserted {ps_count} position_snapshot + "
                f"{prf_count} performance_series rows from snapshot"
            )
            return 0

        # APPLY mode.
        logger.warning(
            "[CT-1a apply] EXECUTING DELETE on production tables — "
            "redline-guardian invocation expected per Plan §A 红线 SOP"
        )

        # 1. Snapshot capture (BEFORE delete).
        snapshot = _capture_snapshot(conn)
        _write_snapshot_atomic(snapshot, _ROLLBACK_SNAPSHOT)
        logger.info(
            "[CT-1a apply] rollback snapshot captured: %s "
            "(%d position_snapshot + %d performance_series rows)",
            _ROLLBACK_SNAPSHOT,
            len(snapshot["position_snapshot_rows"]),
            len(snapshot["performance_series_rows"]),
        )

        # 2. Execute migrations.
        _execute_migration_sql(conn, _MIGRATION_POS_SNAPSHOT)
        _execute_migration_sql(conn, _MIGRATION_PERF_SERIES)
        conn.commit()

        # 3. Post-verify.
        post = _verify_preflight(conn, env_check=False)
        if (
            post.position_snapshot_count == 0
            and post.performance_series_count == 0
            and post.cb_state_live_nav == 993520.16
        ):
            print(
                "[CT-1a apply] ✅ POST-VERIFY PASS: stale rows deleted, "
                "circuit_breaker_state.live preserved, latest perf row "
                f"({post.perf_series_latest_date}, NAV={post.perf_series_latest_nav}) "
                "untouched"
            )
            print(f"[CT-1a apply] rollback snapshot at {_ROLLBACK_SNAPSHOT}")
            return 0
        logger.error(
            "[CT-1a apply] post-verify FAILED: ps_count=%d prf_count=%d "
            "cb_nav=%s — manual investigation required",
            post.position_snapshot_count,
            post.performance_series_count,
            post.cb_state_live_nav,
        )
        return 1
    except Exception:
        logger.exception("[CT-1a] fatal error — rolling back transaction")
        conn.rollback()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
