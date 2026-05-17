"""V3 CT-2c-pre — factor_values recompute 2026-05-08 ~ 2026-05-15 (CORE3+dv_ttm).

Scope (4 factors × 6 trading days):
  - Factors: turnover_mean_20, volatility_20, bp_ratio, dv_ttm
  - Dates: 5-08 (Fri), 5-11 ~ 5-15 (Mon-Fri)
  - Pre-requisite: klines_daily + daily_basic fresh through 2026-05-15 (Step 2 ✅)

Per CLAUDE.md §策略配置 — these 4 factors are the entire PT signal set
(CORE3+dv_ttm WF OOS Sharpe=0.8659). Other 80+ factors are research/registry,
not signal-critical; defer their recompute to post-Monday BAU schtask (Step 11).

Pipeline (sustained Phase C C3 + DATA_SYSTEM_V1):
  Stage A: compute_batch_factors(..., factor_names=[4 factors], write=True)
    → DataPipeline.ingest → factor_values.raw_value (铁律 17 合规)
  Stage B: DataOrchestrator.neutralize_factors([4 factors], incremental=True, validate=True)
    → fast_neutralize_batch → factor_values.neutral_value + zscore

Modes (sustained CT-1a/CT-2b/backfill_klines 3-mode runner体例):
  --dry-run  (default): preflight + plan, 0 mutation
  --apply              : execute 2-stage pipeline
  --verify             : post-apply state verify (factor_values latest >= 2026-05-15)

关联铁律: 11 (IC 唯一入库) / 17 (DataPipeline) / 25 / 33 / 41
关联 Plan: V3 PT Cutover Plan v0.4 CT-2c-pre operational health remediation
关联 Finding #15 (factor_values 19 days stale) / Phase C C3 / DATA_SYSTEM_V1
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import warnings
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# ruff: noqa: E402
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "backend" / ".env")

from app.services.db import get_sync_conn

logger = logging.getLogger("recompute_factor_values_2026_05")

# CORE3+dv_ttm — production PT signal set per configs/pt_live.yaml.
_TARGET_FACTORS: tuple[str, ...] = (
    "turnover_mean_20",
    "volatility_20",
    "bp_ratio",
    "dv_ttm",
)

# Backfill date range (inclusive). 5-08 (Fri) + 5-11~5-15 (Mon-Fri).
_START = date(2026, 5, 8)
_END = date(2026, 5, 15)

_REQUIRED_ENV_FOR_APPLY: tuple[str, ...] = ()  # No external secrets needed (DB only).


def _now_iso() -> tuple[str, str]:
    """Return (utc_iso, shanghai_iso) — 铁律 41."""
    now_utc = datetime.now(UTC)
    return (
        now_utc.isoformat(),
        now_utc.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
    )


def _read_state() -> dict[str, dict]:
    """Read per-factor latest trade_date + row counts."""
    out = {}
    with get_sync_conn() as conn, conn.cursor() as cur:
        for f in _TARGET_FACTORS:
            cur.execute(
                "SELECT MAX(trade_date)::text, COUNT(*) FROM factor_values WHERE factor_name = %s",
                (f,),
            )
            r = cur.fetchone()
            out[f] = {"latest": r[0], "rows": r[1]}

        # Klines/daily_basic prerequisite check.
        cur.execute("SELECT MAX(trade_date)::text FROM klines_daily")
        out["__klines_latest"] = cur.fetchone()[0]
        cur.execute("SELECT MAX(trade_date)::text FROM daily_basic")
        out["__basic_latest"] = cur.fetchone()[0]
    return out


def _preflight_summary(state: dict) -> str:
    target = "2026-05-15"
    lines = [
        "=== Preflight ===",
        f"  Prerequisite klines_daily latest: {state['__klines_latest']}  (need >= {target})",
        f"  Prerequisite daily_basic latest:  {state['__basic_latest']}  (need >= {target})",
        "",
        f"  Target factors ({len(_TARGET_FACTORS)}): {', '.join(_TARGET_FACTORS)}",
        f"  Target dates: {_START.isoformat()} ~ {_END.isoformat()} (inclusive)",
        "",
        "  Per-factor current state:",
    ]
    for f in _TARGET_FACTORS:
        s = state[f]
        lines.append(f"    {f:25s}  latest={s['latest']}  rows={s['rows']:,}")
    return "\n".join(lines)


def _check_prerequisites(state: dict) -> list[str]:
    """Pre-apply gate — klines + daily_basic must be fresh."""
    failures = []
    target = "2026-05-15"
    if not state["__klines_latest"] or state["__klines_latest"] < target:
        failures.append(
            f"klines_daily latest={state['__klines_latest']} < {target} — "
            "run scripts/backfill_klines_2026_05.py --apply first"
        )
    if not state["__basic_latest"] or state["__basic_latest"] < target:
        failures.append(
            f"daily_basic latest={state['__basic_latest']} < {target} — "
            "run scripts/backfill_klines_2026_05.py --apply first"
        )
    return failures


def _dry_run() -> int:
    state = _read_state()
    print(_preflight_summary(state))
    print()

    failures = _check_prerequisites(state)
    if failures:
        print("⚠️ Prerequisite check FAIL:")
        for f in failures:
            print(f"  - {f}")
        print()

    print("=== Plan ===")
    print("  Stage A: compute_batch_factors(")
    print(f"             start_date={_START.isoformat()},")
    print(f"             end_date={_END.isoformat()},")
    print(f"             factor_names={list(_TARGET_FACTORS)},")
    print("             write=True")
    print("           ) -> factor_values.raw_value via DataPipeline.ingest (铁律 17)")
    print()
    print("  Stage B: DataOrchestrator(")
    print(f"             '{_START.isoformat()}', '{_END.isoformat()}'")
    print("           ).neutralize_factors(")
    print(f"             {list(_TARGET_FACTORS)},")
    print("             incremental=True, validate=True")
    print("           ) -> factor_values.neutral_value + zscore via fast_neutralize_batch")
    print()
    print("=== DRY RUN COMPLETE — re-run with --apply to execute ===")
    return 0


def _apply() -> int:
    """Execute Stage A (raw compute) + Stage B (neutralize)."""
    # Lazy import — these touch heavy compute deps.
    from app.services.data_orchestrator import DataOrchestrator
    from app.services.factor_compute_service import compute_batch_factors

    state_pre = _read_state()
    print(_preflight_summary(state_pre))
    print()

    failures = _check_prerequisites(state_pre)
    if failures:
        print("❌ apply BLOCKED — prerequisites not met:")
        for f in failures:
            print(f"  - {f}")
        return 1

    utc_iso, sh_iso = _now_iso()
    print(f"=== APPLY started — UTC={utc_iso} SH={sh_iso} ===")
    print()

    # ── Stage A: compute raw_value via batch ──────────────────────────────
    print("=== Stage A: compute_batch_factors (raw_value via DataPipeline) ===")
    t_a = time.time()
    try:
        # Suppress DeprecationWarning (still 铁律 17 合规 per Phase C C3 2026-04-16).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            # factor_set='full' required — dv_ttm lives in PHASE0_FULL_FACTORS
            # (line 182 of engines/factor_engine/__init__.py), NOT PHASE0_CORE_FACTORS.
            # factor_names filters DOWN within the loaded set; passing 'core' (default)
            # silently drops dv_ttm. Phase 0 Finding #27.
            result_a = compute_batch_factors(
                start_date=_START,
                end_date=_END,
                factor_set="full",
                factor_names=list(_TARGET_FACTORS),
                write=True,
            )
        elapsed_a = time.time() - t_a
        print(f"  ✅ Stage A done in {elapsed_a:.1f}s")
        print(f"  result: {result_a}")
    except Exception as e:
        logger.exception("Stage A FAILED: %s", e)
        print(f"  ❌ Stage A FAILED: {e}")
        return 1
    print()

    # ── Stage B: neutralize + zscore ──────────────────────────────────────
    print("=== Stage B: DataOrchestrator.neutralize_factors ===")
    t_b = time.time()
    try:
        orch = DataOrchestrator(
            start_date=_START.isoformat(),
            end_date=_END.isoformat(),
        )
        result_b = orch.neutralize_factors(
            list(_TARGET_FACTORS),
            incremental=True,
            validate=True,
        )
        elapsed_b = time.time() - t_b
        print(f"  ✅ Stage B done in {elapsed_b:.1f}s")
        # PipelineResult — print summary if available.
        if hasattr(result_b, "summary"):
            print(f"  summary: {result_b.summary()}")
        else:
            print(f"  result: {result_b}")
    except Exception as e:
        logger.exception("Stage B FAILED: %s", e)
        print(f"  ❌ Stage B FAILED: {e}")
        return 1
    print()

    # ── Post-apply state verify ───────────────────────────────────────────
    state_post = _read_state()
    print("=== Post-apply state ===")
    print(_preflight_summary(state_post))
    print()

    ok = all(state_post[f]["latest"] >= "2026-05-15" for f in _TARGET_FACTORS)
    if ok:
        print("✅✅✅ FACTOR RECOMPUTE SUCCESS — 4 factors fresh through 2026-05-15 ✅✅✅")
        return 0
    print("⚠️ Some factors still stale post-apply — review state above")
    return 1


def _verify() -> int:
    state = _read_state()
    print(_preflight_summary(state))
    print()
    target = "2026-05-15"
    stale = [f for f in _TARGET_FACTORS if (state[f]["latest"] or "") < target]
    if not stale:
        print(f"✅ Verify PASS — all {len(_TARGET_FACTORS)} factors fresh through {target}")
        return 0
    print(f"❌ Verify FAIL — {len(stale)} factor(s) still stale:")
    for f in stale:
        print(f"  {f}: {state[f]['latest']} (expected >= {target})")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True, help="(default) preflight + plan, 0 mutation")
    g.add_argument("--apply", action="store_true", help="EXECUTE 2-stage pipeline")
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
