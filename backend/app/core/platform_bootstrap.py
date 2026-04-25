"""MVP 1.3b Wiring 补全 — Platform DBFactorRegistry + DBFeatureFlag 生产注入 helper.

背景:
  MVP 1.3b 原交付 (commit e7d9ce3, 2026-04-17) 完整实现了:
    - DBFactorRegistry / DBFeatureFlag / signal_engine._get_direction 3 层 fallback
    - feature_flags use_db_direction=True 已入库
    - 30+ 单测全绿
  但生产入口 (run_paper_trading / FastAPI / Celery) 均未调用 init_platform_dependencies
  → signal_engine `_PLATFORM_REGISTRY` / `_PLATFORM_FLAG_DB` 永远 None
  → `_get_direction` 永远走 Layer 0 hardcoded, DB flag 形同虚设.

  本模块补全此 wiring (铁律 10 全链路验证 + 铁律 36 precondition).

Usage:
    from app.core.platform_bootstrap import bootstrap_platform_deps
    bootstrap_platform_deps()   # 幂等, 失败自动 fallback hardcoded

关联铁律:
  - 10: 基础设施改动后全链路验证
  - 33: 禁 silent failure — 本模块 catch 后 logger.warning, 属 read-path fallback 允许
  - 36: MVP 前核 precondition — MVP 2.1b 启动前必须确认 1.3b 真正激活
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_BOOTSTRAP_DONE = False


def bootstrap_platform_deps(force: bool = False) -> bool:
    """把 Platform DBFactorRegistry + DBFeatureFlag 注入 signal_engine 全局.

    Args:
      force: True 重新注入 (测试重置用, 生产无需).

    Returns:
      True 若注入成功, False 若失败 (signal_engine 自动回 Layer 0 hardcoded).

    Idempotent. 捕获所有异常, 不 raise (read-path fallback 允许, 铁律 33).
    """
    global _BOOTSTRAP_DONE
    if _BOOTSTRAP_DONE and not force:
        return True
    try:
        # engines 在 sys.path (backend/ 已 insert), 与 signal_service 一致风格
        from engines.signal_engine import init_platform_dependencies

        from app.services.db import get_sync_conn

        # Platform 模块用完整路径 (保 MVP 1.1 严格隔离一致性)
        from backend.qm_platform.config.feature_flag import DBFeatureFlag
        from backend.qm_platform.data.access_layer import PlatformDataAccessLayer
        from backend.qm_platform.factor.registry import DBFactorRegistry

        dal = PlatformDataAccessLayer(conn_factory=get_sync_conn)
        registry = DBFactorRegistry(dal=dal, conn_factory=get_sync_conn)
        flag_db = DBFeatureFlag(conn_factory=get_sync_conn)

        init_platform_dependencies(registry=registry, flag_db=flag_db)
        _BOOTSTRAP_DONE = True

        # Operational visibility — 启动即暴露 Layer 路径
        try:
            flag_on = flag_db.is_enabled("use_db_direction")
            layer = "Layer 1 (DB + cache)" if flag_on else "Layer 0 (hardcoded)"
            logger.info(
                "[platform_bootstrap] DBFactorRegistry + DBFeatureFlag injected. "
                "use_db_direction=%s, signal_engine._get_direction 走 %s.",
                flag_on,
                layer,
            )
        except Exception as flag_err:  # noqa: BLE001 — flag 查询失败不致命, 走 hardcoded fallback
            logger.info(
                "[platform_bootstrap] injected (flag 状态查询失败: %s, "
                "signal_engine 走 hardcoded fallback).",
                flag_err,
            )
        return True
    except Exception as e:  # noqa: BLE001 — wiring 失败不阻断启动, 3 层 fallback 保底
        logger.warning(
            "[platform_bootstrap] 注入失败: %s. "
            "signal_engine._get_direction 走 Layer 0 hardcoded fallback (安全, 铁律 33).",
            e,
        )
        return False


def reset_platform_deps() -> None:
    """测试用 — 重置 bootstrap state 并清空 signal_engine globals.

    不 raise — 测试 teardown 场景.
    """
    global _BOOTSTRAP_DONE
    _BOOTSTRAP_DONE = False
    try:
        from engines.signal_engine import init_platform_dependencies

        init_platform_dependencies(registry=None, flag_db=None)
    except Exception:  # noqa: BLE001
        pass  # silent_ok: test teardown, signal_engine 不可 import 时允许


__all__ = ["bootstrap_platform_deps", "reset_platform_deps"]
