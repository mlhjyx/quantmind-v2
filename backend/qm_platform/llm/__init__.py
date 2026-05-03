"""Framework LLM — V3 LLM 路由公共 API (S4 PR #226 sediment, ADR-032).

归属: Framework #LLM 平台 SDK 子模块 (V3 §5.5 LiteLLM 路由真预约).
位置: backend/qm_platform/llm/ (沿用 ADR-031 §3 path 决议).

scope (S4 PR #226 真**重构 18 → 6 public export**):
- get_llm_router / reset_llm_router (factory + reset helper, bootstrap.py)
- RiskTaskType / LLMMessage / LLMResponse (公共 dataclass + enum, types.py)
- RouterConfigError / UnknownTaskError (公共 exception, types.py)

公共 API 真**唯一 sanctioned 入口** (沿用 ADR-022 反 silent overwrite + ADR-032):

    from backend.qm_platform.llm import get_llm_router, RiskTaskType, LLMMessage

    router = get_llm_router()
    response = router.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "判定...")],
        decision_id="risk-event-uuid-xxx",
    )
    print(response.content, response.cost_usd, response.is_fallback)

反**naked import** (反 bypass audit + budget governance):
    # ❌ 反向用法 — scripts/check_llm_imports.sh S4 pattern 自动 BLOCK caller code
    from backend.qm_platform.llm._internal.router import LiteLLMRouter

实施 (S4 PR #226 sediment):
- _internal/router.py : LiteLLMRouter (移自 backend/qm_platform/llm/router.py)
- _internal/budget.py : BudgetGuard / BudgetAwareRouter (移自 ../budget.py)
- _internal/audit.py  : LLMCallLogger (移自 ../audit.py)
- bootstrap.py        : get_llm_router / reset_llm_router (新建 factory)

关联铁律: 31 (Engine 层纯计算) / 33 (fail-loud) / 34 (Config SSOT) / 41 (timezone)

关联文档:
- ADR-032 (S4 caller bootstrap factory + naked LiteLLMRouter export 限制)
- ADR-031 §6 (S2 渐进 deprecate plan, S4 真前置 enforcement)
- ADR-022 (反 silent overwrite)
- docs/LLM_IMPORT_POLICY.md §10.9 (caller 接入文档)
"""
from .bootstrap import get_llm_router, reset_llm_router
from .types import (
    LLMMessage,
    LLMResponse,
    RiskTaskType,
    RouterConfigError,
    UnknownTaskError,
)

__all__ = [
    # S4 公共 factory (PR #226)
    "get_llm_router",
    "reset_llm_router",
    # 公共 enum + dataclass + exception (PR #222 sediment, sustained S4)
    "RiskTaskType",
    "LLMMessage",
    "LLMResponse",
    "RouterConfigError",
    "UnknownTaskError",
]
