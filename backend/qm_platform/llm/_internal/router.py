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

from ..types import (
    LLMMessage,
    LLMResponse,
    RiskTaskType,
    RouterConfigError,
    UnknownTaskError,
)

# parents[4] 沿用 S4 PR #226 真 _internal/ 子包深度 (反 PR #222 真 parents[3]).
# backend/qm_platform/llm/_internal/router.py → parents[0]=_internal → parents[1]=llm
# → parents[2]=qm_platform → parents[3]=backend → parents[4]=REPO_ROOT.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "litellm_router.yaml"


# 5-07 sub-PR 8b-llm-fix yaml-referenced env var whitelist (CC fresh grep
# config/litellm_router.yaml `os.environ/X` syntax sustained):
# - line 34/48: api_key: os.environ/DEEPSEEK_API_KEY
# - line 66: api_base: os.environ/OLLAMA_BASE_URL
# 反 production secret leak 红线 — 限 yaml 真**真消费** env vars (反 propagate 全
# Pydantic Settings 字段 → os.environ).
_YAML_REFERENCED_ENVS: tuple[str, ...] = (
    "DEEPSEEK_API_KEY",
    "OLLAMA_BASE_URL",
)


def _propagate_settings_to_environ() -> None:
    """Propagate Pydantic Settings → os.environ for LiteLLM yaml `os.environ/X`.

    真因 sediment (sub-PR 8b-llm-diag 5-07 root cause):
        Pydantic-settings v2.x design 0 propagate `.env` → os.environ (Settings 真
        class attr holder 反 env mutator). LiteLLM yaml `os.environ/X` syntax 自
        `os.environ.get(X)` → empty string when Pydantic 沿用 .env file load.
        DeepSeek API 真**Authentication Fails (governor)** 401 → Router fallback
        Ollama. 5-03 PR #222 起 sustained 4 days production 0 catch, 5-07 sub-PR
        8b-pre Step 2 e2e first verify catch.

    设计:
        - Idempotent: 不覆盖已 set os.environ value (沿用 shell env priority).
        - Whitelist: 限 _YAML_REFERENCED_ENVS (反 production secret 全 propagate).
        - Graceful: backend.app.config import 失败 → no-op (test contexts without
          backend.app installed; 沿用 _internal/ 子包真生产**反 hard couple**).
        - Empty value skip: settings.X 真**默认 ""** 沿用 (反 propagate 真 None /
          empty string → os.environ 真**反误 set** misleading).

    关联:
        - ADR-031 §6 (S2 LiteLLMRouter implementation path 决议)
        - V3 §5.5 (LLM 路由真预约)
        - LL-110 (web_fetch 官方文档 verify SOP)
        - LL-112 (user 第 7 push back catch correctly 体例)
        - 真讽刺 #17 sediment 加深 (修复 metric ≠ 修复真生产 issue 4 days sustained)
    """
    import os

    try:
        from backend.app.config import settings
    except ImportError:
        return  # test contexts without backend.app installed (graceful no-op)

    for env_var in _YAML_REFERENCED_ENVS:
        value = getattr(settings, env_var, "") or ""
        if value and not os.environ.get(env_var):
            os.environ[env_var] = value


# V3 §5.5 + 决议 3 (a) — 7 任务 → primary model alias mapping (Python in-code SSOT).
# alias 真值跟 config/litellm_router.yaml model_list 对齐 (PR #221 sediment).
TASK_TO_MODEL_ALIAS: dict[RiskTaskType, str] = {
    RiskTaskType.NEWS_CLASSIFY: "deepseek-v4-flash",
    RiskTaskType.FUNDAMENTAL_SUMMARIZE: "deepseek-v4-flash",
    RiskTaskType.BULL_AGENT: "deepseek-v4-pro",
    RiskTaskType.BEAR_AGENT: "deepseek-v4-pro",
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
        # 5-07 sub-PR 8b-llm-fix: propagate Pydantic .env → os.environ for yaml
        # `os.environ/X` syntax 真生效 sustained. 真因 sediment详 sub-PR 8b-llm-diag
        # memory file (Pydantic-settings v2.x 0 propagate by design) +
        # _propagate_settings_to_environ docstring 真 idempotent + whitelist 体例.
        _propagate_settings_to_environ()

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

        # 沿用 reviewer Chunk C P3 hardening: model_alias 必在 init-validated set,
        # 反 caller 真 typo/unknown alias 走 LiteLLM internal opaque error (fail-loud, 铁律 33).
        loaded_aliases = {entry["model_name"] for entry in self._raw_config["model_list"]}
        if model_alias not in loaded_aliases:
            raise RouterConfigError(
                f"model_alias '{model_alias}' 不在 yaml model_list (loaded: {sorted(loaded_aliases)}); "
                "caller 必传 init-validated alias (e.g. FALLBACK_ALIAS)."
            )

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
    # sub-PR 8a-followup-B-yaml 5-07 reviewer P1-1 adopt: yaml V4 underlying 切换体例
    # sustained — substring 真**align** yaml litellm_params.model (deepseek/deepseek-v4-*).
    # 反 sub-PR 8a-followup-A 旧体例 ("deepseek-chat" / "deepseek-reasoner") — yaml V4 切换后
    # 旧 substring 真**Case 2 false positive 反 introduce** (沿用 BUG #1 reverse case).
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek-v4-pro",
}


class FallbackDetectionError(RuntimeError):
    """primary alias 不在 PRIMARY_MODEL_SUBSTRINGS 真 known set (反 silent miss, 铁律 33).

    沿用 reviewer Chunk A P2: 未来加 alias 必同步 PRIMARY_MODEL_SUBSTRINGS,
    否则 _is_fallback 真 silent return False 真 fallback 状态漏报.
    """


def _is_fallback(*, actual_model: str, primary_alias: str) -> bool:
    """检测 fallback 路径: actual_model 真模型名跟 primary alias 期望模型 0 重叠.

    LiteLLM Router 真**返 model identifier 体例双 case** (5-07 sub-PR 8a-followup-A
    sediment, sub-PR 8a e2e 真生产 first verify):

    Case 1 (primary success, alias-pass-through): LiteLLM Router 真**返 yaml model_name
    alias** (e.g. `deepseek-v4-flash`) 反 underlying provider/model name. 真**default
    Router behavior** sustained — caller 真传 model=alias, Router 真**route 走 yaml
    model_list 真 first match** + 真**返 alias 沿用 caller 真 input alias** 体例.
    → 真**alias equality short-circuit**: actual_model == primary_alias 真**primary
    成功** signal (反 fallback).

    Case 2 (primary success, underlying-name): LiteLLM Router 真**直传 underlying
    provider/model name** (e.g. `deepseek/deepseek-chat`) 真**rare case** 走
    `_call_with_fallback` internal path. → 真**substring 检测体例 sustained**:
    expected_substring (`deepseek-chat`) in actual_model (`deepseek/deepseek-chat`) ✅.

    Case 3 (fallback path): LiteLLM Router 真**fallback chain 触发** 时 真**返
    fallback model 真 underlying name** (e.g. `ollama_chat/qwen3.5:9b`). → 真
    **substring 检测体例**: expected_substring (`deepseek-chat`) NOT in
    `ollama_chat/qwen3.5:9b` → return True (correct).

    sub-PR 8a-followup-A 真**修 BUG #1** (5-07 sediment): Case 1 alias-pass-through
    真**default behavior** Sprint 1 PR #222 真**单测未 cover**, _is_fallback()
    真**substring 检测** Case 1 真**false positive** (return True for primary
    success) — 真**生产影响**: llm_call_log 全 row is_fallback=t (反 production
    实际 primary success), BudgetGuard fallback metric 真污染.

    primary_alias 不在 known set → raise (反 silent miss, 沿用铁律 33).
    """
    if not actual_model or not primary_alias:
        return False

    # NEW (sub-PR 8a-followup-A 5-07): alias equality short-circuit (Case 1 primary
    # success signal). LiteLLM Router 真**default behavior** 返 yaml model_name alias
    # 反 underlying provider/model — sub-PR 8a e2e 真生产 first verify.
    # 沿用 .lower() 对齐 line 399 substring check (reviewer P1-1 adopt: case-variant
    # alias 真**反 introduce false positive** — e.g. "DeepSeek-V4-Flash" vs lowercase).
    if actual_model.lower() == primary_alias.lower():
        return False

    if primary_alias not in PRIMARY_MODEL_SUBSTRINGS:
        raise FallbackDetectionError(
            f"primary alias '{primary_alias}' 不在 PRIMARY_MODEL_SUBSTRINGS known set; "
            "新加 alias 必同步本表 (沿用铁律 33 fail-loud)."
        )

    expected_substring = PRIMARY_MODEL_SUBSTRINGS[primary_alias]
    return expected_substring not in actual_model.lower()
