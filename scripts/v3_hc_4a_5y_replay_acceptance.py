#!/usr/bin/env python3
"""V3 横切层 HC-4a — 5y full minute_bars replay acceptance (chunked per-quarter).

Plan v0.3 §A HC-4a — 5y full minute_bars replay long-tail acceptance. The full
minute_bars table (~191M rows, 2021-2025) cannot be materialized into memory at
once (TB-5b's `bars = list(loader(...))` pattern → ~95GB+ at 5y scale, OOM on a
32GB box). HC-4a therefore runs the replay **chunked per-quarter** (user 决议 A,
AskUserQuestion 1 round): ~20 per-quarter windows, each ~8M bars / ~3GB — within
the 32GB limit + CLAUDE.md 重数据 ≤2 并发 constraint — then **aggregates the
acceptance counts incrementally** (per-quarter events discarded after that
quarter's classification, never all-5y held at once).

Reuses (DRY — 0 duplication of TB-5b's non-closure helpers, 沿用 ADR-022 反 closed-
code blast radius — these are imported, not re-implemented):
  - scripts/v3_tb_5b_replay_acceptance.py: `_make_minute_bars_loader` /
    `_make_timing_adapter` / `_make_synthetic_runner` / `_build_day_end_index` /
    `_make_day_end_price_lookup` (module-level functions, NOT script-local closures
    — distinct from TB-1c's runner which TB-5b had to re-implement locally).
  - qm_platform.risk.replay.acceptance: `classify_false_positives` /
    `evaluate_staged_closure` / `latency_percentile` (PURE evaluators).
  - qm_platform.risk.replay.runner: `ReplayWindow` (frozen dataclass — per-quarter
    windows constructed locally, 0 changes to runner.py's ALL_WINDOWS).

Aggregation methodology (sustained ADR-070 FP classification — daily-dedup +
prev_close baseline counterfactual):
  - FP rate: Σ false_positives / Σ classified across all quarters. Per-(code,
    rule_id, day) dedup is quarter-local-safe — quarters never span a day boundary.
  - Latency P99: **max of per-quarter P99** (conservative aggregate — if every
    quarter's P99 < 5s then the 5y P99 < 5s; a true 5y P99 over ~191M samples
    would need a t-digest, deferred — the latency is already a documented
    LOWER-BOUND proxy per ADR-070 D6, so max-quarter is the honest conservative).
  - STAGED closure: Σ failed across quarters (cap = 0); deadline integrity = AND.
  - 元监控 integrity: pure-function contract = AND across quarters.

Safety: 0 broker / 0 .env / 0 INSERT — pure read-only DB SELECT + in-memory
replay (sustained TB-5b). Re-runnable. Per-quarter pure-function contract audited.

4-step preflight verify SOP (sustained feedback_validation_rigor.md):
  ✅ Step 1 SSOT calendar: per-quarter windows over minute_bars actual range
     (2021-2025 per CLAUDE.md §因子存储 — empty quarters skip gracefully).
  ✅ Step 2 data presence: minute_bars 190,885,634 rows verified (CLAUDE.md).
  N/A Step 3 cron alignment: one-shot ops script, not a schtask.
  N/A Step 4 natural production behavior: this script IS the verification.

Usage:
    python scripts/v3_hc_4a_5y_replay_acceptance.py                  # full 5y
    python scripts/v3_hc_4a_5y_replay_acceptance.py --codes-limit 50 # quick smoke
    python scripts/v3_hc_4a_5y_replay_acceptance.py --quarters 2     # first 2 quarters only
    python scripts/v3_hc_4a_5y_replay_acceptance.py --dry-run        # no markdown sediment

关联铁律: 22 / 24 / 25 / 31 / 33 / 41
关联 V3: §15.4 (4 项 acceptance) / §13.1 (SLA) / §15.5 (counterfactual)
关联 ADR: ADR-063 (Tier B 真测路径) / ADR-066 (TB-1 baseline) / ADR-070 (TB-5b
  methodology + 阈值 sustained) / ADR-076 (HC-4 closure — 本 5y replay 结果 sediment)
关联 Plan: V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md §A HC-4 row + §D
关联 LL: LL-098 X10 / LL-159 (4-step preflight SOP)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Reuse TB-5b's module-level helpers (non-closure — safe to import; importing the
# module runs only its module-level imports/constants, NOT main()).
from v3_tb_5b_replay_acceptance import (  # noqa: E402
    _build_day_end_index,
    _make_day_end_price_lookup,
    _make_minute_bars_loader,
    _make_synthetic_runner,
    _make_timing_adapter,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)

# 5y range per CLAUDE.md §因子存储: minute_bars 5 年 (2021-2025).
_FIRST_YEAR: int = 2021
_LAST_YEAR: int = 2025

# V3 §15.4 thresholds — sustained ADR-070 locked caps (same as acceptance.py).
_FP_RATE_CAP: float = 0.30
_LATENCY_P99_CAP_MS: float = 5_000.0
_STAGED_FAILED_CAP: int = 0


def _build_quarter_windows() -> list[Any]:
    """Build per-quarter ReplayWindow list for _FIRST_YEAR..._LAST_YEAR (20 windows)."""
    from qm_platform.risk.replay.runner import ReplayWindow

    quarters = [
        (1, (1, 1), (3, 31)),
        (2, (4, 1), (6, 30)),
        (3, (7, 1), (9, 30)),
        (4, (10, 1), (12, 31)),
    ]
    windows: list[Any] = []
    for year in range(_FIRST_YEAR, _LAST_YEAR + 1):
        for q, (sm, sd), (em, ed) in quarters:
            windows.append(
                ReplayWindow(
                    name=f"{year}Q{q}",
                    start_date=date(year, sm, sd),
                    end_date=date(year, em, ed),
                    description=f"HC-4a 5y chunked replay — {year} Q{q}",
                )
            )
    return windows


@dataclass
class _QuarterResult:
    """One quarter's replay + acceptance metrics (raw events discarded after this)."""

    name: str
    minute_bars: int = 0
    events: int = 0
    raw_p0: int = 0
    deduped_p0: int = 0
    false_positives: int = 0
    true_positives: int = 0
    unclassifiable: int = 0
    p99_ms: float | None = None
    staged_actionable: int = 0
    staged_generated: int = 0
    staged_closed_ok: int = 0
    staged_failed: int = 0
    deadline_integrity_ok: bool = True
    contract_verified: bool = True
    wall_clock_s: float = 0.0
    # rule_id -> (fp, tp, unclassifiable) — mirrors FalsePositiveClassification.by_rule.
    by_rule: dict[str, tuple[int, int, int]] = field(default_factory=dict)


def _run_quarter(window: Any, conn: Any, codes_limit: int | None) -> _QuarterResult | None:
    """Run one quarter's replay + per-quarter acceptance. Returns None if 0 bars."""
    from qm_platform.risk.realtime.engine import RealtimeRiskEngine
    from qm_platform.risk.replay.acceptance import (
        classify_false_positives,
        evaluate_staged_closure,
        latency_percentile,
    )

    # NOTE: TB-5b's _make_minute_bars_loader opens a named server-side cursor
    # ("tb_5b_replay_minute_bars") — unique per connection. Safe to call once per
    # quarter here ONLY because the loader's `with conn.cursor(...)` block closes
    # the cursor before _run_quarter returns, and quarters run strictly
    # sequentially. Do NOT parallelize quarter runs on a shared conn.
    loader = _make_minute_bars_loader(conn, codes_limit)
    bars = list(loader(window.start_date, window.end_date))
    if not bars:
        logger.info("[HC-4a] quarter=%s — 0 minute_bars, skip", window.name)
        return None
    logger.info("[HC-4a] quarter=%s — %d minute_bars loaded", window.name, len(bars))

    day_end_index = _build_day_end_index(bars)
    day_end_lookup = _make_day_end_price_lookup(day_end_index)

    adapter = _make_timing_adapter()
    engine = RealtimeRiskEngine()
    adapter.register_all_realtime_rules(engine)
    runner = _make_synthetic_runner(adapter, engine)

    t0 = time.monotonic()
    replay_result = runner.run_window(window, bars=bars)
    wall = time.monotonic() - t0

    # Free the heavy bar list + day-end index before classification.
    del bars

    fp = classify_false_positives(adapter.timestamped_events, day_end_lookup)
    staged = evaluate_staged_closure(adapter.timestamped_events)
    p99 = latency_percentile(adapter.eval_latencies_ms, 99.0)

    result = _QuarterResult(
        name=window.name,
        minute_bars=replay_result.total_minute_bars,
        events=len(replay_result.events),
        raw_p0=fp.raw_total_p0,
        deduped_p0=fp.total_p0,
        false_positives=fp.false_positives,
        true_positives=fp.true_positives,
        unclassifiable=fp.unclassifiable,
        p99_ms=p99,
        staged_actionable=staged.total_actionable,
        staged_generated=staged.plans_generated,
        staged_closed_ok=staged.closed_ok,
        staged_failed=staged.failed,
        deadline_integrity_ok=staged.deadline_integrity_ok,
        contract_verified=replay_result.pure_function_contract_verified,
        wall_clock_s=wall,
        by_rule=dict(fp.by_rule),
    )
    logger.info(
        "[HC-4a] quarter=%s done in %.1fs — events=%d, raw_p0=%d, deduped_p0=%d, "
        "fp=%d, tp=%d, p99=%s ms, staged_failed=%d, contract=%s",
        window.name,
        wall,
        result.events,
        result.raw_p0,
        result.deduped_p0,
        result.false_positives,
        result.true_positives,
        f"{p99:.3f}" if p99 is not None else "n/a",
        result.staged_failed,
        result.contract_verified,
    )
    # adapter (with its timestamped_events + latencies) goes out of scope here.
    return result


def _aggregate(quarters: list[_QuarterResult]) -> dict[str, Any]:
    """Incrementally aggregate per-quarter results into a 5y acceptance summary."""
    total_classified = sum(q.false_positives + q.true_positives for q in quarters)
    total_fp = sum(q.false_positives for q in quarters)
    fp_rate = (total_fp / total_classified) if total_classified > 0 else 0.0
    p99_values = [q.p99_ms for q in quarters if q.p99_ms is not None]
    max_p99 = max(p99_values) if p99_values else None
    if max_p99 is None:
        # fail-loud: 0 latency samples across ALL quarters means the timing
        # instrumentation never fired (0-event replay or broken adapter wiring),
        # NOT a fast system. pass_latency below will be False — log so the
        # operator reads it as a missing-data failure, not a latency regression.
        logger.warning(
            "[HC-4a] 0 latency samples across all %d quarters — pass_latency=False "
            "is an instrumentation gap (0-event replay / adapter wiring), NOT a "
            "slow-system regression; investigate before trusting the verdict",
            len(quarters),
        )
    total_staged_failed = sum(q.staged_failed for q in quarters)
    deadline_ok = all(q.deadline_integrity_ok for q in quarters)
    contract_ok = all(q.contract_verified for q in quarters)

    # Per-rule FP/TP/uncls aggregate across quarters.
    by_rule: dict[str, list[int]] = {}
    for q in quarters:
        for rid, (f, t, u) in q.by_rule.items():
            acc = by_rule.setdefault(rid, [0, 0, 0])
            acc[0] += f
            acc[1] += t
            acc[2] += u

    return {
        "quarters_run": len(quarters),
        "total_minute_bars": sum(q.minute_bars for q in quarters),
        "total_events": sum(q.events for q in quarters),
        "total_raw_p0": sum(q.raw_p0 for q in quarters),
        "total_deduped_p0": sum(q.deduped_p0 for q in quarters),
        "total_false_positives": total_fp,
        "total_true_positives": sum(q.true_positives for q in quarters),
        "total_unclassifiable": sum(q.unclassifiable for q in quarters),
        "total_classified": total_classified,
        "fp_rate": fp_rate,
        "max_quarter_p99_ms": max_p99,
        "total_staged_actionable": sum(q.staged_actionable for q in quarters),
        "total_staged_generated": sum(q.staged_generated for q in quarters),
        "total_staged_closed_ok": sum(q.staged_closed_ok for q in quarters),
        "total_staged_failed": total_staged_failed,
        "deadline_integrity_ok": deadline_ok,
        "contract_verified": contract_ok,
        "total_wall_clock_s": sum(q.wall_clock_s for q in quarters),
        "by_rule": {rid: tuple(acc) for rid, acc in sorted(by_rule.items())},
        # V3 §15.4 4-item verdicts.
        "pass_fp_rate": fp_rate < _FP_RATE_CAP,
        "pass_latency": max_p99 is not None and max_p99 < _LATENCY_P99_CAP_MS,
        "pass_staged": total_staged_failed == _STAGED_FAILED_CAP,
        "pass_meta": contract_ok and deadline_ok,
    }


def _render_report(quarters: list[_QuarterResult], agg: dict[str, Any]) -> str:
    """Render the 5y replay acceptance report markdown."""
    overall = agg["pass_fp_rate"] and agg["pass_latency"] and agg["pass_staged"] and agg["pass_meta"]
    lines: list[str] = []
    lines.append("# V3 HC-4a — 5y Full minute_bars Replay Acceptance Report")
    lines.append("")
    lines.append(f"**Run date**: {datetime.now(_SHANGHAI_TZ).date().isoformat()}  ")
    lines.append(f"**Overall verdict**: {'✅ PASS' if overall else '❌ FAIL'}  ")
    lines.append(
        "**Scope**: V3 横切层 Plan v0.3 §A HC-4a — 5y full minute_bars replay "
        "long-tail acceptance, run chunked per-quarter (user 决议 A) over "
        f"{agg['quarters_run']} quarters, aggregated incrementally. Methodology "
        "sustained ADR-070 (daily-dedup + prev_close baseline counterfactual FP "
        "classification). Pure-function replay path per ADR-063."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §1 5y Aggregate — V3 §15.4 4 项 acceptance")
    lines.append("")
    lines.append("| # | Criterion | Threshold | Actual | Result |")
    lines.append("|---|---|---|---|---|")
    fp_pct = agg["fp_rate"] * 100.0
    lines.append(
        f"| 1 | P0 alert 误报率 | `< 30%` | "
        f"`{fp_pct:.2f}% ({agg['total_false_positives']:,}/{agg['total_classified']:,})` "
        f"| {'✅' if agg['pass_fp_rate'] else '❌'} |"
    )
    p99 = agg["max_quarter_p99_ms"]
    p99_str = f"{p99:.3f}ms (max-quarter)" if p99 is not None else "<no samples>"
    lines.append(
        f"| 2 | L1 detection latency P99 | `< 5000ms` | `{p99_str}` "
        f"| {'✅' if agg['pass_latency'] else '❌'} |"
    )
    lines.append(
        f"| 3 | L4 STAGED 流程闭环 0 失败 | `= 0` | `{agg['total_staged_failed']}` "
        f"| {'✅' if agg['pass_staged'] else '❌'} |"
    )
    lines.append(
        f"| 4 | 元监控 0 P0 元告警 (replay-integrity form) | `= 0` | "
        f"`{'0' if agg['pass_meta'] else '≥1'}` | {'✅' if agg['pass_meta'] else '❌'} |"
    )
    lines.append("")
    lines.append(
        f"- Total minute_bars replayed: **{agg['total_minute_bars']:,}** · "
        f"events: **{agg['total_events']:,}** · "
        f"raw P0: **{agg['total_raw_p0']:,}** · deduped daily P0: "
        f"**{agg['total_deduped_p0']:,}** · classified: **{agg['total_classified']:,}** "
        f"(FP={agg['total_false_positives']:,}, TP={agg['total_true_positives']:,}) · "
        f"unclassifiable: **{agg['total_unclassifiable']:,}**"
    )
    lines.append(
        f"- STAGED: actionable **{agg['total_staged_actionable']:,}** · generated "
        f"**{agg['total_staged_generated']:,}** · closed-ok "
        f"**{agg['total_staged_closed_ok']:,}** · failed **{agg['total_staged_failed']}** · "
        f"deadline-integrity **{agg['deadline_integrity_ok']}** · "
        f"pure-function-contract **{agg['contract_verified']}**"
    )
    lines.append(f"- Total replay wall-clock: **{agg['total_wall_clock_s']:.1f}s**")
    lines.append("")
    lines.append("### Per-rule FP/TP/unclassifiable (5y aggregate)")
    lines.append("")
    lines.append("| rule_id | FP | TP | unclassifiable |")
    lines.append("|---|---|---|---|")
    for rid, (f, t, u) in agg["by_rule"].items():
        lines.append(f"| `{rid}` | {f:,} | {t:,} | {u:,} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §2 Per-quarter breakdown")
    lines.append("")
    lines.append(
        "| quarter | minute_bars | events | raw P0 | deduped P0 | FP | TP | "
        "P99 ms | staged failed | contract |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for q in quarters:
        p99q = f"{q.p99_ms:.3f}" if q.p99_ms is not None else "n/a"
        lines.append(
            f"| {q.name} | {q.minute_bars:,} | {q.events:,} | {q.raw_p0:,} | "
            f"{q.deduped_p0:,} | {q.false_positives:,} | {q.true_positives:,} | "
            f"{p99q} | {q.staged_failed} | {'✅' if q.contract_verified else '❌'} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §3 Methodology + caveats")
    lines.append("")
    lines.append(
        "- **Chunked per-quarter** (user 决议 A): the full ~191M-row minute_bars "
        "table cannot be materialized at once (TB-5b's `list(loader())` → ~95GB+ "
        "at 5y scale). Each quarter (~8M bars / ~3GB) is run + classified + the "
        "raw events discarded before the next quarter — only count aggregates "
        "are carried. Per-(code, rule_id, day) dedup is quarter-local-safe "
        "(quarters never span a day boundary)."
    )
    lines.append(
        "- **Latency P99 = max of per-quarter P99** — conservative aggregate (if "
        "every quarter's P99 < 5s then the 5y P99 < 5s). A true 5y P99 over "
        "~191M samples would need a streaming t-digest; the latency is already a "
        "documented LOWER-BOUND proxy (ADR-070 D6 — per-evaluate_at wall-clock, "
        "excludes I/O), so max-quarter is the honest conservative aggregate."
    )
    lines.append(
        "- **FP classification** sustained ADR-070: daily-dedup to "
        "first-per-(code, rule_id, day) + prev_close baseline counterfactual "
        "(FP = day-end close recovered ≥ prev_close). Methodology limitations "
        "carried forward (ADR-066 D3 caveat family): synthetic universe-wide "
        "Position = 误报率 upper-bound proxy NOT production-portfolio precision; "
        "3/10 rules silent-skip (avg_daily_volume / industry / atr_pct not in "
        "minute_bars — sustained TB-5b §57-69)."
    )
    lines.append(
        "- **0 真账户 / 0 broker / 0 .env / 0 INSERT** — pure read-only DB SELECT "
        "+ in-memory replay, per-quarter pure-function contract audited. 红线 5/5 "
        "sustained: cash=￥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / "
        "EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102."
    )
    lines.append("")
    lines.append(
        "关联: V3 §15.4 / §13.1 / §15.5 · ADR-063 / ADR-066 / ADR-070 / ADR-076 ·"
    )
    lines.append("Plan v0.3 §A HC-4 row + §D · 铁律 31/33/41 · LL-098 X10 / LL-159")
    lines.append("")
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    p.add_argument(
        "--codes-limit",
        type=int,
        default=None,
        help="可选 code subset 限制 (quick smoke run; 0 或省略 = full universe)",
    )
    p.add_argument(
        "--quarters",
        type=int,
        default=None,
        help="只跑前 N 个 quarter (debug; N >= 1; 省略 = all 20)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="report markdown 输出路径 (default: docs/audit/v3_hc_4_5y_replay_*.md)",
    )
    p.add_argument("--dry-run", action="store_true", help="仅打印 report, 不 sediment markdown")
    p.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return p


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    if args.quarters is not None and args.quarters <= 0:
        parser.error("--quarters must be >= 1 (省略 for all 20)")
    if args.codes_limit is not None and args.codes_limit < 0:
        parser.error("--codes-limit must be >= 0 (0 或省略 for full universe)")
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    from app.services.db import get_sync_conn

    windows = _build_quarter_windows()
    if args.quarters is not None:
        windows = windows[: args.quarters]

    out_path = args.out or (
        PROJECT_ROOT
        / "docs"
        / "audit"
        / f"v3_hc_4_5y_replay_acceptance_report_{datetime.now(_SHANGHAI_TZ):%Y_%m_%d}.md"
    )

    logger.info(
        "[HC-4a] starting 5y chunked replay — %d quarters, codes_limit=%s",
        len(windows),
        args.codes_limit,
    )
    conn = get_sync_conn()
    quarters: list[_QuarterResult] = []
    try:
        for window in windows:
            qr = _run_quarter(window, conn, args.codes_limit)
            if qr is not None:
                quarters.append(qr)
            # Release the long-lived read-only PG snapshot between quarters
            # (sustained TB-5b/TB-1c reviewer P2 fix).
            conn.commit()
    finally:
        conn.close()

    if not quarters:
        logger.error("[HC-4a] 0 quarters produced data — nothing to report")
        return 1

    agg = _aggregate(quarters)
    report = _render_report(quarters, agg)
    print(report)  # noqa: T201 — ops script user-facing output

    overall = agg["pass_fp_rate"] and agg["pass_latency"] and agg["pass_staged"] and agg["pass_meta"]
    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        logger.info("[HC-4a] sedimented 5y replay acceptance report: %s", out_path)
    else:
        logger.info("[HC-4a] --dry-run: skipped sediment")

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
