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

import os
import threading
from datetime import date
from typing import Any

from .provider import CalendarProvider

__all__ = ["get_calendar", "reset_calendar", "CalendarProvider"]

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
