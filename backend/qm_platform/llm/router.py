"""LiteLLMRouter — V3 LLM 路由 only path (S2.1 sub-task core).

归属: Framework #LLM 平台 SDK 子模块 (V3 §5.5 / ADR-031).

scope (S2.1 — 本 PR):
- LiteLLM Router 实例化 (sustained config/litellm_router.yaml PR #221 sediment)
- 7 任务 → model alias 路由 (Python in-code, 反 yaml-Python 双 SSOT 漂移)
- LLMResponse 包装 (含 decision_id 透传 + is_fallback 检测)
- 0 budget guardrails (S2.2 scope)
- 0 cost monitoring + audit trail INSERT (S2.3 scope)

7 任务 → model alias mapping (沿用 V3 §5.5 + 决议 3 (a)):
    NEWS_CLASSIFY / FUNDAMENTAL_SUMMARIZE / BULL_AGENT / BEAR_AGENT / EMBEDDING
        → "deepseek-v4-flash" (fallback "qwen3-local")
    JUDGE / RISK_REFLECTOR
        → "deepseek-v4-pro" (fallback "qwen3-local")

关联:
- ADR-031 (S2 LiteLLMRouter implementation path 决议)
- V3 §5.5 (LLM 路由真预约) / V3 §11.1 (模块清单, 本 PR 修订路径 row 1)
- config/litellm_router.yaml (PR #221 sediment, 本模块 consume only, 0 改)
- docs/LLM_IMPORT_POLICY.md §10 / §10.5 (本 PR 新增)
- 决议 2 (p1): deepseek_client.py 0 mutation, 渐进 deprecate (ADR-031 §6)
- 决议 X2 = (ii): 新建模块, 不改造 deepseek_client

铁律: 31 (Engine 层纯计算 — Router 模块本身只路由 + 调用 LiteLLM, 0 DB IO) /
      33 (fail-loud, unknown task raise) / 34 (config SSOT) /
      41 (UTC 内部, latency_ms float)
"""
from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from litellm import Router

from .types import (
    LLMMessage,
    LLMResponse,
    RiskTaskType,
    RouterConfigError,
    UnknownTaskError,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "litellm_router.yaml"

# V3 §5.5 + 决议 3 (a) — 7 任务 → primary model alias mapping (Python in-code SSOT).
# alias 真值跟 config/litellm_router.yaml model_list 对齐 (PR #221 sediment).
TASK_TO_MODEL_ALIAS: dict[RiskTaskType, str] = {
    RiskTaskType.NEWS_CLASSIFY: "deepseek-v4-flash",
    RiskTaskType.FUNDAMENTAL_SUMMARIZE: "deepseek-v4-flash",
    RiskTaskType.BULL_AGENT: "deepseek-v4-flash",
    RiskTaskType.BEAR_AGENT: "deepseek-v4-flash",
    RiskTaskType.EMBEDDING: "deepseek-v4-flash",
    RiskTaskType.JUDGE: "deepseek-v4-pro",
    RiskTaskType.RISK_REFLECTOR: "deepseek-v4-pro",
}

# fallback alias (V3 §5.5 灾备 path, S3 真消费).
FALLBACK_ALIAS = "qwen3-local"


class LiteLLMRouter:
    """V3 LLM 路由 only path (V3 §5.5 + ADR-020 + ADR-031).

    使用示例 (S2.2/S2.3 真消费, 本 PR 仅 core):
        from backend.qm_platform.llm import LiteLLMRouter, RiskTaskType, LLMMessage

        router = LiteLLMRouter()
        response = router.completion(
            task=RiskTaskType.JUDGE,
            messages=[LLMMessage("user", "判定...")],
            decision_id="risk-event-uuid-xxx",
        )
        print(response.content, response.cost_usd, response.is_fallback)

    NOT 含 (留下游 sub-task):
        - budget guardrails: S2.2 (BudgetGuard 类, $50/月 + 80% warn + 100% Ollama fallback)
        - cost daily 持久化 + audit trail: S2.3 (LLMCallLogger + llm_call_log + llm_cost_daily 表)
        - DingTalk push: S2.3
    """

    def __init__(
        self,
        config_path: Path | str | None = None,
        *,
        set_verbose: bool = False,
        debug_level: str = "INFO",
    ) -> None:
        """初始化 LiteLLMRouter.

        Args:
            config_path: yaml config 路径, 默认 config/litellm_router.yaml.
            set_verbose: LiteLLM verbose log.
            debug_level: LiteLLM debug level.

        Raises:
            RouterConfigError: yaml 加载或 schema 验证失败 (fail-loud).
        """
        path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
        if not path.exists():
            raise RouterConfigError(f"router config 缺失: {path}")

        try:
            with path.open("r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise RouterConfigError(f"router config YAML parse 失败: {path} ({exc})") from exc

        if not isinstance(config, dict):
            raise RouterConfigError(f"router config 顶层应是 dict: {path}")

        for required in ("model_list", "router_settings"):
            if required not in config:
                raise RouterConfigError(f"router config 缺 key: {required}")

        self._config_path = path
        self._raw_config = config

        # NOTE: yaml 真 litellm_settings (drop_params/telemetry/set_verbose/request_timeout)
        # 走 LiteLLM module-level globals (litellm.drop_params 等), Router() init 不消费.
        # S2.1 暂不在本模块 import litellm 真模块全局 (反 cross-module side effect),
        # 留 S2.2/S2.3 真起手时统一在 application bootstrap 真 LLM init 真位置 apply.
        router_settings = config.get("router_settings", {}) or {}
        self._router = Router(
            model_list=config["model_list"],
            num_retries=router_settings.get("num_retries", 0),
            allowed_fails=router_settings.get("allowed_fails", 3),
            cooldown_time=router_settings.get("cooldown_time", 30),
            fallbacks=router_settings.get("fallbacks"),
            set_verbose=set_verbose,
            debug_level=debug_level,
        )

        loaded_aliases = {entry["model_name"] for entry in config["model_list"]}
        for alias in set(TASK_TO_MODEL_ALIAS.values()) | {FALLBACK_ALIAS}:
            if alias not in loaded_aliases:
                raise RouterConfigError(
                    f"router config model_list 缺 alias '{alias}' (TASK_TO_MODEL_ALIAS / FALLBACK_ALIAS 真依赖)"
                )

    @property
    def config_path(self) -> Path:
        return self._config_path

    def model_for(self, task: RiskTaskType) -> str:
        """返 task 真 primary model alias (反 silent fallback)."""
        if task not in TASK_TO_MODEL_ALIAS:
            raise UnknownTaskError(
                f"task '{task}' 不在 RiskTaskType enum (反 silent fallback, 沿用铁律 33)"
            )
        return TASK_TO_MODEL_ALIAS[task]

    def completion(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        decision_id: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """同步路由 + 调用 LiteLLM completion.

        Args:
            task: RiskTaskType 7 任务 enum 之一.
            messages: LLMMessage list 或 dict list ({"role": ..., "content": ...}).
            decision_id: caller 真 trace ID, S2.3 audit trail 真依赖. None 时 LLMResponse 真 None.
            timeout: 单次调用 timeout (秒). None 走 yaml router_settings 默认.
            **kwargs: 透传 LiteLLM completion (e.g. temperature / max_tokens / response_format).

        Returns:
            LLMResponse (含 cost_usd, is_fallback, decision_id 透传).

        Raises:
            UnknownTaskError: task 不在 enum (反 silent fallback).
        """
        primary_alias = self.model_for(task)

        message_dicts = [
            {"role": m.role, "content": m.content} if isinstance(m, LLMMessage) else dict(m)
            for m in messages
        ]

        completion_kwargs: dict[str, Any] = dict(kwargs)
        if timeout is not None:
            completion_kwargs["timeout"] = timeout

        start = time.perf_counter()
        result = self._router.completion(
            model=primary_alias,
            messages=message_dicts,
            **completion_kwargs,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        return self._build_response(
            result=result,
            primary_alias=primary_alias,
            latency_ms=latency_ms,
            decision_id=decision_id,
        )

    def completion_with_alias_override(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        model_alias: str,
        decision_id: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """覆盖 task → primary alias 走 caller 指定 model_alias (S2.2 BudgetAwareRouter capped fallback 消费).

        path C — additive change (NOT mutation 现 completion 方法), 沿用 ADR-022 反
        silent overwrite + 决议 2 (p1) deepseek_client 0 mutation 体例.

        典型 use case (BudgetAwareRouter capped 状态强制 fallback):
            response = router.completion_with_alias_override(
                task=RiskTaskType.JUDGE,
                messages=[...],
                model_alias=FALLBACK_ALIAS,   # 强制走 qwen3-local
                decision_id="risk-event-uuid",
            )
            # response.is_fallback == True (检测路径沿用 PRIMARY_MODEL_SUBSTRINGS)
            # response.decision_id == "risk-event-uuid" (透传, S2.3 audit 真依赖)

        Args:
            task: 原始任务 (audit cite 沿用 PR #222 contract, 不影响路由).
            messages: LLMMessage list 或 dict list.
            model_alias: 强制覆盖 task 真 primary alias (e.g. "qwen3-local").
            decision_id: caller trace ID (S2.3 audit 透传, 沿用 PR #222 contract).
            timeout: 单次调用 timeout (秒).
            **kwargs: 透传 LiteLLM completion (e.g. temperature / max_tokens).

        Returns:
            LLMResponse (model 真 LiteLLM 实际返值, is_fallback 走子串检测;
            primary_alias 仍走 task 默认值, 反 fallback 检测漏报).

        Raises:
            UnknownTaskError: task 不在 enum (反 silent fallback, 沿用铁律 33).
        """
        primary_alias = self.model_for(task)  # 仍校验 task 合法性, 反 silent fallback

        message_dicts = [
            {"role": m.role, "content": m.content} if isinstance(m, LLMMessage) else dict(m)
            for m in messages
        ]

        completion_kwargs: dict[str, Any] = dict(kwargs)
        if timeout is not None:
            completion_kwargs["timeout"] = timeout

        start = time.perf_counter()
        result = self._router.completion(
            model=model_alias,
            messages=message_dicts,
            **completion_kwargs,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        return self._build_response(
            result=result,
            primary_alias=primary_alias,
            latency_ms=latency_ms,
            decision_id=decision_id,
        )

    def _build_response(
        self,
        *,
        result: Any,
        primary_alias: str,
        latency_ms: float,
        decision_id: str | None,
    ) -> LLMResponse:
        """LiteLLM completion 真 ChatCompletion → LLMResponse (含 fallback 检测)."""
        choices = getattr(result, "choices", None) or []
        content = ""
        if choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", "") or ""

        actual_model = getattr(result, "model", primary_alias) or primary_alias

        usage = getattr(result, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage is not None else 0

        cost_usd = _extract_cost_usd(result)

        is_fallback = _is_fallback(actual_model=actual_model, primary_alias=primary_alias)

        return LLMResponse(
            content=content,
            model=actual_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            decision_id=decision_id,
            is_fallback=is_fallback,
        )


def _extract_cost_usd(result: Any) -> Decimal:
    """从 LiteLLM ChatCompletion 提取 cost_usd (Decimal).

    LiteLLM 走 `_hidden_params` 注入 `response_cost` (USD float). 缺时返 0.
    """
    hidden = getattr(result, "_hidden_params", None) or {}
    cost = hidden.get("response_cost") if isinstance(hidden, dict) else None
    if cost is None:
        return Decimal("0")
    try:
        return Decimal(str(cost))
    except (ValueError, ArithmeticError):
        return Decimal("0")


PRIMARY_MODEL_SUBSTRINGS: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-chat",
    "deepseek-v4-pro": "deepseek-reasoner",
}


class FallbackDetectionError(RuntimeError):
    """primary alias 不在 PRIMARY_MODEL_SUBSTRINGS 真 known set (反 silent miss, 铁律 33).

    沿用 reviewer Chunk A P2: 未来加 alias 必同步 PRIMARY_MODEL_SUBSTRINGS,
    否则 _is_fallback 真 silent return False 真 fallback 状态漏报.
    """


def _is_fallback(*, actual_model: str, primary_alias: str) -> bool:
    """检测 fallback 路径: actual_model 真模型名跟 primary alias 期望模型 0 重叠.

    primary deepseek-v4-flash → deepseek/deepseek-chat (含 'deepseek-chat' 子串)
    primary deepseek-v4-pro → deepseek/deepseek-reasoner (含 'deepseek-reasoner' 子串)
    fallback qwen3-local → ollama/qwen3:8b (跟两个 primary 子串都不命中)

    actual_model 跟期望 primary 子串 0 命中 → 走 fallback 路径 (含 qwen3-local).
    primary_alias 不在 known set → raise (反 silent miss, 沿用铁律 33).
    """
    if not actual_model or not primary_alias:
        return False

    if primary_alias not in PRIMARY_MODEL_SUBSTRINGS:
        raise FallbackDetectionError(
            f"primary alias '{primary_alias}' 不在 PRIMARY_MODEL_SUBSTRINGS known set; "
            "新加 alias 必同步本表 (沿用铁律 33 fail-loud)."
        )

    expected_substring = PRIMARY_MODEL_SUBSTRINGS[primary_alias]
    return expected_substring not in actual_model.lower()
