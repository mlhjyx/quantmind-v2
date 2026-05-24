"""Performance Report Celery task (Sprint 1.24 closure — iter 30).

Wraps strategy performance aggregation into a Celery task dispatched by
`POST /api/reports/generate`. Output = structured JSON written to
`reports/{strategy_id}_{date}_{execution_mode}.json` (filesystem artifact —
no new DB table per scope bound; consumers read via GET /api/reports/{sid}/latest).

Closes the Sprint 1.24 TODO at `backend/app/api/report.py:198` ("报告生成 Celery
任务尚未实现"). Endpoint flow before iter 30: returned uuid4 + "accepted" stub
with no real backend task. After iter 30: real Celery .delay() dispatch + real
AsyncResult task_id + filesystem JSON artifact consumable via GET /latest.

Scope guardrails (iter 30 opinionated, reviewer can iterate):
  - JSON content = (a) rolling_stats(60d): sharpe / mdd / total_return / latest_nav
    (b) latest_nav row (nav / daily_return / cum_return / drawdown / cash_ratio /
    position_count / turnover) (c) recent 20 trade_log entries summary
  - 0 new DB table; filesystem JSON (reports/ dir already exists per `ls reports/`)
  - sync psycopg2 in task body (sustained pattern from daily_metrics_extract_tasks)
  - target_date = today Asia/Shanghai (post-market relevance)
  - 0 broker call / 0 .env mutation / 0 yaml mutation / 0 production data write

铁律: 22 (doc-tracking) / 31 (task layer not engine) / 32 (caller owns commit;
  task uses connection-per-task with explicit commit) / 33 (silent failure ban —
  errors propagate to Celery retry; per-section try wraps with fail-loud log) /
  41 (Asia/Shanghai for target_date) / 43 (Celery task, schtask-equivalent
  hardening: explicit timeout via soft_time_limit/time_limit decorator + per-task
  try/except + JSON write atomicity via tmp-rename).

关联 ADR: ADR-DRAFT row to be promoted post-merge (no standalone ADR commit per
  v5 prompt §4 HARD BAN — ADR row co-ships with code or trails as REGISTRY-only
  promote).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.services.db import get_sync_conn
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.report_generate")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

# Reviewer P2-8 noted: reports/ dir grows unbounded (~36k files/year @ 100 strategies
# daily cadence). Out-of-scope for iter 30; future Celery Beat cleanup task should
# enforce retention (e.g. keep latest N per (sid, mode) + drop > 90 days). Tracked
# as future-iter candidate; not blocking this PR.


def _today_shanghai() -> date:
    """Returns current Asia/Shanghai date (timezone-aware).

    Reports are end-of-day artifacts; using SH-date avoids UTC-vs-SH boundary
    drift around midnight (沿用 daily_metrics_extract_tasks._today_shanghai 体例).
    """
    return datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai")).date()


def _report_path(strategy_id: str, target_date: date, execution_mode: str) -> Path:
    """Filesystem path for a report artifact.

    Pattern: reports/{strategy_id}_{date_iso}_{mode}.json
    Existing reports/ dir already has unrelated files; this namespace is
    distinct via the (sid, date, mode) tuple in filename.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_sid = strategy_id.replace("/", "_").replace("\\", "_")
    return REPORTS_DIR / f"{safe_sid}_{target_date.isoformat()}_{execution_mode}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically via tmp-rename (反 partial-write on crash).

    Reader (GET /latest endpoint) may concurrent-read; tmp-rename ensures
    the destination path always contains a complete JSON document. Critical
    when Celery worker crashes mid-write — partial file would corrupt the
    artifact namespace silently.
    """
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        # os.replace is atomic across POSIX + Windows (vs os.rename which fails on Win if dst exists)
        os.replace(tmp_path, str(path))
    except Exception:
        # Cleanup tmp on failure (反 reports/.{name}.{rand}.tmp 累积 silent debt).
        # silent_ok: cleanup-best-effort; tmp already gone (race) or perms issue.
        with suppress(OSError):
            os.unlink(tmp_path)
        raise


def _fetch_rolling_stats(conn, strategy_id: str, execution_mode: str, lookback: int) -> dict | None:
    """Sync version of PerformanceRepository.get_rolling_stats (sustained pattern).

    Async repo is asyncio-only; Celery task is sync. Re-implementing the query
    here is cleaner than asyncio.run() in task body (反 nested-event-loop).
    Returns same shape as the async repo for consumer parity.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT nav, daily_return
               FROM performance_series
               WHERE strategy_id = CAST(%s AS uuid) AND execution_mode = %s
               ORDER BY trade_date DESC LIMIT %s""",
            (strategy_id, execution_mode, lookback),
        )
        rows = cur.fetchall()
    finally:
        cur.close()

    if not rows:
        return None

    import numpy as np

    navs = [float(r[0]) for r in rows]
    rets = [float(r[1]) if r[1] is not None else 0.0 for r in rows]
    n = len(rets)
    daily_mean = float(np.mean(rets))
    daily_std = float(np.std(rets, ddof=1)) if n > 1 else 0.0
    sharpe = daily_mean / daily_std * float(np.sqrt(252)) if daily_std > 0 else 0.0

    # MDD: navs is DESC-by-trade_date; reverse-traverse for time-forward peak tracking.
    # Sustained quant-review fix from PerformanceRepository.get_rolling_stats:104-110
    # (peak starts from earliest NAV, not latest).
    peak = navs[-1]
    max_dd = 0.0
    for nav in reversed(navs):
        peak = max(peak, nav)
        max_dd = min(max_dd, nav / peak - 1)

    # Key shape parity with PerformanceRepository.get_rolling_stats:111-117.
    # Reviewer P1-3: docstring claims parity; use `days` (not `lookback_days`).
    return {
        "days": n,
        "sharpe": round(sharpe, 4),
        "mdd": round(max_dd, 4),
        "total_return": round(navs[0] / navs[-1] - 1, 6) if navs[-1] > 0 else 0.0,
        "latest_nav": round(navs[0], 4),
    }


def _fetch_latest_nav_row(conn, strategy_id: str, execution_mode: str) -> dict | None:
    """Sync fetch of latest performance_series row (mirrors get_latest_nav shape)."""
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT trade_date, nav, daily_return, cumulative_return, drawdown,
                      cash_ratio, cash, position_count, turnover, benchmark_nav
               FROM performance_series
               WHERE strategy_id = CAST(%s AS uuid) AND execution_mode = %s
               ORDER BY trade_date DESC LIMIT 1""",
            (strategy_id, execution_mode),
        )
        row = cur.fetchone()
    finally:
        cur.close()

    if not row:
        return None

    return {
        "trade_date": row[0].isoformat() if row[0] else None,
        "nav": float(row[1]) if row[1] is not None else 0.0,
        "daily_return": float(row[2]) if row[2] is not None else 0.0,
        "cumulative_return": float(row[3]) if row[3] is not None else 0.0,
        "drawdown": float(row[4]) if row[4] is not None else 0.0,
        "cash_ratio": float(row[5]) if row[5] is not None else 0.0,
        "cash": float(row[6]) if row[6] is not None else 0.0,
        "position_count": int(row[7]) if row[7] is not None else 0,
        "turnover": float(row[8]) if row[8] is not None else 0.0,
        "benchmark_nav": float(row[9]) if row[9] is not None else 0.0,
    }


def _fetch_recent_trades(
    conn, strategy_id: str, execution_mode: str, limit: int = 20
) -> list[dict]:
    """Sync fetch of recent trade_log rows for the (sid, mode) tuple.

    Reviewer P0-1 fix: trade_log column names are `direction` (NOT `side`) and
    `fill_price` (NOT `price`). DDL canonical source = docs/QUANTMIND_V2_DDL_FINAL.sql
    §trade_log; sustained pattern across 5 other `FROM trade_log` callsites in
    backend/. JSON payload key uses canonical column name for parity.
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT trade_date, code, direction, quantity, fill_price,
                      signal_price, reject_reason
               FROM trade_log
               WHERE strategy_id = CAST(%s AS uuid) AND execution_mode = %s
               ORDER BY trade_date DESC, code ASC
               LIMIT %s""",
            (strategy_id, execution_mode, limit),
        )
        rows = cur.fetchall()
    finally:
        cur.close()

    return [
        {
            "trade_date": r[0].isoformat() if r[0] else None,
            "code": r[1],
            "direction": r[2],
            "quantity": int(r[3]) if r[3] is not None else 0,
            "fill_price": float(r[4]) if r[4] is not None else None,
            "signal_price": float(r[5]) if r[5] is not None else None,
            "reject_reason": r[6],
        }
        for r in rows
    ]


@celery_app.task(
    name="app.tasks.report_tasks.generate_performance_report",
    soft_time_limit=30,  # 30s soft — DB aggregation typically <2s
    time_limit=60,  # 60s hard kill (反 stuck task blocking worker)
)
def generate_performance_report(
    strategy_id: str,
    execution_mode: str = "paper",
) -> dict[str, Any]:
    """Aggregate strategy performance into a JSON artifact.

    Pulls rolling_stats(60d) + latest_nav row + recent 20 trade_log entries
    for the (strategy_id, execution_mode) tuple, builds a structured payload,
    writes to reports/{sid}_{date}_{mode}.json atomically.

    Args:
        strategy_id: Strategy UUID string. Empty raises ValueError (caller
            should fall back to settings.PAPER_STRATEGY_ID before dispatch).
        execution_mode: "paper" | "live". Defaults "paper".

    Returns:
        {
            "ok": True,
            "report_path": str (absolute path),
            "strategy_id": str,
            "execution_mode": str,
            "target_date": str (ISO),
            "data_available": bool (False if 0 rows in performance_series),
            "summary": {sharpe, mdd, total_return, latest_nav} | None,
        }

    Raises:
        ValueError: strategy_id empty.
        psycopg2.Error: any DB error propagates to Celery retry.
        OSError: filesystem write errors propagate (反 silent_ok on artifact loss).
    """
    if not strategy_id:
        raise ValueError("strategy_id required (caller must default to PAPER_STRATEGY_ID)")
    if execution_mode not in ("paper", "live"):
        raise ValueError(f"execution_mode must be 'paper' or 'live', got {execution_mode!r}")

    target_date = _today_shanghai()
    out_path = _report_path(strategy_id, target_date, execution_mode)

    # Sustained pre-assign conn=None (8c-partial pattern from daily_metrics_extract).
    conn = None
    try:
        conn = get_sync_conn()
        rolling = _fetch_rolling_stats(conn, strategy_id, execution_mode, lookback=60)
        latest = _fetch_latest_nav_row(conn, strategy_id, execution_mode)
        trades = _fetch_recent_trades(conn, strategy_id, execution_mode, limit=20)
        # Read-only task — explicit no-op commit not required, but call for
        # symmetry with sustained sync-task pattern (released-snapshot consistency).
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()

    data_available = bool(latest)
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "strategy_id": strategy_id,
        "execution_mode": execution_mode,
        "target_date_shanghai": target_date.isoformat(),
        "data_available": data_available,
        "summary": rolling,  # None if 0 rows in performance_series
        "latest_nav": latest,  # None if 0 rows
        "recent_trades": trades,  # [] if 0 rows
        "trades_count": len(trades),
        "schema_version": "1.0",
    }

    _atomic_write_json(out_path, payload)

    logger.info(
        "[report-generate] sid=%s mode=%s date=%s data_available=%s trades=%d -> %s",
        strategy_id,
        execution_mode,
        target_date,
        data_available,
        len(trades),
        out_path,
    )

    return {
        "ok": True,
        "report_path": str(out_path),
        "strategy_id": strategy_id,
        "execution_mode": execution_mode,
        "target_date": target_date.isoformat(),
        "data_available": data_available,
        "summary": rolling,
    }


def latest_report_path(strategy_id: str, execution_mode: str = "paper") -> Path | None:
    """Find the most-recent report JSON for (strategy_id, execution_mode).

    Used by the GET /api/reports/{sid}/latest endpoint. Returns None if no
    matching artifact exists (caller should 404).

    Resolves by mtime; date in filename is informational. Files for OTHER
    (sid, mode) tuples are filtered out by prefix match.
    """
    if not REPORTS_DIR.exists():
        return None
    safe_sid = strategy_id.replace("/", "_").replace("\\", "_")
    prefix = f"{safe_sid}_"
    suffix = f"_{execution_mode}.json"
    candidates = [
        p for p in REPORTS_DIR.glob(f"{prefix}*{suffix}") if p.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


__all__ = [
    "generate_performance_report",
    "latest_report_path",
    "REPORTS_DIR",
]
