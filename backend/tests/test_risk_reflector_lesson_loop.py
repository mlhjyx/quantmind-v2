"""V3 §8.3 RiskReflectorAgent lesson→risk_memory 闭环 tests (TB-4c).

Coverage:
  - _compose_lesson_text — overall_summary → ≤500-char lesson (truncation)
  - _compose_context_snapshot — ReflectionOutput → JSONB-safe dict
  - RiskReflectorAgent.sediment_lesson — BGE-M3 embed → RiskMemory → persist
  - _ensure_embedding_service — fail-loud when embedding_factory not injected
  - 4 边界 case prompt eval (Plan v0.2 §A TB-4c acceptance):
    empty week / 1 event / 100 events / V4-Pro timeout — ReflectorAgent
    robustness across 4 input profiles (ADR-069 候选 sediment baseline)

LL-159 4-step preflight sustained — unit tests with stub embedding service +
stub conn + monkeypatched persist_risk_memory, 0 LLM call / 0 real DB / 0 BGE-M3
model load. Sustained TB-2b/TB-3 mock 体例.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.risk.risk_reflector_agent import (
    RiskReflectorAgent,
    _compose_context_snapshot,
    _compose_lesson_text,
)

# Import from backend.qm_platform.* to match risk_reflector_agent.py's import
# root — `qm_platform.*` and `backend.qm_platform.*` are distinct module objects
# (dual .pth root), so exception classes + monkeypatch targets must align with
# what the SUT actually imports.
from backend.qm_platform.risk.memory.embedding_service import EMBEDDING_DIM
from backend.qm_platform.risk.reflector import (
    ReflectionDimension,
    ReflectionDimensionOutput,
    ReflectionInput,
    ReflectionOutput,
    ReflectorAgentError,
)

_NOW = datetime(2026, 5, 11, 19, 0, 0, tzinfo=UTC)
_PERIOD_START = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
_PERIOD_END = datetime(2026, 5, 11, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_output(
    *,
    period_label: str = "2026_W19",
    overall_summary: str = "W19 复盘: 12 alerts 全及时, STAGED 80% 准确率.",
) -> ReflectionOutput:
    dims = tuple(
        ReflectionDimensionOutput(
            dimension=dim,
            summary=f"{dim.value} 摘要.",
            findings=[f"{dim.value} f1"],
            candidates=[f"{dim.value} c1"],
        )
        for dim in ReflectionDimension
    )
    return ReflectionOutput(
        period_label=period_label,
        generated_at=_NOW,
        reflections=dims,
        overall_summary=overall_summary,
        raw_response='{"overall_summary": "..."}',
    )


class _StubEmbeddingService:
    """Stub BGE-M3 EmbeddingService — deterministic 1024-dim tuple."""

    def __init__(self, dim: int = EMBEDDING_DIM, fail: bool = False) -> None:
        self._dim = dim
        self._fail = fail
        self.calls: list[str] = []

    def encode(self, text: str) -> tuple[float, ...]:
        self.calls.append(text)
        if self._fail:
            raise RuntimeError("stub BGE-M3 encode failure")
        return tuple(0.001 * i for i in range(self._dim))


class _StubConn:
    """Minimal psycopg2 connection stub for sediment_lesson tests."""

    def commit(self) -> None:  # noqa: D102
        pass

    def rollback(self) -> None:  # noqa: D102
        pass


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubRouter:
    """Stub LiteLLM router — returns configured response OR raises."""

    def __init__(self, response_text: str | None = None, raise_exc: Exception | None = None) -> None:
        self._text = response_text
        self._raise = raise_exc
        self.calls: list[dict[str, Any]] = []

    def completion(self, task: Any, messages: Any, *, decision_id: str | None = None, **kw: Any) -> _StubResponse:
        self.calls.append({"task": task, "decision_id": decision_id})
        if self._raise is not None:
            raise self._raise
        return _StubResponse(self._text or _valid_5dim_json())


def _valid_5dim_json(overall: str = "综合摘要.") -> str:
    return json.dumps(
        {
            "overall_summary": overall,
            "reflections": {
                dim.value: {
                    "summary": f"{dim.value} 摘要.",
                    "findings": [],
                    "candidates": [],
                }
                for dim in ReflectionDimension
            },
        }
    )


# ---------------------------------------------------------------------------
# _compose_lesson_text
# ---------------------------------------------------------------------------


class TestComposeLessonText:
    def test_short_summary_passthrough(self) -> None:
        out = _make_output(overall_summary="短摘要.")
        lesson = _compose_lesson_text(out)
        assert lesson == "短摘要."

    def test_strips_whitespace(self) -> None:
        out = _make_output(overall_summary="  带空白的摘要.  ")
        lesson = _compose_lesson_text(out)
        assert lesson == "带空白的摘要."

    def test_truncates_over_500_chars(self) -> None:
        # ReflectionOutput allows ≤600 char overall_summary; risk_memory.lesson
        # DDL CHECK caps at 500 — _compose_lesson_text must truncate.
        long_summary = "测" * 550
        out = _make_output(overall_summary=long_summary)
        lesson = _compose_lesson_text(out)
        assert len(lesson) == 500  # 499 chars + ellipsis
        assert lesson.endswith("…")

    def test_exactly_500_not_truncated(self) -> None:
        exact = "x" * 500
        out = _make_output(overall_summary=exact)
        lesson = _compose_lesson_text(out)
        assert len(lesson) == 500
        assert not lesson.endswith("…")

    def test_exactly_501_truncated_to_500(self) -> None:
        """PR #345 reviewer-fix LOW 1: 501-char is the first value triggering
        truncation — boundary test nails the off-by-one math (lesson[:499] + '…'
        = 500 codepoints, '…' = U+2026 single codepoint)."""
        over_by_one = "y" * 501
        out = _make_output(overall_summary=over_by_one)
        lesson = _compose_lesson_text(out)
        assert len(lesson) == 500
        assert lesson.endswith("…")
        assert lesson[:499] == "y" * 499


# ---------------------------------------------------------------------------
# _compose_context_snapshot
# ---------------------------------------------------------------------------


class TestComposeContextSnapshot:
    def test_json_serializable(self) -> None:
        out = _make_output()
        ctx = _compose_context_snapshot(out)
        # Must round-trip through json (risk_memory.context_snapshot is JSONB).
        json.dumps(ctx)

    def test_contains_metadata(self) -> None:
        out = _make_output(period_label="2026_W19")
        ctx = _compose_context_snapshot(out)
        assert ctx["source"] == "risk_reflector"
        assert ctx["period_label"] == "2026_W19"
        assert ctx["total_findings"] == 5  # 1 per dim
        assert ctx["total_candidates"] == 5
        assert "generated_at" in ctx

    def test_dimension_summaries_all_5(self) -> None:
        out = _make_output()
        ctx = _compose_context_snapshot(out)
        dim_summaries = ctx["dimension_summaries"]
        assert isinstance(dim_summaries, dict)
        assert set(dim_summaries.keys()) == {
            "detection",
            "threshold",
            "action",
            "context",
            "strategy",
        }


# ---------------------------------------------------------------------------
# RiskReflectorAgent.sediment_lesson
# ---------------------------------------------------------------------------


class TestSedimentLesson:
    def test_happy_path(self, monkeypatch) -> None:
        stub_emb = _StubEmbeddingService()
        captured: dict[str, Any] = {}

        def _stub_persist(conn: Any, memory: Any) -> int:
            captured["memory"] = memory
            return 99

        import backend.qm_platform.risk.memory.repository as repo_mod

        monkeypatch.setattr(repo_mod, "persist_risk_memory", _stub_persist)

        svc = RiskReflectorAgent(
            router_factory=lambda: _StubRouter(),
            embedding_factory=lambda: stub_emb,
        )
        out = _make_output()
        memory_id = svc.sediment_lesson(
            out, _StubConn(), event_type="WeeklyReflection"
        )
        assert memory_id == 99
        # BGE-M3 encode called with lesson text.
        assert len(stub_emb.calls) == 1
        assert stub_emb.calls[0] == out.overall_summary
        # RiskMemory constructed correctly.
        mem = captured["memory"]
        assert mem.event_type == "WeeklyReflection"
        assert mem.symbol_id is None
        assert mem.lesson == out.overall_summary
        assert len(mem.embedding) == EMBEDDING_DIM
        assert mem.action_taken is None
        assert mem.outcome is None
        # event_timestamp defaults to output.generated_at.
        assert mem.event_timestamp == _NOW

    def test_with_symbol_id_and_event_timestamp(self, monkeypatch) -> None:
        import backend.qm_platform.risk.memory.repository as repo_mod

        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            repo_mod,
            "persist_risk_memory",
            lambda conn, memory: captured.update(memory=memory) or 1,
        )
        svc = RiskReflectorAgent(
            router_factory=lambda: _StubRouter(),
            embedding_factory=lambda: _StubEmbeddingService(),
        )
        out = _make_output()
        custom_ts = datetime(2026, 5, 10, 14, 30, 0, tzinfo=UTC)
        svc.sediment_lesson(
            out,
            _StubConn(),
            event_type="LimitDown",
            symbol_id="600519.SH",
            event_timestamp=custom_ts,
        )
        mem = captured["memory"]
        assert mem.symbol_id == "600519.SH"
        assert mem.event_timestamp == custom_ts

    def test_missing_embedding_factory_raises(self) -> None:
        svc = RiskReflectorAgent(router_factory=lambda: _StubRouter())
        # embedding_factory=None → sediment_lesson must fail-loud.
        with pytest.raises(RuntimeError, match="requires embedding_factory"):
            svc.sediment_lesson(
                _make_output(), _StubConn(), event_type="WeeklyReflection"
            )

    def test_naive_event_timestamp_raises(self) -> None:
        svc = RiskReflectorAgent(
            router_factory=lambda: _StubRouter(),
            embedding_factory=lambda: _StubEmbeddingService(),
        )
        with pytest.raises(ValueError, match="event_timestamp must be tz-aware"):
            svc.sediment_lesson(
                _make_output(),
                _StubConn(),
                event_type="WeeklyReflection",
                event_timestamp=datetime(2026, 5, 10, 14, 30),  # naive
            )

    def test_embedding_failure_propagates(self) -> None:
        svc = RiskReflectorAgent(
            router_factory=lambda: _StubRouter(),
            embedding_factory=lambda: _StubEmbeddingService(fail=True),
        )
        with pytest.raises(RuntimeError, match="stub BGE-M3 encode failure"):
            svc.sediment_lesson(
                _make_output(), _StubConn(), event_type="WeeklyReflection"
            )

    def test_embedding_service_cached(self, monkeypatch) -> None:
        """embedding_factory invoked once, then cached (sustained TB-3b 体例)."""
        import backend.qm_platform.risk.memory.repository as repo_mod

        monkeypatch.setattr(repo_mod, "persist_risk_memory", lambda conn, memory: 1)
        factory_calls = {"n": 0}

        def _factory() -> _StubEmbeddingService:
            factory_calls["n"] += 1
            return _StubEmbeddingService()

        svc = RiskReflectorAgent(
            router_factory=lambda: _StubRouter(), embedding_factory=_factory
        )
        svc.sediment_lesson(_make_output(), _StubConn(), event_type="WeeklyReflection")
        svc.sediment_lesson(_make_output(), _StubConn(), event_type="WeeklyReflection")
        assert factory_calls["n"] == 1  # cached after first


# ---------------------------------------------------------------------------
# 4 边界 case prompt eval (Plan v0.2 §A TB-4c acceptance)
# ---------------------------------------------------------------------------


class TestFourBoundaryCasePromptEval:
    """Plan v0.2 §A TB-4c acceptance: 4 边界 case prompt eval — ReflectorAgent
    robustness across input profiles (empty week / 1 event / 100 events /
    V4-Pro timeout). ADR-069 候选 sediment baseline.

    Tests use mocked router — the eval verifies the agent's parse + validation
    pipeline handles each profile, NOT real V4-Pro reasoning quality (that is
    留 production prompt eval per quantmind-v3-prompt-iteration-evaluator skill).
    """

    def _service(self, router: _StubRouter) -> RiskReflectorAgent:
        return RiskReflectorAgent(
            router_factory=lambda: router,
            embedding_factory=lambda: _StubEmbeddingService(),
        )

    def test_case1_empty_week(self) -> None:
        """Empty week — all-placeholder input, V4-Pro returns 数据不足 reflection."""
        empty_resp = _valid_5dim_json(overall="本周期 0 events — 数据不足, 待下周期.")
        svc = self._service(_StubRouter(response_text=empty_resp))
        inp = ReflectionInput(
            period_label="2026_W19",
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            events_summary="[empty — 0 risk events this period]",
            plans_summary="[empty]",
            pnl_outcome="[empty]",
            rag_top5="[empty]",
        )
        out = svc.reflect(inp, now=_NOW)
        assert "数据不足" in out.overall_summary
        assert len(out.reflections) == 5

    def test_case2_single_event(self) -> None:
        """1 event — minimal data, valid reflection."""
        svc = self._service(_StubRouter())
        inp = ReflectionInput(
            period_label="2026_W19",
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            events_summary="1 alert: LimitDown 600519.SH 14:23 (P1)",
            plans_summary="STAGED: 1 executed",
            pnl_outcome="Day P&L: -0.8%",
            rag_top5="1. 类似 LimitDown lesson",
        )
        out = svc.reflect(inp, now=_NOW)
        assert len(out.reflections) == 5

    def test_case3_hundred_events(self) -> None:
        """100 events — large input, no truncation issues in agent pipeline."""
        svc = self._service(_StubRouter())
        large_events = "\n".join(
            f"{i}. alert {i}: RapidDrop 6005{i:02d}.SH (P{i % 3})" for i in range(100)
        )
        inp = ReflectionInput(
            period_label="2026_W19",
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            events_summary=large_events,  # ~3500 chars
            plans_summary="STAGED: 60 executed / 30 cancelled / 10 timeout",
            pnl_outcome="Day P&L volatile: -5% to +3%",
            rag_top5="1-5. 多条 historical lessons",
        )
        out = svc.reflect(inp, now=_NOW)
        assert len(out.reflections) == 5
        # Large input flows through user_template substitution without error.

    def test_case4_v4pro_timeout(self) -> None:
        """V4-Pro timeout — router raises, fail-loud propagates (反 LL-157 silent skip)."""
        svc = self._service(_StubRouter(raise_exc=TimeoutError("V4-Pro deepseek-reasoner timeout")))
        inp = ReflectionInput(
            period_label="2026_W19",
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            events_summary="some events",
            plans_summary="some plans",
            pnl_outcome="some pnl",
            rag_top5="some rag",
        )
        # Timeout must propagate — NOT silently skipped (V3 §14 #13 + 铁律 33).
        with pytest.raises(TimeoutError, match="V4-Pro deepseek-reasoner timeout"):
            svc.reflect(inp, now=_NOW)

    def test_case4_malformed_response_fail_loud(self) -> None:
        """V4-Pro malformed JSON — ReflectorAgentError fail-loud (反 silent skip)."""
        svc = self._service(_StubRouter(response_text="not valid json"))
        inp = ReflectionInput(
            period_label="2026_W19",
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            events_summary="e",
            plans_summary="p",
            pnl_outcome="pnl",
            rag_top5="r",
        )
        with pytest.raises(ReflectorAgentError, match="JSON parse failure"):
            svc.reflect(inp, now=_NOW)
