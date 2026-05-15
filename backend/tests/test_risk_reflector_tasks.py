"""V3 §8 RiskReflector Celery Beat tasks tests (TB-4b).

Coverage:
  - _weekly_bounds / _monthly_bounds period computation (tz-aware, ISO week, prev month)
  - _build_reflection_input + 4 gather helpers (IC-2c 2026-05-15 de-stub —
    replaces _build_stub_input placeholder with real risk_event_log /
    execution_plans / trade_log / RiskMemoryRAG queries; per-source fail-soft)
  - _render_reflection_markdown — full report rendering (5 维 sections + findings + candidates)
  - _render_dingtalk_summary — short 摘要 + truncation hard cap
  - _slugify_event — filename slug (non-alnum → _, length cap, CJK preserved)
  - _write_reflection_markdown — file write + parent mkdir
  - _run_reflection — shared body (gather → reflect → sediment → push) with mocks
  - weekly_reflection / monthly_reflection / event_reflection Celery tasks
  - Beat schedule entries present (risk-reflector-weekly + risk-reflector-monthly)
  - celery_app imports include risk_reflector_tasks

LL-159 4-step preflight sustained — unit tests with mocked service + mocked
DingTalk + tmp_path file writes, 0 LLM call / 0 DB / 0 real DingTalk POST.
Sustained TB-2c market_regime_tasks test 体例.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.tasks import risk_reflector_tasks as rrt

# Import from backend.qm_platform.* to match risk_reflector_tasks.py's import
# root (PR #345 MEDIUM 1 — aligned to backend.qm_platform.*). `qm_platform.*`
# and `backend.qm_platform.*` are distinct module objects (.pth dual root) —
# isinstance checks + class identity must use the SUT's root.
from backend.qm_platform.risk.reflector import (
    ReflectionDimension,
    ReflectionDimensionOutput,
    ReflectionInput,
    ReflectionOutput,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW_SUNDAY = datetime(2026, 5, 10, 19, 0, 0, tzinfo=UTC)  # Sunday 2026-05-10
_NOW_MONTH_1ST = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)  # 月 1 日


def _valid_output(period_label: str = "2026_W19") -> ReflectionOutput:
    dims = tuple(
        ReflectionDimensionOutput(
            dimension=dim,
            summary=f"{dim.value} 摘要 — 本周期数据.",
            findings=[f"{dim.value} 发现 1"] if dim is ReflectionDimension.DETECTION else [],
            candidates=[f"{dim.value} 候选 1"]
            if dim in (ReflectionDimension.THRESHOLD, ReflectionDimension.ACTION)
            else [],
        )
        for dim in ReflectionDimension
    )
    return ReflectionOutput(
        period_label=period_label,
        generated_at=_NOW_SUNDAY,
        reflections=dims,
        overall_summary=f"{period_label} 综合摘要: 复盘完成.",
        raw_response='{"overall_summary": "..."}',
    )


class _StubConn:
    """Minimal psycopg2 connection stub — records commit/rollback/close."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _StubService:
    """Stub RiskReflectorAgent — records reflect + sediment_lesson calls."""

    def __init__(
        self,
        output: ReflectionOutput | None = None,
        raise_exc: Exception | None = None,
        sediment_raise_exc: Exception | None = None,
    ) -> None:
        self._output = output
        self._raise = raise_exc
        self._sediment_raise = sediment_raise_exc
        self.calls: list[dict[str, Any]] = []
        self.sediment_calls: list[dict[str, Any]] = []

    def reflect(
        self,
        input_data: ReflectionInput,
        *,
        decision_id: str | None = None,
        now: datetime | None = None,
    ) -> ReflectionOutput:
        self.calls.append({"input_data": input_data, "decision_id": decision_id})
        if self._raise is not None:
            raise self._raise
        return self._output or _valid_output(input_data.period_label)

    def sediment_lesson(
        self,
        output: ReflectionOutput,
        conn: Any,
        *,
        event_type: str,
        symbol_id: str | None = None,
        event_timestamp: datetime | None = None,
    ) -> int:
        self.sediment_calls.append(
            {
                "output": output,
                "conn": conn,
                "event_type": event_type,
                "symbol_id": symbol_id,
                "event_timestamp": event_timestamp,
            }
        )
        if self._sediment_raise is not None:
            raise self._sediment_raise
        return 42  # stub memory_id


def _patch_input_gather_deps(monkeypatch: Any) -> None:
    """Shared helper — patches IC-2c input-gathering deps for ad-hoc tests.

    Used by tests that bypass the `stub_env` fixture (e.g. failing-service
    error-propagation tests). Patches `_get_rag` (stub returning empty
    retrieve()) + `get_sync_conn` (stub _StubConn) so `_run_reflection`'s
    input-gathering phase can complete before the test's actual assertion
    target (service.reflect raise / sediment_lesson raise / retry dispatch).
    """
    from unittest.mock import MagicMock

    stub_rag = MagicMock()
    stub_rag.retrieve.return_value = []
    monkeypatch.setattr(rrt, "_get_rag", lambda: stub_rag)

    import app.services.db as db_mod

    monkeypatch.setattr(db_mod, "get_sync_conn", lambda: _StubConn())


@pytest.fixture
def stub_env(monkeypatch, tmp_path):
    """Patch _get_service + _get_rag + REFLECTIONS_DIR + send_with_dedup + get_sync_conn.

    IC-2c (2026-05-15) addition: _get_rag patched to return stub RAG with
    empty retrieve() result — input gathering returns "数据不足: RAG returned
    0 hits" placeholder, which reflector_v1.yaml prompt handles per design.
    """
    from unittest.mock import MagicMock

    stub_svc = _StubService()
    monkeypatch.setattr(rrt, "_get_service", lambda: stub_svc)

    # IC-2c: _get_rag stub — empty hits (consistent with placeholder fail-soft semantics)
    stub_rag = MagicMock()
    stub_rag.retrieve.return_value = []
    monkeypatch.setattr(rrt, "_get_rag", lambda: stub_rag)

    monkeypatch.setattr(rrt, "REFLECTIONS_DIR", tmp_path)

    dingtalk_calls: list[dict[str, Any]] = []

    def _stub_send(**kwargs: Any) -> dict[str, Any]:
        dingtalk_calls.append(kwargs)
        return {"sent": False, "dedup_hit": False, "reason": "alerts_disabled", "fire_count": 0}

    # send_with_dedup is imported inside _push_dingtalk_summary — patch at source module.
    import app.services.dingtalk_alert as dingtalk_mod

    monkeypatch.setattr(dingtalk_mod, "send_with_dedup", _stub_send)

    # get_sync_conn imported inside _run_reflection — patch at source module (TB-4c).
    import app.services.db as db_mod

    conns: list[_StubConn] = []

    def _stub_get_conn() -> _StubConn:
        c = _StubConn()
        conns.append(c)
        return c

    monkeypatch.setattr(db_mod, "get_sync_conn", _stub_get_conn)

    return {
        "service": stub_svc,
        "reflections_dir": tmp_path,
        "dingtalk_calls": dingtalk_calls,
        "conns": conns,
    }


# ---------------------------------------------------------------------------
# Period bounds
# ---------------------------------------------------------------------------


class TestWeeklyBounds:
    def test_period_is_7_days(self) -> None:
        label, start, end = rrt._weekly_bounds(_NOW_SUNDAY)
        assert (end - start).days == 7
        assert end == _NOW_SUNDAY

    def test_period_label_iso_week(self) -> None:
        label, _, _ = rrt._weekly_bounds(_NOW_SUNDAY)
        # 2026-05-10 is ISO week 19.
        assert label == "2026_W19"

    def test_bounds_tz_aware(self) -> None:
        _, start, end = rrt._weekly_bounds(_NOW_SUNDAY)
        assert start.tzinfo is not None
        assert end.tzinfo is not None

    def test_year_boundary_iso_week(self) -> None:
        """PR #344 reviewer-fix MEDIUM 1: ISO week year-boundary edge case —
        2025-12-29 (Monday) is ISO week 1 of 2026, so iso_year (2026) != calendar
        year (2025). period_label must use iso_year not calendar year."""
        boundary = datetime(2025, 12, 29, 19, 0, 0, tzinfo=UTC)
        label, _, _ = rrt._weekly_bounds(boundary)
        # isocalendar() → (2026, 1, 1) — label uses iso_year=2026, NOT 2025.
        assert label == "2026_W01"


class TestMonthlyBounds:
    def test_reflects_previous_month(self) -> None:
        label, start, end = rrt._monthly_bounds(_NOW_MONTH_1ST)
        # Fired 2026-05-01 → reflects April 2026.
        assert label == "2026_04"
        assert start == datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)

    def test_january_rolls_to_previous_year(self) -> None:
        jan_1st = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
        label, start, end = rrt._monthly_bounds(jan_1st)
        assert label == "2025_12"
        assert start == datetime(2025, 12, 1, 0, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    def test_bounds_tz_aware(self) -> None:
        _, start, end = rrt._monthly_bounds(_NOW_MONTH_1ST)
        assert start.tzinfo is not None
        assert end.tzinfo is not None


# ---------------------------------------------------------------------------
# _build_reflection_input + 4 gather helpers (IC-2c 2026-05-15 de-stub)
# ---------------------------------------------------------------------------


class _MockCursor:
    """SQL-route dispatch mock — table-name-specific routing (LL-171 lesson 3
    SSOT pattern: stock_basic / daily_basic / risk_event_log / execution_plans
    / trade_log are disjoint table names, so substring routing is order-stable
    after WU-IC-2a P2 fix sustained).
    """

    def __init__(self, routes: dict[str, list[tuple]]) -> None:
        self._routes = routes
        self._last_sql = ""

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._last_sql = sql

    def fetchall(self) -> list[tuple]:
        sql = self._last_sql
        # Route by most-specific table name first (sustained LL-171 lesson 3)
        if "risk_event_log" in sql:
            return self._routes.get("risk_event_log", [])
        if "execution_plans" in sql:
            return self._routes.get("execution_plans", [])
        if "trade_log" in sql:
            return self._routes.get("trade_log", [])
        return []

    def close(self) -> None:
        pass


class _MockConn:
    def __init__(self, routes: dict[str, list[tuple]] | None = None) -> None:
        self._routes = routes or {}

    def cursor(self) -> _MockCursor:
        return _MockCursor(self._routes)

    def close(self) -> None:
        pass


_T_START = datetime(2026, 5, 3, 0, 0, tzinfo=UTC)
_T_END = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)


class TestGatherEventsSummary:
    """`_gather_events_summary` — risk_event_log GROUP BY (rule_id, severity)."""

    def test_returns_markdown_table_with_totals(self) -> None:
        rows = [
            ("limit_down_detection", "p0", 5),
            ("rapid_drop_5min", "p1", 3),
            ("near_limit_down", "p2", 2),
        ]
        conn = _MockConn({"risk_event_log": rows})
        result = rrt._gather_events_summary(conn, _T_START, _T_END)
        assert "| rule_id | severity | count |" in result
        assert "| limit_down_detection | p0 | 5 |" in result
        assert "Total: 10 events" in result
        assert "3 (rule, severity) groups" in result

    def test_zero_rows_returns_placeholder(self) -> None:
        conn = _MockConn({"risk_event_log": []})
        result = rrt._gather_events_summary(conn, _T_START, _T_END)
        assert "数据不足" in result
        assert "0 risk_event_log rows" in result

    def test_db_error_fails_soft(self) -> None:
        from unittest.mock import MagicMock

        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("simulated PG down")
        result = rrt._gather_events_summary(conn, _T_START, _T_END)
        assert "数据不足: events_summary 查询失败" in result
        assert "RuntimeError" in result


class TestGatherPlansSummary:
    """`_gather_plans_summary` — execution_plans GROUP BY (status, user_decision)."""

    def test_returns_markdown_table_with_cancel_rate(self) -> None:
        rows = [
            ("CANCELLED", "cancel", 3),
            ("CONFIRMED", "confirm", 7),
            ("PENDING_CONFIRM", "null", 1),
        ]
        conn = _MockConn({"execution_plans": rows})
        result = rrt._gather_plans_summary(conn, _T_START, _T_END)
        assert "| status | user_decision | count |" in result
        # Cancel rate: 3 cancelled / (3+7) confirmed = 30%
        assert "Cancel rate: 3/10 = 30.0%" in result

    def test_no_cancel_rate_when_no_terminal_states(self) -> None:
        rows = [("PENDING_CONFIRM", "null", 5)]
        conn = _MockConn({"execution_plans": rows})
        result = rrt._gather_plans_summary(conn, _T_START, _T_END)
        # No CONFIRMED + 0 CANCELLED → no cancel-rate line
        assert "Cancel rate" not in result

    def test_zero_rows_returns_placeholder(self) -> None:
        conn = _MockConn({"execution_plans": []})
        result = rrt._gather_plans_summary(conn, _T_START, _T_END)
        assert "数据不足" in result
        assert "0 execution_plans rows" in result

    def test_db_error_fails_soft(self) -> None:
        from unittest.mock import MagicMock

        conn = MagicMock()
        conn.cursor.side_effect = ConnectionError("PG dropped")
        result = rrt._gather_plans_summary(conn, _T_START, _T_END)
        assert "数据不足: plans_summary 查询失败" in result


class TestGatherPnlOutcome:
    """`_gather_pnl_outcome` — trade_log paper-mode aggregate."""

    def test_returns_markdown_table(self) -> None:
        rows = [
            ("buy", 5, 50000.00, 50028.50, 5.7),
            ("sell", 4, 40000.00, 39985.30, -3.7),
        ]
        conn = _MockConn({"trade_log": rows})
        result = rrt._gather_pnl_outcome(conn, _T_START, _T_END)
        assert "| direction | count | gross ¥ | total_cost ¥ | avg slippage bps |" in result
        assert "| buy | 5 |" in result
        assert "| sell | 4 |" in result

    def test_zero_rows_returns_placeholder(self) -> None:
        conn = _MockConn({"trade_log": []})
        result = rrt._gather_pnl_outcome(conn, _T_START, _T_END)
        assert "数据不足" in result
        assert "0 paper-mode filled trade_log rows" in result

    def test_db_error_fails_soft(self) -> None:
        from unittest.mock import MagicMock

        conn = MagicMock()
        conn.cursor.side_effect = OSError("disk full")
        result = rrt._gather_pnl_outcome(conn, _T_START, _T_END)
        assert "数据不足: pnl_outcome 查询失败" in result


class TestGatherRagTop5:
    """`_gather_rag_top5` — RiskMemoryRAG.retrieve → markdown table."""

    def _make_hit(self, cosine: float, event_type: str, symbol: str | None, lesson: str) -> Any:
        """Build SimilarMemoryHit + RiskMemory dual fake for table rendering."""
        from unittest.mock import MagicMock

        memory = MagicMock()
        memory.event_type = event_type
        memory.symbol_id = symbol
        memory.lesson = lesson
        hit = MagicMock()
        hit.memory = memory
        hit.cosine_similarity = cosine
        return hit

    def test_renders_markdown_table_with_top_hits(self) -> None:
        from unittest.mock import MagicMock

        rag = MagicMock()
        rag.retrieve.return_value = [
            self._make_hit(0.92, "LimitDown", "600519.SH", "茅台 4-29 跌停反思"),
            self._make_hit(0.85, "RapidDrop", None, "市场级 RapidDrop 5min 复盘"),
        ]
        result = rrt._gather_rag_top5(rag, "query text", event_type=None)
        assert "| cosine | event_type | symbol | lesson |" in result
        assert "| 0.920 | LimitDown | 600519.SH |" in result
        assert "| 0.850 | RapidDrop | — |" in result  # None → em-dash placeholder
        rag.retrieve.assert_called_once_with("query text", k=5, event_type=None)

    def test_empty_hits_returns_placeholder(self) -> None:
        from unittest.mock import MagicMock

        rag = MagicMock()
        rag.retrieve.return_value = []
        result = rrt._gather_rag_top5(rag, "q", event_type="LimitDown")
        assert "数据不足: RAG returned 0 hits" in result
        assert "event_type='LimitDown'" in result

    def test_retrieve_exception_fails_soft(self) -> None:
        from unittest.mock import MagicMock

        rag = MagicMock()
        rag.retrieve.side_effect = ValueError("query embed failed")
        result = rrt._gather_rag_top5(rag, "q")
        assert "数据不足: RAG retrieve 失败" in result
        assert "ValueError" in result

    def test_long_lesson_truncated_with_pipe_escape(self) -> None:
        from unittest.mock import MagicMock

        rag = MagicMock()
        # Pipes inside the first 80 chars (truncation window) so escape fires
        long_lesson = "pipe1 | pipe2 | " + ("X" * 100)
        rag.retrieve.return_value = [
            self._make_hit(0.7, "LimitDown", "000001.SZ", long_lesson),
        ]
        result = rrt._gather_rag_top5(rag, "q")
        # Truncated to 80 + "..." + pipe-escaped
        assert "..." in result
        # Original pipes inside the truncation window must be escaped
        assert "pipe1 \\| pipe2 \\|" in result

    def test_newline_in_lesson_replaced_with_space(self) -> None:
        from unittest.mock import MagicMock

        rag = MagicMock()
        rag.retrieve.return_value = [
            self._make_hit(0.8, "RapidDrop", "300001.SZ", "line1\nline2"),
        ]
        result = rrt._gather_rag_top5(rag, "q")
        # Newlines replaced with spaces (would break markdown table otherwise)
        assert "line1 line2" in result
        assert "line1\nline2" not in result.split("\n")[2]  # 3rd line = first data row


class TestBuildReflectionInput:
    """Integration: `_build_reflection_input` orchestrates all 4 sources."""

    def test_full_path_assembles_4_real_summaries(self) -> None:
        from unittest.mock import MagicMock

        conn = _MockConn(
            {
                "risk_event_log": [("limit_down_detection", "p0", 5)],
                "execution_plans": [("CONFIRMED", "confirm", 7)],
                "trade_log": [("buy", 5, 50000.00, 50028.50, 5.7)],
            }
        )
        rag = MagicMock()
        rag.retrieve.return_value = [
            TestGatherRagTop5._make_hit(
                TestGatherRagTop5(), 0.9, "LimitDown", "600519.SH", "lesson"
            )
        ]

        result = rrt._build_reflection_input(
            "2026_W19",
            _T_START,
            _T_END,
            conn=conn,
            rag=rag,
            rag_event_type_filter=None,
        )
        assert isinstance(result, ReflectionInput)
        assert result.period_label == "2026_W19"
        assert "| limit_down_detection | p0 | 5 |" in result.events_summary
        assert "| CONFIRMED | confirm | 7 |" in result.plans_summary
        assert "| buy | 5 |" in result.pnl_outcome
        assert "| 0.900 | LimitDown |" in result.rag_top5

    def test_per_source_fail_soft_independent(self) -> None:
        """If risk_event_log raises but other 3 sources succeed, only events_summary
        gets the placeholder; other fields still real."""
        from unittest.mock import MagicMock

        # Build a conn where ONLY risk_event_log query raises
        class _PartialFailConn:
            def cursor(self) -> Any:
                return _PartialFailCursor()

            def close(self) -> None:
                pass

        class _PartialFailCursor:
            def __init__(self) -> None:
                self._last_sql = ""

            def execute(self, sql: str, params: tuple = ()) -> None:
                self._last_sql = sql
                if "risk_event_log" in sql:
                    raise RuntimeError("simulated risk_event_log down")

            def fetchall(self) -> list[tuple]:
                if "execution_plans" in self._last_sql:
                    return [("CONFIRMED", "confirm", 1)]
                if "trade_log" in self._last_sql:
                    return [("buy", 1, 100.0, 100.5, 1.5)]
                return []

            def close(self) -> None:
                pass

        rag = MagicMock()
        rag.retrieve.return_value = []

        result = rrt._build_reflection_input(
            "2026_W19",
            _T_START,
            _T_END,
            conn=_PartialFailConn(),
            rag=rag,
            rag_event_type_filter=None,
        )
        assert "数据不足" in result.events_summary
        assert "RuntimeError" in result.events_summary
        # Other 3 sources still real / empty (NOT contaminated by events fail)
        assert "| CONFIRMED | confirm | 1 |" in result.plans_summary
        assert "| buy | 1 |" in result.pnl_outcome
        assert "数据不足: RAG returned 0 hits" in result.rag_top5

    def test_event_type_filter_passed_to_rag(self) -> None:
        """rag_event_type_filter forwarded to RAG.retrieve event_type kwarg."""
        from unittest.mock import MagicMock

        conn = _MockConn({"risk_event_log": [], "execution_plans": [], "trade_log": []})
        rag = MagicMock()
        rag.retrieve.return_value = []

        rrt._build_reflection_input(
            "event-LimitDown-2026-05-15",
            _T_START,
            _T_END,
            conn=conn,
            rag=rag,
            rag_event_type_filter="LimitDown",
        )
        rag.retrieve.assert_called_once()
        call_kwargs = rag.retrieve.call_args.kwargs
        assert call_kwargs.get("event_type") == "LimitDown"


# ---------------------------------------------------------------------------
# _render_reflection_markdown
# ---------------------------------------------------------------------------


class TestRenderReflectionMarkdown:
    def test_contains_header_and_summary(self) -> None:
        out = _valid_output("2026_W19")
        md = rrt._render_reflection_markdown(out)
        assert "# RiskReflector 反思报告 — 2026_W19" in md
        assert "## 综合摘要" in md
        assert "2026_W19 综合摘要" in md

    def test_contains_all_5_dimensions(self) -> None:
        out = _valid_output()
        md = rrt._render_reflection_markdown(out)
        for dim in ("Detection", "Threshold", "Action", "Context", "Strategy"):
            assert f"## {dim}" in md

    def test_renders_findings_and_candidates(self) -> None:
        out = _valid_output()
        md = rrt._render_reflection_markdown(out)
        assert "**发现**:" in md
        assert "- detection 发现 1" in md
        assert "**改进候选**:" in md
        assert "- threshold 候选 1" in md

    def test_footer_present(self) -> None:
        out = _valid_output()
        md = rrt._render_reflection_markdown(out)
        assert "参数候选需 user 显式 approve" in md


# ---------------------------------------------------------------------------
# _render_dingtalk_summary
# ---------------------------------------------------------------------------


class TestRenderDingtalkSummary:
    def test_contains_period_and_summary(self) -> None:
        out = _valid_output("2026_W19")
        target = rrt.REFLECTIONS_DIR / "2026_W19.md"
        summary = rrt._render_dingtalk_summary(out, target)
        assert "2026_W19" in summary
        assert "综合摘要" in summary

    def test_contains_findings_candidates_count(self) -> None:
        out = _valid_output()
        target = rrt.REFLECTIONS_DIR / "2026_W19.md"
        summary = rrt._render_dingtalk_summary(out, target)
        # 1 finding (detection) + 2 candidates (threshold + action).
        assert "1 项" in summary  # findings
        assert "2 项" in summary  # candidates

    def test_truncation_hard_cap(self, monkeypatch) -> None:
        # Force a tiny cap to test truncation path.
        monkeypatch.setattr(rrt, "_DINGTALK_SUMMARY_MAX_CHARS", 100)
        out = _valid_output()
        target = rrt.REFLECTIONS_DIR / "2026_W19.md"
        summary = rrt._render_dingtalk_summary(out, target)
        assert len(summary) <= 100
        assert "截断" in summary

    def test_links_full_report_weekly(self) -> None:
        """PR #344 reviewer-fix LOW 1: report link uses actual target_path
        relative to repo root (weekly = top-level YYYY_WW.md)."""
        out = _valid_output("2026_W19")
        target = rrt.REFLECTIONS_DIR / "2026_W19.md"
        summary = rrt._render_dingtalk_summary(out, target)
        assert "docs/risk_reflections/2026_W19.md" in summary.replace("\\", "/")

    def test_links_full_report_event_subdir(self) -> None:
        """PR #344 reviewer-fix LOW 1: event reflections write to event/ subdir —
        report link must reflect actual path NOT computed period_label.md."""
        out = _valid_output("event-2026-05-10-limitdown_cluster")
        target = rrt.REFLECTIONS_DIR / "event" / "2026-05-10_limitdown_cluster.md"
        summary = rrt._render_dingtalk_summary(out, target)
        # Link must point to event/ subdir, NOT top-level event-...-cluster.md.
        assert "event/2026-05-10_limitdown_cluster.md" in summary.replace("\\", "/")


# ---------------------------------------------------------------------------
# _slugify_event
# ---------------------------------------------------------------------------


class TestSlugifyEvent:
    def test_basic_slug(self) -> None:
        assert rrt._slugify_event("LimitDown Cluster") == "limitdown_cluster"

    def test_non_alnum_collapsed(self) -> None:
        assert rrt._slugify_event("portfolio < -5%!!!") == "portfolio_5"

    def test_cjk_preserved(self) -> None:
        # CJK chars preserved (not stripped as non-alnum).
        slug = rrt._slugify_event("跌停潮 事件")
        assert "跌停潮" in slug

    def test_length_cap_60(self) -> None:
        long_summary = "x" * 200
        assert len(rrt._slugify_event(long_summary)) == 60

    def test_empty_fallback(self) -> None:
        assert rrt._slugify_event("!!!") == "event"
        assert rrt._slugify_event("   ") == "event"


# ---------------------------------------------------------------------------
# _write_reflection_markdown
# ---------------------------------------------------------------------------


class TestWriteReflectionMarkdown:
    def test_writes_file(self, tmp_path: Path) -> None:
        out = _valid_output("2026_W19")
        target = tmp_path / "2026_W19.md"
        rrt._write_reflection_markdown(out, target)
        assert target.exists()
        assert "# RiskReflector 反思报告" in target.read_text(encoding="utf-8")

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        out = _valid_output()
        target = tmp_path / "event" / "2026-05-10_test.md"
        rrt._write_reflection_markdown(out, target)
        assert target.exists()
        assert target.parent.name == "event"


# ---------------------------------------------------------------------------
# _run_reflection (shared body)
# ---------------------------------------------------------------------------


class TestRunReflection:
    def test_full_flow(self, stub_env) -> None:
        target = stub_env["reflections_dir"] / "2026_W19.md"
        result = rrt._run_reflection(
            period_label="2026_W19",
            period_start=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
            period_end=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
            target_path=target,
            decision_id="test-decision",
            dedup_key="risk_reflector:weekly:2026_W19",
            event_type="Reflection:Weekly",
        )
        assert result["ok"] is True
        assert result["period_label"] == "2026_W19"
        assert result["report_path"] == str(target)
        assert result["memory_id"] == 42  # stub sediment memory_id
        assert target.exists()
        # Service was invoked with stub input.
        assert len(stub_env["service"].calls) == 1
        assert stub_env["service"].calls[0]["decision_id"] == "test-decision"
        # DingTalk push attempted.
        assert len(stub_env["dingtalk_calls"]) == 1
        assert stub_env["dingtalk_calls"][0]["dedup_key"] == "risk_reflector:weekly:2026_W19"
        # TB-4c: lesson sediment invoked + conn committed + closed (铁律 32).
        assert len(stub_env["service"].sediment_calls) == 1
        sediment = stub_env["service"].sediment_calls[0]
        assert sediment["event_type"] == "Reflection:Weekly"
        assert sediment["event_timestamp"] == datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
        # IC-2c (2026-05-15): 2 conns opened — [0] input-gather (read-only,
        # close-only, no commit/rollback), [1] sediment (commit on success).
        # Pre-IC-2c: only 1 sediment conn (stub_input gather used no DB).
        assert len(stub_env["conns"]) == 2
        # Input-gather conn (conns[0]): closed only, NO commit/rollback
        assert stub_env["conns"][0].committed is False
        assert stub_env["conns"][0].rolled_back is False
        assert stub_env["conns"][0].closed is True
        # Sediment conn (conns[-1]): committed + closed
        assert stub_env["conns"][-1].committed is True
        assert stub_env["conns"][-1].rolled_back is False
        assert stub_env["conns"][-1].closed is True

    def test_propagates_service_error(self, monkeypatch, tmp_path) -> None:
        from qm_platform.risk.reflector import ReflectorAgentError

        failing_svc = _StubService(raise_exc=ReflectorAgentError("V4-Pro timeout"))
        monkeypatch.setattr(rrt, "_get_service", lambda: failing_svc)
        _patch_input_gather_deps(monkeypatch)  # IC-2c: stub RAG + get_sync_conn
        monkeypatch.setattr(rrt, "REFLECTIONS_DIR", tmp_path)
        with pytest.raises(ReflectorAgentError, match="V4-Pro timeout"):
            rrt._run_reflection(
                period_label="2026_W19",
                period_start=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
                period_end=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
                target_path=tmp_path / "2026_W19.md",
                decision_id="test",
                dedup_key="test",
                event_type="Reflection:Weekly",
            )

    def test_sediment_error_rolls_back_conn(self, monkeypatch, tmp_path) -> None:
        """TB-4c: sediment_lesson failure → conn.rollback() + close + raise (铁律 33)."""
        from qm_platform.risk.memory.interface import RiskMemoryError

        svc = _StubService(sediment_raise_exc=RiskMemoryError("BGE-M3 OOM"))
        monkeypatch.setattr(rrt, "_get_service", lambda: svc)
        _patch_input_gather_deps(monkeypatch)  # IC-2c: stub RAG + get_sync_conn
        monkeypatch.setattr(rrt, "REFLECTIONS_DIR", tmp_path)

        import app.services.dingtalk_alert as dingtalk_mod

        monkeypatch.setattr(
            dingtalk_mod,
            "send_with_dedup",
            lambda **kw: {"sent": False, "reason": "alerts_disabled"},
        )

        import app.services.db as db_mod

        conns: list[_StubConn] = []

        def _stub_get_conn() -> _StubConn:
            c = _StubConn()
            conns.append(c)
            return c

        monkeypatch.setattr(db_mod, "get_sync_conn", _stub_get_conn)

        with pytest.raises(RiskMemoryError, match="BGE-M3 OOM"):
            rrt._run_reflection(
                period_label="2026_W19",
                period_start=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
                period_end=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
                target_path=tmp_path / "2026_W19.md",
                decision_id="test",
                dedup_key="test",
                event_type="Reflection:Weekly",
            )
        # IC-2c (2026-05-15): 2 conns opened — [0] input-gather (read-only),
        # [1] sediment (rolled back due to sediment_lesson raise).
        assert len(conns) == 2
        # Input-gather conn (conns[0]): closed only, NO commit/rollback
        assert conns[0].committed is False
        assert conns[0].rolled_back is False
        assert conns[0].closed is True
        # Sediment conn (conns[-1]): rolled back + closed (反 leak)
        assert conns[-1].committed is False
        assert conns[-1].rolled_back is True
        assert conns[-1].closed is True


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


class TestCeleryTasks:
    def test_weekly_reflection(self, stub_env) -> None:
        result = rrt.weekly_reflection(decision_id="weekly-smoke")
        assert result["ok"] is True
        assert result["period_label"].startswith("20")
        assert "_W" in result["period_label"]
        # Report written to patched REFLECTIONS_DIR.
        assert Path(result["report_path"]).exists()
        # TB-4c: lesson sedimented with Reflection:Weekly event_type.
        assert result["memory_id"] == 42
        assert stub_env["service"].sediment_calls[0]["event_type"] == "Reflection:Weekly"
        assert stub_env["service"].sediment_calls[0]["symbol_id"] is None

    def test_weekly_reflection_auto_decision_id(self, stub_env) -> None:
        result = rrt.weekly_reflection()
        assert stub_env["service"].calls[0]["decision_id"].startswith("reflector-weekly-")
        assert result["ok"] is True

    def test_monthly_reflection(self, stub_env) -> None:
        result = rrt.monthly_reflection(decision_id="monthly-smoke")
        assert result["ok"] is True
        # period_label = YYYY_MM (no _W).
        assert "_W" not in result["period_label"]
        assert Path(result["report_path"]).exists()
        # TB-4c: lesson sedimented with Reflection:Monthly event_type.
        assert stub_env["service"].sediment_calls[0]["event_type"] == "Reflection:Monthly"

    def test_event_reflection(self, stub_env) -> None:
        result = rrt.event_reflection(
            event_summary="LimitDown Cluster 5 stocks",
            decision_id="event-smoke",
        )
        assert result["ok"] is True
        assert result["period_label"].startswith("event-")
        # Report written under event/ subdir.
        assert "event" in result["report_path"]
        assert Path(result["report_path"]).exists()
        # TB-4c: default event_type when caller omits.
        assert stub_env["service"].sediment_calls[0]["event_type"] == "Reflection:Event"

    def test_event_reflection_custom_event_type_and_symbol(self, stub_env) -> None:
        """TB-4c: L1 dispatch supplies triggering event_type + symbol_id."""
        rrt.event_reflection(
            event_summary="600519 跌停",
            event_type="LimitDown",
            symbol_id="600519.SH",
            decision_id="event-limitdown",
        )
        sediment = stub_env["service"].sediment_calls[0]
        assert sediment["event_type"] == "LimitDown"
        assert sediment["symbol_id"] == "600519.SH"

    def test_event_reflection_empty_summary_raises(self, stub_env) -> None:
        with pytest.raises(ValueError, match="event_summary must be non-empty"):
            rrt.event_reflection(event_summary="")

    def test_event_reflection_custom_window(self, stub_env) -> None:
        rrt.event_reflection(
            event_summary="test event",
            event_window_hours=48,
            decision_id="event-48h",
        )
        inp = stub_env["service"].calls[0]["input_data"]
        # period span ~48h.
        assert (inp.period_end - inp.period_start).total_seconds() == 48 * 3600


# ---------------------------------------------------------------------------
# Beat schedule + celery_app wiring
# ---------------------------------------------------------------------------


class TestBeatScheduleWiring:
    def test_beat_schedule_has_2_reflector_entries(self) -> None:
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE

        assert "risk-reflector-weekly" in CELERY_BEAT_SCHEDULE
        assert "risk-reflector-monthly" in CELERY_BEAT_SCHEDULE

    def test_weekly_entry_targets_correct_task(self) -> None:
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE

        entry = CELERY_BEAT_SCHEDULE["risk-reflector-weekly"]
        assert entry["task"] == "app.tasks.risk_reflector_tasks.weekly_reflection"

    def test_monthly_entry_targets_correct_task(self) -> None:
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE

        entry = CELERY_BEAT_SCHEDULE["risk-reflector-monthly"]
        assert entry["task"] == "app.tasks.risk_reflector_tasks.monthly_reflection"

    def test_celery_app_imports_reflector_tasks(self) -> None:
        from app.tasks.celery_app import celery_app

        assert "app.tasks.risk_reflector_tasks" in celery_app.conf.imports


# ---------------------------------------------------------------------------
# HC-2b G5 — retry-once-skip + RISK_REFLECTOR_FAILED 元告警 (V3 §14 mode 14)
# ---------------------------------------------------------------------------


class _FakeRetryError(BaseException):
    """Stand-in for celery.exceptions.Retry — raised by _FakeTask.retry().

    Inherits BaseException (NOT Exception) for fidelity with real
    celery.exceptions.Retry — so it propagates past any `except Exception`
    just as the real Retry control-flow exception does (reviewer MEDIUM).
    """


class _FakeTask:
    """Minimal bound-task stub — request.retries / max_retries / retry()."""

    def __init__(self, retries: int = 0, max_retries: int = 1) -> None:
        from types import SimpleNamespace

        self.request = SimpleNamespace(retries=retries)
        self.max_retries = max_retries
        self.retry_calls: list[dict[str, Any]] = []

    def retry(self, *, exc: BaseException, countdown: int) -> None:
        self.retry_calls.append({"exc": exc, "countdown": countdown})
        raise _FakeRetryError(str(exc))  # mimic celery.exceptions.Retry control flow


class TestRiskReflectorFailedEnum:
    """RISK_REFLECTOR_FAILED enum + severity SSOT (HC-2b G5)."""

    def test_rule_id_in_enum(self) -> None:
        from backend.qm_platform.risk.metrics.meta_alert_interface import MetaAlertRuleId

        assert MetaAlertRuleId.RISK_REFLECTOR_FAILED.value == "risk_reflector_failed"

    def test_severity_is_p1(self) -> None:
        """V3 §14 mode 14 ⚠️ P1 — 反思失败 = degraded 非系统失效."""
        from backend.qm_platform.risk.metrics.meta_alert_interface import (
            RULE_SEVERITY,
            MetaAlertRuleId,
            MetaAlertSeverity,
        )

        assert RULE_SEVERITY[MetaAlertRuleId.RISK_REFLECTOR_FAILED] is MetaAlertSeverity.P1


class TestRetrySkipDispatch:
    """_dispatch_with_retry_skip — V3 §14 mode 14 retry-once-then-skip."""

    def test_success_returns_result_no_retry(self, stub_env) -> None:
        task = _FakeTask(retries=0)
        target = stub_env["reflections_dir"] / "2026_W19.md"
        result = rrt._dispatch_with_retry_skip(
            task,
            cadence_label="weekly",
            period_label="2026_W19",
            period_start=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
            period_end=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
            target_path=target,
            decision_id="test",
            dedup_key="risk_reflector:weekly:2026_W19",
            event_type="Reflection:Weekly",
        )
        assert result["ok"] is True
        assert task.retry_calls == []  # success → 0 retry

    def test_first_failure_triggers_retry(self, monkeypatch, tmp_path) -> None:
        """retries=0 < max_retries=1 → task.retry() called (countdown SSOT)."""
        from qm_platform.risk.reflector import ReflectorAgentError

        failing = _StubService(raise_exc=ReflectorAgentError("V4-Pro timeout"))
        monkeypatch.setattr(rrt, "_get_service", lambda: failing)
        _patch_input_gather_deps(monkeypatch)  # IC-2c: stub RAG + get_sync_conn
        monkeypatch.setattr(rrt, "REFLECTIONS_DIR", tmp_path)
        task = _FakeTask(retries=0, max_retries=1)
        with pytest.raises(_FakeRetryError):
            rrt._dispatch_with_retry_skip(
                task,
                cadence_label="weekly",
                period_label="2026_W19",
                period_start=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
                period_end=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
                target_path=tmp_path / "2026_W19.md",
                decision_id="test",
                dedup_key="test",
                event_type="Reflection:Weekly",
            )
        assert len(task.retry_calls) == 1
        assert task.retry_calls[0]["countdown"] == rrt._REFLECTOR_RETRY_COUNTDOWN_S

    def test_retries_exhausted_emits_meta_alert_and_reraises(self, monkeypatch, tmp_path) -> None:
        """retries==max_retries → emit RISK_REFLECTOR_FAILED 元告警 + re-raise 原 exc."""
        from qm_platform.risk.reflector import ReflectorAgentError

        failing = _StubService(raise_exc=ReflectorAgentError("V4-Pro timeout x2"))
        monkeypatch.setattr(rrt, "_get_service", lambda: failing)
        _patch_input_gather_deps(monkeypatch)  # IC-2c: stub RAG + get_sync_conn
        monkeypatch.setattr(rrt, "REFLECTIONS_DIR", tmp_path)

        emit_calls: list[dict[str, Any]] = []
        monkeypatch.setattr(
            rrt,
            "_emit_reflector_failure_meta_alert",
            lambda **kw: emit_calls.append(kw),
        )
        task = _FakeTask(retries=1, max_retries=1)
        with pytest.raises(ReflectorAgentError, match="V4-Pro timeout x2"):
            rrt._dispatch_with_retry_skip(
                task,
                cadence_label="monthly",
                period_label="2026_04",
                period_start=datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
                period_end=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
                target_path=tmp_path / "2026_04.md",
                decision_id="test",
                dedup_key="test",
                event_type="Reflection:Monthly",
            )
        assert task.retry_calls == []  # exhausted → no further retry
        assert len(emit_calls) == 1
        assert emit_calls[0]["cadence_label"] == "monthly"
        assert emit_calls[0]["period_label"] == "2026_04"
        assert isinstance(emit_calls[0]["exc"], ReflectorAgentError)


class TestEmitReflectorFailureMetaAlert:
    """_emit_reflector_failure_meta_alert — RISK_REFLECTOR_FAILED via channel chain."""

    def test_builds_correct_meta_alert_and_pushes(self, monkeypatch) -> None:
        from backend.qm_platform.risk.metrics.meta_alert_interface import (
            MetaAlertRuleId,
            MetaAlertSeverity,
        )

        pushed: list[dict[str, Any]] = []

        class _StubMMS:
            def push_triggered(self, alerts: Any, *, conn: Any) -> list[dict[str, Any]]:
                pushed.append({"alerts": alerts, "conn": conn})
                return [{"channel": "log_p0"}]

        import app.services.risk.meta_monitor_service as mms_mod

        monkeypatch.setattr(mms_mod, "MetaMonitorService", _StubMMS)

        import app.services.db as db_mod

        conns: list[_StubConn] = []

        def _get_conn() -> _StubConn:
            c = _StubConn()
            conns.append(c)
            return c

        monkeypatch.setattr(db_mod, "get_sync_conn", _get_conn)

        rrt._emit_reflector_failure_meta_alert(
            cadence_label="weekly",
            period_label="2026_W19",
            exc=RuntimeError("boom"),
        )
        assert len(pushed) == 1
        alert = pushed[0]["alerts"][0]
        assert alert.rule_id is MetaAlertRuleId.RISK_REFLECTOR_FAILED
        assert alert.severity is MetaAlertSeverity.P1
        assert alert.triggered is True
        assert "weekly" in alert.detail
        assert "2026_W19" in alert.detail
        assert "boom" in alert.detail
        assert conns[0].committed is True
        assert conns[0].closed is True

    def test_push_failure_is_fail_soft(self, monkeypatch) -> None:
        """元告警 push 自身失败 → log + swallow (NOT raise — 不掩盖原 reflection 失败)."""

        class _BoomMMS:
            def push_triggered(self, alerts: Any, *, conn: Any) -> list[dict[str, Any]]:
                raise RuntimeError("DingTalk + email + log all broken")

        import app.services.risk.meta_monitor_service as mms_mod

        monkeypatch.setattr(mms_mod, "MetaMonitorService", _BoomMMS)

        import app.services.db as db_mod

        conns: list[_StubConn] = []

        def _get_conn() -> _StubConn:
            c = _StubConn()
            conns.append(c)
            return c

        monkeypatch.setattr(db_mod, "get_sync_conn", _get_conn)

        # Must NOT raise — fail-soft (原 reflection 失败 caller 仍 raise propagate).
        rrt._emit_reflector_failure_meta_alert(
            cadence_label="weekly",
            period_label="2026_W19",
            exc=RuntimeError("orig"),
        )
        assert conns[0].rolled_back is True  # push raised → rollback
        assert conns[0].closed is True


class TestReflectionTaskDecorators:
    """weekly/monthly_reflection task decorator — bind=True + max_retries=1."""

    def test_weekly_is_bound_with_max_retries_1(self) -> None:
        assert rrt.weekly_reflection.max_retries == 1

    def test_monthly_is_bound_with_max_retries_1(self) -> None:
        assert rrt.monthly_reflection.max_retries == 1
