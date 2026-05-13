#!/usr/bin/env python3
"""V3 Tier B TB-1c — Replay 2 critical windows against real DB minute_bars.

Plan v0.2 §A TB-1 row 第 3 sub-PR (TB-1c) — closure sediment.

走 RiskBacktestAdapter.evaluate_at + RealtimeRiskEngine + ReplayRunner subclass
(per-bar synthetic Position injection) 跑 2 关键窗口:

  1. 2024Q1 量化踩踏 (2024-01-02 → 2024-02-08, 28 trading days)
  2. 2025-04-07 关税冲击 (2025-04-01 → 2025-04-11, 8 trading days)

Output: docs/risk_reflections/replay/{YEAR}_replay_{window_name}.md per V3 §8.2 体例.

设计 (per architecture (α) sustained user ack 2026-05-13 + ADR-066 候选 sediment):
  - 同 RiskBacktestAdapter class 注入 broker + notifier + price_reader stubs
  - 10 RealtimeRiskRule 全注册 (cadence 分发 tick/5min/15min) per ADR-029 amend
  - Synthetic per-bar Position: 每根 minute_bars 行综合成 Position(code, shares=100,
    entry_price=prev_close, current_price=close), 测量 "若全 universe 持仓 1 股" 的
    fire count baseline (V3 §15.5 sim-to-real gap audit 起步基线).
  - Pure-function contract: 0 broker / 0 INSERT / 0 alert (adapter audit verify).
  - 数据依赖: minute_bars 5min K + klines_daily.close LAG(1) for prev_close.
    其余 fields (avg_daily_volume / industry / atr_pct) 留 TB-5c batch 后补,
    所以 VolumeSpike / LiquidityCollapse / IndustryConcentration / TrailingStop
    silent skip — expected in this v1 baseline.

4-step preflight verify SOP (sustained feedback_validation_rigor.md):
  ✅ Step 1 SSOT calendar: trading_calendar 已查, minute_bars 自然日分布与 SSOT 对齐.
  ✅ Step 2 data presence: 2024Q1 28 days × ~118K rows / 2025-04 8 days × ~120K rows.
  N/A Step 3 cron alignment: 一次性 ops, 非 schtask 触发.
  N/A Step 4 natural production behavior: 本脚本 IS the test, 非 audit 生产路径.

关联铁律: 22 / 24 / 25 / 31 / 33 / 41
关联 V3: §11.4 RiskBacktestAdapter pure function / §15.5 历史回放 sim-to-real gap
关联 ADR: ADR-029 (10 rules) / ADR-064 (Plan v0.2 D3=b 2 关键窗口) / ADR-066 候选 (TB-1 closure)
关联 LL: LL-098 X10 / LL-159 (4-step preflight SOP)

用法:
    # 全 2 windows (默认)
    python scripts/v3_tb_1_replay_2_windows.py

    # 单 window
    python scripts/v3_tb_1_replay_2_windows.py --window 2024q1
    python scripts/v3_tb_1_replay_2_windows.py --window 2025_0407

    # 限制 code subset (debug / quick run)
    python scripts/v3_tb_1_replay_2_windows.py --codes-limit 100

    # Skip sediment (dry-run, just print summary)
    python scripts/v3_tb_1_replay_2_windows.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import deque
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# 延迟 import — 加快 --help / 错参 fail-fast
if TYPE_CHECKING:
    from qm_platform.risk.interface import Position, RiskContext  # noqa: F401
    from qm_platform.risk.replay.runner import ReplayWindow  # noqa: F401

logger = logging.getLogger(__name__)

# 5min K bars: 240 min trading day / 5 = 48 bars/code/day
# Lookback ring needs at least 4 bars (15min / 5min = 3 + 1 current)
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
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "docs" / "risk_reflections" / "replay",
        help="reflection markdown 输出目录",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印 summary, 不 sediment markdown",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return p


def _make_minute_bars_loader(conn, codes_limit: int | None):
    """Build a streaming loader that yields minute_bars rows + prev_close from klines_daily.

    使用 server-side cursor (named cursor) 防止 21M+ rows OOM materialize 全量.
    yield dict 与 ReplayRunner.run_window 约定一致 (trade_time / code / open / high
    / low / close / volume / amount / prev_close).

    Args:
        conn: psycopg2 connection (caller manages close).
        codes_limit: optional cap on distinct codes (for debug, None = all).

    Returns:
        loader callable matching ReplayRunner.minute_bars_loader signature.
    """

    def loader(start_date: date, end_date: date):
        # JOIN minute_bars + LAG(klines_daily.close) per code/date.
        # CTE prev_close 限 7 day prior buffer 防止 LAG 跨非交易日 NULL — 取得最近一日 close.
        # 注: end_date inclusive (window 体例), SQL 用 < (end_date + 1) bound.
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
        params: list = [start_date, end_date, start_date, end_date]

        if codes_limit is not None and codes_limit > 0:
            # Pick deterministic subset (ORDER BY code, LIMIT) — for debug only.
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

        # Server-side cursor 防 21M rows full materialize.
        with conn.cursor("tb_1c_replay_minute_bars") as cur:
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


def _make_runner(adapter, engine, loader):
    """Create the per-bar synthetic-position ReplayRunner subclass instance.

    Overrides build_context to inject 1-code Position synthesized from the bar
    + enriched realtime dict with rolling 5min / 15min price lookbacks.
    """
    from qm_platform.risk.interface import Position, RiskContext
    from qm_platform.risk.replay.runner import ReplayRunner

    class Tb1cRunner(ReplayRunner):
        """TB-1c synthetic-position replay runner (universe-wide fire count baseline).

        State per instance:
            _price_history: dict[code, deque[(ts, close)]] last 4 bars (covers 15min)
            _last_seen_date: dict[code, date] — detect day boundary for history reset

        Day boundary reset rationale: overnight gap is not "5min ago" — clear history
        when bar's date != last seen date for that code (V3 §11.4 sustained, 铁律 41
        timezone-aware date compare).
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._price_history: dict[str, deque[tuple[datetime, float]]] = {}
            self._last_seen_date: dict[str, date] = {}

        def _lookback_price(self, code: str, ts: datetime, minutes_back: int) -> float | None:
            """Find the most recent close at or before (ts - minutes_back).

            Returns None when:
              - no history (first bar of day for code)
              - all history newer than target lookback time
              - history exists but all from a different date (day boundary already
                handled by reset, but defensive)
            """
            hist = self._price_history.get(code)
            if not hist:
                return None
            target = ts - timedelta(minutes=minutes_back)
            # deque iteration newest-last; reverse to find most-recent ≤ target
            for hist_ts, hist_price in reversed(hist):
                if hist_ts <= target:
                    return hist_price
            return None

        def build_context(  # type: ignore[override]
            self,
            timestamp: datetime,
            positions: tuple,  # ignored — TB-1c synthesizes per-bar
            bar_row: dict[str, Any],
        ) -> RiskContext:
            code = bar_row["code"]
            close = bar_row["close"]
            prev_close = bar_row.get("prev_close", 0.0) or 0.0
            open_price = bar_row.get("open", 0.0) or 0.0

            # Day boundary detection: reset history on new trading day for this code.
            bar_date = timestamp.date()
            last_date = self._last_seen_date.get(code)
            if last_date is not None and last_date != bar_date:
                # 新交易日: 历史清零 (overnight 不算 "5min ago")
                hist = self._price_history.get(code)
                if hist is not None:
                    hist.clear()
            self._last_seen_date[code] = bar_date

            # Lookback 5min / 15min — BEFORE appending current bar (避免本根回看自身).
            price_5min_ago = self._lookback_price(code, timestamp, 5)
            price_15min_ago = self._lookback_price(code, timestamp, 15)

            # Update history ring buffer.
            hist = self._price_history.setdefault(code, deque(maxlen=_LOOKBACK_RING_SIZE))
            hist.append((timestamp, close))

            # Synthesize Position from bar (universe-wide treat-as-held mode).
            # entry_price = prev_close 是 "若 T-1 收盘买入 1 股" 假设, 等同 day-trade 入场.
            # 0 prev_close (data missing) → entry_price=close (0% pnl, TrailingStop skip).
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
                    # 留空: avg_daily_volume / industry / atr_pct
                    # → VolumeSpike / LiquidityCollapse / IndustryConcentration /
                    #   TrailingStop silent skip (expected in v1 baseline)
                },
            }
            return RiskContext(
                strategy_id="tb_1c_synthetic_universe",
                execution_mode="paper",
                timestamp=timestamp,
                positions=(synthetic_pos,),
                portfolio_nav=1_000_000.0,
                prev_close_nav=1_000_000.0,
                realtime=realtime,
            )

    return Tb1cRunner(adapter, engine, minute_bars_loader=loader)


def _sediment_reflection(result, out_dir: Path) -> Path:
    """Write reflection markdown to docs/risk_reflections/replay/.

    File naming per V3 §8.2 体例: {YEAR}_replay_{window_name}.md
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{result.window.start_date.year}_replay_{result.window.name}.md"
    target = out_dir / fname

    lines: list[str] = []
    lines.append(f"# Replay Sediment — {result.window.name}")
    lines.append("")
    lines.append(f"**Window**: {result.window.start_date} → {result.window.end_date}  ")
    lines.append(f"**Description**: {result.window.description}  ")
    lines.append(f"**Run date**: {datetime.now(UTC).date().isoformat()}  ")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- Total minute_bars consumed: **{result.total_minute_bars:,}**")
    lines.append(f"- Total unique timestamps: **{result.total_timestamps:,}**")
    lines.append(f"- Wall clock: **{result.wall_clock_seconds:.1f}s**")
    lines.append(
        f"- Pure-function contract verified (0 broker / 0 INSERT / 0 alert): "
        f"**{result.pure_function_contract_verified}**"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    if result.summary is not None:
        lines.append(result.summary.to_markdown())

    lines.append("")
    lines.append("## Sim-to-real gap audit (V3 §15.5)")
    lines.append("")
    lines.append(
        "**Methodology**: synthetic per-bar Position (universe-wide treat-as-held, "
        "shares=100, entry_price=prev_close). 此为 fire-count baseline — 测量 "
        '"若全 universe 持仓" 的规则触发上限. 真生产持仓 < universe, 故 '
        "production fire count 应 ≤ baseline."
    )
    lines.append("")
    lines.append("**Data dependency caveats (v1 baseline)**:")
    lines.append(
        "- `prev_close` 来自 klines_daily.close LAG(1, partition by code), "
        "若某 code 在 window start 前无 klines_daily 行 → entry_price=close → "
        "TrailingStop silent skip (pnl=0)."
    )
    lines.append(
        "- `avg_daily_volume` / `industry` / `atr_pct` 留 TB-5c batch 补 → "
        "**VolumeSpike / LiquidityCollapse / IndustryConcentration / TrailingStop "
        "在 v1 baseline 中 silent skip** (expected sparsity)."
    )
    lines.append(
        "- `price_5min_ago` / `price_15min_ago` per-code rolling state, "
        "overnight gap 清零 (avoid cross-day false lookback)."
    )
    lines.append("")
    lines.append("**Next steps (TB-5c batch closure)**:")
    lines.append(
        "1. Compare 本 baseline events 与 risk_event_log 同窗口告警数 → "
        "gap = sim_baseline - production_actual."
    )
    lines.append("2. 入 ADR-066 closure 终态 + V3 §15.5 sim-to-real gap 量化指标.")
    lines.append(
        "3. 补 avg_daily_volume / industry / atr_pct 数据后重跑 baseline, "
        "覆盖 10/10 rules 完整 fire count."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("关联:")
    lines.append("- V3 §11.4 RiskBacktestAdapter pure function")
    lines.append("- V3 §15.5 历史回放 sim-to-real gap counterfactual")
    lines.append("- ADR-029 (10 RealtimeRiskRule)")
    lines.append("- ADR-064 D3=b (2 关键窗口 sustained)")
    lines.append("- ADR-066 候选 (TB-1 closure)")
    lines.append("- LL-098 X10 / LL-159 (4-step preflight SOP)")
    lines.append("")

    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def main() -> int:
    args = _build_arg_parser().parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # 延迟 import 加快 --help / 错参 fail-fast.
    from qm_platform.risk.backtest_adapter import RiskBacktestAdapter
    from qm_platform.risk.realtime.engine import RealtimeRiskEngine
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

    conn = get_sync_conn()
    rc = 0
    try:
        for window in selected:
            logger.info(
                "[TB-1c] window=%s start_date=%s end_date=%s",
                window.name,
                window.start_date,
                window.end_date,
            )
            # Fresh adapter + engine per window — 防止跨 window state 串扰.
            adapter = RiskBacktestAdapter()
            engine = RealtimeRiskEngine()
            adapter.register_all_realtime_rules(engine)

            loader = _make_minute_bars_loader(conn, args.codes_limit)
            runner = _make_runner(adapter, engine, loader)

            result = runner.run_window(window, positions=())
            events_n = result.summary.total_events if result.summary else 0
            logger.info(
                "[TB-1c] window=%s: events=%d, timestamps=%d, bars=%d, "
                "wall_clock=%.1fs, contract_verified=%s",
                window.name,
                events_n,
                result.total_timestamps,
                result.total_minute_bars,
                result.wall_clock_seconds,
                result.pure_function_contract_verified,
            )

            if not result.pure_function_contract_verified:
                logger.error(
                    "[TB-1c] V3 §11.4 pure-function contract FAILED — "
                    "adapter detected broker/alert side effects during replay"
                )
                rc = 1

            if not args.dry_run:
                target = _sediment_reflection(result, args.out_dir)
                logger.info("[TB-1c] sedimented reflection: %s", target)
            else:
                logger.info("[TB-1c] --dry-run: skipped sediment")

            # Reviewer P2 fix (PR #332): release long-lived read-only PG snapshot
            # between windows. Without this, multi-window run holds a single
            # transaction across ~40s — VACUUM cannot clean tuples modified during
            # that span. conn.commit() is no-op semantically (0 DML executed) but
            # closes the transaction and frees the snapshot.
            conn.commit()
    finally:
        conn.close()

    return rc


if __name__ == "__main__":
    sys.exit(main())
