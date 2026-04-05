"""BacktestService — 回测引擎的Service层封装。

封装 backend/engines/backtest_engine.py 给API层使用。
负责: 创建回测记录 → 提交Celery异步任务 → 查询结果 → 策略对比。

设计文档对照:
- docs/DEV_BACKEND.md §三 services/backtest_service.py（submit_backtest/get_result）
- docs/DEV_BACKTEST_ENGINE.md §4.12.3 Celery Task模板

协同矩阵（DEV_BACKEND.md）:
- BacktestService → NotificationService（回测完成/失败通知）
- 不直接调用其他Service

FastAPI Depends注入模式:
    async def get_backtest_service(
        session: AsyncSession = Depends(get_async_session),
    ) -> BacktestService:
        return BacktestService(session)
"""

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class BacktestService:
    """回测管理Service层。

    提供:
    - submit_backtest: 提交回测任务（异步Celery）
    - get_backtest_result: 查询回测结果
    - get_backtest_list: 查询历史回测列表
    - compare_strategies: 多策略回测对比
    - cancel_backtest: 取消运行中的回测
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def submit_backtest(
        self,
        strategy_id: str,
        config: dict[str, Any],
        market: str = "astock",
    ) -> str:
        """创建回测记录并提交Celery异步任务。

        Args:
            strategy_id: 策略ID（对应strategy_configs表）
            config: 回测配置（含start_date/end_date/top_n/rebalance_freq等）
            market: 市场类型（'astock'或'forex'）

        Returns:
            run_id（UUID字符串），可用于后续查询

        Raises:
            ValueError: 策略不存在时抛出
        """
        run_id = str(uuid.uuid4())

        # 写入backtest_run记录
        await self._session.execute(
            text(
                """
                INSERT INTO backtest_run
                    (run_id, strategy_id, status, config, market, created_at)
                VALUES
                    (:run_id, :strategy_id, 'pending', :config::jsonb,
                     :market, NOW())
                """
            ),
            {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "config": _dict_to_json(config),
                "market": market,
            },
        )
        await self._session.commit()

        # 提交Celery任务
        try:
            if market == "astock":
                from app.tasks.backtest_tasks import run_backtest  # type: ignore

                task = run_backtest.delay(run_id)
            else:
                from app.tasks.forex_tasks import run_forex_backtest_task  # type: ignore

                task = run_forex_backtest_task.delay(run_id, strategy_id, config)

            # 更新celery_task_id
            await self._session.execute(
                text("UPDATE backtest_run SET celery_task_id = :task_id WHERE run_id = :run_id"),
                {"task_id": task.id, "run_id": run_id},
            )
            await self._session.commit()
            logger.info(
                f"[BacktestService] 回测任务已提交: "
                f"run_id={run_id}, strategy={strategy_id}, task_id={task.id}"
            )
        except Exception as exc:
            # Celery提交失败，标记为error
            await self._session.execute(
                text(
                    "UPDATE backtest_run SET status = 'error', error_msg = :msg "
                    "WHERE run_id = :run_id"
                ),
                {"msg": str(exc), "run_id": run_id},
            )
            await self._session.commit()
            logger.error(f"[BacktestService] Celery任务提交失败: {exc}", exc_info=True)
            raise

        return run_id

    async def get_backtest_result(self, run_id: str) -> dict[str, Any] | None:
        """查询单个回测结果。

        Args:
            run_id: 回测任务ID

        Returns:
            结果字典，含status/metrics/trades摘要；不存在返回None
        """
        result = await self._session.execute(
            text(
                """
                SELECT run_id, strategy_id, status, config,
                       result_metrics, error_msg, created_at, finished_at,
                       market, celery_task_id
                FROM backtest_run
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        )
        row = result.fetchone()
        if not row:
            return None

        keys = [
            "run_id",
            "strategy_id",
            "status",
            "config",
            "result_metrics",
            "error_msg",
            "created_at",
            "finished_at",
            "market",
            "celery_task_id",
        ]
        data = dict(zip(keys, row, strict=False))

        # 附加交易摘要（条数）
        trades_result = await self._session.execute(
            text("SELECT COUNT(*) FROM backtest_trades WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        trade_count = trades_result.scalar() or 0
        data["trade_count"] = trade_count

        return data

    async def get_backtest_list(
        self,
        strategy_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """查询历史回测列表。

        Args:
            strategy_id: 可选策略过滤
            status: 可选状态过滤（pending/running/completed/error）
            limit: 分页大小
            offset: 分页偏移

        Returns:
            list[dict]: 回测记录列表，按created_at降序
        """
        conditions = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if strategy_id:
            conditions.append("strategy_id = :strategy_id")
            params["strategy_id"] = strategy_id
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        result = await self._session.execute(
            text(
                f"""
                SELECT run_id, strategy_id, status, market,
                       created_at, finished_at, result_metrics
                FROM backtest_run
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
        rows = result.fetchall()
        keys = [
            "run_id",
            "strategy_id",
            "status",
            "market",
            "created_at",
            "finished_at",
            "result_metrics",
        ]
        return [dict(zip(keys, row, strict=False)) for row in rows]

    async def compare_strategies(self, run_ids: list[str]) -> dict[str, Any]:
        """多策略回测对比（最多5个）。

        Args:
            run_ids: 要对比的回测run_id列表（2-5个）

        Returns:
            dict: {
                "runs": [每个回测的metrics摘要],
                "comparison": {sharpe对比/mdd对比/年化收益对比}
            }

        Raises:
            ValueError: run_ids数量不在[2,5]范围内
        """
        if not (2 <= len(run_ids) <= 5):
            raise ValueError(f"compare_strategies需要2-5个run_id，当前: {len(run_ids)}")

        result = await self._session.execute(
            text(
                """
                SELECT run_id, strategy_id, status, result_metrics
                FROM backtest_run
                WHERE run_id = ANY(:run_ids)
                  AND status = 'completed'
                ORDER BY created_at ASC
                """
            ),
            {"run_ids": run_ids},
        )
        rows = result.fetchall()

        runs = []
        for row in rows:
            runs.append(
                {
                    "run_id": row[0],
                    "strategy_id": row[1],
                    "status": row[2],
                    "metrics": row[3] or {},
                }
            )

        # 提取关键指标做对比
        comparison: dict[str, Any] = {}
        metric_keys = ["sharpe_ratio", "annual_return", "max_drawdown", "win_rate", "calmar_ratio"]
        for key in metric_keys:
            comparison[key] = {
                r["strategy_id"]: r["metrics"].get(key) for r in runs if r["metrics"]
            }

        return {"runs": runs, "comparison": comparison}

    async def cancel_backtest(self, run_id: str) -> bool:
        """取消运行中的回测（撤销Celery任务）。

        Args:
            run_id: 回测任务ID

        Returns:
            True表示成功取消，False表示任务不存在或已完成
        """
        result = await self._session.execute(
            text("SELECT status, celery_task_id FROM backtest_run WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        row = result.fetchone()
        if not row:
            return False

        status, celery_task_id = row
        if status not in ("pending", "running"):
            logger.info(f"[BacktestService] 回测已结束({status})，无需取消: {run_id}")
            return False

        # 撤销Celery任务
        if celery_task_id:
            try:
                from app.tasks import celery_app  # type: ignore

                celery_app.control.revoke(celery_task_id, terminate=True)
            except Exception as exc:
                logger.warning(f"[BacktestService] Celery revoke失败: {exc}")

        await self._session.execute(
            text(
                "UPDATE backtest_run SET status = 'cancelled', "
                "finished_at = NOW() WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        )
        await self._session.commit()
        logger.info(f"[BacktestService] 回测已取消: {run_id}")
        return True


def _dict_to_json(d: dict[str, Any]) -> str:
    """将dict序列化为JSON字符串（用于PostgreSQL JSONB插入）。"""
    import json
    from datetime import date

    def _default(obj: Any) -> Any:
        if isinstance(obj, date):
            return obj.isoformat()
        raise TypeError(f"无法序列化类型: {type(obj)}")

    return json.dumps(d, default=_default, ensure_ascii=False)
