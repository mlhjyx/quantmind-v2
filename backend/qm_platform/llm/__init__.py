"""Framework LLM — V3 LLM 路由 only path (S2.1 sub-task core, sustained ADR-020 + ADR-031).

归属: Framework #LLM 平台 SDK 子模块 (V3 §5.5 LiteLLM 路由真预约).
位置: backend/qm_platform/llm/ (沿用 ADR-031 §3 path 决议, 修订 V3 §11.1 line 1217 真路径).

scope (S2.1 — 本 PR):
- LiteLLM Router 实例化 + 7 任务 → model alias 路由
- LLMResponse 含 decision_id 透传 + is_fallback 检测
- 0 budget guardrails (S2.2 scope: BudgetGuard + llm_cost_daily 表)
- 0 cost monitoring + audit trail INSERT (S2.3 scope: LLMCallLogger + llm_call_log)

关联铁律: 31 (Engine 层纯计算 — Router 0 DB IO) / 33 (fail-loud) /
          34 (Config SSOT) / 41 (timezone)

Application 消费示例 (下游 sub-task 真消费, 本 PR 仅 core):
    from backend.qm_platform.llm import LiteLLMRouter, RiskTaskType, LLMMessage

    router = LiteLLMRouter()
    response = router.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "判定...")],
        decision_id="risk-event-uuid-xxx",
    )
    print(response.content, response.cost_usd, response.is_fallback)
"""
from .router import (
    DEFAULT_CONFIG_PATH,
    FALLBACK_ALIAS,
    PRIMARY_MODEL_SUBSTRINGS,
    TASK_TO_MODEL_ALIAS,
    FallbackDetectionError,
    LiteLLMRouter,
)
from .types import (
    LLMMessage,
    LLMResponse,
    RiskTaskType,
    RouterConfigError,
    UnknownTaskError,
)

__all__ = [
    "LiteLLMRouter",
    "RiskTaskType",
    "LLMMessage",
    "LLMResponse",
    "TASK_TO_MODEL_ALIAS",
    "PRIMARY_MODEL_SUBSTRINGS",
    "FALLBACK_ALIAS",
    "DEFAULT_CONFIG_PATH",
    "RouterConfigError",
    "UnknownTaskError",
    "FallbackDetectionError",
]
