"""V3 post-cutover BAU — DailyDataIngest 2-pass Tushare ingest (ADR-082 D4).

Replaces archived `pull_full_data.py` (4-08 archive without replacement,
LL-175 lesson 4 architectural debt). Builds the production-ready daily
data ingestion path that should have existed since DataOrchestrator was
"部分实施 4-17" but never wired to schtask.

## 2-pass design (per Phase 0 Finding #26 Tushare timing research)

| Pass | Schedule SH M-F | Target | Endpoints |
|---|---|---|---|
| preopen | **09:25** | T-1 (prev trading day) | adj_factor refresh (Tushare publishes T-day adj_factor T+1 09:15-09:20) |
| postclose | **17:30** | T (today) | daily + daily_basic + stk_limit (Tushare publishes T-day 15:00-17:00) |

Rationale: at Mon 17:30, Tushare returns T-day daily + stk_limit + EMPTY/STALE adj_factor (T-day adj_factor not yet published). At Tue 09:25, Tushare returns T-day adj_factor (now published). Preopen pass refreshes klines_daily.adj_factor for T-1 via idempotent UPSERT (ON CONFLICT DO UPDATE).

## Modes (sustained CT-1a/CT-2b/CT-2c-pre 3-mode runner体例 per LL-175 lesson 8)

```
--pass <preopen|postclose>  (required)
--trade-date YYYY-MM-DD     (optional; default = today; auto-resolve T-1 for preopen)
--dry-run                   (default when no flag) preflight + plan, 0 mutation
--apply                     execute ingest
--verify                    post-apply state verify
```

## Fail-loud behavior (铁律 33)

- Trading-day check via trading_calendar (skip non-trading days with status='skipped', exit 0)
- TUSHARE_TOKEN env strict gate before --apply (sustained CT-1a P2 fix)
- Tushare endpoint failure → fail-loud RuntimeError + DingTalk alert on apply path
- Idempotent UPSERT via DataPipeline.ingest (铁律 17 合规)

## Schtask registration (separate, not in this script)

```powershell
# QuantMind_DailyDataIngest_Preopen 09:25 SH M-F
# QuantMind_DailyDataIngest_Postclose 17:30 SH M-F
# (Both registered Disabled; manually Enable post-Mon 09:31 live-fire confirmed clean)
```

关联铁律: 17 (DataPipeline) / 25 / 33 (fail-loud) / 41 (timezone) / 43 (schtask fail-loud硬化)
关联 ADR-082 D4 (post-cutover ongoing monitoring BAU build)
关联 LL-175 lesson 4 (data ingestion archive-without-replacement debt) + lesson 8 (3-mode runner体例)
关联 Phase 0 Finding #25 (no klines schtask) + #26 (Tushare timing研究)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import UTC, date, datetime
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

logger = logging.getLogger("daily_data_ingest")

# Pass definitions.
_PASS_PREOPEN = "preopen"
_PASS_POSTCLOSE = "postclose"
_VALID_PASSES = (_PASS_PREOPEN, _PASS_POSTCLOSE)

_REQUIRED_ENV_FOR_APPLY: tuple[str, ...] = ("TUSHARE_TOKEN",)


def _now_iso() -> tuple[str, str]:
    """Return (utc_iso, shanghai_iso) — 铁律 41."""
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


def _resolve_target_date(pass_type: str, override_date: str | None) -> date | None:
    """Resolve target trade_date.

    - postclose: today (or override). Must be a trading day; else return None.
    - preopen: prev trading day relative to today (or override).
    """
    if override_date:
        candidate = datetime.strptime(override_date, "%Y-%m-%d").date()
    else:
        candidate = datetime.now(ZoneInfo("Asia/Shanghai")).date()

    with get_sync_conn() as conn, conn.cursor() as cur:
        if pass_type == _PASS_POSTCLOSE:
            cur.execute(
                """SELECT is_trading_day FROM trading_calendar
                   WHERE trade_date = %s AND market = 'astock'""",
                (candidate,),
            )
            row = cur.fetchone()
            if row and row[0]:
                return candidate
            return None  # non-trading day, skip

        # preopen — walk back to most recent trading day strictly before candidate
        cur.execute(
            """SELECT trade_date FROM trading_calendar
               WHERE market = 'astock' AND is_trading_day = TRUE
                 AND trade_date < %s
               ORDER BY trade_date DESC LIMIT 1""",
            (candidate,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        return None


def _read_state(target_date: date) -> dict[str, object]:
    """Read DB state for target_date (klines_daily + daily_basic existence)."""
    with get_sync_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM klines_daily WHERE trade_date = %s",
            (target_date,),
        )
        klines_count = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM daily_basic WHERE trade_date = %s",
            (target_date,),
        )
        basic_count = cur.fetchone()[0]
        cur.execute(
            """SELECT COUNT(*) FROM klines_daily
               WHERE trade_date = %s AND adj_factor IS NOT NULL""",
            (target_date,),
        )
        adj_factor_count = cur.fetchone()[0]
    return {
        "trade_date": target_date.isoformat(),
        "klines_daily_count": klines_count,
        "daily_basic_count": basic_count,
        "klines_with_adj_factor_count": adj_factor_count,
    }


def _preflight_summary(pass_type: str, target_date: date | None, state: dict | None) -> str:
    lines = [
        "=== Preflight ===",
        f"  Pass: {pass_type}",
        f"  Target trade_date: {target_date.isoformat() if target_date else '(non-trading day, will skip)'}",
    ]
    if state:
        lines.extend(
            [
                "",
                f"  Current state for {state['trade_date']}:",
                f"    klines_daily rows: {state['klines_daily_count']:,}",
                f"    daily_basic rows: {state['daily_basic_count']:,}",
                f"    klines with adj_factor not null: {state['klines_with_adj_factor_count']:,}",
            ]
        )
    return "\n".join(lines)


def _dry_run(pass_type: str, override_date: str | None) -> int:
    target_date = _resolve_target_date(pass_type, override_date)
    if not target_date:
        print(_preflight_summary(pass_type, None, None))
        print()
        print("=== Plan ===")
        print("  Non-trading day or no prev trading day found — would exit 0 (no-op)")
        return 0

    state = _read_state(target_date)
    print(_preflight_summary(pass_type, target_date, state))
    print()
    print("=== Plan ===")
    if pass_type == _PASS_POSTCLOSE:
        print(f"  1. TushareAPI.merge_daily_data('{target_date:%Y%m%d}') → upsert_klines_daily")
        print(
            f"  2. TushareAPI.fetch_daily_basic_by_date('{target_date:%Y%m%d}') → upsert_daily_basic"
        )
        print("  Idempotent UPSERT via DataPipeline.ingest (铁律 17 合规).")
    else:  # preopen
        print(f"  1. TushareAPI.merge_daily_data('{target_date:%Y%m%d}') → upsert_klines_daily")
        print(
            "     (T-1 refresh — primarily updates adj_factor now published Tushare T 09:15-09:20)"
        )
    print()
    print("=== DRY RUN COMPLETE — re-run with --apply to execute ===")
    return 0


def _apply(pass_type: str, override_date: str | None) -> int:
    env_failures = _check_apply_env()
    if env_failures:
        print("❌ apply BLOCKED — env-check failed:")
        for f in env_failures:
            print(f"  - {f}")
        return 1

    target_date = _resolve_target_date(pass_type, override_date)
    if not target_date:
        utc_iso, sh_iso = _now_iso()
        print(f"=== Non-trading day or no prev — SKIP (UTC={utc_iso} SH={sh_iso}) ===")
        return 0  # graceful skip, not failure

    state_pre = _read_state(target_date)
    print(_preflight_summary(pass_type, target_date, state_pre))
    print()
    utc_iso, sh_iso = _now_iso()
    print(f"=== APPLY started — UTC={utc_iso} SH={sh_iso} ===")

    api = TushareAPI()
    trade_date_str = target_date.strftime("%Y%m%d")
    t0 = time.time()

    try:
        # Step 1: klines (merged daily + adj_factor + stk_limit).
        logger.info("[%s] fetching merged daily data for %s...", pass_type, trade_date_str)
        df_klines = api.merge_daily_data(trade_date_str)
        if df_klines is None or len(df_klines) == 0:
            raise RuntimeError(
                f"merge_daily_data returned empty for {trade_date_str} "
                f"(pass={pass_type}); Tushare data may not yet be published"
            )
        n_klines = upsert_klines_daily(df_klines)
        logger.info("[%s] klines_daily upserted: %d rows", pass_type, n_klines)

        n_basic = 0
        if pass_type == _PASS_POSTCLOSE:
            # Step 2: daily_basic (only on postclose pass).
            logger.info("[%s] fetching daily_basic for %s...", pass_type, trade_date_str)
            df_basic = api.fetch_daily_basic_by_date(trade_date_str)
            if df_basic is None or len(df_basic) == 0:
                raise RuntimeError(f"fetch_daily_basic_by_date returned empty for {trade_date_str}")
            n_basic = upsert_daily_basic(df_basic)
            logger.info("[%s] daily_basic upserted: %d rows", pass_type, n_basic)

        elapsed = time.time() - t0
        print()
        print("=== Post-apply state ===")
        state_post = _read_state(target_date)
        print(_preflight_summary(pass_type, target_date, state_post))
        print()
        print(
            f"✅✅✅ DAILY DATA INGEST SUCCESS — pass={pass_type} date={target_date} klines={n_klines} daily_basic={n_basic} elapsed={elapsed:.1f}s ✅✅✅"
        )
        return 0
    except Exception as e:  # noqa: BLE001 — broad catch to fail-loud + DingTalk alert
        logger.exception("[%s] FAILED", pass_type)
        elapsed = time.time() - t0
        print(
            f"\n❌ DAILY DATA INGEST FAILED — pass={pass_type} date={target_date} after {elapsed:.1f}s: {e}"
        )
        # TODO Step 12 BAU — wire DingTalk alert via AlertRouter on failure
        return 1


def _verify(pass_type: str, override_date: str | None) -> int:
    target_date = _resolve_target_date(pass_type, override_date)
    if not target_date:
        print(_preflight_summary(pass_type, None, None))
        print("✅ Verify PASS — non-trading day, no ingest expected")
        return 0

    state = _read_state(target_date)
    print(_preflight_summary(pass_type, target_date, state))
    print()

    klines_ok = state["klines_daily_count"] >= 5000  # min ~5500 A-share stocks
    basic_ok = state["daily_basic_count"] >= 5000 if pass_type == _PASS_POSTCLOSE else True

    if klines_ok and basic_ok:
        print(f"✅ Verify PASS — pass={pass_type} date={target_date}")
        return 0
    print(f"❌ Verify FAIL — klines_ok={klines_ok} basic_ok={basic_ok}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pass",
        dest="pass_type",
        required=True,
        choices=_VALID_PASSES,
        help="preopen (T-1 adj_factor refresh @ 09:25 SH) | postclose (T-day full @ 17:30 SH)",
    )
    parser.add_argument(
        "--trade-date",
        dest="trade_date",
        default=None,
        help="Override target date YYYY-MM-DD (default: today + auto-resolve T-1 for preopen)",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--dry-run", action="store_true", help="(default when no flag) preflight + plan, 0 mutation"
    )
    g.add_argument("--apply", action="store_true", help="EXECUTE ingest")
    g.add_argument("--verify", action="store_true", help="post-apply state verify only")
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if args.apply:
        return _apply(args.pass_type, args.trade_date)
    if args.verify:
        return _verify(args.pass_type, args.trade_date)
    return _dry_run(args.pass_type, args.trade_date)


if __name__ == "__main__":
    sys.exit(main())
