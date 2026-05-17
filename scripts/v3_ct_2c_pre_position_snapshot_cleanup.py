"""V3 CT-2c-pre — pre-cutover position_snapshot cleanup (CT-1a precedent extension).

Scope: DELETE 162 stale pre-cutover live-mode position_snapshot rows
  - strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0' (production)
  - execution_mode = 'live'
  - trade_date <= 2026-04-17 (all pre-cutover; emergency_close happened 4-29)

Rationale: signal_phase's `_assert_positions_not_evaporated` check (Step 1.5)
  fails-loud when xtquant=0 positions but DB has prev snapshot with quantity > 0.
  After 4-29 clearance, ALL 162 pre-cutover snapshots are stale (xtquant truth = 0).
  CT-1a cleared 114 rows (4-20~4-27, mid-rebalance churn) but kept 4-17 baseline.
  Live-mode trading requires "fresh start" (prev_date=None per line 51-52 of
  backend/app/services/pt_qmt_state.py), so all 162 stale rows must be cleared.

Pipeline (sustained CT-1a 3-mode + atomic-snapshot-then-delete体例):
  1. Preflight verify (count = 162, strategy_id correct, xtquant=0)
  2. Atomic JSON snapshot to docs/audit/ (rollback always available)
  3. Single-tx DELETE with row-count assertion
  4. Post-delete verify (count = 0 for strategy live-mode)

Modes:
  --dry-run  (default): preflight + plan, 0 mutation
  --apply              : snapshot + atomic delete + post-verify
  --rollback           : restore from rollback snapshot JSON (per ADR-077 §3 precedent)
  --verify             : post-apply state verify

关联铁律: 17 (DataPipeline 例外: subset-column UPSERT, LL-066) / 25 / 32 (txn boundary) / 33 / 41
关联 Plan: V3 PT Cutover Plan v0.4 CT-2c-pre operational health remediation
关联 Finding #14 / #30 / Step 7 in CT-2c remediation roadmap
关联 CT-1a precedent: scripts/v3_ct_1a_apply_cleanup.py (PR #370)
"""

from __future__ import annotations

import argparse
import json
import logging
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

from app.data_fetcher.data_loader import get_sync_conn

logger = logging.getLogger("v3_ct_2c_pre_position_snapshot_cleanup")

_TARGET_STRATEGY_ID = "28fc37e5-2d32-4ada-92e0-41c11a5103d0"
_TARGET_EXECUTION_MODE = "live"
_TARGET_MAX_TRADE_DATE = "2026-04-17"  # all rows <= this date are stale pre-cutover
_EXPECTED_ROW_COUNT = 162  # verified via preflight Phase 0 audit

_ROLLBACK_SNAPSHOT_PATH = (
    PROJECT_ROOT
    / "docs"
    / "audit"
    / "v3_ct_2c_pre_position_snapshot_cleanup_rollback_snapshot_2026_05_17.json"
)


def _now_iso() -> tuple[str, str]:
    """Return (utc_iso, shanghai_iso) — 铁律 41."""
    now_utc = datetime.now(UTC)
    return (
        now_utc.isoformat(),
        now_utc.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
    )


def _read_target_rows(cur) -> list[dict]:
    """Read all target rows (for snapshot + count verify)."""
    cur.execute(
        """SELECT code, trade_date::text, strategy_id::text, market,
                  quantity, avg_cost, market_value, weight, unrealized_pnl,
                  holding_days, execution_mode
           FROM position_snapshot
           WHERE strategy_id = %s
             AND execution_mode = %s
             AND trade_date <= %s
           ORDER BY trade_date, code""",
        (_TARGET_STRATEGY_ID, _TARGET_EXECUTION_MODE, _TARGET_MAX_TRADE_DATE),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _read_xtquant_truth_via_redis() -> dict:
    """Read current xtquant truth via Redis (sustained CT-1a体例)."""
    import redis

    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
    nav_raw = r.get("portfolio:nav")
    pc = r.hgetall("portfolio:current")
    return {
        "portfolio_nav_raw": nav_raw,
        "portfolio_current_hkeys": list(pc.keys()) if pc else [],
        "position_count": len(pc) if pc else 0,
    }


def _preflight_summary(rows: list[dict], xtquant: dict) -> str:
    """Render preflight summary."""
    n = len(rows)
    dates_set = sorted(set(r["trade_date"] for r in rows))
    lines = [
        "=== Preflight ===",
        f"  Target rows count: {n}  (expected: {_EXPECTED_ROW_COUNT})",
        f"  Target strategy_id: {_TARGET_STRATEGY_ID}",
        f"  Target execution_mode: {_TARGET_EXECUTION_MODE}",
        f"  Target trade_date <= {_TARGET_MAX_TRADE_DATE}",
        f"  Distinct trade_dates ({len(dates_set)}): {', '.join(dates_set)}",
        "",
        "  xtquant truth (via Redis):",
        f"    portfolio:current position_count: {xtquant['position_count']}  (expected: 0)",
        f"    portfolio:nav: {xtquant['portfolio_nav_raw']}",
    ]
    return "\n".join(lines)


def _check_preflight(rows: list[dict], xtquant: dict) -> list[str]:
    """Strict preflight verify."""
    failures = []
    if len(rows) != _EXPECTED_ROW_COUNT:
        failures.append(
            f"Row count drift: actual={len(rows)} expected={_EXPECTED_ROW_COUNT}"
        )
    if xtquant["position_count"] != 0:
        failures.append(
            f"xtquant has {xtquant['position_count']} positions (expected 0 — clearance baseline)"
        )
    # All rows must match strategy + mode + date constraints (defense-in-depth).
    for r in rows:
        if r["strategy_id"] != _TARGET_STRATEGY_ID:
            failures.append(f"Row strategy_id mismatch: {r['strategy_id']}")
            break  # one failure is enough
        if r["execution_mode"] != _TARGET_EXECUTION_MODE:
            failures.append(f"Row execution_mode mismatch: {r['execution_mode']}")
            break
        if r["trade_date"] > _TARGET_MAX_TRADE_DATE:
            failures.append(f"Row trade_date > {_TARGET_MAX_TRADE_DATE}: {r['trade_date']}")
            break
    return failures


def _write_snapshot_atomic(rows: list[dict], xtquant: dict) -> None:
    """Atomic snapshot write — tempfile + os.replace (sustained CT-1a体例)."""
    import os
    import tempfile

    utc_iso, sh_iso = _now_iso()
    snapshot = {
        "captured_at_utc": utc_iso,
        "captured_at_shanghai": sh_iso,
        "scope": {
            "strategy_id": _TARGET_STRATEGY_ID,
            "execution_mode": _TARGET_EXECUTION_MODE,
            "trade_date_max": _TARGET_MAX_TRADE_DATE,
            "expected_count": _EXPECTED_ROW_COUNT,
        },
        "xtquant_truth_at_snapshot": xtquant,
        "rows": rows,
        "row_count": len(rows),
    }
    _ROLLBACK_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write via tempfile + os.replace.
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(_ROLLBACK_SNAPSHOT_PATH.parent),
        prefix="snap_",
        suffix=".json.tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp_path, _ROLLBACK_SNAPSHOT_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    logger.info(
        "Snapshot written atomically: %s (%d rows, %d bytes)",
        _ROLLBACK_SNAPSHOT_PATH,
        len(rows),
        _ROLLBACK_SNAPSHOT_PATH.stat().st_size,
    )


def _dry_run() -> int:
    """Preflight + plan, 0 mutation."""
    with get_sync_conn() as conn, conn.cursor() as cur:
        rows = _read_target_rows(cur)
    xtquant = _read_xtquant_truth_via_redis()
    print(_preflight_summary(rows, xtquant))
    print()

    failures = _check_preflight(rows, xtquant)
    if failures:
        print("⚠️ Preflight check FAIL:")
        for f in failures:
            print(f"  - {f}")
        print()
    else:
        print("✅ Preflight check PASS")
        print()

    print("=== Plan ===")
    print(f"  1. Capture atomic JSON snapshot to {_ROLLBACK_SNAPSHOT_PATH}")
    print(f"  2. Single-tx DELETE {len(rows)} rows matching constraints")
    print(f"  3. Assert affected row count == {len(rows)} (else rollback)")
    print("  4. Post-delete verify: COUNT(*) = 0 for strategy + execution_mode")
    print()
    print("=== DRY RUN COMPLETE — re-run with --apply to execute ===")
    return 0 if not failures else 1


def _apply() -> int:
    """Atomic snapshot + delete + post-verify."""
    with get_sync_conn() as conn, conn.cursor() as cur:
        rows = _read_target_rows(cur)
    xtquant = _read_xtquant_truth_via_redis()
    print(_preflight_summary(rows, xtquant))
    print()

    failures = _check_preflight(rows, xtquant)
    if failures:
        print("❌ apply BLOCKED — preflight failed:")
        for f in failures:
            print(f"  - {f}")
        return 1

    utc_iso, sh_iso = _now_iso()
    print(f"=== APPLY started — UTC={utc_iso} SH={sh_iso} ===")
    print()

    # Step 1: snapshot.
    print("=== Step 1: capture rollback snapshot ===")
    _write_snapshot_atomic(rows, xtquant)
    print(f"  ✅ Snapshot: {_ROLLBACK_SNAPSHOT_PATH}")
    print()

    # Step 2 + 3: single-tx DELETE with row-count assert.
    print("=== Step 2+3: atomic DELETE with row-count assertion ===")
    t0 = time.time()
    with get_sync_conn() as conn:
        prev_autocommit = conn.autocommit
        conn.autocommit = False
        try:
            cur = conn.cursor()
            cur.execute(
                """DELETE FROM position_snapshot
                   WHERE strategy_id = %s
                     AND execution_mode = %s
                     AND trade_date <= %s""",
                (_TARGET_STRATEGY_ID, _TARGET_EXECUTION_MODE, _TARGET_MAX_TRADE_DATE),
            )
            affected = cur.rowcount
            if affected != _EXPECTED_ROW_COUNT:
                conn.rollback()
                print(
                    f"  ❌ Row count assertion FAILED: affected={affected} "
                    f"expected={_EXPECTED_ROW_COUNT} — transaction rolled back"
                )
                return 1
            conn.commit()
            elapsed = time.time() - t0
            print(f"  ✅ DELETE committed: {affected} rows in {elapsed:.2f}s")
        except Exception as e:
            conn.rollback()
            logger.exception("DELETE failed: %s", e)
            print(f"  ❌ DELETE FAILED: {e} — transaction rolled back")
            return 1
        finally:
            conn.autocommit = prev_autocommit
    print()

    # Step 4: post-verify.
    print("=== Step 4: post-delete state verify ===")
    with get_sync_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = %s""",
            (_TARGET_STRATEGY_ID, _TARGET_EXECUTION_MODE),
        )
        remaining = cur.fetchone()[0]
    if remaining == 0:
        print(f"  ✅ Post-verify PASS — 0 rows remain (was {_EXPECTED_ROW_COUNT})")
        print()
        print("✅✅✅ CT-2c-pre position_snapshot cleanup SUCCESS ✅✅✅")
        return 0
    print(f"  ⚠️ Post-verify WARN — {remaining} rows remain (expected 0)")
    return 1


def _rollback() -> int:
    """Restore from rollback snapshot JSON."""
    if not _ROLLBACK_SNAPSHOT_PATH.exists():
        print(f"❌ Rollback snapshot not found: {_ROLLBACK_SNAPSHOT_PATH}")
        return 1
    snapshot = json.loads(_ROLLBACK_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    rows = snapshot.get("rows", [])
    if not rows:
        print("❌ Snapshot has no rows (corrupt or already restored)")
        return 1
    print(f"=== ROLLBACK from {_ROLLBACK_SNAPSHOT_PATH} ===")
    print(f"  Captured: UTC={snapshot.get('captured_at_utc')}")
    print(f"  Rows to restore: {len(rows)}")
    print()
    with get_sync_conn() as conn:
        prev_autocommit = conn.autocommit
        conn.autocommit = False
        try:
            cur = conn.cursor()
            for r in rows:
                cur.execute(
                    """INSERT INTO position_snapshot
                       (code, trade_date, strategy_id, market, quantity, avg_cost,
                        market_value, weight, unrealized_pnl, holding_days, execution_mode)
                       VALUES (%(code)s, %(trade_date)s, %(strategy_id)s, %(market)s,
                               %(quantity)s, %(avg_cost)s, %(market_value)s, %(weight)s,
                               %(unrealized_pnl)s, %(holding_days)s, %(execution_mode)s)
                       ON CONFLICT (code, trade_date, strategy_id) DO UPDATE SET
                         market = EXCLUDED.market,
                         quantity = EXCLUDED.quantity,
                         avg_cost = EXCLUDED.avg_cost,
                         market_value = EXCLUDED.market_value,
                         weight = EXCLUDED.weight,
                         unrealized_pnl = EXCLUDED.unrealized_pnl,
                         holding_days = EXCLUDED.holding_days,
                         execution_mode = EXCLUDED.execution_mode""",
                    r,
                )
            conn.commit()
            print(f"  ✅ Restored {len(rows)} rows")
            return 0
        except Exception as e:
            conn.rollback()
            logger.exception("Rollback failed: %s", e)
            print(f"  ❌ Rollback FAILED: {e}")
            return 1
        finally:
            conn.autocommit = prev_autocommit


def _verify() -> int:
    """Post-apply state verify."""
    with get_sync_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = %s""",
            (_TARGET_STRATEGY_ID, _TARGET_EXECUTION_MODE),
        )
        n = cur.fetchone()[0]
    if n == 0:
        print(f"✅ Verify PASS — 0 live-mode position_snapshot rows for strategy {_TARGET_STRATEGY_ID}")
        return 0
    print(f"❌ Verify FAIL — {n} rows remain (expected 0)")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True, help="(default) preflight + plan")
    g.add_argument("--apply", action="store_true", help="EXECUTE cleanup")
    g.add_argument("--rollback", action="store_true", help="restore from snapshot")
    g.add_argument("--verify", action="store_true", help="post-apply state verify")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if args.apply:
        return _apply()
    if args.rollback:
        return _rollback()
    if args.verify:
        return _verify()
    return _dry_run()


if __name__ == "__main__":
    sys.exit(main())
