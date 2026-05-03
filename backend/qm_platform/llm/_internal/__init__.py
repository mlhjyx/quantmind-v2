"""Internal-only LLM 路由实现 — caller 不直接 import.

caller (application code in backend/app/, backend/engines/, scripts/) 必走
公共 factory: ``from backend.qm_platform.llm import get_llm_router``.

scope (S4 PR #226 sediment, ADR-032):
- _internal/router.py : LiteLLMRouter (LiteLLM 7 任务路由实现)
- _internal/budget.py : BudgetGuard / BudgetAwareRouter / BudgetState 状态机
- _internal/audit.py  : LLMCallLogger / LLMCallRecord / compute_prompt_hash

caller 走公共 path 体例 (沿用 alert.py get_alert_router 体例):

    from backend.qm_platform.llm import get_llm_router, RiskTaskType, LLMMessage

    router = get_llm_router()
    response = router.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "判定...")],
        decision_id="risk-event-uuid-xxx",
    )

反**naked import** (反 silent overwrite, 沿用 ADR-022 + ADR-032):
    # ❌ 反向用法 — bypass factory + audit + budget governance
    from backend.qm_platform.llm._internal.router import LiteLLMRouter

scripts/check_llm_imports.sh 真 S4 pattern 自动 BLOCK caller code 走 _internal
直接 import (沿用 PR #219 体例 + S4 allowlist marker `# llm-internal-allow:`).

test 真**例外**: backend/tests/* 沿用 hook scope 排除, 直接 import _internal/ 真合法
(沿用 mock 体例 — monkeypatch.setattr(litellm.Router, "completion", mock) 真**深内部
mock** 真依赖 _internal/router 真直接 import).

关联铁律: 31 (Engine 纯计算) / 33 (fail-loud) / 34 (Config SSOT)

关联文档:
- ADR-032 (S4 caller bootstrap factory + naked LiteLLMRouter export 限制)
- ADR-031 §6 (S2 渐进 deprecate plan, S4 真前置 enforcement)
- ADR-022 (反 silent overwrite)
- docs/LLM_IMPORT_POLICY.md §10.9 (caller 接入文档)
"""
