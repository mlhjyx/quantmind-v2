"""因子挖掘 Celery 任务 — GP/BruteForce 引擎的异步执行封装。

每个 task 用 asyncio.run() 包装 async 逻辑（DEV_BACKEND.md 标准写法）。
完成后更新 pipeline_runs.status + stats，并写入 gp_approval_queue。

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6: 完整闭环流程
  - docs/DEV_BACKEND.md §4.12.3: Celery Task 模板
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.mining_tasks")


def _generate_run_id(config: dict[str, Any], engine: str = "gp") -> str:
    """根据当前时间+配置生成唯一 run_id。

    格式: {engine}_{YYYY}w{WW}_{hash8}
    例如: gp_2026w14_a1b2c3d4 / bruteforce_2026w14_a1b2c3d4

    Args:
        config: GP 配置字典（用于哈希，保证同周不同配置产生不同ID）。

    Returns:
        唯一 run_id 字符串。
    """
    now = datetime.now(UTC)
    year = now.year
    week = now.isocalendar()[1]
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8]
    return f"{engine}_{year}w{week:02d}_{config_hash}"


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
def run_gp_mining(self, run_id: str | None, config: dict[str, Any]) -> dict[str, Any]:
    """GP 因子挖掘 Celery 任务。

    asyncio.run() 包装：在 Celery prefork Worker 中安全运行 async 代码。

    Beat 调度时 run_id=None，此时自动生成 run_id 并写入 pipeline_runs。
    手动触发时需传入已写入 pipeline_runs 的 run_id。

    Args:
        run_id: 本次运行 ID。None 时自动生成（Beat 调度场景）。
        config: GP 配置 {generations/population/islands/time_budget_minutes}。

    Returns:
        {"run_id": str, "status": str, "passed_factors": int, "stats": dict}
    """
    # D1 O3 (PN-003 iter 12) — pause gate-at-entry. If pipeline_settings.paused_at
    # is NOT NULL, skip this Beat tick entirely. No pipeline_runs row written, no
    # failure marked. Next Beat tick re-attempts (advisory pause, not abort).
    paused = asyncio.run(_is_pipeline_paused())
    if paused is not None:
        paused_at, paused_reason = paused
        logger.info(
            "GP 挖掘任务跳过 (pipeline paused)",
            extra={
                "event": "pipeline_skipped_paused",
                "engine": "gp",
                "paused_at": paused_at.isoformat()
                if hasattr(paused_at, "isoformat")
                else str(paused_at),
                "paused_reason": paused_reason,
            },
        )
        return {"status": "skipped_paused", "engine": "gp", "run_id": run_id}

    # Beat 触发时 run_id=None，自动生成并写入 pipeline_runs
    if run_id is None:
        run_id = _generate_run_id(config)
        asyncio.run(_init_pipeline_run(run_id, config))
        logger.info(
            "Beat 调度触发 GP 挖掘，自动生成 run_id",
            extra={"run_id": run_id, "config": config},
        )

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
    from engines.mining.pipeline_utils import (
        compute_forward_returns,
        load_existing_factor_data,
        load_market_data,
        run_full_gate,
        send_dingtalk_notification,
    )

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://xin:quantmind@localhost:5432/quantmind_v2",
    )
    dingtalk_webhook = os.environ.get("DINGTALK_WEBHOOK_URL", "")
    dingtalk_secret = os.environ.get("DINGTALK_SECRET", "")

    # 加载数据
    market_data = await load_market_data(db_url)
    existing_factors = await load_existing_factor_data(db_url)

    if market_data.empty:
        error_msg = "行情数据为空，GP任务中止"
        await _mark_run_failed(run_id, error_msg)
        return {"run_id": run_id, "status": "failed", "passed_factors": 0}

    forward_returns = compute_forward_returns(market_data)

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
        passed_factors = run_full_gate(
            candidates=gp_results[:20],
            market_data=market_data,
            forward_returns=forward_returns,
            blacklist=set(),
        )
    stats["passed_gate_full"] = len(passed_factors)

    # 写 DB
    await _write_results_to_db(db_url, run_id, stats, passed_factors)

    # 钉钉通知
    send_dingtalk_notification(
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
# BruteForce 挖掘任务
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
    """BruteForce 因子挖掘 Celery 任务。

    Args:
        run_id: 运行 ID。
        config: BruteForce 配置。

    Returns:
        {"run_id": str, "status": "completed", "passed_factors": int, "stats": dict}
    """
    # D1 O3 (PN-003 iter 12) — pause gate-at-entry, see run_gp_mining for rationale.
    paused = asyncio.run(_is_pipeline_paused())
    if paused is not None:
        paused_at, paused_reason = paused
        logger.info(
            "BruteForce 挖掘任务跳过 (pipeline paused)",
            extra={
                "event": "pipeline_skipped_paused",
                "engine": "bruteforce",
                "paused_at": paused_at.isoformat()
                if hasattr(paused_at, "isoformat")
                else str(paused_at),
                "paused_reason": paused_reason,
            },
        )
        return {"status": "skipped_paused", "engine": "bruteforce", "run_id": run_id}

    if not run_id:
        run_id = _generate_run_id(config, engine="bruteforce")
        asyncio.run(_init_pipeline_run(run_id, config, engine_type="bruteforce"))

    logger.info("BruteForce 挖掘任务启动", extra={"run_id": run_id, "config": config})
    start = time.monotonic()

    try:
        result = asyncio.run(_run_bruteforce_mining_async(run_id, config))
        elapsed = time.monotonic() - start
        logger.info(
            "BruteForce 挖掘任务完成",
            extra={
                "run_id": run_id,
                "elapsed_min": round(elapsed / 60, 1),
                "passed_factors": result.get("passed_factors", 0),
            },
        )
        return result
    except Exception as exc:
        logger.error(
            "BruteForce 挖掘任务异常",
            extra={"run_id": run_id, "error": str(exc)},
            exc_info=True,
        )
        asyncio.run(_mark_run_failed(run_id, str(exc)))
        raise


async def _run_bruteforce_mining_async(run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """BruteForce 挖掘主逻辑.

    当前闭环为 discovery-grade: 运行 BruteForce G1-G3 快速 Gate, 将候选以
    quick_gate_only 标记写入 gp_approval_queue, 后续仍需人工/完整 Gate 审查。
    """
    import os

    from engines.mining.ast_dedup import ASTDeduplicator
    from engines.mining.bruteforce_engine import FACTOR_TEMPLATES, BruteForceEngine, FactorTemplate
    from engines.mining.pipeline_utils import (
        load_market_data,
        send_dingtalk_notification,
    )

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://xin:quantmind@localhost:5432/quantmind_v2",
    )
    dingtalk_webhook = os.environ.get("DINGTALK_WEBHOOK", "")
    dingtalk_secret = os.environ.get("DINGTALK_SECRET")
    start = time.monotonic()

    lookback_days = int(config.get("lookback_days", 365))
    forward_days = int(config.get("forward_days", config.get("horizon", 20)))
    max_combinations = max(1, int(config.get("max_combinations", 1000)))
    gate_top_k = max(1, min(int(config.get("gate_top_k", 20)), 100))

    market_data = await load_market_data(db_url, lookback_days=lookback_days)
    if market_data.empty:
        await _mark_run_failed(run_id, "BruteForce行情数据为空")
        return {"run_id": run_id, "status": "failed", "error": "market_data_empty"}

    panel_data = _prepare_bruteforce_panel(market_data)
    forward_returns = _compute_panel_forward_returns(panel_data, forward_days=forward_days)
    if forward_returns.dropna().empty:
        await _mark_run_failed(run_id, "BruteForce前向收益为空")
        return {"run_id": run_id, "status": "failed", "error": "forward_returns_empty"}

    templates = _select_bruteforce_templates(
        config=config,
        all_templates=FACTOR_TEMPLATES,
        template_cls=FactorTemplate,
    )
    templates = templates[:max_combinations]
    if not templates:
        await _mark_run_failed(run_id, "BruteForce模板筛选后为空")
        return {"run_id": run_id, "status": "failed", "error": "templates_empty"}

    engine = BruteForceEngine(
        g1_ic_threshold=float(config.get("g1_ic_threshold", 0.015)),
        g2_corr_threshold=float(config.get("g2_corr_threshold", 0.7)),
        g3_t_threshold=float(config.get("g3_t_threshold", 2.0)),
        min_ic_periods=int(config.get("min_ic_periods", 12)),
    )
    enumerated_count = len(engine.enumerate_candidates(templates))
    quick_results = engine.run(
        panel_data=panel_data,
        forward_returns=forward_returns,
        active_factors=None,
        templates=templates,
    )
    quick_results.sort(key=lambda c: (abs(c.t_stat), abs(c.ic_mean)), reverse=True)

    dedup = ASTDeduplicator()
    passed_factors = [
        _bruteforce_candidate_to_queue_payload(candidate, dedup)
        for candidate in quick_results[:gate_top_k]
    ]
    best = passed_factors[0] if passed_factors else None
    elapsed_seconds = round(time.monotonic() - start, 1)
    stats: dict[str, Any] = {
        "engine": "bruteforce",
        "quick_gate_only": True,
        "total_evaluated": enumerated_count,
        "passed_quick_gate": len(quick_results),
        "passed_gate_full": len(passed_factors),
        "best_fitness": best["fitness"] if best else 0.0,
        "best_expr": best["factor_expr"] if best else "",
        "elapsed_seconds": elapsed_seconds,
        "lookback_days": lookback_days,
        "forward_days": forward_days,
        "template_count": len(templates),
    }

    await _write_results_to_db(
        db_url,
        run_id,
        stats,
        passed_factors,
        factor_prefix="bf",
    )

    send_dingtalk_notification(
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
# 内部辅助函数
# ---------------------------------------------------------------------------


async def _is_pipeline_paused() -> tuple[Any, str | None] | None:
    """D1 O3 (PN-003 iter 12) — 检查 pipeline_settings.paused_at 状态.

    Returns:
        (paused_at, paused_reason) tuple when paused; None when active.
        表无 row (migration 未跑) → None (defensive default mirrors API helper).
        DB 查询失败 → None (fail-safe: 优先保证 Beat 调度不卡死, log warn).

    沿用 _init_pipeline_run / _mark_run_failed 的 asyncpg DB_URL 体例.
    """
    import os

    import asyncpg

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://xin:quantmind@localhost:5432/quantmind_v2",
    )
    try:
        conn = await asyncpg.connect(db_url)
        try:
            row = await conn.fetchrow(
                "SELECT paused_at, paused_reason FROM pipeline_settings WHERE id = 1"
            )
        finally:
            await conn.close()
        if row is None or row["paused_at"] is None:
            return None
        return (row["paused_at"], row["paused_reason"])
    except Exception as exc:
        # Fail-safe trade-off (PN-003 §6 R2 + P2 reviewer fix iter 12): on DB
        # error we return None → Beat task proceeds. This trades pause-safety
        # for Beat liveness — a pause request the DB can't surface lets a
        # paused pipeline still fire. We accept this because (a) pause is
        # advisory not a safety control (red lines live in .env + broker
        # guard), and (b) blocking Beat indefinitely on transient DB blip is
        # worse than the rare missed pause. 沿用铁律 33 显式 silent_ok 注释.
        logger.warning(  # silent_ok: gate-at-entry fail-safe — Beat liveness > pause safety
            "_is_pipeline_paused DB 查询失败 (跳过 pause 检查)",
            extra={"error": str(exc)},
        )
        return None


def _prepare_bruteforce_panel(market_data: Any) -> Any:
    """将 pipeline_utils 行情宽表转换为 BruteForce 所需 MultiIndex 面板."""
    rename_map = {"trade_date": "date", "code": "symbol_id", "turnover": "turnover_rate"}
    panel = market_data.rename(columns=rename_map).copy()
    required = {"date", "symbol_id", "close"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"BruteForce行情数据缺少必要列: {sorted(missing)}")
    panel = panel.sort_values(["symbol_id", "date"], kind="mergesort")
    return panel.set_index(["date", "symbol_id"]).sort_index()


def _compute_panel_forward_returns(panel_data: Any, forward_days: int = 20) -> Any:
    """按 symbol 计算 MultiIndex(date, symbol_id) 前向收益."""
    close = panel_data["close"].astype("float64")
    future = close.groupby(level="symbol_id").shift(-forward_days)
    return (future / close - 1.0).rename(f"fwd_ret_{forward_days}d")


def _select_bruteforce_templates(
    config: dict[str, Any],
    all_templates: list[Any],
    template_cls: type[Any],
) -> list[Any]:
    """按前端 BruteForce 配置筛选内置模板和窗口."""
    requested_fields = set(config.get("fields") or [])
    field_aliases = {"turnover": "turnover_rate"}
    requested_fields = {field_aliases.get(f, f) for f in requested_fields}
    requested_windows = {int(w) for w in config.get("windows") or []}
    requested_functions = set(config.get("functions") or [])

    selected: list[Any] = []
    for template in all_templates:
        if requested_fields and not set(template.required_fields).issubset(requested_fields):
            continue
        windows = tuple(
            w for w in template.windows if not requested_windows or w in requested_windows
        )
        if not windows:
            continue
        if requested_functions and not any(
            fn in template.expr_template for fn in requested_functions
        ):
            continue
        selected.append(
            template_cls(
                name=template.name,
                category=template.category,
                description=template.description,
                economic_rationale=template.economic_rationale,
                direction=template.direction,
                required_fields=list(template.required_fields),
                windows=windows,
                expr_template=template.expr_template,
                academic_support=template.academic_support,
            )
        )
    return selected


def _bruteforce_candidate_to_queue_payload(candidate: Any, dedup: Any) -> dict[str, Any]:
    """把 BruteForce FactorCandidate 转成 gp_approval_queue 写入结构."""
    ast_hash = dedup.ast_hash(candidate.expression)
    direction = 1 if candidate.direction == "positive" else -1
    fitness = abs(candidate.ic_mean) * max(abs(candidate.t_stat), 1.0)
    return {
        "factor_expr": candidate.expression,
        "ast_hash": ast_hash,
        "fitness": round(float(fitness), 6),
        "ic_mean": round(float(candidate.ic_mean), 6),
        "t_stat": round(float(candidate.t_stat), 4),
        "complexity": round(len(candidate.expression) / 100.0, 4),
        "novelty": round(1.0 - max(float(candidate.max_corr_with_active), 0.0), 4),
        "gate_result": {
            "G1": "PASS" if candidate.passed_g1 else "FAIL",
            "G2": "PASS" if candidate.passed_g2 else "FAIL",
            "G3": "PASS" if candidate.passed_g3 else "FAIL",
            "G4": "PENDING_NEUTRAL_IC",
            "G5": "PENDING_DIRECTION_REVIEW",
            "G6": "PENDING_QUANT_REVIEW",
            "G7": "PENDING_BACKTEST",
            "G8": "PENDING_STRATEGY_FIT",
            "quick_gate_only": True,
            "engine": "bruteforce",
            "factor_name": candidate.name,
            "category": candidate.category,
            "direction": candidate.direction,
            "expected_direction": direction,
            "window": candidate.window,
            "academic_support": candidate.academic_support,
            "economic_rationale": candidate.economic_rationale,
        },
        "parent_seed": candidate.name,
        "generation": 0,
        "island_id": 0,
        "param_slots": {"window": candidate.window},
    }


async def _init_pipeline_run(
    run_id: str,
    config: dict[str, Any],
    engine_type: str = "gp",
) -> None:
    """在 pipeline_runs 写入初始记录（status='running'）。

    Beat 自动调度场景下由 task 自身负责写入，而非调用方。

    Args:
        run_id: 自动生成的运行 ID。
        config: 引擎配置字典，写入 config 列备查。
        engine_type: pipeline_runs.engine_type。
    """
    import os

    import asyncpg

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://xin:quantmind@localhost:5432/quantmind_v2",
    )
    try:
        conn = await asyncpg.connect(db_url)
        await conn.execute(
            """
            INSERT INTO pipeline_runs
                (run_id, engine_type, status, config, started_at)
            VALUES ($1, $2, 'running', $3, NOW())
            ON CONFLICT (run_id) DO NOTHING
            """,
            run_id,
            engine_type,
            json.dumps(config),
        )
        await conn.close()
        logger.info("pipeline_runs 初始记录写入成功", extra={"run_id": run_id})
    except Exception as exc:
        logger.error(
            "_init_pipeline_run DB 写入失败（任务继续）",
            extra={"run_id": run_id, "error": str(exc)},
        )


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
        "postgresql://xin:quantmind@localhost:5432/quantmind_v2",
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
    factor_prefix: str = "gp",
) -> None:
    """将运行结果写入 pipeline_runs + gp_approval_queue。

    Args:
        db_url: PostgreSQL 连接字符串。
        run_id: 运行 ID。
        stats: 引擎运行统计。
        passed_factors: 待审批候选列表；可来自完整 Gate 或 quick-gate-only 发现路径。
        factor_prefix: gp_approval_queue.factor_name 前缀。
    """
    import asyncpg

    try:
        conn = await asyncpg.connect(db_url)

        # result_summary 规范字段（Phase 2 要求）:
        # total_evaluated, passed_gate, best_fitness, elapsed_seconds
        result_summary = {
            "total_evaluated": stats.get("total_evaluated", 0),
            "passed_gate": stats.get("passed_gate_full", 0),  # 标准化字段名
            "best_fitness": stats.get("best_fitness", 0.0),
            "elapsed_seconds": stats.get("elapsed_seconds", 0.0),
            # 附加字段（供前端详情页使用）
            "passed_quick_gate": stats.get("passed_quick_gate", 0),
            "n_generations_completed": stats.get("n_generations_completed", 0),
            "timeout": stats.get("timeout", False),
        }
        await conn.execute(
            """
            UPDATE pipeline_runs
            SET status = 'completed', finished_at = NOW(), result_summary = $1
            WHERE run_id = $2
            """,
            json.dumps(result_summary),
            run_id,
        )

        for factor in passed_factors:
            await conn.execute(
                """
                INSERT INTO gp_approval_queue
                    (run_id, factor_name, factor_expr, ast_hash,
                     gate_report, status, created_at)
                VALUES ($1, $2, $3, $4, $5, 'pending', NOW())
                -- ON CONFLICT DO NOTHING: gp_approval_queue 无 ast_hash UNIQUE
                -- 约束 → 当前对该子句无自然冲突键, 实为 no-op。真去重靠
                -- mining_knowledge.ast_hash 黑名单 (UNIQUE 约束需 DDL, follow-up)。
                ON CONFLICT DO NOTHING
                """,
                run_id,
                f"{factor_prefix}_{factor['ast_hash'][:8]}",
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
