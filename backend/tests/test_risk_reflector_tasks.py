"""V3 §8 RiskReflector Celery Beat tasks tests (TB-4b).

Coverage:
  - _weekly_bounds / _monthly_bounds period computation (tz-aware, ISO week, prev month)
  - _build_stub_input placeholder ReflectionInput (TB-4c replaces)
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
from qm_platform.risk.reflector import (
    ReflectionDimension,
    ReflectionDimensionOutput,
    ReflectionInput,
    ReflectionOutput,
)

from app.tasks import risk_reflector_tasks as rrt

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


@pytest.fixture
def stub_env(monkeypatch, tmp_path):
    """Patch _get_service + REFLECTIONS_DIR + send_with_dedup + get_sync_conn."""
    stub_svc = _StubService()
    monkeypatch.setattr(rrt, "_get_service", lambda: stub_svc)
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
# _build_stub_input
# ---------------------------------------------------------------------------


class TestBuildStubInput:
    def test_returns_valid_reflection_input(self) -> None:
        start = datetime(2026, 5, 3, 0, 0, tzinfo=UTC)
        end = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
        inp = rrt._build_stub_input("2026_W19", start, end)
        assert isinstance(inp, ReflectionInput)
        assert inp.period_label == "2026_W19"

    def test_placeholder_marked_tb4c(self) -> None:
        start = datetime(2026, 5, 3, 0, 0, tzinfo=UTC)
        end = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
        inp = rrt._build_stub_input("2026_W19", start, end)
        # All 4 summary fields should be clearly-marked stub placeholders.
        assert "TB-4b stub" in inp.events_summary
        assert "TB-4c" in inp.events_summary
        assert inp.events_summary == inp.plans_summary == inp.pnl_outcome == inp.rag_top5


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
            event_type="WeeklyReflection",
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
        assert sediment["event_type"] == "WeeklyReflection"
        assert sediment["event_timestamp"] == datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
        assert len(stub_env["conns"]) == 1
        assert stub_env["conns"][0].committed is True
        assert stub_env["conns"][0].rolled_back is False
        assert stub_env["conns"][0].closed is True

    def test_propagates_service_error(self, monkeypatch, tmp_path) -> None:
        from qm_platform.risk.reflector import ReflectorAgentError

        failing_svc = _StubService(raise_exc=ReflectorAgentError("V4-Pro timeout"))
        monkeypatch.setattr(rrt, "_get_service", lambda: failing_svc)
        monkeypatch.setattr(rrt, "REFLECTIONS_DIR", tmp_path)
        with pytest.raises(ReflectorAgentError, match="V4-Pro timeout"):
            rrt._run_reflection(
                period_label="2026_W19",
                period_start=datetime(2026, 5, 3, 0, 0, tzinfo=UTC),
                period_end=datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
                target_path=tmp_path / "2026_W19.md",
                decision_id="test",
                dedup_key="test",
                event_type="WeeklyReflection",
            )

    def test_sediment_error_rolls_back_conn(self, monkeypatch, tmp_path) -> None:
        """TB-4c: sediment_lesson failure → conn.rollback() + close + raise (铁律 33)."""
        from qm_platform.risk.memory.interface import RiskMemoryError

        svc = _StubService(sediment_raise_exc=RiskMemoryError("BGE-M3 OOM"))
        monkeypatch.setattr(rrt, "_get_service", lambda: svc)
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
                event_type="WeeklyReflection",
            )
        # conn rolled back + closed (反 leak).
        assert len(conns) == 1
        assert conns[0].committed is False
        assert conns[0].rolled_back is True
        assert conns[0].closed is True


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
        # TB-4c: lesson sedimented with WeeklyReflection event_type.
        assert result["memory_id"] == 42
        assert stub_env["service"].sediment_calls[0]["event_type"] == "WeeklyReflection"
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
        # TB-4c: lesson sedimented with MonthlyReflection event_type.
        assert stub_env["service"].sediment_calls[0]["event_type"] == "MonthlyReflection"

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
        assert stub_env["service"].sediment_calls[0]["event_type"] == "EventReflection"

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
