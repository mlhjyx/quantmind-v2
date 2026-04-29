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

        reviewer P3-2 采纳 (oh-my-claudecode): assertion 紧匹配实际 message text
        防中文 fallback 单点漏判 — 必含 "Edit backend/.env" + "Fix options" 实际文案.
        """
        with pytest.raises(NamespaceMismatchError) as exc_info:
            assert_execution_mode_consistency(
                env_mode="paper",
                db_modes={"live": 295},
            )

        msg = str(exc_info.value)
        assert "EXECUTION_MODE drift" in msg
        assert "paper" in msg
        assert "live" in msg
        # 必给出 4 个修法 (A/B/C/D 含新 D bypass)
        assert "Edit backend/.env" in msg, f"未含修法 A: {msg}"
        assert "Migrate DB data" in msg, f"未含修法 B: {msg}"
        assert "batch 2" in msg.lower(), f"未含修法 C: {msg}"
        assert "SKIP_NAMESPACE_ASSERT" in msg, f"未含修法 D bypass: {msg}"

    def test_raises_when_env_live_but_db_only_has_paper(self):
        """对称漂移: env=live but DB has paper → RAISE."""
        with pytest.raises(NamespaceMismatchError):
            assert_execution_mode_consistency(
                env_mode="live",
                db_modes={"paper": 100},
            )

    def test_passes_with_warning_when_db_empty(self, caplog):
        """env=live + DB recent 30d 空 (PT 暂停 30+ 天 / 新 deploy fresh DB) → no raise + warn.

        reviewer P1 采纳 (everything-claude-code): window 7d → 30d, 防 PT 暂停 8+ 天
        guard 误 silent skip 命中 4-29 真生产 9 天暂停事件.
        """
        with caplog.at_level("WARNING", logger="app.services.startup_assertions"):
            assert_execution_mode_consistency(
                env_mode="live",
                db_modes={},
            )  # no raise
        warning_msgs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("empty" in msg.lower() or "skip" in msg.lower() or "30d" in msg.lower()
                   for msg in warning_msgs), (
            f"DB 空时应有 warning 提示 'skip mode assertion'. 实际: {warning_msgs}"
        )

    def test_passes_when_env_in_multimode_db_during_migration(self):
        """env=live + DB 既有 paper 又有 live (迁移过渡期) → 容忍, 因 env 已在 db_modes 内."""
        assert_execution_mode_consistency(
            env_mode="live",
            db_modes={"live": 200, "paper": 50},
        )  # no raise — env 在 dict 内即过

    def test_drift_message_suggests_highest_count_mode(self):
        """reviewer P2-1 采纳 (oh-my-claudecode): multi-mode dict 漂移时, 推荐 mode
        必为 count 最高 (max), 非 dict insertion order 第一项 (非确定性).
        """
        with pytest.raises(NamespaceMismatchError) as exc_info:
            assert_execution_mode_consistency(
                env_mode="forex",  # 假设第三方 mode (绝不在 db_modes 内)
                db_modes={"paper": 50, "live": 295},
            )
        msg = str(exc_info.value)
        # 推荐应是 'live' (count 295 > paper 50), 非 'paper' (insertion order 第一)
        assert "EXECUTION_MODE='live'" in msg, (
            f"max(by count) 推荐失效: 应推 'live' (count 295). 实际: {msg}"
        )


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
        """main.py lifespan 必 import + 真调 run_startup_assertions(...).

        reviewer P2-2 采纳 (everything-claude-code): 紧 regex 防 future refactor
        把 import 留下但删 call (or 注释掉) silently 绕过守门.
        """
        import re
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "app"
            / "main.py"
        ).read_text(encoding="utf-8")
        # 必 import + 必真 call (而非注释)
        assert "from app.services.startup_assertions import" in src, (
            "main.py 必 import startup_assertions"
        )
        assert re.search(r"\brun_startup_assertions\s*\(", src), (
            "main.py lifespan 必真 call run_startup_assertions(...). "
            "P0 批 1 Fix 2: 防 ADR-008 命名空间漂移再发, 启动 fail-loud."
        )

    def test_main_lifespan_disposes_engine_on_assertion_failure(self):
        """reviewer P0 采纳: main.py lifespan 启动断言 raise 时必 dispose engine.

        防 SQLAlchemy async engine 池泄漏 — Servy MaxRestartAttempts=5 重启循环
        每次失败累积一个 engine pool 占 PG max_connections 槽位, 最终全部耗尽.
        """
        from pathlib import Path

        src = (
            Path(__file__).resolve().parent.parent
            / "app"
            / "main.py"
        ).read_text(encoding="utf-8")
        # lifespan 中必含 try/except 包 run_startup_assertions + engine.dispose
        assert "engine.dispose()" in src, (
            "main.py lifespan 必显式 dispose engine (启动失败 cleanup)"
        )
        # try/except 块结构 (近似 SAST)
        assert "try:" in src and "run_startup_assertions" in src, (
            "main.py lifespan run_startup_assertions 必包 try/except 防 engine 泄漏"
        )

    def test_skip_namespace_assert_env_var_bypass(self, monkeypatch):
        """reviewer P1 采纳: SKIP_NAMESPACE_ASSERT=1 应急 bypass 跳过断言."""
        from app.services.startup_assertions import run_startup_assertions

        # 注入 bypass env
        monkeypatch.setenv("SKIP_NAMESPACE_ASSERT", "1")

        # conn_factory 应不被调用 (early return)
        called = []

        def _conn_factory():
            called.append(True)
            raise RuntimeError("conn_factory 不应被调用 (bypass 应早退)")

        run_startup_assertions(_conn_factory)  # no raise, no DB call
        assert called == [], "bypass 时不应调 conn_factory"
