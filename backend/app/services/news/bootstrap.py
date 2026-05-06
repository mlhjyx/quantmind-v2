"""NewsClassifierService bootstrap — get_news_classifier factory + reset helper.

scope (sub-PR 7b.3 v2 #242, ADR-032 line 36 真预约 + alert.py 体例):
- get_news_classifier(): lazy-init NewsClassifierService 全局单例 (沿用 alert.py:528-554 体例)
- reset_news_classifier(): 重置单例 (test isolation 真依赖)
- 沿用 double-checked lock (反 race condition + 反 重复 init)
- conn_factory 沿用 ADR-032 line 36 真预约: caller 真**显式 wire** 启用全 governance
  (NewsClassifierService.persist 走 caller 真 conn, 沿用铁律 32 Service 不 commit)

caller 真**唯一 sanctioned 入口** (反 直接 NewsClassifierService(...) bypass singleton):
    from backend.app.services.news import get_news_classifier

    classifier = get_news_classifier()
    result = classifier.classify(news_item, decision_id="news-uuid-xxx")
    # 入库走 caller 真 conn (沿用 sub-PR 7c NewsIngestionService orchestrator):
    with conn:
        classifier.persist(result, conn=conn, news_id=inserted_news_id)

test isolation (沿用 alert.py reset_alert_router 体例):
    @pytest.fixture(autouse=True)
    def _reset_news_classifier_singleton():
        yield
        from backend.app.services.news import reset_news_classifier
        reset_news_classifier()

关联铁律: 31 (Engine 层纯计算 — bootstrap factory 0 DB IO, conn 走 caller DI) /
          32 (Service 不 commit — NewsClassifierService.persist 0 commit, caller 管事务) /
          33 (fail-loud — Router init 失败 raise 沿用 get_llm_router 体例) /
          34 (Config SSOT — settings 默认走 backend.app.config.settings)

关联文档:
- ADR-032 §Decision (caller bootstrap factory 体例) — 沿用 get_llm_router pattern
- ADR-031 §6 line 148 (sub-PR 7b.3 NewsClassifierService.persist 真 wire 真预约)
- backend/qm_platform/observability/alert.py:528-554 (factory 体例参考)
- backend/qm_platform/llm/bootstrap.py (LLM router factory, 0 wire 本 factory — 沿用
  inner injection: caller 调 get_llm_router(conn_factory) 后传给 NewsClassifierService)
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .news_classifier_service import NewsClassifierService

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from backend.qm_platform.llm.bootstrap import (
        BudgetAwareRouter,
        LiteLLMRouter,
    )

# 沿用 alert.py 体例: module-level singleton + threading.Lock + double-checked.
_classifier_singleton: NewsClassifierService | None = None
_singleton_lock = threading.Lock()


def get_news_classifier(
    *,
    router: BudgetAwareRouter | LiteLLMRouter | None = None,
    conn_factory: Callable[[], Any] | None = None,
) -> NewsClassifierService:
    """Lazy-init 全局 NewsClassifierService 单例 (沿用 alert.py double-checked lock 体例).

    Args:
        router: optional pre-built router DI (默认走 get_llm_router(conn_factory=...)).
        conn_factory: optional conn factory 透传 get_llm_router (默认 None 走降级 mode).

    Returns:
        NewsClassifierService 全局单例 (process-level cache, 沿用 alert.py 体例).

    NOTE (router DI 体例):
        参数 router 优先 (caller 已有 router 实例) → 0 重复初始化 LiteLLMRouter.
        参数 router=None 时 lazy 调 get_llm_router(conn_factory=conn_factory) 沿用
        ADR-032 line 36 真预约 + bootstrap.py:82 docstring "application 真生产 caller
        必显式传 conn_factory" 体例 sustained.

    NOTE (singleton lifecycle, 沿用 alert.py + llm/bootstrap.py 体例):
        process-level cache (module-level _classifier_singleton).
        每 process 唯一实例, 反**重复 yaml prompt 加载 cost** + 反 race condition.

        test isolation 真依赖 reset_news_classifier() (autouse fixture, 沿用 alert.py).
    """
    global _classifier_singleton
    if _classifier_singleton is None:
        with _singleton_lock:
            if _classifier_singleton is None:
                if router is None:
                    # 默认走 get_llm_router 真**唯一 sanctioned 入口** sustained ADR-032.
                    from backend.qm_platform.llm import get_llm_router
                    router = get_llm_router(conn_factory=conn_factory)
                _classifier_singleton = NewsClassifierService(router=router)
    return _classifier_singleton


def reset_news_classifier() -> None:
    """重置全局单例 (单测用, 沿用 alert.py reset_alert_router 体例)."""
    global _classifier_singleton
    with _singleton_lock:
        _classifier_singleton = None
