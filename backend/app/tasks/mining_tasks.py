"""因子挖掘 Celery 任务 — GP/BruteForce 引擎的异步执行封装。

每个 task 用 asyncio.run() 包装 async 逻辑（DEV_BACKEND.md 标准写法）。
完成后更新 pipeline_runs.status + stats，并写入 approval_queue。

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6: 完整闭环流程
  - docs/DEV_BACKEND.md §4.12.3: Celery Task 模板
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.mining_tasks")


# ---------------------------------------------------------------------------
# GP 挖掘任务
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="app.tasks.mining_tasks.run_gp_mining",
    acks_late=True,
    max_retries=0,  # GP任务不自动重试（耗时长）
    soft_time_limit=10800,  # 3小时软超时（GP 120min + Gate 60min + 余量）
    time_limit=11400,  # 3.17小时硬超时
)
def run_gp_mining(self, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """GP 因子挖掘 Celery 任务。

    asyncio.run() 包装：在 Celery prefork Worker 中安全运行 async 代码。

    Args:
        run_id: 本次运行 ID（已写入 pipeline_runs）。
        config: GP 配置 {generations/population/islands/time_budget_minutes}。

    Returns:
        {"run_id": str, "status": str, "passed_factors": int}
    """
    logger.info("GP 挖掘任务启动", extra={"run_id": run_id, "config": config})
    start = time.monotonic()

    try:
        result = asyncio.run(_run_gp_mining_async(run_id, config))
        elapsed = time.monotonic() - start
        logger.info(
            "GP 挖掘任务完成",
            extra={
                "run_id": run_id,
                "elapsed_min": round(elapsed / 60, 1),
                "passed_factors": result.get("passed_factors", 0),
            },
        )
        return result
    except Exception as exc:
        logger.error("GP 挖掘任务异常", extra={"run_id": run_id, "error": str(exc)}, exc_info=True)
        asyncio.run(_mark_run_failed(run_id, str(exc)))
        raise


async def _run_gp_mining_async(run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """GP 挖掘异步主逻辑（在 asyncio.run 中执行）。

    复用 scripts/run_gp_pipeline.py 的数据加载 + Gate 逻辑。

    Args:
        run_id: 运行 ID。
        config: GP 配置字典。

    Returns:
        {"run_id": str, "status": "completed", "passed_factors": int, "stats": dict}
    """
    import os

    from engines.mining.gp_engine import GPConfig, GPEngine

    from scripts.run_gp_pipeline import (  # type: ignore[import]
        _compute_forward_returns,
        _load_existing_factor_data,
        _load_market_data,
        _run_full_gate,
        _send_dingtalk_notification,
    )

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://quantmind:quantmind@localhost:5432/quantmind",
    )
    dingtalk_webhook = os.environ.get("DINGTALK_WEBHOOK_URL", "")
    dingtalk_secret = os.environ.get("DINGTALK_SECRET", "")

    # 加载数据
    market_data = await _load_market_data(db_url)
    existing_factors = await _load_existing_factor_data(db_url)

    if market_data.empty:
        error_msg = "行情数据为空，GP任务中止"
        await _mark_run_failed(run_id, error_msg)
        return {"run_id": run_id, "status": "failed", "passed_factors": 0}

    forward_returns = _compute_forward_returns(market_data)

    # 初始化 GP Engine
    gp_config = GPConfig(
        n_islands=config.get("islands", 3),
        population_per_island=config.get("population", 100),
        n_generations=config.get("generations", 50),
        time_budget_minutes=config.get("time_budget_minutes", 120.0),
        migration_interval=10,
        migration_size=5,
    )

    engine = GPEngine(
        config=gp_config,
        existing_factor_data=existing_factors,
    )

    gp_results, gp_stats = engine.evolve(
        market_data=market_data,
        forward_returns=forward_returns,
        run_id=run_id,
    )

    stats: dict[str, Any] = {
        "total_evaluated": gp_stats.total_evaluated,
        "passed_quick_gate": gp_stats.passed_quick_gate,
        "best_fitness": round(gp_stats.best_fitness, 6),
        "n_generations_completed": gp_stats.n_generations_completed,
        "elapsed_seconds": round(gp_stats.elapsed_seconds, 1),
        "timeout": gp_stats.timeout,
    }

    # 完整 Gate G1-G8（取 Top 20）
    passed_factors: list[dict[str, Any]] = []
    if gp_results:
        passed_factors = _run_full_gate(
            candidates=gp_results[:20],
            market_data=market_data,
            forward_returns=forward_returns,
            blacklist=set(),
        )
    stats["passed_gate_full"] = len(passed_factors)

    # 写 DB
    await _write_results_to_db(db_url, run_id, stats, passed_factors)

    # 钉钉通知
    _send_dingtalk_notification(
        webhook_url=dingtalk_webhook,
        secret=dingtalk_secret,
        run_id=run_id,
        stats=stats,
        passed_factors=passed_factors,
    )

    return {
        "run_id": run_id,
        "status": "completed",
        "passed_factors": len(passed_factors),
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# BruteForce 挖掘任务（占位，Sprint 1.18 实现）
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="app.tasks.mining_tasks.run_bruteforce_mining",
    acks_late=True,
    max_retries=0,
    soft_time_limit=7200,
    time_limit=7800,
)
def run_bruteforce_mining(self, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """BruteForce 因子挖掘 Celery 任务（Sprint 1.18 占位）。

    Args:
        run_id: 运行 ID。
        config: BruteForce 配置。

    Returns:
        {"run_id": str, "status": "not_implemented"}
    """
    logger.warning("BruteForce 挖掘任务尚未实现", extra={"run_id": run_id})
    asyncio.run(_mark_run_failed(run_id, "BruteForce引擎尚未实现（Sprint 1.18）"))
    return {"run_id": run_id, "status": "not_implemented"}


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


async def _mark_run_failed(run_id: str, error_msg: str) -> None:
    """标记 pipeline_runs 为 failed 状态。

    Args:
        run_id: 运行 ID。
        error_msg: 错误信息。
    """
    import os

    import asyncpg

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://quantmind:quantmind@localhost:5432/quantmind",
    )
    try:
        conn = await asyncpg.connect(db_url)
        await conn.execute(
            """
            UPDATE pipeline_runs
            SET status = 'failed', finished_at = NOW(), error_message = $1
            WHERE run_id = $2
            """,
            error_msg,
            run_id,
        )
        await conn.close()
    except Exception as exc:
        logger.error("_mark_run_failed DB 写入失败", extra={"error": str(exc)})


async def _write_results_to_db(
    db_url: str,
    run_id: str,
    stats: dict[str, Any],
    passed_factors: list[dict[str, Any]],
) -> None:
    """将运行结果写入 pipeline_runs + approval_queue。

    Args:
        db_url: PostgreSQL 连接字符串。
        run_id: 运行 ID。
        stats: GP 运行统计。
        passed_factors: 通过完整 Gate 的因子列表。
    """
    import asyncpg

    try:
        conn = await asyncpg.connect(db_url)

        await conn.execute(
            """
            UPDATE pipeline_runs
            SET status = 'completed', finished_at = NOW(), stats = $1
            WHERE run_id = $2
            """,
            json.dumps(stats),
            run_id,
        )

        for factor in passed_factors:
            await conn.execute(
                """
                INSERT INTO approval_queue
                    (run_id, factor_name, factor_expr, ast_hash,
                     gate_result, status, created_at)
                VALUES ($1, $2, $3, $4, $5, 'pending', NOW())
                ON CONFLICT DO NOTHING
                """,
                run_id,
                f"gp_{factor['ast_hash'][:8]}",
                factor["factor_expr"],
                factor["ast_hash"],
                json.dumps(factor["gate_result"]),
            )

        await conn.close()
        logger.info(
            "GP 结果写入 DB 完成",
            extra={"run_id": run_id, "candidates": len(passed_factors)},
        )
    except Exception as exc:
        logger.error("GP 结果 DB 写入失败", extra={"run_id": run_id, "error": str(exc)})
