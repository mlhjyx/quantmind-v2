"""CalendarProvider — facade wrapping TradingDayChecker + PT day counter.

设计 (Audit Section X §39):
    - Wraps `backend/engines/trading_day_checker.py` TradingDayChecker (existing 4-layer fallback)
    - Adds pt_day_counter / n_trading_days_between (Dashboard "PT Day X/Y" wire backing)
    - Singleton via get_calendar() (沿用 alert.py / llm bootstrap.py 体例)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


class CalendarProvider:
    """Trading calendar SSOT facade."""

    def __init__(self, *, conn_factory: Any = None):
        """初始化.

        Args:
            conn_factory: 可选 conn factory. None 时 TradingDayChecker 走 Layer 4 heuristic.
        """
        self._conn_factory = conn_factory
        self._checker: Any = None  # lazy-init to avoid eager import

    def _get_checker(self) -> Any:
        """Lazy-init TradingDayChecker (反 eager DB connect on module load)."""
        if self._checker is not None:
            return self._checker

        # Lazy import — keep calendar module loadable even when engines/ unavailable
        try:
            from engines.trading_day_checker import TradingDayChecker
        except ImportError:
            try:
                from backend.engines.trading_day_checker import TradingDayChecker
            except ImportError as exc:
                raise RuntimeError(
                    "TradingDayChecker 不可加载, calendar provider 走 Layer 4 heuristic 也需该模块"
                ) from exc

        conn = self._conn_factory() if self._conn_factory else None
        self._checker = TradingDayChecker(conn=conn)
        return self._checker

    def is_trading_day(self, check_date: date | None = None) -> bool:
        """判断是否交易日 (走 TradingDayChecker 4-layer fallback)."""
        is_td, _ = self._get_checker().is_trading_day(check_date)
        return is_td

    def is_trading_day_with_reason(self, check_date: date | None = None) -> tuple[bool, str]:
        """is_trading_day + reason (debug 用)."""
        return self._get_checker().is_trading_day(check_date)

    def next_trading_day(self, after_date: date | None = None) -> date:
        """下一个交易日 (不含 after_date 本身)."""
        return self._get_checker().next_trading_day(after_date)

    def prev_trading_day(self, before_date: date | None = None) -> date:
        """前一个交易日 (不含 before_date 本身)."""
        d = (before_date or date.today()) - timedelta(days=1)
        for _ in range(30):
            if self.is_trading_day(d):
                return d
            d -= timedelta(days=1)
        # Fallback heuristic: 前一工作日
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d

    def n_trading_days_between(self, d1: date, d2: date) -> int:
        """区间 [d1, d2] 含两端的交易日数.

        Args:
            d1: 起始日 (含).
            d2: 结束日 (含).

        Returns:
            交易日总数. d1 > d2 时返 0.
        """
        if d1 > d2:
            return 0
        count = 0
        d = d1
        # Cap loop at 366 days to avoid infinite (safe for PT 60-day scope)
        for _ in range(366):
            if d > d2:
                break
            if self.is_trading_day(d):
                count += 1
            d += timedelta(days=1)
        return count

    def pt_day_counter(
        self,
        *,
        start_date: date | None = None,
        total_days: int | None = None,
        today: date | None = None,
    ) -> dict[str, Any]:
        """PT 进度计数 (Dashboard "PT Day X/Y" wire backing).

        Args:
            start_date: PT 开始日期. None 走 parse_pt_start_date() (.env PT_START_DATE / default 2026-03-15)
            total_days: PT 计划总天数. None 走 parse_pt_total_days() (.env PT_TOTAL_DAYS / default 60)
            today: 今天日期 (test 注入). None = date.today().

        Returns:
            dict 含 current_day / total_days / start_date / today / completion_pct.
        """
        # Lazy import to avoid circular
        from . import parse_pt_start_date, parse_pt_total_days

        _start = start_date or parse_pt_start_date()
        _total = total_days or parse_pt_total_days()
        _today = today or date.today()

        if _today < _start:
            current = 0
        else:
            current = self.n_trading_days_between(_start, _today)

        completion_pct = round(100.0 * current / max(_total, 1), 1) if _total > 0 else 0.0

        return {
            "current_day": current,
            "total_days": _total,
            "start_date": _start.isoformat(),
            "today": _today.isoformat(),
            "completion_pct": completion_pct,
            "label": f"PT Day {current}/{_total}",
        }
