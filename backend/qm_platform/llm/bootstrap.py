"""LLM Router caller bootstrap — get_llm_router factory + reset helper.

scope (S4 PR #226 sediment, ADR-032):
- get_llm_router(): lazy-init BudgetAwareRouter 全局单例 (沿用 alert.py 体例)
- reset_llm_router(): 重置单例 (test isolation 真依赖)
- 沿用 double-checked lock (反 race condition + 反 重复 init)
- conn_factory=None 默认走**降级 path** (LiteLLMRouter only, 反 BudgetGuard / Audit)
  application bootstrap (Sprint 2+) 真显式 wire conn_factory 启用全 governance.

caller 真**唯一 sanctioned 入口** (反 naked LiteLLMRouter bypass):
    from backend.qm_platform.llm import get_llm_router, RiskTaskType, LLMMessage

    router = get_llm_router()  # 默认走 default_settings + None conn_factory
    response = router.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "判定...")],
        decision_id="risk-event-uuid-xxx",
    )

test isolation (沿用 alert.py reset_alert_router 体例):
    @pytest.fixture(autouse=True)
    def _reset_llm_singleton():
        yield
        from backend.qm_platform.llm import reset_llm_router
        reset_llm_router()

关联铁律: 31 (Engine 纯计算 — factory 0 DB IO, 走 conn_factory DI) /
          33 (fail-loud — conn_factory=None 走降级 LiteLLMRouter, audit/budget 0 wire,
              反 silent skip — 显式 docstring cite + caller 真知降级 mode) /
          34 (Config SSOT — settings 默认走 backend.app.config.settings)

关联文档:
- ADR-032 (S4 caller bootstrap factory + naked LiteLLMRouter export 限制)
- ADR-031 §6 (S2 渐进 deprecate plan, S4 真前置 enforcement)
- ADR-022 (反 silent overwrite)
- docs/LLM_IMPORT_POLICY.md §10.9 (caller 接入文档)
- backend/qm_platform/observability/alert.py:528-554 (factory 体例参考)
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ._internal.audit import LLMCallLogger
from ._internal.budget import BudgetAwareRouter, BudgetGuard
from ._internal.router import LiteLLMRouter

if TYPE_CHECKING:
    from backend.app.config import Settings

# 沿用 alert.py 体例: module-level singleton + threading.Lock + double-checked.
# Union[BudgetAwareRouter, LiteLLMRouter] 真**降级 mode** 兼容
# (conn_factory=None 走 naked LiteLLMRouter, 反 BudgetGuard 真 None DB call).
_router_singleton: BudgetAwareRouter | LiteLLMRouter | None = None
_singleton_lock = threading.Lock()


def get_llm_router(
    *,
    settings: Settings | None = None,
    conn_factory: Callable[[], Any] | None = None,
) -> BudgetAwareRouter | LiteLLMRouter:
    """Lazy-init 全局 LLM Router 单例 (沿用 alert.py double-checked lock 体例).

    caller 真**唯一 sanctioned 入口** — 反 naked LiteLLMRouter bypass audit + budget
    (沿用 ADR-032 + scripts/check_llm_imports.sh S4 pattern hook 自动 BLOCK).

    Args:
        settings: optional Settings DI (默认走 backend.app.config.settings 全局).
        conn_factory: optional psycopg2 conn factory (默认 None — 走降级 mode).

    Returns:
        BudgetAwareRouter (conn_factory != None 时, 全 governance 启用) 或
        LiteLLMRouter (conn_factory = None 时, 降级 mode — 0 budget / 0 audit).

    NOTE (降级 mode):
        conn_factory=None 时, BudgetGuard 真不可用 (反 None DB call 真 silent miss).
        本 factory 沿用决议**降级走 naked LiteLLMRouter** (反 raise — caller code 真
        Sprint 2+ application bootstrap 时再 wire conn_factory).

        application 真生产 caller (RiskReflector / Bull/Bear / NewsClassifier) 必显式
        传 conn_factory (沿用 backend.app 真 conn pool DI 体例), 反**降级 mode 漏气**.

    NOTE (singleton lifecycle):
        process-level cache (module-level _router_singleton) — 沿用 alert.py 体例.
        每 process 唯一实例, 反**重复 LiteLLM Router init cost** + 反 race condition.

        test isolation 真依赖 reset_llm_router() (autouse fixture, 沿用 alert.py).
    """
    global _router_singleton
    if _router_singleton is None:
        with _singleton_lock:
            if _router_singleton is None:
                # default settings 走 backend.app.config (反 hidden coupling import).
                if settings is None:
                    from backend.app.config import settings as default_settings
                    eff_settings = default_settings
                else:
                    eff_settings = settings

                inner_router = LiteLLMRouter()

                if conn_factory is None:
                    # 降级 mode (沿用决议): naked LiteLLMRouter 真 caller-visible
                    # (反 raise — Sprint 2+ application bootstrap 时再 wire).
                    _router_singleton = inner_router
                else:
                    # 全 governance mode (BudgetGuard + LLMCallLogger wire).
                    from decimal import Decimal
                    budget = BudgetGuard(
                        conn_factory,
                        monthly_budget_usd=Decimal(str(eff_settings.LLM_MONTHLY_BUDGET_USD)),
                        warn_threshold=Decimal(str(eff_settings.LLM_BUDGET_WARN_THRESHOLD)),
                        cap_threshold=Decimal(str(eff_settings.LLM_BUDGET_CAP_THRESHOLD)),
                    )
                    audit = LLMCallLogger(conn_factory)
                    _router_singleton = BudgetAwareRouter(
                        inner_router, budget, audit=audit
                    )
    return _router_singleton


def reset_llm_router() -> None:
    """重置全局单例 (单测用, 沿用 reset_alert_router 体例).

    autouse fixture 真 cross-test cleanup:
        @pytest.fixture(autouse=True)
        def _reset_llm_singleton():
            yield
            reset_llm_router()
    """
    global _router_singleton
    with _singleton_lock:
        _router_singleton = None
