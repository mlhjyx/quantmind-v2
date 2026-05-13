"""V3 §8 ReflectorAgent — V4-Pro single-call wrapper (TB-4a).

Engine PURE side wrapper around LiteLLM V4-Pro call for V3 §8.1 5 维反思:
  - yaml prompt load (sustained TB-2b agents.py _load_prompt 体例)
  - LiteLLMRouter completion call via RiskTaskType.RISK_REFLECTOR
    (deepseek-v4-pro per ADR-036 sustained, already wired in router.py)
  - JSON parse + code-fence strip (V4-Pro occasional markdown wrap)
  - 5 维 schema validation (Detection/Threshold/Action/Context/Strategy 全)
  - Output: ReflectionOutput frozen dataclass with audit-trail raw_response

DI pattern sustained (TB-2b BullAgent/BearAgent/RegimeJudge `_RouterProtocol`):
  - Constructor accepts router (LiteLLMRouter | BudgetAwareRouter | test stub)
    via duck typing — anything implementing .completion(task, messages, ...)

Cost budget (V3 §16.2 line 726 sustained per ADR-064 cumulative):
  - V4-Pro RiskReflector ~$5-10/月 estimate (4 周/月 + 1 月/月 + ~2 event/月 ≈
    7 calls/month × ~3500 tokens × $0.001/1K ≈ $0.025/月 actual estimate ←
    much lower than budget; final 实测 baseline 锁 TB-4 closure ADR-069)

关联 V3: §8.1 (5 维反思) / §8.4 (V4-Pro 路由) / §11.2 line 1228 (RiskReflectorAgent
  location SSOT — Application orchestration at app/services/risk/risk_reflector_agent.py
  composes 本 ReflectorAgent wrapper)
关联 ADR: ADR-022 (反 retroactive) / ADR-031 (LiteLLMRouter path) / ADR-032
  (caller bootstrap factory) / ADR-036 (V4-Pro mapping) / ADR-064 D2 sustained /
  ADR-069 候选 (TB-4 closure cumulative)
关联 铁律: 22 / 24 (单一职责 single-call wrapper) / 31 (Engine PURE wrapper) /
  33 (fail-loud JSON parse + schema) / 34 (yaml prompt SSOT path)
关联 LL: LL-067 reviewer / LL-098 X10 / LL-115 family (prompt drift) /
  LL-157 (silent skip — V4-Pro timeout fail-loud) / LL-160 (DI factory)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from backend.qm_platform.llm import LLMMessage, RiskTaskType

from .interface import (
    ReflectionDimension,
    ReflectionDimensionOutput,
    ReflectionInput,
    ReflectionOutput,
    ReflectorAgentError,
)

if TYPE_CHECKING:
    from backend.qm_platform.llm import LLMResponse

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 常量 (V3 §8.1 + V3 §8.4 + DDL 锁定, sustained TB-2b agents.py 体例)
# ─────────────────────────────────────────────────────────────

PROMPT_VERSION: str = "v1"
"""yaml prompt version (sustained TB-2b regime_judge_v1.yaml 体例)."""

REFLECTOR_PROMPT_PATH: Path = (
    Path(__file__).resolve().parents[4] / "prompts" / "risk" / "reflector_v1.yaml"
)
"""yaml prompt path — resolve from backend/qm_platform/risk/reflector/agent.py.

parents[0]=reflector, [1]=risk, [2]=qm_platform, [3]=backend, [4]=repo_root.
Sustained TB-2b agents.py path resolution 体例 (BULL/BEAR/JUDGE_PROMPT_PATH).
"""

REQUIRED_DIMENSIONS_COUNT: int = 5
"""V3 §8.1 line 927-933: Detection / Threshold / Action / Context / Strategy
5 维必全 (反缺反多反重复, sustained TB-2b REQUIRED_ARGS_COUNT=3 体例)."""


# ─────────────────────────────────────────────────────────────
# Router protocol (DI 体例, sustained TB-2b _RouterProtocol)
# ─────────────────────────────────────────────────────────────


class _RouterProtocol(Protocol):
    """LiteLLMRouter | BudgetAwareRouter | test stub 共通 completion 接口 (duck typing)."""

    def completion(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        decision_id: str | None = ...,
        **kwargs: Any,
    ) -> LLMResponse: ...


# ─────────────────────────────────────────────────────────────
# Prompt loading helpers (sustained TB-2b agents.py 体例)
# ─────────────────────────────────────────────────────────────


class PromptLoadError(RuntimeError):
    """yaml prompt 加载或 schema 失败 (沿用 TB-2b PromptLoadError 体例 + 铁律 33+34)."""


_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n(?P<body>.*?)\n```\s*$",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` markdown fence — V4-Pro 真生产 occasional wrap.

    Sustained TB-2b agents.py _strip_code_fence 体例 (反 markdown fence in JSON).
    """
    m = _CODE_FENCE_RE.match(text.strip())
    if m:
        return m.group("body").strip()
    return text.strip()


def _load_prompt(path: Path = REFLECTOR_PROMPT_PATH) -> dict[str, Any]:
    """Load + validate yaml prompt schema (sustained TB-2b agents.py _load_prompt 体例).

    required keys: version (str) / system_prompt (str) / user_template (str).
    Raises PromptLoadError on file IO / parse / schema 不全.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise PromptLoadError(
            f"reflector prompt yaml not found at {path} (铁律 34 SSOT violation)"
        ) from exc
    except yaml.YAMLError as exc:
        raise PromptLoadError(
            f"reflector prompt yaml parse failure at {path}"
        ) from exc

    if not isinstance(data, dict):
        raise PromptLoadError(
            f"reflector prompt yaml root must be dict, got {type(data).__name__}"
        )
    for key in ("version", "system_prompt", "user_template"):
        if key not in data:
            raise PromptLoadError(
                f"reflector prompt yaml missing required key {key!r} at {path}"
            )
        if not isinstance(data[key], str):
            raise PromptLoadError(
                f"reflector prompt yaml {key!r} must be str, got {type(data[key]).__name__}"
            )

    if data["version"] != PROMPT_VERSION:
        raise PromptLoadError(
            f"reflector prompt yaml version mismatch: expected {PROMPT_VERSION!r}, "
            f"got {data['version']!r}"
        )

    return data


# ─────────────────────────────────────────────────────────────
# Response parsing — 5 维 JSON schema validation
# ─────────────────────────────────────────────────────────────


def _parse_reflection_response(
    raw_text: str,
    *,
    period_label: str,
    generated_at: datetime,
) -> ReflectionOutput:
    """Parse V4-Pro JSON response → ReflectionOutput frozen dataclass.

    Args:
        raw_text: V4-Pro response.content_str. May contain markdown code fence.
        period_label: pass-through to ReflectionOutput.period_label.
        generated_at: pass-through to ReflectionOutput.generated_at (caller-supplied tz-aware).

    Returns:
        ReflectionOutput with raw_response audit-trail preserved.

    Raises:
        ReflectorAgentError: JSON parse failure / schema mismatch / 5 维 不全 /
            individual dimension validation failure (chain original cause).
    """
    cleaned = _strip_code_fence(raw_text)
    try:
        parsed: Any = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ReflectorAgentError(
            f"reflector V4-Pro response JSON parse failure (text_len={len(raw_text)}, "
            f"cleaned_len={len(cleaned)})"
        ) from exc

    if not isinstance(parsed, dict):
        raise ReflectorAgentError(
            f"reflector V4-Pro response root must be JSON object, got {type(parsed).__name__}"
        )

    # Schema: {overall_summary: str, reflections: {detection: {...}, threshold: {...}, ...}}
    if "overall_summary" not in parsed:
        raise ReflectorAgentError(
            "reflector V4-Pro response missing 'overall_summary' field"
        )
    overall_summary = parsed["overall_summary"]
    if not isinstance(overall_summary, str):
        raise ReflectorAgentError(
            f"reflector V4-Pro response 'overall_summary' must be str, "
            f"got {type(overall_summary).__name__}"
        )

    if "reflections" not in parsed:
        raise ReflectorAgentError(
            "reflector V4-Pro response missing 'reflections' field"
        )
    reflections_raw = parsed["reflections"]
    if not isinstance(reflections_raw, dict):
        raise ReflectorAgentError(
            f"reflector V4-Pro response 'reflections' must be dict, "
            f"got {type(reflections_raw).__name__}"
        )

    # Parse each of the 5 dimensions — fail-loud on any missing / malformed.
    dim_outputs: list[ReflectionDimensionOutput] = []
    for dim in ReflectionDimension:
        key = dim.value
        if key not in reflections_raw:
            raise ReflectorAgentError(
                f"reflector V4-Pro response missing dimension {key!r} "
                f"(V3 §8.1 line 927-933 sustained 5 维必全)"
            )
        dim_data = reflections_raw[key]
        if not isinstance(dim_data, dict):
            raise ReflectorAgentError(
                f"reflector V4-Pro response 'reflections.{key}' must be dict, "
                f"got {type(dim_data).__name__}"
            )
        summary = dim_data.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ReflectorAgentError(
                f"reflector V4-Pro response 'reflections.{key}.summary' must be "
                f"non-empty str"
            )
        findings_raw = dim_data.get("findings", [])
        if not isinstance(findings_raw, list):
            raise ReflectorAgentError(
                f"reflector V4-Pro response 'reflections.{key}.findings' must be list"
            )
        candidates_raw = dim_data.get("candidates", [])
        if not isinstance(candidates_raw, list):
            raise ReflectorAgentError(
                f"reflector V4-Pro response 'reflections.{key}.candidates' must be list"
            )
        # Coerce each list item to str (V4-Pro may emit numbers / null, normalize).
        findings = [str(f).strip() for f in findings_raw if f is not None and str(f).strip()]
        candidates = [
            str(c).strip() for c in candidates_raw if c is not None and str(c).strip()
        ]
        try:
            dim_outputs.append(
                ReflectionDimensionOutput(
                    dimension=dim,
                    summary=summary.strip(),
                    findings=findings,
                    candidates=candidates,
                )
            )
        except ValueError as exc:
            # Re-raise as ReflectorAgentError for caller single-exception catch.
            raise ReflectorAgentError(
                f"reflector V4-Pro response 'reflections.{key}' validation failure"
            ) from exc

    try:
        return ReflectionOutput(
            period_label=period_label,
            generated_at=generated_at,
            reflections=tuple(dim_outputs),
            overall_summary=overall_summary.strip(),
            raw_response=raw_text,
        )
    except ValueError as exc:
        raise ReflectorAgentError(
            "reflector V4-Pro response ReflectionOutput construction failure"
        ) from exc


# ─────────────────────────────────────────────────────────────
# ReflectorAgent — V4-Pro single-call wrapper
# ─────────────────────────────────────────────────────────────


class ReflectorAgent:
    """V3 §8.1 5 维反思 V4-Pro single-call Engine PURE wrapper.

    Args:
        router: LiteLLMRouter | BudgetAwareRouter | test stub (duck-typed
            `_RouterProtocol`). Caller (TB-4c service / TB-4b Beat task)
            constructs via `from backend.qm_platform.llm import get_llm_router`.
        prompt_path: yaml prompt path. Default REFLECTOR_PROMPT_PATH —
            override for tests (sustained TB-2b 体例).

    Lifecycle:
      - Construction: validates router protocol via duck typing (no eager call).
      - First reflect(): lazy yaml load + cached on instance (~1 file read).
      - Subsequent reflect(): yaml cache hit (~0 cost).

    Thread-safety:
      - reflect() is concurrency-safe under typical Beat task (1 task at a time
        per Beat schedule per `--pool=solo --concurrency=1` sustained).
      - yaml cache populated on first reflect — no race per single-process Beat.
    """

    def __init__(
        self,
        router: _RouterProtocol,
        *,
        prompt_path: Path = REFLECTOR_PROMPT_PATH,
    ) -> None:
        self._router = router
        self._prompt_path = prompt_path
        self._prompt_cache: dict[str, Any] | None = None

    def _get_prompt(self) -> dict[str, Any]:
        """Lazy yaml load + cache (sustained TB-2b agents.py 体例 simplified)."""
        if self._prompt_cache is None:
            self._prompt_cache = _load_prompt(self._prompt_path)
        return self._prompt_cache

    def reflect(
        self,
        input_data: ReflectionInput,
        *,
        decision_id: str | None = None,
        now: datetime | None = None,
    ) -> ReflectionOutput:
        """V3 §8.1 5 维反思 V4-Pro 单次 call + JSON parse + schema validate.

        Args:
            input_data: ReflectionInput dataclass (caller-prepared period
                + events_summary + plans_summary + pnl_outcome + rag_top5).
                TB-4a accepts pre-composed strs; TB-4c service will compose
                these from real DB queries.
            decision_id: optional UUID-like identifier for audit chain trace
                (sustained TB-2b agents.py decision_id 体例 — flows through
                LiteLLM router → llm_call_log table per ADR-031 cumulative).
            now: tz-aware datetime for ReflectionOutput.generated_at. None =
                current UTC. Tests pass fixed timestamp for determinism.

        Returns:
            ReflectionOutput with 5 维 ReflectionDimensionOutput tuple +
            overall_summary + raw_response audit-trail.

        Raises:
            PromptLoadError: yaml prompt file 缺失 / parse 失败 / schema 不全.
            ReflectorAgentError: V4-Pro response JSON parse / schema 不全 /
                individual dimension validation failure.
            (LLM-layer exceptions propagate — router.completion() may raise
             LiteLLM SDK errors per ADR-039 retry policy.)
        """
        if now is None:
            now = datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("ReflectorAgent.reflect: now must be tz-aware (铁律 41)")

        prompt = self._get_prompt()
        system_prompt = prompt["system_prompt"]
        user_template = prompt["user_template"]

        # Substitute user_template placeholders with ReflectionInput fields.
        # Sustained TB-2b agents.py .format(**kwargs) 体例.
        user_message = user_template.format(
            period_label=input_data.period_label,
            period_start=input_data.period_start.isoformat(),
            period_end=input_data.period_end.isoformat(),
            events_summary=input_data.events_summary,
            plans_summary=input_data.plans_summary,
            pnl_outcome=input_data.pnl_outcome,
            rag_top5=input_data.rag_top5,
        )

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_message),
        ]

        logger.info(
            "[risk-reflector] dispatching V4-Pro reflect period=%s decision_id=%s "
            "input_lens={events=%d, plans=%d, pnl=%d, rag=%d}",
            input_data.period_label,
            decision_id or "(none)",
            len(input_data.events_summary),
            len(input_data.plans_summary),
            len(input_data.pnl_outcome),
            len(input_data.rag_top5),
        )

        response = self._router.completion(
            task=RiskTaskType.RISK_REFLECTOR,
            messages=messages,
            decision_id=decision_id,
        )

        # LLMResponse contract: .content (str) — sustained TB-2b agents.py 体例.
        raw_text = getattr(response, "content", None)
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ReflectorAgentError(
                f"reflector V4-Pro response.content must be non-empty str, "
                f"got {type(raw_text).__name__}"
            )

        output = _parse_reflection_response(
            raw_text,
            period_label=input_data.period_label,
            generated_at=now,
        )

        logger.info(
            "[risk-reflector] reflect complete period=%s decision_id=%s "
            "overall_summary_len=%d total_findings=%d total_candidates=%d",
            input_data.period_label,
            decision_id or "(none)",
            len(output.overall_summary),
            sum(len(r.findings) for r in output.reflections),
            sum(len(r.candidates) for r in output.reflections),
        )

        return output
