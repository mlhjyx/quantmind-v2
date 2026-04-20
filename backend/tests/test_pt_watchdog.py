"""Unit tests for ``scripts.pt_watchdog`` — F21 regression (Session 20→21).

F21 根因 (2026-04-20 Session 20):
  ``get_perf_gap_days`` (L120-134) 原 SQL 子查询 ``WHERE execution_mode = 'paper'``
  与 ``get_latest_perf_date`` (L96-105) 的 ``IN ('paper', 'live')`` 不对称.
  Session 20 cutover (.env paper→live) 后, paper namespace 永无新数据,
  fallback 到 '2020-01-01' 致 gap=1524 天假警. 钉钉 20:00 P0 误报 "PT链路异常".

本测试文件单元覆盖 pt_watchdog 3 个 namespace 查询函数的 SQL 结构对称性,
防止未来 regression 重新引入 hardcoded 'paper' / 'live'.

覆盖 (3 tests):
  1. ``get_latest_perf_date`` SQL 含 ``IN ('paper', 'live')`` (pre-existing 正确)
  2. ``get_perf_gap_days`` SQL 含 ``IN ('paper', 'live')`` **F21 regression 核心**
  3. ``get_latest_signal_date`` SQL 含 ``IN ('paper', 'live')`` (pre-existing 正确)

模式: mock ``conn.cursor().execute()`` 断言 SQL 字符串结构 (无 DB 依赖).
仿 ``test_pt_audit.py`` 动态 import 非 package script 模式.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent


def _load_mod():
    """Dynamic import ``scripts/pt_watchdog.py`` (非 package)."""
    spec_path = _REPO / "scripts" / "pt_watchdog.py"
    module_name = "pt_watchdog_test_shim"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, spec_path)
    assert spec is not None and spec.loader is not None, f"Cannot load {spec_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_mod()


def _call_with_mock_conn(fn, return_value: tuple | None = (0,)) -> str:
    """Call ``fn(conn)`` with mock psycopg2 conn, return SQL string executed.

    Args:
        fn: pt_watchdog function under test (单参数 ``conn``).
        return_value: mock ``cursor.fetchone()`` 返回值 (不影响 SQL 断言).

    Returns:
        SQL 字符串 (cursor.execute 首参).
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = return_value

    fn(mock_conn)

    assert mock_cur.execute.called, f"{fn.__name__} 未调用 cursor.execute"
    call_args = mock_cur.execute.call_args
    return call_args[0][0]


def _assert_symmetric_namespace(sql: str, function_name: str) -> None:
    """断言 SQL 含 ``IN ('paper', 'live')`` 跨命名空间读取, 无硬编 single-namespace."""
    # 容忍 IN 参数顺序
    has_in_both = (
        "IN ('paper', 'live')" in sql or "IN ('live', 'paper')" in sql
    )
    assert has_in_both, (
        f"{function_name} SQL 必须跨 paper + live 命名空间读取 "
        f"(IN ('paper', 'live')), 实际 SQL:\n{sql}"
    )
    # F21 regression: 防硬编 single 'paper' 或 'live'
    assert "WHERE execution_mode = 'paper'" not in sql, (
        f"{function_name} F21 regression: 含 hardcoded WHERE execution_mode = 'paper'. "
        f"必须用 IN (...). SQL:\n{sql}"
    )
    assert "WHERE execution_mode = 'live'" not in sql, (
        f"{function_name} 含 hardcoded WHERE execution_mode = 'live'. "
        f"watchdog 是跨模式运维视图, 应用 IN (...). SQL:\n{sql}"
    )


# ─── Tests ──────────────────────────────────────────────────────────


def test_get_latest_perf_date_queries_both_namespaces():
    """`get_latest_perf_date` (L96-105) 跨命名空间读取 — pre-existing 正确性验证."""
    sql = _call_with_mock_conn(mod.get_latest_perf_date, return_value=(None,))
    _assert_symmetric_namespace(sql, "get_latest_perf_date")
    assert "MAX(trade_date)" in sql
    assert "performance_series" in sql


def test_get_perf_gap_days_queries_both_namespaces_f21_regression():
    """**F21 regression 核心** (2026-04-20 Session 20 钉钉假警 1524 天).

    Before Fix A: `WHERE execution_mode = 'paper'` + paper 0 行 fallback '2020-01-01'
      → gap=1524 (6 年交易日) 假警
    After Fix A: `WHERE execution_mode IN ('paper', 'live')` + live 有今日数据
      → gap=0 真实
    """
    sql = _call_with_mock_conn(mod.get_perf_gap_days, return_value=(0,))
    _assert_symmetric_namespace(sql, "get_perf_gap_days")
    # 额外: 确保 subquery + fallback 结构保留 (未误删安全网)
    assert "COALESCE(MAX(trade_date)" in sql
    assert "trading_calendar" in sql
    assert "is_trading_day = TRUE" in sql


def test_get_latest_signal_date_queries_both_namespaces():
    """`get_latest_signal_date` (L108-117) 跨命名空间读取 — pre-existing 正确性验证."""
    sql = _call_with_mock_conn(mod.get_latest_signal_date, return_value=(None,))
    _assert_symmetric_namespace(sql, "get_latest_signal_date")
    assert "MAX(trade_date)" in sql
    assert "signals" in sql


# ─── Contract Tests ─────────────────────────────────────────────────


def test_module_exports_namespace_query_functions():
    """Contract: 3 个 namespace-aware 查询函数必须存在于 module."""
    assert hasattr(mod, "get_latest_perf_date"), "pt_watchdog 必须导出 get_latest_perf_date"
    assert hasattr(mod, "get_perf_gap_days"), "pt_watchdog 必须导出 get_perf_gap_days"
    assert hasattr(mod, "get_latest_signal_date"), "pt_watchdog 必须导出 get_latest_signal_date"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
