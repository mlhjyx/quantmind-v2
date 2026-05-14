#!/usr/bin/env python3
"""V3 Tier B TB-5b — Replay acceptance verification over 2 关键窗口.

Plan v0.2 §A TB-5 row 第 2 sub-PR (TB-5b) — replay 验收 4 项 + 5 SLA verify.

Builds the acceptance layer on top of TB-1's replay infrastructure (ReplayRunner +
RiskBacktestAdapter.evaluate_at). For each of the 2 关键窗口 (ADR-064 D3=b):

  1. 2024Q1 量化踩踏 (2024-01-02 → 2024-02-09)
  2. 2025-04-07 关税冲击 (2025-04-01 → 2025-04-11)

it re-runs the synthetic-universe replay WITH new instrumentation, then computes
the V3 §15.4 4 项 acceptance + the 2 replay-exercisable V3 §13.1 SLA via the PURE
`qm_platform.risk.replay.acceptance` module.

Instrumentation (0 changes to closed TB-1 code — sustained ADR-022 反 retroactive
edit):
  - `_TimingAdapter` — RiskBacktestAdapter subclass capturing, as a side-channel,
    (a) per-evaluate_at wall-clock latency samples and (b) (timestamp, RuleResult)
    pairs. The ReplayRunner calls our adapter's evaluate_at transparently.
  - day-end price index — `{(code, date): day_end_close}` built during bar
    streaming, powers the counterfactual false-positive lookup (V3 §15.5).

The synthetic-universe runner mirrors TB-1c's `Tb1cRunner` (per-bar synthetic
Position + 5min/15min lookback ring + day-boundary reset). It is re-implemented
locally rather than imported because TB-1c's runner lives inside a script-local
closure; consolidating both into a shared module is deferred (out of TB-5b scope,
反 closed-code blast radius).

Safety: 0 broker / 0 .env / 0 INSERT — pure read-only DB SELECT + in-memory replay.
Re-runnable. Pure-function contract audited per window via adapter.

4-step preflight verify SOP (sustained feedback_validation_rigor.md):
  ✅ Step 1 SSOT calendar: same 2 windows TB-1c already replayed against (ADR-066).
  ✅ Step 2 data presence: TB-1c consumed 3.3M + 0.96M bars — data verified present.
  N/A Step 3 cron alignment: one-shot ops script, not a schtask.
  N/A Step 4 natural production behavior: this script IS the verification.

Usage:
    python scripts/v3_tb_5b_replay_acceptance.py                  # both windows
    python scripts/v3_tb_5b_replay_acceptance.py --window 2024q1  # single window
    python scripts/v3_tb_5b_replay_acceptance.py --codes-limit 100 --dry-run

关联铁律: 22 / 24 / 25 / 31 / 33 / 41
关联 V3: §15.4 (4 项 acceptance) / §13.1 (SLA) / §15.5 (counterfactual) / §15.6 (TB-5a)
关联 ADR: ADR-063 (Tier B 真测路径) / ADR-064 D3=b (2 关键窗口) / ADR-066 (TB-1 baseline) /
  ADR-070 (本 sub-PR sediment 锁 methodology + 阈值)
关联 Plan: V3_TIER_B_SPRINT_PLAN_v0.1.md §A TB-5 row + §C + §D
关联 LL: LL-098 X10 / LL-159 (4-step preflight SOP)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

if TYPE_CHECKING:
    from qm_platform.risk.interface import RiskContext, RuleResult
    from qm_platform.risk.realtime.engine import RealtimeRiskEngine

# Asia/Shanghai for user-facing report date + filename (铁律 41 — display tz).
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

logger = logging.getLogger(__name__)

# 5min K bars: 240 min trading day / 5 = 48 bars/code/day.
# Lookback ring needs ≥ 4 bars (15min / 5min = 3 + 1 current).
_LOOKBACK_RING_SIZE: int = 4


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "--window",
        choices=("all", "2024q1", "2025_0407"),
        default="all",
        help="选择 replay window (default: all 2 windows)",
    )
    p.add_argument(
        "--codes-limit",
        type=int,
        default=None,
        help="可选 code subset 限制 (debug / quick run, 0 = unlimited)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="acceptance report markdown 输出路径 (default: docs/audit/v3_tb_5b_*.md)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印 acceptance report, 不 sediment markdown",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return p


def _make_minute_bars_loader(conn: Any, codes_limit: int | None):
    """Build a streaming loader: minute_bars rows + prev_close from klines_daily.

    Mirrors TB-1c's loader (scripts/v3_tb_1_replay_2_windows.py). Server-side
    cursor 防 21M+ rows OOM. yield dict 与 ReplayRunner.run_window 约定一致.
    """

    def loader(start_date: date, end_date: date):
        sql = """
        WITH last_close AS (
          SELECT code, trade_date,
                 LAG(close) OVER (PARTITION BY code ORDER BY trade_date) AS prev_close
            FROM klines_daily
           WHERE trade_date >= (%s::date - INTERVAL '10 days')
             AND trade_date <= %s
        )
        SELECT mb.trade_time, mb.code,
               mb.open, mb.high, mb.low, mb.close,
               mb.volume, mb.amount,
               lc.prev_close
          FROM minute_bars mb
     LEFT JOIN last_close lc
            ON lc.code = mb.code AND lc.trade_date = mb.trade_time::date
         WHERE mb.trade_time >= %s
           AND mb.trade_time < (%s::date + INTERVAL '1 day')
        """
        params: list[Any] = [start_date, end_date, start_date, end_date]

        if codes_limit is not None and codes_limit > 0:
            sql += """
             AND mb.code IN (
               SELECT DISTINCT code FROM minute_bars
                WHERE trade_time >= %s AND trade_time < (%s::date + INTERVAL '1 day')
                ORDER BY code
                LIMIT %s
             )
            """
            params.extend([start_date, end_date, codes_limit])

        sql += " ORDER BY mb.trade_time, mb.code"

        with conn.cursor("tb_5b_replay_minute_bars") as cur:
            cur.itersize = 50_000
            cur.execute(sql, tuple(params))
            for row in cur:
                yield {
                    "trade_time": row[0],
                    "code": row[1],
                    "open": float(row[2] or 0),
                    "high": float(row[3] or 0),
                    "low": float(row[4] or 0),
                    "close": float(row[5] or 0),
                    "volume": int(row[6] or 0),
                    "amount": float(row[7] or 0),
                    "prev_close": float(row[8] or 0),
                }

    return loader


def _make_timing_adapter():
    """RiskBacktestAdapter subclass capturing latency + (ts, RuleResult) side-channel.

    0 changes to closed TB-1 code — the ReplayRunner calls `adapter.evaluate_at`
    transparently; this subclass times the call + records each emitted RuleResult
    against its timestamp (RuleResult itself carries no timestamp).
    """
    from qm_platform.risk.backtest_adapter import RiskBacktestAdapter

    class _TimingAdapter(RiskBacktestAdapter):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.eval_latencies_ms: list[float] = []
            self.timestamped_events: list[tuple[datetime, RuleResult]] = []

        def evaluate_at(
            self,
            timestamp: datetime,
            context: RiskContext,
            engine: RealtimeRiskEngine,
        ) -> list[RuleResult]:
            t0 = time.perf_counter()
            results = super().evaluate_at(timestamp, context, engine)
            self.eval_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            for r in results:
                self.timestamped_events.append((timestamp, r))
            return results

    return _TimingAdapter()


def _make_synthetic_runner(adapter: Any, engine: Any):
    """Synthetic-universe ReplayRunner subclass (mirrors TB-1c Tb1cRunner).

    Per-bar synthetic Position (universe-wide treat-as-held, shares=100) + 5min /
    15min lookback ring + day-boundary reset. See module docstring for why this is
    re-implemented locally rather than imported.
    """
    from qm_platform.risk.interface import Position, RiskContext
    from qm_platform.risk.replay.runner import ReplayRunner

    class _SyntheticUniverseRunner(ReplayRunner):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._price_history: dict[str, deque[tuple[datetime, float]]] = {}
            self._last_seen_date: dict[str, date] = {}

        def _lookback_price(self, code: str, ts: datetime, minutes_back: int) -> float | None:
            hist = self._price_history.get(code)
            if not hist:
                return None
            target = ts - timedelta(minutes=minutes_back)
            for hist_ts, hist_price in reversed(hist):
                if hist_ts <= target:
                    return hist_price
            return None

        def build_context(  # type: ignore[override]
            self,
            timestamp: datetime,
            positions: tuple,
            bar_row: dict[str, Any],
        ) -> RiskContext:
            code = bar_row["code"]
            close = bar_row["close"]
            prev_close = bar_row.get("prev_close", 0.0) or 0.0
            open_price = bar_row.get("open", 0.0) or 0.0

            # Day-boundary reset: overnight gap is not "5min ago".
            bar_date = timestamp.date()
            last_date = self._last_seen_date.get(code)
            if last_date is not None and last_date != bar_date:
                hist = self._price_history.get(code)
                if hist is not None:
                    hist.clear()
            self._last_seen_date[code] = bar_date

            price_5min_ago = self._lookback_price(code, timestamp, 5)
            price_15min_ago = self._lookback_price(code, timestamp, 15)

            hist = self._price_history.setdefault(code, deque(maxlen=_LOOKBACK_RING_SIZE))
            hist.append((timestamp, close))

            entry_basis = prev_close if prev_close > 0 else close
            peak = max(entry_basis, close)
            synthetic_pos = Position(
                code=code,
                shares=100,
                entry_price=entry_basis,
                peak_price=peak,
                current_price=close,
            )
            realtime = {
                code: {
                    "prev_close": prev_close,
                    "open_price": open_price,
                    "current_price": close,
                    "high": bar_row.get("high", 0.0) or 0.0,
                    "low": bar_row.get("low", 0.0) or 0.0,
                    "day_volume": bar_row.get("volume", 0) or 0,
                    "amount": bar_row.get("amount", 0.0) or 0.0,
                    "price_5min_ago": price_5min_ago,
                    "price_15min_ago": price_15min_ago,
                },
            }
            return RiskContext(
                strategy_id="tb_5b_synthetic_universe",
                execution_mode="paper",
                timestamp=timestamp,
                positions=(synthetic_pos,),
                portfolio_nav=1_000_000.0,
                prev_close_nav=1_000_000.0,
                realtime=realtime,
            )

    return _SyntheticUniverseRunner(adapter, engine)


def _normalize_ts(raw_ts: datetime):
    """Normalize a minute_bars trade_time the same way ReplayRunner does."""
    from qm_platform.risk.replay.runner import SHANGHAI_TZ

    if raw_ts.tzinfo is None:
        return raw_ts.replace(tzinfo=SHANGHAI_TZ)
    return raw_ts.astimezone(SHANGHAI_TZ)


def _build_day_end_index(
    bars: list[dict[str, Any]],
) -> dict[tuple[str, date], float]:
    """Build `{(code, trading_date): day_end_close}` from the bar stream.

    Bars arrive ORDER BY trade_time, code — the LAST close seen for a
    (code, date) key is that day's end-of-day close. Powers the counterfactual
    "did the held position end the day underwater" lookup (ADR-070 methodology).
    """
    index: dict[tuple[str, date], float] = {}
    for bar in bars:
        ts = _normalize_ts(bar["trade_time"])
        # Later bars overwrite earlier ones → final write = day-end close.
        index[(bar["code"], ts.date())] = float(bar["close"])
    return index


def _make_day_end_price_lookup(
    day_end_index: dict[tuple[str, date], float],
):
    """Build the day_end_price_lookup callable for classify_false_positives.

    (code, alert_ts) -> the code's end-of-day close on alert_ts's trading day,
    or None if that (code, date) had no bars.
    """

    def lookup(code: str, alert_ts: datetime) -> float | None:
        return day_end_index.get((code, alert_ts.date()))

    return lookup


def _run_window_acceptance(window: Any, conn: Any, codes_limit: int | None):
    """Run one window's replay + acceptance evaluation. Returns ReplayAcceptanceReport."""
    from qm_platform.risk.realtime.engine import RealtimeRiskEngine
    from qm_platform.risk.replay.acceptance import (
        classify_false_positives,
        evaluate_replay_acceptance,
        evaluate_staged_closure,
    )

    logger.info(
        "[TB-5b] window=%s start=%s end=%s — loading minute_bars...",
        window.name,
        window.start_date,
        window.end_date,
    )

    # Materialize bars once → build day-end index → feed run_window.
    loader = _make_minute_bars_loader(conn, codes_limit)
    bars = list(loader(window.start_date, window.end_date))
    logger.info("[TB-5b] window=%s: %d minute_bars loaded", window.name, len(bars))

    day_end_index = _build_day_end_index(bars)
    day_end_lookup = _make_day_end_price_lookup(day_end_index)

    adapter = _make_timing_adapter()
    engine = RealtimeRiskEngine()
    adapter.register_all_realtime_rules(engine)
    runner = _make_synthetic_runner(adapter, engine)

    t0 = time.monotonic()
    replay_result = runner.run_window(window, bars=bars)
    logger.info(
        "[TB-5b] window=%s: replay done in %.1fs — events=%d, timestamps=%d, "
        "contract_verified=%s, latency_samples=%d, timestamped_events=%d",
        window.name,
        time.monotonic() - t0,
        len(replay_result.events),
        replay_result.total_timestamps,
        replay_result.pure_function_contract_verified,
        len(adapter.eval_latencies_ms),
        len(adapter.timestamped_events),
    )

    # Free the heavy bar list before the acceptance phase.
    del bars

    fp_classification = classify_false_positives(adapter.timestamped_events, day_end_lookup)
    staged_closure = evaluate_staged_closure(adapter.timestamped_events)
    report = evaluate_replay_acceptance(
        replay_result=replay_result,
        fp_classification=fp_classification,
        staged_closure=staged_closure,
        latencies_ms=adapter.eval_latencies_ms,
    )
    logger.info(
        "[TB-5b] window=%s: acceptance %s — fp_rate=%.2f%%, staged_failed=%d",
        window.name,
        "PASS" if report.all_pass else "FAIL",
        fp_classification.fp_rate * 100.0,
        staged_closure.failed,
    )
    return report


def _sediment_report(reports: list[Any], out_path: Path) -> Path:
    """Write the combined acceptance report markdown to docs/audit/."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    overall = all(r.all_pass for r in reports)

    lines: list[str] = []
    lines.append("# V3 TB-5b — Replay Acceptance Report (2 关键窗口)")
    lines.append("")
    lines.append(f"**Run date**: {datetime.now(_SHANGHAI_TZ).date().isoformat()}  ")
    lines.append(f"**Overall verdict**: {'✅ PASS' if overall else '❌ FAIL'}  ")
    lines.append(
        "**Scope**: V3 §15.4 4 项 acceptance + V3 §13.1 SLA (replay-exercisable "
        "subset) on the 2 关键窗口 (ADR-064 D3=b), via the pure "
        "`qm_platform.risk.replay.acceptance` evaluator. ADR-063 转 Tier B 真测路径."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    for report in reports:
        lines.append(report.to_markdown())
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("关联: V3 §15.4 / §13.1 / §15.5 · ADR-063 / ADR-064 / ADR-066 / ADR-070 ·")
    lines.append("Plan v0.2 §A TB-5 row + §C + §D · 铁律 31/33/41 · LL-098 X10 / LL-159")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main() -> int:
    args = _build_arg_parser().parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    from qm_platform.risk.replay.runner import (
        ALL_WINDOWS,
        WINDOW_2024Q1_QUANT_CRASH,
        WINDOW_2025_04_07_TARIFF_SHOCK,
    )

    from app.services.db import get_sync_conn

    selected = {
        "all": list(ALL_WINDOWS),
        "2024q1": [WINDOW_2024Q1_QUANT_CRASH],
        "2025_0407": [WINDOW_2025_04_07_TARIFF_SHOCK],
    }[args.window]

    out_path = args.out or (
        PROJECT_ROOT
        / "docs"
        / "audit"
        / f"v3_tb_5b_replay_acceptance_report_{datetime.now(_SHANGHAI_TZ):%Y_%m_%d}.md"
    )

    conn = get_sync_conn()
    reports: list[Any] = []
    rc = 0
    try:
        for window in selected:
            report = _run_window_acceptance(window, conn, args.codes_limit)
            reports.append(report)
            if not report.all_pass:
                rc = 1
            # Release the long-lived read-only PG snapshot between windows
            # (sustained TB-1c reviewer P2 fix).
            conn.commit()
    finally:
        conn.close()

    # Print each report to console.
    for report in reports:
        print(report.to_markdown())  # noqa: T201 — ops script user-facing output
        print()  # noqa: T201

    if not args.dry_run:
        target = _sediment_report(reports, out_path)
        logger.info("[TB-5b] sedimented acceptance report: %s", target)
    else:
        logger.info("[TB-5b] --dry-run: skipped sediment")

    return rc


if __name__ == "__main__":
    sys.exit(main())
