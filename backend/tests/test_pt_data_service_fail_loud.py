"""Unit tests for LL-058 fail-loud + tolerant health check.

2026-04-18 Session 6 末补: 修 PT 04-17 silent failure 根因.

Bug A: pt_data_service.fetch_daily_data L100-105 silent swallow update_stock_status 失败.
       修: raise 让 signal_phase catch + scheduler_task_log "failed" + pt_watchdog 告警.

Bug B: health_check.check_stock_status hard fail 1 天滞后就阻塞整 PT.
       修: ≤ 2 交易日 warning pass, > 2 天 fail.

铁律 33 fail-loud + 铁律 40 测试债不增长.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401

# scripts/ 不是 package, 手动 sys.path 添加
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import health_check as hc  # noqa: E402


# ═══════════════════════════════════════════════════════════════
# Bug A: pt_data_service fetch_daily_data fail-loud on status failure
# ═══════════════════════════════════════════════════════════════


def test_fetch_daily_data_source_contains_fail_loud_raise():
    """静态 check: pt_data_service.fetch_daily_data L100-105 含 raise 语句.

    Bug A 修复 (LL-058 铁律 33): update_stock_status_daily 异常不 silent swallow.
    用 inspect.getsource 验证源码含 `raise` (而非 mock 整 fetch_daily_data —
    后者涉及 ThreadPoolExecutor + Tushare API mock 成本高, 实战已由 signal phase
    04-17 retry SUCCESS 验证 path work).

    铁律 33 fail-loud.
    """
    import inspect

    from backend.app.services import pt_data_service as pds

    src = inspect.getsource(pds.fetch_daily_data)
    # 验证修复后的关键片段
    assert "stock_status_daily 更新失败" in src, "fail-loud error message present"
    assert "FAIL-LOUD" in src, "FAIL-LOUD marker in comment"
    assert "raise" in src, "raise statement present (not silent swallow)"
    # 确保不是老版本的 silent swallow
    silent_pattern = '\"\"\"results[\"status_rows\"] = 0\n        except'
    assert silent_pattern not in src, "old silent swallow pattern not present"


def test_update_stock_status_daily_exists_and_callable():
    """sanity: update_stock_status_daily 函数签名稳定, 供 fetch_daily_data 调用."""
    from backend.app.services.pt_data_service import update_stock_status_daily

    sig = __import__("inspect").signature(update_stock_status_daily)
    params = list(sig.parameters)
    assert "trade_date" in params
    assert "conn" in params


# ═══════════════════════════════════════════════════════════════
# Bug B: health_check.check_stock_status tolerant (≤ 2 day lag = warning)
# ═══════════════════════════════════════════════════════════════


def _make_mock_conn(max_status_date, prev_trading_day, lag_days, status_count=5000):
    """Mock conn 模拟 check_stock_status 4 次 cur.execute 调用."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    # 调用序: (1) MAX(trade_date) stock_status_daily
    #        (2) MAX(trade_date) trading_calendar < trade_date
    #        (3) COUNT(*) trading_calendar (lag_days 计算, 如果 lag 触发)
    #        (4) COUNT(*) stock_status_daily (覆盖率)
    fetchone_responses = [
        (max_status_date,),
        (prev_trading_day,),
    ]
    if max_status_date is not None and prev_trading_day and max_status_date < prev_trading_day:
        # 触发 lag 计算分支
        fetchone_responses.append((lag_days,))
    fetchone_responses.append((status_count,))
    mock_cur.fetchone.side_effect = fetchone_responses
    return mock_conn


def test_check_stock_status_no_lag_passes():
    """max_status_date == prev_trading_day → PASS."""
    conn = _make_mock_conn(
        max_status_date=date(2026, 4, 17),
        prev_trading_day=date(2026, 4, 17),
        lag_days=0,
    )
    ok, msg = hc.check_stock_status(conn, date(2026, 4, 18))
    assert ok is True
    assert "5000行" in msg


def test_check_stock_status_lag_1_day_warning_passes():
    """滞后 1 交易日 → warning 但 PASS (不阻塞 signal)."""
    conn = _make_mock_conn(
        max_status_date=date(2026, 4, 16),
        prev_trading_day=date(2026, 4, 17),
        lag_days=1,
    )
    ok, msg = hc.check_stock_status(conn, date(2026, 4, 18))
    assert ok is True, "LL-058: ≤ 2 交易日滞后应 warning pass, 不 fail"
    assert "WARN" in msg
    assert "滞后1交易日" in msg


def test_check_stock_status_lag_2_days_warning_passes():
    """滞后 2 交易日 → warning 但 PASS (边界)."""
    conn = _make_mock_conn(
        max_status_date=date(2026, 4, 15),
        prev_trading_day=date(2026, 4, 17),
        lag_days=2,
    )
    ok, msg = hc.check_stock_status(conn, date(2026, 4, 18))
    assert ok is True, "滞后 2 天是边界, 仍允许"
    assert "WARN" in msg
    assert "滞后2交易日" in msg


def test_check_stock_status_lag_3_days_fails():
    """滞后 > 2 交易日 → hard FAIL."""
    conn = _make_mock_conn(
        max_status_date=date(2026, 4, 14),
        prev_trading_day=date(2026, 4, 17),
        lag_days=3,
    )
    ok, msg = hc.check_stock_status(conn, date(2026, 4, 18))
    assert ok is False
    assert "数据严重滞后" in msg
    assert "滞后3交易日" in msg


def test_check_stock_status_empty_table_fails():
    """stock_status_daily 完全空 → FAIL."""
    conn = _make_mock_conn(
        max_status_date=None, prev_trading_day=date(2026, 4, 17), lag_days=0
    )
    ok, msg = hc.check_stock_status(conn, date(2026, 4, 18))
    assert ok is False
    assert "stock_status_daily表为空" in msg
