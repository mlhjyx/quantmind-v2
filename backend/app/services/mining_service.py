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

铁律 32: Service 内部不 commit/rollback。事务由 get_db() 上下文管理器自动管理
    (成功→commit, 异常→rollback)。F18 Phase E (2026-04-16) 移除冗余 commit/rollback。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Celery 任务名称（在 app.tasks.mining_tasks 中注册）
_CELERY_TASK_GP = "app.tasks.mining_tasks.run_gp_mining"
_CELERY_TASK_BRUTEFORCE = "app.tasks.mining_tasks.run_bruteforce_mining"


def _gate_status_text(status: Any) -> str:
    """Return stable API text for GateStatus/str-like status values."""
    return str(getattr(status, "value", status))


def _summarize_gate_report(report: Any, quick_only: bool = False) -> dict[str, str]:
    """Summarize the current FactorGate ``GateReport`` contract for API output."""
    gates = getattr(report, "gates", None)
    if gates is None:
        gates = getattr(report, "gate_results", {})

    quick_gate_ids = {f"G{i}" for i in range(1, 6)}
    result: dict[str, str] = {}
    for gate_id, gate_result in gates.items():
        if quick_only and gate_id not in quick_gate_ids:
            continue
        result[str(gate_id)] = _gate_status_text(getattr(gate_result, "status", gate_result))
    return result


def _gate_report_passed(
    report: Any, gate_summary: dict[str, str], quick_only: bool = False
) -> bool:
    """Map FactorGate report status to the legacy mining evaluate boolean."""
    if quick_only:
        quick_gate_ids = [f"G{i}" for i in range(1, 6)]
        present = [gate_summary[g] for g in quick_gate_ids if g in gate_summary]
        return bool(present) and all(status == "PASS" for status in present)

    legacy_passed = getattr(report, "overall_passed", None)
    if legacy_passed is not None:
        return bool(legacy_passed)
    return str(getattr(report, "overall_status", "")) in {"PASS", "PARTIAL"}


def _gate_report_metric(report: Any, metric: str) -> float:
    """Extract IC/t-stat style summary metrics from the current GateReport shape."""
    direct = getattr(report, metric, None)
    if direct is not None:
        return float(direct)

    gates = getattr(report, "gates", None) or getattr(report, "gate_results", {})
    if metric == "ic_mean":
        g1 = gates.get("G1")
        if g1 is not None:
            data = getattr(g1, "data", {}) or {}
            if "ic_mean" in data:
                return float(data["ic_mean"])
            value = getattr(g1, "metric_value", None)
            if value is not None:
                return float(value)
    if metric == "t_stat":
        for gate_id in ("G6", "G3"):
            gate = gates.get(gate_id)
            if gate is None:
                continue
            data = getattr(gate, "data", {}) or {}
            for key in ("raw_t_stat", "t_stat_newey_west"):
                if key in data:
                    return float(data[key])
            value = getattr(gate, "metric_value", None)
            if value is not None:
                return float(value)
    return 0.0


def _evaluation_forward_returns(market_data: Any, forward_days: int = 20) -> Any:
    """Build a panel forward-return Series aligned to evaluation factor values."""
    close_frame = market_data[["trade_date", "code", "close"]].copy()
    close_frame = close_frame.sort_values(["code", "trade_date"], kind="mergesort")
    close = close_frame.set_index(["trade_date", "code"])["close"].astype("float64")
    future = close.groupby(level="code").shift(-forward_days)
    return (future / close - 1.0).rename(f"fwd_ret_{forward_days}d")


def _with_evaluation_panel_index(series: Any, market_data: Any) -> Any:
    """Attach (trade_date, code) panel index when DSL evaluation preserved row order."""
    if len(series) != len(market_data):
        return series
    result = series.copy()
    result.index = market_data.set_index(["trade_date", "code"]).index
    return result


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
    # D1 O3 — Pause gate helper (PN-003 iter 12)
    # ------------------------------------------------------------------

    async def _is_paused(self) -> tuple[datetime, str | None] | None:
        """读取 pipeline_settings 当前 pause 状态.

        Returns:
            (paused_at, paused_reason) when paused_at IS NOT NULL.
            None when active (paused_at IS NULL or table is empty — defensive
            default mirrors PN-001 GET /automation-level behavior).

        Used by start_mining_task to gate-at-entry the /trigger path.
        Return-type-narrowed datetime (P2 reviewer fix iter 12) — row[0] is
        a TIMESTAMPTZ column, asyncpg/SQLAlchemy decode it as datetime.
        """
        result = await self._session.execute(
            text("SELECT paused_at, paused_reason FROM pipeline_settings WHERE id = 1")
        )
        row = result.first()
        if row is None or row[0] is None:
            return None
        return (row[0], row[1])

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

        # D1 O3 (PN-003 iter 12) — pause gate-at-entry. If pipeline_settings.paused_at
        # is NOT NULL, refuse to start a new run regardless of engine availability.
        # Route layer converts RuntimeError → 409 (same pattern as engine-running check).
        paused_state = await self._is_paused()
        if paused_state is not None:
            paused_at, paused_reason = paused_state
            reason_suffix = f" ({paused_reason})" if paused_reason else ""
            raise RuntimeError(
                f"Pipeline paused since {paused_at.isoformat()}{reason_suffix}; "
                f"call POST /api/pipeline/resume before triggering."
            )

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
            pass  # 铁律 32: 不 commit, get_db() 自动管理
        except Exception as exc:
            logger.warning("pipeline_runs 写入失败，继续提交任务", error=str(exc))
            await self._session.rollback()  # SQLAlchemy 要求失败后 rollback 才能继续使用 session

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
            # 铁律 32: 不 commit, get_db() 自动管理

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
            # 铁律 32: 不 commit, get_db() 自动管理
        except Exception as exc:
            logger.warning("取消状态写入失败", error=str(exc))
            await self._session.rollback()  # SQLAlchemy 要求失败后 rollback

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

        factor_values = _with_evaluation_panel_index(factor_values, market_data)
        forward_returns = _evaluation_forward_returns(market_data)

        # 自动命名
        if not factor_name:
            import hashlib

            h = hashlib.sha256(factor_expr.encode()).hexdigest()[:8]
            factor_name = f"eval_{h}"

        # 运行 Gate
        try:
            from engines.factor_gate import FactorGatePipeline
            from engines.mining.pipeline_utils import _compute_gate_ic_series

            gate = FactorGatePipeline()
            ic_series = _compute_gate_ic_series(factor_values, forward_returns)
            report = gate.run_gates(
                factor_name=factor_name,
                ic_series=ic_series,
                neutral_ic_series=None,
                expected_direction=1,
            )
        except Exception as exc:
            raise ValueError(f"Gate 评估失败: {exc}") from exc

        elapsed = time.monotonic() - start

        gate_summary = _summarize_gate_report(report, quick_only=quick_only)

        return {
            "factor_name": factor_name,
            "factor_expr": factor_expr,
            "gate_result": gate_summary,
            "overall_passed": _gate_report_passed(report, gate_summary, quick_only=quick_only),
            "overall_status": str(getattr(report, "overall_status", "UNKNOWN")),
            "ic_mean": round(_gate_report_metric(report, "ic_mean"), 6),
            "t_stat": round(_gate_report_metric(report, "t_stat"), 4),
            "elapsed_seconds": round(elapsed, 2),
            "quick_only": quick_only,
        }
