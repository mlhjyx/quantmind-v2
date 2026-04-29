"""Startup namespace consistency assertion — Risk Framework P0 批 1 Fix 2.

防 ADR-008 命名空间漂移再发: 启动时若 .env EXECUTION_MODE 与 DB position_snapshot
最近 7 天命名空间不一致, 直接 RAISE refuse to start, 强制运维感知 + 决策修法
(改 .env / 迁 DB 数据).

历史: 2026-04-20 17:47 cutover live (Session 20) → 4-29 10:58 .env 改回 paper
但持仓数据继续按 live 写 (pt_qmt_state.save_qmt_state 5 处 hardcoded 'live'),
导致 14:30 risk_daily_check 在 paper 模式下读 trade_log 0 行 → entry_price=0 →
silent skip 全部规则. 卓然 -29% / 南玻 -10% 7 天 risk_event_log 0 行的根因之一.

本启动断言无法替代写路径漂移修复 (批 2), 但能在新一轮漂移发生时**fail loud
拒绝启动**, 让漂移立即可见.

关联铁律: 33 fail-loud / 34 SSOT / 41 timezone (无, pure mode 字段)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.startup_assertions import (
    NamespaceMismatchError,
    assert_execution_mode_consistency,
    fetch_recent_position_modes,
)


def _make_mock_conn(rows: list[tuple[str, int]]):
    """构造 mock psycopg2 conn 返回指定 rows."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


class TestAssertExecutionModeConsistency:
    """启动断言核心契约 (3 case 覆盖 happy / drift / empty)."""

    def test_passes_when_env_aligns_with_db_modes_live(self):
        """env=live + DB recent 7d has 'live' rows → no raise (happy path)."""
        # ADR-008 D2 happy path: .env 与 DB 命名空间一致
        assert_execution_mode_consistency(
            env_mode="live",
            db_modes={"live": 295},
        )  # no raise

    def test_passes_when_env_aligns_with_db_modes_paper(self):
        """env=paper + DB has 'paper' → no raise (paper 命名空间合规)."""
        assert_execution_mode_consistency(
            env_mode="paper",
            db_modes={"paper": 295},
        )

    def test_raises_when_env_paper_but_db_only_has_live(self):
        """4-29 实测漂移: env=paper but DB 30d 全 live → RAISE refuse to start.

        防 paper 模式下读 live 持仓数据 (entry_price=0 silent skip / cb_state
        命名空间错乱 / risk_event_log 0 行 假装健康).
        """
        with pytest.raises(NamespaceMismatchError) as exc_info:
            assert_execution_mode_consistency(
                env_mode="paper",
                db_modes={"live": 295},
            )

        msg = str(exc_info.value)
        assert "EXECUTION_MODE drift" in msg or "drift" in msg.lower()
        assert "paper" in msg
        assert "live" in msg
        # 必给出修法提示 (改 .env 或迁数据)
        assert "fix .env" in msg.lower() or "migrate" in msg.lower() or "命名空间" in msg

    def test_raises_when_env_live_but_db_only_has_paper(self):
        """对称漂移: env=live but DB has paper → RAISE."""
        with pytest.raises(NamespaceMismatchError):
            assert_execution_mode_consistency(
                env_mode="live",
                db_modes={"paper": 100},
            )

    def test_passes_with_warning_when_db_empty(self, caplog):
        """env=live + DB recent 7d 空 (PT 暂停 / 新 deploy fresh DB) → no raise + warn."""
        with caplog.at_level("WARNING", logger="app.services.startup_assertions"):
            assert_execution_mode_consistency(
                env_mode="live",
                db_modes={},
            )  # no raise
        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("empty" in msg.lower() or "skip" in msg.lower() or "0 row" in msg.lower()
                   for msg in warning_msgs), (
            f"DB 空时应有 warning 提示 'skip mode assertion'. 实际: {warning_msgs}"
        )

    def test_passes_when_env_in_multimode_db_during_migration(self):
        """env=live + DB 既有 paper 又有 live (迁移过渡期) → 容忍, 因 env 已在 db_modes 内."""
        assert_execution_mode_consistency(
            env_mode="live",
            db_modes={"live": 200, "paper": 50},
        )  # no raise — env 在 dict 内即过


class TestFetchRecentPositionModes:
    """SQL 查询 helper: position_snapshot 最近 7d execution_mode 分布."""

    def test_returns_dict_from_cursor_fetchall(self):
        """fetchall returns [(mode, count), ...] → dict."""
        conn = _make_mock_conn([("live", 295)])
        result = fetch_recent_position_modes(conn)
        assert result == {"live": 295}

    def test_returns_empty_dict_when_no_rows(self):
        conn = _make_mock_conn([])
        result = fetch_recent_position_modes(conn)
        assert result == {}

    def test_handles_multiple_modes(self):
        conn = _make_mock_conn([("live", 200), ("paper", 50)])
        result = fetch_recent_position_modes(conn)
        assert result == {"live": 200, "paper": 50}


class TestStartupAssertionLifespanIntegration:
    """生产入口: backend/app/main.py lifespan 启动调本断言, 不一致拒启动.

    SAST 守门: main.py lifespan 必含 assert_execution_mode_consistency 调用,
    防 future refactor 误删导致漂移再发不可检.
    """

    def test_main_lifespan_imports_startup_assertion(self):
        """main.py lifespan 必 import + 调 assert_execution_mode_consistency."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "app"
            / "main.py"
        ).read_text(encoding="utf-8")
        assert (
            "assert_execution_mode_consistency" in src
            or "startup_assertions" in src
        ), (
            "main.py lifespan 必调用 startup_assertions.assert_execution_mode_consistency. "
            "P0 批 1 Fix 2: 防 ADR-008 命名空间漂移再发, 启动 fail-loud."
        )
