"""V3 §8 ReflectorAgent tests (TB-4a, skeleton scope).

Coverage:
  - ReflectionInput / ReflectionDimensionOutput / ReflectionOutput frozen
    dataclass validation (fail-loud per 铁律 33)
  - ReflectionDimension StrEnum exact 5 values + str semantics
  - ReflectorAgent prompt yaml load + cache (lazy)
  - ReflectorAgent reflect() with mocked router — happy path 5 维 JSON output
  - ReflectorAgent fail-loud: missing dimension / malformed JSON / wrong types /
    code-fence stripping / dimension validation chained as ReflectorAgentError
  - RiskReflectorAgent service skeleton — lazy router_factory + delegation

LL-159 4-step preflight sustained — unit tests with mocked router, 0 LLM call
+ 0 DB. Sustained TB-2b agents.py mock-LLM test 体例 (24 tests precedent).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.services.risk.risk_reflector_agent import RiskReflectorAgent
from backend.qm_platform.llm import LLMMessage, RiskTaskType
from backend.qm_platform.risk.reflector import (
    ReflectionDimension,
    ReflectionDimensionOutput,
    ReflectionInput,
    ReflectionOutput,
    ReflectorAgent,
    ReflectorAgentError,
)
from backend.qm_platform.risk.reflector.agent import (
    PROMPT_VERSION,
    REFLECTOR_PROMPT_PATH,
    PromptLoadError,
    _load_prompt,
    _parse_reflection_response,
    _strip_code_fence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERIOD_START = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
_PERIOD_END = datetime(2026, 5, 11, 0, 0, 0, tzinfo=UTC)
_NOW = datetime(2026, 5, 11, 19, 0, 0, tzinfo=UTC)


def _valid_input(**overrides: Any) -> ReflectionInput:
    base = {
        "period_label": "W18-2026",
        "period_start": _PERIOD_START,
        "period_end": _PERIOD_END,
        "events_summary": "12 alerts (P0=3, P1=7, P2=2)",
        "plans_summary": "STAGED: 8 executed / 2 cancelled / 0 timeout",
        "pnl_outcome": "Daily P&L: -0.5% / -1.2% / +0.3% / +0.8% / -0.2%",
        "rag_top5": "1. 2024Q1 类似跌停 lesson: STAGED 30min default 减误执",
    }
    base.update(overrides)
    return ReflectionInput(**base)


def _valid_dimension(dim: ReflectionDimension = ReflectionDimension.DETECTION) -> dict[str, Any]:
    return {
        "summary": f"{dim.value}: 周复盘 — 12 alerts 全 detection 及时.",
        "findings": [f"{dim.value} finding 1", f"{dim.value} finding 2"],
        "candidates": [f"{dim.value} candidate 1"],
    }


def _valid_response_dict() -> dict[str, Any]:
    return {
        "overall_summary": "W18 复盘: 12 alerts 全及时, STAGED 80% 准确率, 1 漏报 LimitDown 5min.",
        "reflections": {
            dim.value: _valid_dimension(dim) for dim in ReflectionDimension
        },
    }


class _StubResponse:
    """Stub for LLMResponse — only need .content attribute."""

    def __init__(self, content: str) -> None:
        self.content = content


class _StubRouter:
    """Stub matching _RouterProtocol — records calls + returns configured response."""

    def __init__(self, response_text: str | None = None, raise_exc: Exception | None = None) -> None:
        self._response_text = response_text
        self._raise = raise_exc
        self.calls: list[dict[str, Any]] = []

    def completion(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        decision_id: str | None = None,
        **kwargs: Any,
    ) -> _StubResponse:
        self.calls.append(
            {
                "task": task,
                "messages": messages,
                "decision_id": decision_id,
                "kwargs": kwargs,
            }
        )
        if self._raise is not None:
            raise self._raise
        # Use None sentinel distinct from empty string (sustained 反 falsy-fallback bug).
        text = (
            self._response_text
            if self._response_text is not None
            else json.dumps(_valid_response_dict())
        )
        return _StubResponse(text)


def _find_repo_root() -> Path:
    """Find repo root by CLAUDE.md + backend/ markers (sustained TB-3b 体例)."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "CLAUDE.md").exists() and (parent / "backend").is_dir():
            return parent
    return here.parent.parent.parent


_REPO_ROOT = _find_repo_root()


# ---------------------------------------------------------------------------
# ReflectionDimension StrEnum
# ---------------------------------------------------------------------------


class TestReflectionDimension:
    def test_exact_5_values(self) -> None:
        assert set(ReflectionDimension) == {
            ReflectionDimension.DETECTION,
            ReflectionDimension.THRESHOLD,
            ReflectionDimension.ACTION,
            ReflectionDimension.CONTEXT,
            ReflectionDimension.STRATEGY,
        }

    def test_string_serialization_lowercase(self) -> None:
        assert ReflectionDimension.DETECTION.value == "detection"
        assert ReflectionDimension.THRESHOLD.value == "threshold"
        assert ReflectionDimension.ACTION.value == "action"
        assert ReflectionDimension.CONTEXT.value == "context"
        assert ReflectionDimension.STRATEGY.value == "strategy"

    def test_strenum_natural_str_subclass(self) -> None:
        # StrEnum should JSON-serialize naturally as str (sustained TB-3a ActionTaken).
        assert json.dumps(ReflectionDimension.DETECTION) == '"detection"'


# ---------------------------------------------------------------------------
# ReflectionInput frozen dataclass
# ---------------------------------------------------------------------------


class TestReflectionInput:
    def test_valid_minimal(self) -> None:
        inp = _valid_input()
        assert inp.period_label == "W18-2026"
        assert inp.period_start == _PERIOD_START
        assert inp.period_end == _PERIOD_END

    def test_empty_period_label_raises(self) -> None:
        with pytest.raises(ValueError, match="period_label must be non-empty"):
            _valid_input(period_label="")

    def test_whitespace_period_label_raises(self) -> None:
        with pytest.raises(ValueError, match="period_label must be non-empty"):
            _valid_input(period_label="   ")

    def test_naive_period_start_raises(self) -> None:
        with pytest.raises(ValueError, match="period_start must be tz-aware"):
            _valid_input(period_start=datetime(2026, 5, 4, 0, 0))

    def test_naive_period_end_raises(self) -> None:
        with pytest.raises(ValueError, match="period_end must be tz-aware"):
            _valid_input(period_end=datetime(2026, 5, 11, 0, 0))

    def test_period_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match="must be > period_start"):
            _valid_input(period_end=_PERIOD_START - timedelta(days=1))

    def test_period_end_equal_start_raises(self) -> None:
        with pytest.raises(ValueError, match="must be > period_start"):
            _valid_input(period_end=_PERIOD_START)


# ---------------------------------------------------------------------------
# ReflectionDimensionOutput frozen dataclass
# ---------------------------------------------------------------------------


class TestReflectionDimensionOutput:
    def test_valid_minimal(self) -> None:
        out = ReflectionDimensionOutput(
            dimension=ReflectionDimension.DETECTION,
            summary="OK",
        )
        assert out.findings == []
        assert out.candidates == []

    def test_empty_summary_raises(self) -> None:
        with pytest.raises(ValueError, match="summary must be non-empty"):
            ReflectionDimensionOutput(
                dimension=ReflectionDimension.DETECTION,
                summary="",
            )

    def test_summary_500_char_cap(self) -> None:
        with pytest.raises(ValueError, match="exceeds 500-char hard cap"):
            ReflectionDimensionOutput(
                dimension=ReflectionDimension.DETECTION,
                summary="x" * 501,
            )

    def test_to_jsonable(self) -> None:
        out = ReflectionDimensionOutput(
            dimension=ReflectionDimension.DETECTION,
            summary="OK",
            findings=["f1", "f2"],
            candidates=["c1"],
        )
        d = out.to_jsonable()
        assert d == {
            "dimension": "detection",
            "summary": "OK",
            "findings": ["f1", "f2"],
            "candidates": ["c1"],
        }


# ---------------------------------------------------------------------------
# ReflectionOutput frozen dataclass
# ---------------------------------------------------------------------------


def _valid_output_5dim() -> ReflectionOutput:
    dims = tuple(
        ReflectionDimensionOutput(
            dimension=dim,
            summary=f"{dim.value} summary",
            findings=[],
            candidates=[],
        )
        for dim in ReflectionDimension
    )
    return ReflectionOutput(
        period_label="W18-2026",
        generated_at=_NOW,
        reflections=dims,
        overall_summary="W18 overall: minimal volatility.",
    )


class TestReflectionOutput:
    def test_valid_5dim(self) -> None:
        out = _valid_output_5dim()
        assert len(out.reflections) == 5

    def test_missing_dimension_raises(self) -> None:
        # Build only 4 dimensions, missing STRATEGY.
        dims = tuple(
            ReflectionDimensionOutput(dimension=dim, summary=f"{dim.value}")
            for dim in [
                ReflectionDimension.DETECTION,
                ReflectionDimension.THRESHOLD,
                ReflectionDimension.ACTION,
                ReflectionDimension.CONTEXT,
            ]
        )
        with pytest.raises(ValueError, match="must contain exactly 5 dimensions"):
            ReflectionOutput(
                period_label="W18-2026",
                generated_at=_NOW,
                reflections=dims,
                overall_summary="x",
            )

    def test_duplicate_dimension_raises(self) -> None:
        # 5 entries but DETECTION twice (no STRATEGY).
        dims = tuple(
            [
                ReflectionDimensionOutput(dimension=ReflectionDimension.DETECTION, summary="d1"),
                ReflectionDimensionOutput(dimension=ReflectionDimension.THRESHOLD, summary="t"),
                ReflectionDimensionOutput(dimension=ReflectionDimension.ACTION, summary="a"),
                ReflectionDimensionOutput(dimension=ReflectionDimension.CONTEXT, summary="c"),
                ReflectionDimensionOutput(dimension=ReflectionDimension.DETECTION, summary="d2"),
            ]
        )
        with pytest.raises(ValueError, match="duplicate dimension"):
            ReflectionOutput(
                period_label="W18-2026",
                generated_at=_NOW,
                reflections=dims,
                overall_summary="x",
            )

    def test_naive_generated_at_raises(self) -> None:
        dims = _valid_output_5dim().reflections
        with pytest.raises(ValueError, match="generated_at must be tz-aware"):
            ReflectionOutput(
                period_label="W18-2026",
                generated_at=datetime(2026, 5, 11, 19, 0),
                reflections=dims,
                overall_summary="x",
            )

    def test_empty_period_label_raises(self) -> None:
        dims = _valid_output_5dim().reflections
        with pytest.raises(ValueError, match="period_label must be non-empty"):
            ReflectionOutput(
                period_label="",
                generated_at=_NOW,
                reflections=dims,
                overall_summary="x",
            )

    def test_overall_summary_empty_raises(self) -> None:
        dims = _valid_output_5dim().reflections
        with pytest.raises(ValueError, match="overall_summary must be non-empty"):
            ReflectionOutput(
                period_label="W18-2026",
                generated_at=_NOW,
                reflections=dims,
                overall_summary="",
            )

    def test_overall_summary_600_char_cap(self) -> None:
        dims = _valid_output_5dim().reflections
        with pytest.raises(ValueError, match="exceeds 600-char hard cap"):
            ReflectionOutput(
                period_label="W18-2026",
                generated_at=_NOW,
                reflections=dims,
                overall_summary="x" * 601,
            )

    def test_get_dimension(self) -> None:
        out = _valid_output_5dim()
        d = out.get_dimension(ReflectionDimension.THRESHOLD)
        assert d.dimension is ReflectionDimension.THRESHOLD
        assert d.summary == "threshold summary"

    def test_to_jsonable(self) -> None:
        out = _valid_output_5dim()
        d = out.to_jsonable()
        assert d["period_label"] == "W18-2026"
        assert d["generated_at"] == _NOW.isoformat()
        assert len(d["reflections"]) == 5
        assert d["overall_summary"] == "W18 overall: minimal volatility."


# ---------------------------------------------------------------------------
# _strip_code_fence + _load_prompt
# ---------------------------------------------------------------------------


class TestStripCodeFence:
    def test_no_fence_passthrough(self) -> None:
        assert _strip_code_fence('{"x":1}') == '{"x":1}'

    def test_strip_json_fence(self) -> None:
        wrapped = '```json\n{"x":1}\n```'
        assert _strip_code_fence(wrapped) == '{"x":1}'

    def test_strip_bare_fence(self) -> None:
        wrapped = '```\n{"x":1}\n```'
        assert _strip_code_fence(wrapped) == '{"x":1}'

    def test_strip_with_whitespace(self) -> None:
        wrapped = '   \n```json\n{"x":1}\n```\n  '
        assert _strip_code_fence(wrapped) == '{"x":1}'


class TestLoadPrompt:
    def test_load_production_yaml(self) -> None:
        """Verify production reflector_v1.yaml loads cleanly + has required schema."""
        data = _load_prompt(REFLECTOR_PROMPT_PATH)
        assert data["version"] == PROMPT_VERSION
        assert "system_prompt" in data
        assert "user_template" in data
        # User template must accept all ReflectionInput field substitutions.
        for placeholder in (
            "{period_label}",
            "{period_start}",
            "{period_end}",
            "{events_summary}",
            "{plans_summary}",
            "{pnl_outcome}",
            "{rag_top5}",
        ):
            assert placeholder in data["user_template"], f"missing placeholder {placeholder}"

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.yaml"
        with pytest.raises(PromptLoadError, match="not found"):
            _load_prompt(missing)

    def test_load_missing_key_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("version: v1\nsystem_prompt: hello\n", encoding="utf-8")
        with pytest.raises(PromptLoadError, match="missing required key"):
            _load_prompt(bad)

    def test_load_wrong_version_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "version: v2\nsystem_prompt: x\nuser_template: y\n",
            encoding="utf-8",
        )
        with pytest.raises(PromptLoadError, match="version mismatch"):
            _load_prompt(bad)


# ---------------------------------------------------------------------------
# _parse_reflection_response
# ---------------------------------------------------------------------------


class TestParseReflectionResponse:
    def test_happy_path_5dim(self) -> None:
        raw = json.dumps(_valid_response_dict())
        out = _parse_reflection_response(raw, period_label="W18-2026", generated_at=_NOW)
        assert len(out.reflections) == 5
        assert out.raw_response == raw

    def test_code_fence_wrapped(self) -> None:
        raw = f"```json\n{json.dumps(_valid_response_dict())}\n```"
        out = _parse_reflection_response(raw, period_label="W18-2026", generated_at=_NOW)
        assert out.overall_summary.startswith("W18 复盘")

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(ReflectorAgentError, match="JSON parse failure"):
            _parse_reflection_response("not json", period_label="x", generated_at=_NOW)

    def test_root_not_dict_raises(self) -> None:
        with pytest.raises(ReflectorAgentError, match="root must be JSON object"):
            _parse_reflection_response("[1,2,3]", period_label="x", generated_at=_NOW)

    def test_missing_overall_summary_raises(self) -> None:
        bad = _valid_response_dict()
        del bad["overall_summary"]
        with pytest.raises(ReflectorAgentError, match="missing 'overall_summary'"):
            _parse_reflection_response(json.dumps(bad), period_label="x", generated_at=_NOW)

    def test_missing_reflections_raises(self) -> None:
        bad = _valid_response_dict()
        del bad["reflections"]
        with pytest.raises(ReflectorAgentError, match="missing 'reflections'"):
            _parse_reflection_response(json.dumps(bad), period_label="x", generated_at=_NOW)

    def test_missing_dimension_raises(self) -> None:
        bad = _valid_response_dict()
        del bad["reflections"]["strategy"]
        with pytest.raises(ReflectorAgentError, match="missing dimension 'strategy'"):
            _parse_reflection_response(json.dumps(bad), period_label="x", generated_at=_NOW)

    def test_dimension_summary_empty_raises(self) -> None:
        bad = _valid_response_dict()
        bad["reflections"]["detection"]["summary"] = ""
        with pytest.raises(ReflectorAgentError, match="must be.*non-empty str"):
            _parse_reflection_response(json.dumps(bad), period_label="x", generated_at=_NOW)

    def test_dimension_findings_not_list_raises(self) -> None:
        bad = _valid_response_dict()
        bad["reflections"]["detection"]["findings"] = "not a list"
        with pytest.raises(ReflectorAgentError, match="findings.*must be list"):
            _parse_reflection_response(json.dumps(bad), period_label="x", generated_at=_NOW)

    def test_dimension_candidates_not_list_raises(self) -> None:
        bad = _valid_response_dict()
        bad["reflections"]["detection"]["candidates"] = {"oops": 1}
        with pytest.raises(ReflectorAgentError, match="candidates.*must be list"):
            _parse_reflection_response(json.dumps(bad), period_label="x", generated_at=_NOW)

    def test_findings_coerce_to_str_and_filter_none(self) -> None:
        bad = _valid_response_dict()
        bad["reflections"]["detection"]["findings"] = ["f1", None, 42, ""]
        out = _parse_reflection_response(json.dumps(bad), period_label="x", generated_at=_NOW)
        d = out.get_dimension(ReflectionDimension.DETECTION)
        assert d.findings == ["f1", "42"]  # None + empty filtered, 42 coerced


# ---------------------------------------------------------------------------
# ReflectorAgent (lazy yaml + reflect)
# ---------------------------------------------------------------------------


class TestReflectorAgent:
    def test_lazy_prompt_load(self) -> None:
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        assert agent._prompt_cache is None
        # First reflect triggers yaml load.
        agent.reflect(_valid_input(), now=_NOW)
        assert agent._prompt_cache is not None

    def test_reflect_dispatches_v4pro_task(self) -> None:
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        agent.reflect(_valid_input(), decision_id="trace-123", now=_NOW)
        assert len(router.calls) == 1
        call = router.calls[0]
        assert call["task"] is RiskTaskType.RISK_REFLECTOR
        assert call["decision_id"] == "trace-123"
        assert len(call["messages"]) == 2
        assert call["messages"][0].role == "system"
        assert call["messages"][1].role == "user"

    def test_reflect_substitutes_user_template(self) -> None:
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        agent.reflect(_valid_input(), now=_NOW)
        user_content = router.calls[0]["messages"][1].content
        # User template substitutions must be present.
        assert "W18-2026" in user_content
        assert "12 alerts" in user_content
        assert "STAGED: 8 executed" in user_content

    def test_reflect_returns_reflection_output(self) -> None:
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        out = agent.reflect(_valid_input(), now=_NOW)
        assert isinstance(out, ReflectionOutput)
        assert out.period_label == "W18-2026"
        assert out.generated_at == _NOW
        assert len(out.reflections) == 5

    def test_reflect_now_default_to_utc(self) -> None:
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        out = agent.reflect(_valid_input())
        assert out.generated_at.tzinfo is not None

    def test_reflect_naive_now_raises(self) -> None:
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        with pytest.raises(ValueError, match="now must be tz-aware"):
            agent.reflect(_valid_input(), now=datetime(2026, 5, 11, 19, 0))

    def test_reflect_router_failure_propagates(self) -> None:
        router = _StubRouter(raise_exc=RuntimeError("LiteLLM timeout"))
        agent = ReflectorAgent(router=router)
        with pytest.raises(RuntimeError, match="LiteLLM timeout"):
            agent.reflect(_valid_input(), now=_NOW)

    def test_reflect_empty_content_raises(self) -> None:
        router = _StubRouter(response_text="")
        agent = ReflectorAgent(router=router)
        with pytest.raises(ReflectorAgentError, match="must be non-empty str"):
            agent.reflect(_valid_input(), now=_NOW)

    def test_reflect_malformed_json_raises_reflector_error(self) -> None:
        router = _StubRouter(response_text="not json at all")
        agent = ReflectorAgent(router=router)
        with pytest.raises(ReflectorAgentError, match="JSON parse failure"):
            agent.reflect(_valid_input(), now=_NOW)

    def test_reflect_brace_escape_in_summary_str(self) -> None:
        """PR #343 reviewer-fix MEDIUM 1: free-form summary str with literal
        `{` / `}` (e.g. JSON snippets in events_summary) must NOT break
        str.format() substitution. TB-4c will compose DB data containing
        braces — proactive guard."""
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        # Summary with JSON-like content + dict repr (real-world TB-4c case)
        inp_with_braces = _valid_input(
            events_summary='{"event_id": 42, "symbol": "600519.SH"}',
            plans_summary="STAGED execute_at=2026-05-11T14:00 → {symbol: 600519.SH, qty: 1000}",
            pnl_outcome="Day P&L: {'2026-05-08': -0.5%, '2026-05-09': +1.2%}",
            rag_top5='[{"sim": 0.84, "lesson": "STAGED 30min default"}]',
        )
        # Should NOT raise — escape produces safe-to-format str.
        out = agent.reflect(inp_with_braces, now=_NOW)
        assert isinstance(out, ReflectionOutput)
        # Verify substituted content reached user message intact (after escape
        # produces `{{`/`}}` in template-time → renders as single `{`/`}` in final string).
        user_msg = router.calls[0]["messages"][1].content
        assert "600519.SH" in user_msg
        assert "STAGED" in user_msg


# ---------------------------------------------------------------------------
# RiskReflectorAgent application service skeleton
# ---------------------------------------------------------------------------


class TestRiskReflectorAgentService:
    def test_lazy_router_factory(self) -> None:
        router_calls = {"n": 0}

        def factory() -> _StubRouter:
            router_calls["n"] += 1
            return _StubRouter()

        svc = RiskReflectorAgent(router_factory=factory)
        # Constructor does NOT invoke factory.
        assert router_calls["n"] == 0
        svc.reflect(_valid_input(), now=_NOW)
        assert router_calls["n"] == 1
        # Second reflect reuses cached agent.
        svc.reflect(_valid_input(), now=_NOW)
        assert router_calls["n"] == 1

    def test_delegates_to_reflector_agent(self) -> None:
        router = _StubRouter()
        svc = RiskReflectorAgent(router_factory=lambda: router)
        out = svc.reflect(_valid_input(), decision_id="trace-456", now=_NOW)
        assert isinstance(out, ReflectionOutput)
        assert len(router.calls) == 1
        assert router.calls[0]["decision_id"] == "trace-456"

    def test_agent_factory_override_for_tests(self) -> None:
        """agent_factory hook allows test injection of pre-constructed ReflectorAgent."""
        captured = {"router": None}

        def custom_factory(router: Any) -> ReflectorAgent:
            captured["router"] = router
            return ReflectorAgent(router=router)

        router = _StubRouter()
        svc = RiskReflectorAgent(
            router_factory=lambda: router,
            agent_factory=custom_factory,
        )
        svc.reflect(_valid_input(), now=_NOW)
        assert captured["router"] is router

    def test_propagates_reflector_error(self) -> None:
        router = _StubRouter(response_text="malformed")
        svc = RiskReflectorAgent(router_factory=lambda: router)
        with pytest.raises(ReflectorAgentError):
            svc.reflect(_valid_input(), now=_NOW)


# ---------------------------------------------------------------------------
# Integration: prompt yaml + agent + stub router round-trip
# ---------------------------------------------------------------------------


class TestEndToEndStubIntegration:
    """Smoke: real prompt yaml + real ReflectorAgent + stub router → ReflectionOutput.

    Verifies the full path works without LLM call. Sustained TB-2b 体例 (mock-LLM
    smoke without real provider).
    """

    def test_full_path_with_real_prompt(self) -> None:
        # Use real prompt yaml + stub router with valid 5-dim response.
        router = _StubRouter()
        agent = ReflectorAgent(router=router)
        inp = _valid_input()

        out = agent.reflect(inp, decision_id="e2e-smoke-tb4a", now=_NOW)

        # Verify prompt yaml loaded + system message contains key 5-dim cue.
        system_msg = router.calls[0]["messages"][0].content
        for cue in ("Detection", "Threshold", "Action", "Context", "Strategy"):
            assert cue in system_msg, f"prompt yaml missing 5-dim cue: {cue}"

        # Verify output 5-dim all present.
        for dim in ReflectionDimension:
            d = out.get_dimension(dim)
            assert d.summary, f"missing dimension summary: {dim.value}"

        # Audit-trail: raw_response preserved.
        assert out.raw_response is not None
        assert "overall_summary" in out.raw_response
