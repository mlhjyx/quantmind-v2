"""V3 §5.3 Bull/Bear/Judge Agent classes — TB-2b LiteLLM wire layer.

3 Agent classes wrap LiteLLM router calls + prompt yaml loading + response parsing:
  - BullAgent (RiskTaskType.BULL_AGENT, V4-Pro per ADR-036)
  - BearAgent (RiskTaskType.BEAR_AGENT, V4-Pro per ADR-036)
  - RegimeJudge (RiskTaskType.JUDGE, V4-Pro per ADR-036)

Sustains 3-layer pattern (反 hidden coupling get_llm_router 内调):
  - 本模块 = Engine PURE side (response parsing + prompt loading)
  - app/services/risk/market_regime_service.py = Application orchestration side
  - Beat caller (TB-2c 留) = Schedule dispatch

DI 体例 (sustained NewsClassifierService pattern):
    from backend.qm_platform.llm import get_llm_router
    from backend.qm_platform.risk.regime.agents import BullAgent, BearAgent, RegimeJudge

    router = get_llm_router()
    bull = BullAgent(router=router)
    bull_args = bull.find_arguments(indicators, decision_id="...")

关联铁律: 22 / 33 (fail-loud JSON parse) / 34 (Config SSOT yaml path) / 41 (timezone-aware in caller)
关联 V3: §5.3 (Bull/Bear regime) / §11.2 line 1227 / §16.2 cost cap
关联 ADR: ADR-022 / ADR-036 (V4-Pro mapping) / ADR-064 (Plan v0.2 D2)
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from backend.qm_platform.llm import LLMMessage, RiskTaskType

from .interface import MarketRegimeError, RegimeArgument, RegimeLabel

if TYPE_CHECKING:
    from backend.qm_platform.llm import LLMResponse

    from .interface import MarketIndicators

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 常量 (V3 §5.3 + ADR-036 + DDL 锁定)
# ─────────────────────────────────────────────────────────────

PROMPT_VERSION: str = "v1"
"""yaml prompt version (sustained news_classifier_v1.yaml 体例)."""

BULL_PROMPT_PATH: Path = (
    Path(__file__).resolve().parents[4] / "prompts" / "risk" / "bull_agent_v1.yaml"
)
BEAR_PROMPT_PATH: Path = (
    Path(__file__).resolve().parents[4] / "prompts" / "risk" / "bear_agent_v1.yaml"
)
JUDGE_PROMPT_PATH: Path = (
    Path(__file__).resolve().parents[4] / "prompts" / "risk" / "regime_judge_v1.yaml"
)
"""yaml prompt paths — resolve from backend/qm_platform/risk/regime/agents.py.

parents[0]=regime, [1]=risk, [2]=qm_platform, [3]=backend, [4]=repo_root.
"""

REQUIRED_ARGS_COUNT: int = 3
"""V3 §5.3 line 660-661: Bull/Bear 各 3 论据 (反 4 反 2)."""


# ─────────────────────────────────────────────────────────────
# Router protocol (DI 体例, sustained NewsClassifierService _RouterProtocol)
# ─────────────────────────────────────────────────────────────


class _RouterProtocol(Protocol):
    """LiteLLMRouter | BudgetAwareRouter 共通 completion interface (duck typing)."""

    def completion(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        decision_id: str | None = ...,
        **kwargs: Any,
    ) -> LLMResponse: ...


# ─────────────────────────────────────────────────────────────
# Common helpers (yaml load + code fence strip + JSON parse, sustained 体例)
# ─────────────────────────────────────────────────────────────


class PromptLoadError(RuntimeError):
    """yaml prompt 加载或 schema 失败 (沿用铁律 33+34)."""


_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n(?P<body>.*?)\n```\s*$",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` markdown fence — V4-Pro 真生产 occasional wrap."""
    m = _CODE_FENCE_RE.match(text.strip())
    if m:
        return m.group("body").strip()
    return text.strip()


def _load_prompt(path: Path) -> dict[str, Any]:
    """Load + validate yaml prompt schema (sustained NewsClassifierService._load_prompt 体例).

    required keys: version (str) / system_prompt (str) / user_template (str).
    Raises PromptLoadError on file IO / parse / schema 不全.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise PromptLoadError(f"yaml prompt file not found: {path}") from e
    except yaml.YAMLError as e:
        raise PromptLoadError(f"yaml prompt parse failed: {path} ({e})") from e

    if not isinstance(data, dict):
        raise PromptLoadError(
            f"yaml prompt root must be mapping, got {type(data).__name__}: {path}"
        )

    required = ("version", "system_prompt", "user_template")
    for key in required:
        if key not in data:
            raise PromptLoadError(f"yaml prompt missing required key '{key}' at {path}")
        if not isinstance(data[key], str):
            raise PromptLoadError(
                f"yaml prompt key '{key}' must be str, got {type(data[key]).__name__}: {path}"
            )

    if data["version"] != PROMPT_VERSION:
        raise PromptLoadError(
            f"yaml prompt version mismatch: file={data['version']}, "
            f"expected={PROMPT_VERSION} at {path}"
        )

    return data


def _parse_json_response(response: LLMResponse) -> dict[str, Any]:
    """Parse LLM response → JSON dict + fail-loud on parse error (铁律 33 sustained)."""
    raw = response.content or ""
    json_text = _strip_code_fence(raw)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise MarketRegimeError(
            f"LLM response not JSON: {e}; raw_content_prefix={raw[:200]!r}"
        ) from e

    if not isinstance(payload, dict):
        raise MarketRegimeError(
            f"LLM response must be JSON object, got {type(payload).__name__}; "
            f"raw_content_prefix={raw[:200]!r}"
        )
    return payload


def _format_indicators_for_prompt(indicators: MarketIndicators) -> dict[str, str]:
    """Format MarketIndicators numeric fields for prompt template substitution.

    None → "null" (反 silent empty drop). Numeric → str(value).
    """
    j = indicators.to_jsonable()
    return {
        "timestamp": j["timestamp"],
        "sse_return": "null" if j["sse_return"] is None else f"{j['sse_return']:.4f}",
        "hs300_return": ("null" if j["hs300_return"] is None else f"{j['hs300_return']:.4f}"),
        "breadth_up": "null" if j["breadth_up"] is None else str(j["breadth_up"]),
        "breadth_down": ("null" if j["breadth_down"] is None else str(j["breadth_down"])),
        "north_flow_cny": ("null" if j["north_flow_cny"] is None else f"{j['north_flow_cny']:.2f}"),
        "iv_50etf": "null" if j["iv_50etf"] is None else f"{j['iv_50etf']:.4f}",
    }


# ─────────────────────────────────────────────────────────────
# Bull / Bear Agent base (shared 论据生成 logic)
# ─────────────────────────────────────────────────────────────


class _ArgumentsAgent:
    """Shared Bull/Bear logic — 3 RegimeArgument extraction from LLM JSON response.

    Subclass sets PROMPT_PATH + TASK (RiskTaskType.BULL_AGENT | .BEAR_AGENT).
    """

    PROMPT_PATH: Path
    TASK: RiskTaskType

    def __init__(
        self,
        router: _RouterProtocol,
        *,
        prompt_path: Path | None = None,
    ) -> None:
        self._router = router
        self._prompt = _load_prompt(prompt_path or self.PROMPT_PATH)

    def find_arguments(
        self,
        indicators: MarketIndicators,
        *,
        decision_id: str | None = None,
    ) -> tuple[tuple[RegimeArgument, RegimeArgument, RegimeArgument], Decimal]:
        """Call LLM → parse 3 RegimeArgument tuple + cost_usd Decimal.

        Returns:
            (3-tuple of RegimeArgument, response.cost_usd Decimal).

        Raises:
            MarketRegimeError: parse fail / wrong arg count / RegimeArgument validation
                fail (sustained 铁律 33 fail-loud).
        """
        messages = self._build_messages(indicators)
        response = self._router.completion(
            task=self.TASK,
            messages=messages,
            decision_id=decision_id,
        )
        payload = _parse_json_response(response)
        args = self._parse_arguments(payload)
        return args, response.cost_usd

    def _build_messages(self, indicators: MarketIndicators) -> list[LLMMessage]:
        """Build LLM messages from MarketIndicators + yaml prompt template."""
        system_content = self._prompt["system_prompt"]
        user_content = self._prompt["user_template"].format(
            **_format_indicators_for_prompt(indicators)
        )
        return [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=user_content),
        ]

    @staticmethod
    def _parse_arguments(
        payload: dict[str, Any],
    ) -> tuple[RegimeArgument, RegimeArgument, RegimeArgument]:
        """Extract + validate 3 RegimeArgument from LLM JSON payload.

        Sustains RegimeArgument.__post_init__ validation (non-empty argument +
        weight ∈ [0, 1]). Schema:
            {"arguments": [
                {"argument": "...", "evidence": "...", "weight": 0.x}, x3
            ]}
        """
        if "arguments" not in payload:
            raise MarketRegimeError(
                f"LLM response missing 'arguments' key; payload_keys={list(payload)}"
            )
        args_raw = payload["arguments"]
        if not isinstance(args_raw, list):
            raise MarketRegimeError(f"'arguments' must be list, got {type(args_raw).__name__}")
        if len(args_raw) != REQUIRED_ARGS_COUNT:
            raise MarketRegimeError(
                f"V3 §5.3 sustained: 'arguments' must have exactly "
                f"{REQUIRED_ARGS_COUNT} items, got {len(args_raw)}"
            )

        parsed: list[RegimeArgument] = []
        for i, raw_arg in enumerate(args_raw):
            if not isinstance(raw_arg, dict):
                raise MarketRegimeError(
                    f"arguments[{i}] must be object, got {type(raw_arg).__name__}"
                )
            if "argument" not in raw_arg:
                raise MarketRegimeError(f"arguments[{i}] missing 'argument' key")
            argument = str(raw_arg["argument"])
            evidence = str(raw_arg.get("evidence", ""))
            weight_raw = raw_arg.get("weight", 0.0)
            try:
                weight = float(weight_raw)
            except (TypeError, ValueError) as e:
                raise MarketRegimeError(f"arguments[{i}].weight not numeric: {weight_raw!r}") from e

            try:
                parsed.append(
                    RegimeArgument(
                        argument=argument,
                        evidence=evidence,
                        weight=weight,
                    )
                )
            except ValueError as e:
                # RegimeArgument.__post_init__ raised — propagate as MarketRegimeError.
                raise MarketRegimeError(f"arguments[{i}] validation failed: {e}") from e
        # mypy: tuple of fixed length 3
        return parsed[0], parsed[1], parsed[2]


class BullAgent(_ArgumentsAgent):
    """V3 §5.3 Bull Agent — V4-Pro 找 3 看多论据 (ADR-036 V4-Pro mapping)."""

    PROMPT_PATH = BULL_PROMPT_PATH
    TASK = RiskTaskType.BULL_AGENT


class BearAgent(_ArgumentsAgent):
    """V3 §5.3 Bear Agent — V4-Pro 找 3 看空论据 (ADR-036 V4-Pro mapping)."""

    PROMPT_PATH = BEAR_PROMPT_PATH
    TASK = RiskTaskType.BEAR_AGENT


# ─────────────────────────────────────────────────────────────
# Regime Judge — 加权 6 论据 → regime + confidence + reasoning
# ─────────────────────────────────────────────────────────────


class RegimeJudge:
    """V3 §5.3 Judge — V4-Pro 加权 Bull/Bear 6 论据 → regime + confidence + reasoning."""

    PROMPT_PATH = JUDGE_PROMPT_PATH
    TASK = RiskTaskType.JUDGE

    def __init__(
        self,
        router: _RouterProtocol,
        *,
        prompt_path: Path | None = None,
    ) -> None:
        self._router = router
        self._prompt = _load_prompt(prompt_path or self.PROMPT_PATH)

    def judge(
        self,
        indicators: MarketIndicators,
        bull_arguments: tuple[RegimeArgument, ...],
        bear_arguments: tuple[RegimeArgument, ...],
        *,
        decision_id: str | None = None,
    ) -> tuple[RegimeLabel, float, str, Decimal]:
        """Call LLM → parse (regime, confidence, reasoning, cost_usd).

        Returns:
            4-tuple (RegimeLabel enum, confidence ∈ [0,1] float, reasoning str, cost_usd Decimal).

        Raises:
            MarketRegimeError: parse fail / invalid regime / confidence out-of-range.
        """
        messages = self._build_messages(indicators, bull_arguments, bear_arguments)
        response = self._router.completion(
            task=self.TASK,
            messages=messages,
            decision_id=decision_id,
        )
        payload = _parse_json_response(response)
        regime, confidence, reasoning = self._parse_judgment(payload)
        return regime, confidence, reasoning, response.cost_usd

    def _build_messages(
        self,
        indicators: MarketIndicators,
        bull_args: tuple[RegimeArgument, ...],
        bear_args: tuple[RegimeArgument, ...],
    ) -> list[LLMMessage]:
        """Build LLM messages — indicators + Bull/Bear 6 论据 JSON snippets."""
        system_content = self._prompt["system_prompt"]
        substitutions = _format_indicators_for_prompt(indicators)
        substitutions["bull_arguments"] = json.dumps(
            [
                {"argument": a.argument, "evidence": a.evidence, "weight": a.weight}
                for a in bull_args
            ],
            ensure_ascii=False,
            indent=2,
        )
        substitutions["bear_arguments"] = json.dumps(
            [
                {"argument": a.argument, "evidence": a.evidence, "weight": a.weight}
                for a in bear_args
            ],
            ensure_ascii=False,
            indent=2,
        )
        user_content = self._prompt["user_template"].format(**substitutions)
        return [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=user_content),
        ]

    @staticmethod
    def _parse_judgment(
        payload: dict[str, Any],
    ) -> tuple[RegimeLabel, float, str]:
        """Parse Judge JSON → (RegimeLabel, confidence, reasoning) + validate.

        Schema: {"regime": "Bull|Bear|Neutral|Transitioning",
                 "confidence": 0.xx, "reasoning": "..."}
        """
        required = ("regime", "confidence", "reasoning")
        missing = [k for k in required if k not in payload]
        if missing:
            raise MarketRegimeError(f"Judge response missing keys: {missing}")

        regime_raw = str(payload["regime"])
        # Strict label match — RegimeLabel.value 全 4 状态.
        try:
            regime = RegimeLabel(regime_raw)
        except ValueError as e:
            raise MarketRegimeError(
                f"Judge regime label invalid (must be Bull/Bear/Neutral/Transitioning): "
                f"{regime_raw!r}"
            ) from e

        try:
            confidence = float(payload["confidence"])
        except (TypeError, ValueError) as e:
            raise MarketRegimeError(
                f"Judge confidence not numeric: {payload['confidence']!r}"
            ) from e
        if not (0.0 <= confidence <= 1.0):
            raise MarketRegimeError(f"Judge confidence out of [0, 1]: {confidence}")

        reasoning = str(payload["reasoning"])
        return regime, confidence, reasoning
