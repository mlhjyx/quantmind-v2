"""CalendarProvider — facade wrapping TradingDayChecker + PT day counter.

设计 (Audit Section X §39):
    - Wraps `backend/engines/trading_day_checker.py` TradingDayChecker (existing 4-layer fallback)
    - Adds pt_day_counter / n_trading_days_between (Dashboard "PT Day X/Y" wire backing)
    - Singleton via get_calendar() (沿用 alert.py / llm bootstrap.py 体例)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# P2 fix (python-reviewer Session 57+1 round-2): named magic-number constants.
# 沿用 ADR-022 append-only sediment naming 体例.
#
# _MAX_SEARCH_DAYS: prev_trading_day 回溯上限. A 股最长连续非交易区间 ~14d (春节);
# 30d cap 留 2x buffer. 超过 → 真异常 (data freshness / TradingDayChecker 故障),
# fail-loud 反 silent heuristic fallback (旧 pattern 续走 weekday() ≥ 5 reduction).
_MAX_SEARCH_DAYS: int = 30
# _MAX_CALENDAR_RANGE_DAYS: n_trading_days_between 区间上限. PT 60d scope 真值 buffer.
# 多年 range 走 _MAX_CALENDAR_RANGE_DAYS 显式 raise → 反 silent truncation 误返.
_MAX_CALENDAR_RANGE_DAYS: int = 366


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
        """前一个交易日 (不含 before_date 本身).

        P2 fix (python-reviewer Session 57+1 round-2): 反 silent heuristic fallback.
        Raise RuntimeError if _MAX_SEARCH_DAYS 内未找到 trading day → 真异常
        (TradingDayChecker 故障 OR data freshness issue), 不允许 silent weekday()
        reduction (可能返非交易日, 反 铁律 33 fail-loud).
        """
        d = (before_date or date.today()) - timedelta(days=1)
        for _ in range(_MAX_SEARCH_DAYS):
            if self.is_trading_day(d):
                return d
            d -= timedelta(days=1)
        raise RuntimeError(
            f"prev_trading_day: 回溯 {_MAX_SEARCH_DAYS} 天仍未找到 trading day "
            f"(from {before_date}). 真异常: TradingDayChecker 或 data 异常."
        )

    def n_trading_days_between(self, d1: date, d2: date) -> int:
        """区间 [d1, d2] 含两端的交易日数.

        P2 fix (python-reviewer Session 57+1 round-2): 反 silent truncation.
        Raise ValueError if range > _MAX_CALENDAR_RANGE_DAYS → 真值错返
        (多年 range 默认 365 cap 旧 pattern silent truncate, 误算误差).

        Args:
            d1: 起始日 (含).
            d2: 结束日 (含).

        Returns:
            交易日总数. d1 > d2 时返 0.

        Raises:
            ValueError: range (d2 - d1) > _MAX_CALENDAR_RANGE_DAYS days.
                Caller 需 batch 分段 OR 显式 raise cap.
        """
        if d1 > d2:
            return 0
        range_days = (d2 - d1).days
        if range_days > _MAX_CALENDAR_RANGE_DAYS:
            raise ValueError(
                f"n_trading_days_between: range {range_days} days > "
                f"_MAX_CALENDAR_RANGE_DAYS={_MAX_CALENDAR_RANGE_DAYS}. "
                f"PT 60d scope 真值上限. 多年 range caller 需 batch 分段."
            )
        count = 0
        d = d1
        for _ in range(_MAX_CALENDAR_RANGE_DAYS + 1):
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
