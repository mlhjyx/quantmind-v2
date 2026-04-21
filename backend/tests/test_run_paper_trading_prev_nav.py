"""P1-c regression: run_paper_trading.py prev_nav query 必须含 trade_date < %s 过滤.

根因 (Session 21 2026-04-21): 16:30 signal_phase 读 performance_series 取 prev_nav 时,
15:40 DailyReconciliation 已写当日行, LIMIT 1 ORDER BY DESC 读到今日 self,
→ prev_nav = nav → daily_return = (nav/nav-1) = 0.

修: 加 `AND trade_date < %s` 明确排除今日, 对齐 daily_reconciliation.py:206 的正确 query.
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "run_paper_trading.py"


def _load_script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_prev_nav_query_contains_trade_date_filter() -> None:
    """Regression: prev_nav SQL 必须含 `trade_date < %s` 过滤 (P1-c 根因)."""
    text = _load_script_text()
    # 找到 SELECT nav FROM performance_series 紧邻的 WHERE 子句
    match = re.search(
        r'SELECT nav FROM performance_series.*?ORDER BY trade_date DESC LIMIT 1',
        text,
        re.DOTALL,
    )
    assert match is not None, "prev_nav SELECT query 未找到 — 脚本结构可能变化"
    query = match.group(0)
    assert "trade_date < %s" in query or "trade_date < CAST" in query, (
        f"prev_nav query 缺 `trade_date < %s` 过滤 — P1-c bug 回归!\n"
        f"实际 query 片段:\n{query}"
    )


def test_prev_nav_query_passes_trade_date_param() -> None:
    """Regression: prev_nav cur.execute 必须传 trade_date 参数 (匹配 < %s 占位)."""
    text = _load_script_text()
    # 在 prev_nav SELECT 后找 execute 参数 tuple
    match = re.search(
        r'SELECT nav FROM performance_series.*?LIMIT 1[",\s]+.*?\((.+?)\),\s*\n',
        text,
        re.DOTALL,
    )
    assert match is not None, "prev_nav execute 参数 tuple 未找到"
    params = match.group(1)
    assert "trade_date" in params, (
        f"prev_nav cur.execute 参数缺 trade_date — 与 < %s 占位不匹配, 会 ProgrammingError\n"
        f"实际参数: {params}"
    )


def test_prev_nav_aligns_with_daily_reconciliation_pattern() -> None:
    """对齐铁律: run_paper_trading.py 与 daily_reconciliation.py 同 pattern (trade_date < %s)."""
    recon_path = SCRIPT_PATH.parent / "daily_reconciliation.py"
    recon_text = recon_path.read_text(encoding="utf-8")
    recon_has_filter = "trade_date < %s" in recon_text or "AND trade_date <" in recon_text
    run_pt_text = _load_script_text()
    run_pt_has_filter = "trade_date < %s" in run_pt_text or "AND trade_date <" in run_pt_text

    assert recon_has_filter, "daily_reconciliation.py 缺 trade_date < 过滤 (基准对照丢失)"
    assert run_pt_has_filter, "run_paper_trading.py 缺 trade_date < 过滤 (P1-c 修回归)"
