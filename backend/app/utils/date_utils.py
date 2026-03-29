"""日期/交易日历工具函数。

集中管理交易日判断、日期范围生成等功能。
原始实现在 services/trading_calendar.py，此处提供统一入口。

使用:
    from app.utils.date_utils import is_trading_day, get_next_trading_day
"""

from __future__ import annotations

from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Re-export from services/trading_calendar.py (向后兼容)
# ---------------------------------------------------------------------------
try:
    from app.services.trading_calendar import (
        acquire_lock,
        get_next_trading_day,
        get_prev_trading_day,
        is_trading_day,
    )
except ImportError:
    # Fallback: 当trading_calendar不可用时提供占位
    acquire_lock = None  # type: ignore[assignment]
    get_next_trading_day = None  # type: ignore[assignment]
    get_prev_trading_day = None  # type: ignore[assignment]
    is_trading_day = None  # type: ignore[assignment]

__all__ = [
    "acquire_lock",
    "get_next_trading_day",
    "get_prev_trading_day",
    "is_trading_day",
    "date_range",
    "period_to_start_date",
]


def date_range(start: date, end: date) -> list[date]:
    """生成日期范围列表（含首尾）。

    Args:
        start: 起始日期。
        end: 结束日期。

    Returns:
        日期列表。
    """
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def period_to_start_date(period: str, end_date: date | None = None) -> date:
    """将周期字符串转换为起始日期。

    Args:
        period: 周期代码 — 1m/3m/6m/1y/3y/5y/all。
        end_date: 结束日期，默认今天。

    Returns:
        起始日期。
    """
    end = end_date or date.today()
    mapping: dict[str, int] = {
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
        "3y": 1095,
        "5y": 1825,
        "all": 3650,
    }
    days = mapping.get(period, 90)
    return end - timedelta(days=days)
