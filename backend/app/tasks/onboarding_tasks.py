"""因子入库 Celery 任务 — 将审批通过的 GP 候选因子异步入库。

每个 task 用 asyncio.run() 包装 async 逻辑（DEV_BACKEND.md 标准写法）。
入库完成后更新 approval_queue.onboarding_status（若列存在）并记录日志。

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6.2: 人工审批后的处理
  - docs/DEV_BACKEND.md §4.12.3: Celery Task 模板
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.onboarding_tasks")


@celery_app.task(
    bind=True,
    name="app.tasks.onboarding_tasks.onboard_factor",
    acks_late=True,
    max_retries=2,  # 入库失败最多重试 2 次（宪法 §15.1）
    default_retry_delay=60,  # 重试间隔 60 秒
    soft_time_limit=600,  # 10 分钟软超时（FactorDSL 计算上限）
    time_limit=720,  # 12 分钟硬超时
)
def onboard_factor(self, approval_queue_id: int) -> dict[str, Any]:
    """因子入库 Celery 任务。

    asyncio.run() 包装：在 Celery prefork Worker 中安全运行 async 代码。
    入库步骤：
      1. 读 approval_queue → 验证 status='approved'
      2. 写 factor_registry（upsert）
      3. FactorDSL 计算历史因子值 → 写 factor_values
      4. 计算 Rank IC → 写 factor_ic_history
      5. 更新 factor_registry gate 统计字段

    Args:
        approval_queue_id: approval_queue 表主键 id。

    Returns:
        {
            "success": bool,
            "factor_name": str,
            "registry_id": str,
            "factor_values_written": int,
            "ic_rows_written": int,
            "gate_ic": float | None,
            "gate_t": float | None,
            "error": str | None,
        }
    """
    logger.info(
        "因子入库任务启动",
        extra={"approval_queue_id": approval_queue_id},
    )
    start = time.monotonic()

    try:
        result = asyncio.run(_onboard_factor_async(approval_queue_id))
        elapsed = time.monotonic() - start
        logger.info(
            "因子入库任务完成",
            extra={
                "approval_queue_id": approval_queue_id,
                "factor_name": result.get("factor_name"),
                "elapsed_sec": round(elapsed, 1),
                "factor_values_written": result.get("factor_values_written", 0),
                "ic_rows_written": result.get("ic_rows_written", 0),
                "gate_t": result.get("gate_t"),
            },
        )
        return result
    except ValueError as exc:
        # 数据问题（不存在/非approved）：不重试，直接失败
        error_msg = str(exc)
        logger.error(
            "因子入库数据错误（不重试）",
            extra={"approval_queue_id": approval_queue_id, "error": error_msg},
        )
        return {
            "success": False,
            "factor_name": None,
            "registry_id": None,
            "factor_values_written": 0,
            "ic_rows_written": 0,
            "gate_ic": None,
            "gate_t": None,
            "error": error_msg,
        }
    except Exception as exc:
        error_msg = str(exc)
        logger.error(
            "因子入库任务异常，准备重试",
            extra={
                "approval_queue_id": approval_queue_id,
                "error": error_msg,
                "retries": self.request.retries,
            },
            exc_info=True,
        )
        # 重试（宪法 §15.1：失败重试 ≤2 次，第3次升级汇报）
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error(
                "因子入库任务超过最大重试次数（P0: 需人工介入）",
                extra={"approval_queue_id": approval_queue_id},
            )
            return {
                "success": False,
                "factor_name": None,
                "registry_id": None,
                "factor_values_written": 0,
                "ic_rows_written": 0,
                "gate_ic": None,
                "gate_t": None,
                "error": f"MaxRetriesExceeded: {error_msg}",
            }


async def _onboard_factor_async(approval_queue_id: int) -> dict[str, Any]:
    """因子入库异步主逻辑（在 asyncio.run 中执行）。

    Args:
        approval_queue_id: approval_queue 主键。

    Returns:
        入库结果摘要。
    """
    from app.services.factor_onboarding import FactorOnboardingService

    service = FactorOnboardingService()
    return await service.onboard_factor(approval_queue_id)
