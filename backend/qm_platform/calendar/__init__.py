"""qm_platform.calendar — Trading Calendar SSOT (Audit Section X §39 + Finding #7 unblock).

归属: Framework #Calendar (新增, V3 §17 + Section X §39 calendar SSOT).

设计目标 (Audit findings):
    - 反 Beat schedule / schtask 跨脚本 calendar 漂移 (LL-181 lesson)
    - 反 Dashboard hardcoded "PT Day 3/60" (Frontend Design v3 §6 #7 finding)
    - 单 SSOT singleton — schtask + Beat + frontend 全部 reference 同一 source

公共 API (caller 唯一 sanctioned 入口):
    from backend.qm_platform.calendar import get_calendar

    cal = get_calendar()
    cal.is_trading_day(date.today())  # bool
    cal.next_trading_day(date.today())  # date
    cal.prev_trading_day(date.today())  # date
    cal.pt_day_counter()  # (current_day, total_days)
    cal.n_trading_days_between(d1, d2)  # int

实现:
    - 包装 existing backend/engines/trading_day_checker.py TradingDayChecker (4-layer fallback)
    - 添加 pt_day_counter (PT 进度 sprint 计数, 默认 start=2026-03-15)
    - 添加 n_trading_days_between (区间交易日数, 用于 Dashboard "PT Day X/Y" wire)

关联:
- Audit Section X §39 Beat/Schtask Calendar SSOT 真值落地
- Frontend Design v3 #7 hardcoded "PT Day 3/60" → calendar SSOT 接通
- LL-181 sediment (Beat schedule 漂移 lesson)
"""

from __future__ import annotations

import contextlib
import os
import threading
from datetime import date
from typing import Any

from .provider import CalendarProvider

__all__ = [
    "get_calendar",
    "reset_calendar",
    "CalendarProvider",
    "is_trading_day_today_or_skip",
    "parse_pt_start_date",
    "parse_pt_total_days",
]

_calendar_singleton: CalendarProvider | None = None
_singleton_lock = threading.Lock()


def get_calendar(*, conn_factory: Any = None) -> CalendarProvider:
    """Lazy-init singleton CalendarProvider.

    Args:
        conn_factory: 可选 conn factory (走 TradingDayChecker Layer 3 DB query).
                      None 时 fallback Layer 4 heuristic (周末=非交易日).

    Returns:
        CalendarProvider singleton.
    """
    global _calendar_singleton
    if _calendar_singleton is not None:
        return _calendar_singleton
    with _singleton_lock:
        if _calendar_singleton is None:
            _calendar_singleton = CalendarProvider(conn_factory=conn_factory)
    return _calendar_singleton


def reset_calendar() -> None:
    """重置 singleton (test isolation 真依赖, 沿用 alert.py 体例)."""
    global _calendar_singleton
    with _singleton_lock:
        _calendar_singleton = None


def parse_pt_start_date() -> date:
    """从 .env PT_START_DATE 推导 PT 开始日期, fallback 默认 2026-03-15.

    Default 来源: SHUTDOWN_NOTICE_2026_04_30 §0 — PT 4-29 user 决议清仓前
    已运行约 6 周, 假定 start=2026-03-15 (placeholder, .env override 真值时生效).

    铁律-34-exception (P3 audit Session 57+1 round-4): calendar module 设计为
    loadable outside backend.app context (e.g. unit test isolation / scripts
    standalone import), 不依赖 app.config.settings. 直读 os.environ 是**故意**
    保持 module-level loose-coupling, 反 反向 import (backend.qm_platform → backend.app).
    """
    raw = os.environ.get("PT_START_DATE", "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date(2026, 3, 15)


def parse_pt_total_days() -> int:
    """PT 计划总天数 (60 days standard, .env PT_TOTAL_DAYS override)."""
    raw = os.environ.get("PT_TOTAL_DAYS", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 60


def is_trading_day_today_or_skip(*, logger: Any = None, conn_factory: Any = None) -> bool:
    """H4 fix (Audit Section X §39 + ISSUES_PENDING_REGISTRY §4 A5/§9 H4):
    Celery Beat / Windows Schtask task wrapper helper — checks if today is
    trading day, returns False (caller should `return early`) on non-trading day.

    Usage pattern (Beat task body):
        from backend.qm_platform.calendar import is_trading_day_today_or_skip

        @celery_app.task(name="risk.daily-check")
        def risk_daily_check():
            if not is_trading_day_today_or_skip():
                return  # silent skip non-trading day
            # ... real task body ...

    Schtask Python wrapper:
        from backend.qm_platform.calendar import is_trading_day_today_or_skip
        if not is_trading_day_today_or_skip():
            sys.exit(0)  # quiet exit, schtask LastResult=0

    Reason 沿用 (反 silent skip):
        crontab day_of_week='1-5' 仅过滤周末, A 股 ~15 法定假日/年 仍空触发.

    Layer 3 (Plan 1.5): the helper runs a conn-backed TradingDayChecker so the local
    `trading_calendar` DB table (Layer 3) answers when the Tushare API is unreachable.
    Without Layer 3 the 4-layer chain degrades to a weekday heuristic that CANNOT
    detect 法定节假日 — defeating the gate's purpose (LL-181). A short-lived conn is
    opened from `app.services.db.get_sync_conn` (lazy) and closed after the single
    check; if the DB is unavailable (or under unit-test isolation) the helper degrades
    gracefully to the conn-less Tushare→heuristic path.

    Args:
        logger: optional logger (stdlib logging.Logger or structlog BoundLogger)
            to record the skip event. Every production Beat/schtask caller passes
            a stdlib logging.Logger — the skip log is pre-formatted accordingly.
        conn_factory: optional callable returning a psycopg2 connection (used for
            TradingDayChecker Layer 3). None → lazy `app.services.db.get_sync_conn`;
            if that is unavailable the check degrades to conn-less (Tushare→heuristic).

    Returns:
        True if today is trading day → caller proceeds.
        False if non-trading day → caller should return/exit early.
    """
    today = date.today()
    is_td, reason = _resolve_trading_day(today, conn_factory, logger)
    if not is_td and logger is not None:
        # Logger-agnostic skip log: a single pre-formatted string works with both
        # stdlib logging.Logger and structlog BoundLogger. Every Beat/schtask caller
        # passes a stdlib logger — `logger.info(msg, today=..., reason=...)` would
        # raise TypeError on a stdlib Logger (它不接受任意 kwargs).
        logger.info(
            f"Beat/schtask skip (non-trading day): today={today.isoformat()} reason={reason}"
        )
    return is_td


def _default_conn_factory() -> Any:
    """Lazy `app.services.db.get_sync_conn`, or None if unavailable.

    Returns None under unit-test isolation / when `backend.app` is not importable —
    the caller then degrades to a conn-less trading-day check. 铁律-34-exception:
    same loose-coupling rationale as parse_pt_start_date (the calendar module must
    stay loadable outside the backend.app context).
    """
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415

        return get_sync_conn
    except Exception:
        # Deliberately broad: ANY failure obtaining the conn factory (ImportError
        # under test isolation, or a module-level config error) → return None so the
        # caller degrades to a conn-less check. Supports the never-raises contract.
        return None


def _resolve_trading_day(today: date, conn_factory: Any, logger: Any) -> tuple[bool, str]:
    """Resolve today's trading-day verdict with TradingDayChecker Layer 3 (local
    `trading_calendar` DB table) live, so a Tushare outage falls back to the DB
    table instead of the holiday-blind weekday heuristic.

    Degrades to the conn-less `get_calendar()` path (Tushare→heuristic) if no DB
    connection can be obtained — never raises (the gate must always return a verdict).
    """
    cf = conn_factory or _default_conn_factory()
    if cf is None:
        return get_calendar().is_trading_day_with_reason(today)

    conn = None
    try:
        conn = cf()
    except Exception as exc:
        if logger is not None:
            logger.warning(
                f"calendar gate: DB conn unavailable, degrading to conn-less "
                f"trading-day check (Layer 3 skipped): {exc}"
            )
        return get_calendar().is_trading_day_with_reason(today)

    try:
        # Lazy import — keep the calendar module loadable when engines/ is absent.
        try:
            from engines.trading_day_checker import TradingDayChecker  # noqa: PLC0415
        except ImportError:
            from backend.engines.trading_day_checker import (  # noqa: PLC0415
                TradingDayChecker,
            )
        # Note: when Tushare succeeds (Layer 2), TradingDayChecker._upsert_local
        # commits an idempotent single-row UPSERT to trading_calendar on this conn
        # (self-healing cache) before we close it — the gate is not a pure read.
        return TradingDayChecker(conn=conn).is_trading_day(today)
    except Exception as exc:
        # 铁律 33 fail-safe: the gate MUST always return a verdict (docstring
        # contract). A double-ImportError or any TradingDayChecker runtime failure
        # degrades to the conn-less get_calendar() path rather than crashing the
        # Beat task.
        if logger is not None:
            logger.warning(
                f"calendar gate: TradingDayChecker failed, degrading to conn-less "
                f"trading-day check: {exc}"
            )
        return get_calendar().is_trading_day_with_reason(today)
    finally:
        if conn is not None:
            # silent_ok: conn close failure must not break the gate
            with contextlib.suppress(Exception):
                conn.close()
