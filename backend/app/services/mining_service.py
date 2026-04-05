"""MiningService — 因子挖掘任务管理Service层。

封装 GP Pipeline 任务的提交、查询、取消和候选因子评估。
Celery 任务在 asyncio.run() 内调用（DEV_BACKEND.md 规范）。

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6: 完整闭环流程
  - docs/DEV_BACKEND.md: Service层规范 + Celery asyncio.run()

协同矩阵（DEV_BACKEND.md）:
  - MiningService → Celery tasks（提交异步GP任务）
  - MiningService → DB（pipeline_runs / approval_queue 读写）
  - MiningService → FactorGatePipeline（evaluate端点）
  - 不直接调用其他 Service
"""

from __future__ import annotations

import json
import structlog
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Celery 任务名称（在 app.tasks.mining_tasks 中注册）
_CELERY_TASK_GP = "app.tasks.mining_tasks.run_gp_mining"
_CELERY_TASK_BRUTEFORCE = "app.tasks.mining_tasks.run_bruteforce_mining"


class MiningService:
    """因子挖掘任务管理Service层。

    提供:
      - start_mining_task: 提交挖掘任务（Celery异步）
      - list_tasks: 查询任务列表
      - get_task_detail: 查询单任务详情（含候选因子）
      - cancel_task: 取消运行中任务
      - evaluate_factor_gate: 对单因子DSL表达式运行Gate
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # start_mining_task
    # ------------------------------------------------------------------

    async def start_mining_task(
        self,
        engine: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """提交挖掘任务到 Celery。

        先检查同引擎是否有正在运行的任务（避免并发GP导致资源竞争）。
        写入 pipeline_runs 初始记录，然后提交 Celery 任务。

        Args:
            engine: 引擎类型 gp/bruteforce/llm。
            config: 引擎配置 {generations/population/islands/time_budget_minutes/...}。

        Returns:
            {"task_id": str, "run_id": str, "status": "submitted"}

        Raises:
            ValueError: engine 不合法。
            RuntimeError: 同引擎任务已在运行（防止资源竞争）。
        """
        valid_engines = {"gp", "bruteforce", "llm"}
        if engine not in valid_engines:
            raise ValueError(f"engine 必须是 {valid_engines} 之一，收到: {engine!r}")

        # 检查同引擎是否已有 running 任务
        running_check = await self._session.execute(
            text(
                "SELECT run_id FROM pipeline_runs "
                "WHERE engine_type = :engine AND status = 'running' "
                "LIMIT 1"
            ),
            {"engine": engine},
        )
        existing = running_check.fetchone()
        if existing:
            raise RuntimeError(
                f"{engine.upper()} 引擎已有任务在运行 (run_id={existing[0]})，请等待完成或先取消。"
            )

        # 生成 run_id
        iso_cal = datetime.now().date().isocalendar()
        run_id = f"{engine}_{iso_cal.year}w{iso_cal.week:02d}_{uuid.uuid4().hex[:6]}"
        task_id = str(uuid.uuid4())

        # 写入 pipeline_runs（初始状态 running）
        try:
            await self._session.execute(
                text(
                    """
                    INSERT INTO pipeline_runs
                        (run_id, engine_type, started_at, status, config)
                    VALUES
                        (:run_id, :engine, NOW(), 'running', :config)
                    """
                ),
                {
                    "run_id": run_id,
                    "engine": engine,
                    "config": json.dumps({**config, "celery_task_id": task_id}),
                },
            )
            await self._session.commit()
        except Exception as exc:
            logger.warning("pipeline_runs 写入失败，继续提交任务", error=str(exc))
            await self._session.rollback()

        # 提交 Celery 任务（懒导入避免循环依赖）
        try:
            from app.tasks.celery_app import celery_app

            task_name = _CELERY_TASK_GP if engine == "gp" else _CELERY_TASK_BRUTEFORCE
            celery_app.send_task(
                task_name,
                kwargs={"run_id": run_id, "config": config},
                task_id=task_id,
            )
            logger.info(
                "挖掘任务已提交",
                engine=engine,
                run_id=run_id,
                task_id=task_id,
            )
        except Exception as exc:
            # Celery 不可用时降级：记录日志，返回 pending 状态
            logger.error("Celery 任务提交失败，任务处于 pending 状态", error=str(exc))
            await self._session.execute(
                text(
                    "UPDATE pipeline_runs SET status='failed', "
                    "error_message=:err WHERE run_id=:run_id"
                ),
                {"err": f"Celery提交失败: {exc}", "run_id": run_id},
            )
            await self._session.commit()

        return {"task_id": task_id, "run_id": run_id, "status": "submitted"}

    # ------------------------------------------------------------------
    # list_tasks
    # ------------------------------------------------------------------

    async def list_tasks(
        self,
        engine: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询挖掘任务列表（按 started_at 降序）。

        Args:
            engine: 按引擎筛选（None=不筛选）。
            status: 按状态筛选（None=不筛选）。
            limit: 最多返回条数。

        Returns:
            任务列表，每项含 run_id/engine/status/started_at/finished_at/stats。
        """
        where_clauses = []
        params: dict[str, Any] = {"limit": limit}

        if engine:
            where_clauses.append("engine_type = :engine")
            params["engine"] = engine
        if status:
            where_clauses.append("status = :status")
            params["status"] = status

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        rows = await self._session.execute(
            text(
                f"""
                SELECT run_id, engine_type, status, started_at, finished_at,
                       config, result_summary, error_message
                FROM pipeline_runs
                {where_sql}
                ORDER BY started_at DESC
                LIMIT :limit
                """
            ),
            params,
        )

        result = []
        for row in rows.fetchall():
            run_id, eng, st, started, finished, cfg, stats_json, err = row
            result.append(
                {
                    "run_id": run_id,
                    "engine": eng,
                    "status": st,
                    "started_at": started.isoformat() if started else None,
                    "finished_at": finished.isoformat() if finished else None,
                    "config": cfg if isinstance(cfg, dict) else (json.loads(cfg) if cfg else {}),
                    "stats": stats_json
                    if isinstance(stats_json, dict)
                    else (json.loads(stats_json) if stats_json else {}),
                    "error_message": err,
                }
            )

        return result

    # ------------------------------------------------------------------
    # get_task_detail
    # ------------------------------------------------------------------

    async def get_task_detail(self, task_id: str) -> dict[str, Any] | None:
        """获取单个任务详情（通过 run_id 或 celery task_id 查询）。

        Args:
            task_id: Celery task_id（也接受 run_id 格式）。

        Returns:
            任务详情字典（含 candidates），不存在时返回 None。
        """
        # 先尝试 config->>'celery_task_id' 匹配
        row = await self._session.execute(
            text(
                """
                SELECT run_id, engine_type, status, started_at, finished_at,
                       config, result_summary, error_message
                FROM pipeline_runs
                WHERE config->>'celery_task_id' = :task_id
                   OR run_id = :task_id
                LIMIT 1
                """
            ),
            {"task_id": task_id},
        )
        record = row.fetchone()
        if not record:
            return None

        run_id, eng, st, started, finished, cfg, stats_json, err = record

        # 查 approval_queue 候选因子
        cands_rows = await self._session.execute(
            text(
                """
                SELECT id, factor_name, factor_expr, ast_hash,
                       gate_report, status, created_at
                FROM gp_approval_queue
                WHERE run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"run_id": run_id},
        )
        candidates = []
        for c in cands_rows.fetchall():
            cid, fname, fexpr, ahash, gate_r, cstatus, cat = c
            candidates.append(
                {
                    "id": cid,
                    "factor_name": fname,
                    "factor_expr": fexpr,
                    "ast_hash": ahash,
                    "gate_report": gate_r
                    if isinstance(gate_r, dict)
                    else (json.loads(gate_r) if gate_r else {}),
                    "status": cstatus,
                    "created_at": cat.isoformat() if cat else None,
                }
            )

        return {
            "task_id": task_id,
            "run_id": run_id,
            "engine": eng,
            "status": st,
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
            "config": cfg if isinstance(cfg, dict) else (json.loads(cfg) if cfg else {}),
            "stats": stats_json
            if isinstance(stats_json, dict)
            else (json.loads(stats_json) if stats_json else {}),
            "error_message": err,
            "candidates": candidates,
        }

    # ------------------------------------------------------------------
    # cancel_task
    # ------------------------------------------------------------------

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """取消运行中的挖掘任务。

        Args:
            task_id: Celery task_id 或 run_id。

        Returns:
            {"task_id": str, "cancelled": bool, "message": str}

        Raises:
            LookupError: task_id 不存在。
            ValueError: 任务已完成，无法取消。
        """
        detail = await self.get_task_detail(task_id)
        if detail is None:
            raise LookupError(f"任务不存在: {task_id}")

        if detail["status"] in ("completed", "failed", "timeout"):
            raise ValueError(f"任务已结束 (status={detail['status']})，无法取消。")

        # 通过 Celery revoke 发送中止信号
        try:
            from app.tasks.celery_app import celery_app

            celery_task_id = detail.get("config", {}).get("celery_task_id") or task_id
            celery_app.control.revoke(celery_task_id, terminate=True, signal="SIGTERM")
            logger.info("Celery revoke 发送", task_id=celery_task_id)
        except Exception as exc:
            logger.warning("Celery revoke 失败", error=str(exc))

        # 更新 DB 状态
        try:
            await self._session.execute(
                text(
                    "UPDATE pipeline_runs SET status='failed', "
                    "finished_at=NOW(), error_message='用户手动取消' "
                    "WHERE run_id = :run_id AND status = 'running'"
                ),
                {"run_id": detail["run_id"]},
            )
            await self._session.commit()
        except Exception as exc:
            logger.warning("取消状态写入失败", error=str(exc))
            await self._session.rollback()

        return {
            "task_id": task_id,
            "run_id": detail["run_id"],
            "cancelled": True,
            "message": f"取消信号已发送，run_id={detail['run_id']}",
        }

    # ------------------------------------------------------------------
    # evaluate_factor_gate
    # ------------------------------------------------------------------

    async def evaluate_factor_gate(
        self,
        factor_expr: str,
        factor_name: str | None = None,
        quick_only: bool = False,
    ) -> dict[str, Any]:
        """对单个DSL表达式运行 Gate 评估。

        从DB加载最近截面数据（asyncpg直连），同步调用 FactorGatePipeline。

        Args:
            factor_expr: 因子DSL表达式字符串。
            factor_name: 可选因子名称，未填则自动生成。
            quick_only: True=只跑G1-G4快速Gate。

        Returns:
            {
              "factor_name": str,
              "factor_expr": str,
              "gate_result": {G1: "PASS"|"FAIL", ...},
              "overall_passed": bool,
              "ic_mean": float,
              "t_stat": float,
              "elapsed_seconds": float,
            }

        Raises:
            ValueError: DSL表达式非法。
            ConnectionError: DB数据加载失败。
        """
        import time

        start = time.monotonic()

        # 解析 DSL
        try:
            from engines.mining.factor_dsl import FactorDSL

            dsl = FactorDSL()
            tree = dsl.from_string(factor_expr)
            valid, reason = dsl.validate(tree)
            if not valid:
                raise ValueError(f"DSL 表达式非法: {reason}")
        except Exception as exc:
            raise ValueError(f"DSL 解析失败: {exc}") from exc

        # 加载行情数据（使用现有DB session的连接字符串）
        import os

        import asyncpg
        import pandas as pd

        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://quantmind:quantmind@localhost:5432/quantmind",
        )

        try:
            conn = await asyncpg.connect(db_url)
            from datetime import date

            cutoff = date.today().replace(year=date.today().year - 1)
            rows = await conn.fetch(
                """
                SELECT k.trade_date, s.ts_code AS code,
                       k.open, k.high, k.low, k.close,
                       k.volume, k.amount, k.turnover_rate,
                       v.pe_ttm, v.pb
                FROM klines_daily k
                JOIN symbols s ON k.symbol_id = s.id
                LEFT JOIN stock_valuation v
                    ON v.symbol_id = k.symbol_id AND v.trade_date = k.trade_date
                WHERE k.trade_date >= $1
                  AND s.market = 'A' AND s.status = 'active'
                ORDER BY k.trade_date, s.ts_code
                LIMIT 500000
                """,
                cutoff,
            )
            await conn.close()
        except Exception as exc:
            raise ConnectionError(f"行情数据加载失败: {exc}") from exc

        if not rows:
            raise ConnectionError("行情数据为空，无法评估")

        market_data = pd.DataFrame(
            rows,
            columns=[
                "trade_date",
                "code",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "turnover_rate",
                "pe_ttm",
                "pb",
            ],
        )
        market_data = market_data.sort_values(["code", "trade_date"])
        market_data["returns"] = market_data.groupby("code")["close"].pct_change()

        # 计算因子值
        try:
            factor_values = tree.evaluate(market_data)
        except Exception as exc:
            raise ValueError(f"因子计算失败: {exc}") from exc

        if factor_values is None or (hasattr(factor_values, "empty") and factor_values.empty):
            raise ValueError("因子值计算结果为空")

        # 计算前向收益
        from scripts.run_gp_pipeline import _compute_forward_returns  # type: ignore[import]

        forward_returns = _compute_forward_returns(market_data)

        # 自动命名
        if not factor_name:
            import hashlib

            h = hashlib.sha256(factor_expr.encode()).hexdigest()[:8]
            factor_name = f"eval_{h}"

        # 运行 Gate
        try:
            from engines.factor_gate import FactorGatePipeline

            gate = FactorGatePipeline()

            if quick_only:
                report = gate.run_quick(
                    factor_values=factor_values,
                    forward_returns=forward_returns,
                )
            else:
                report = gate.run(
                    factor_name=factor_name,
                    factor_values=factor_values,
                    forward_returns=forward_returns,
                )
        except Exception as exc:
            raise ValueError(f"Gate 评估失败: {exc}") from exc

        elapsed = time.monotonic() - start

        gate_summary = {g: str(r.status) for g, r in report.gate_results.items()}

        return {
            "factor_name": factor_name,
            "factor_expr": factor_expr,
            "gate_result": gate_summary,
            "overall_passed": report.overall_passed,
            "ic_mean": round(float(getattr(report, "ic_mean", 0.0) or 0.0), 6),
            "t_stat": round(float(getattr(report, "t_stat", 0.0) or 0.0), 4),
            "elapsed_seconds": round(elapsed, 2),
            "quick_only": quick_only,
        }
