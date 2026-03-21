"""Health Repository — health_checks + scheduler_task_log表访问。

健康检查和调度日志的读写。
"""

from datetime import date
from typing import Optional

from app.repositories.base_repository import BaseRepository


class HealthRepository(BaseRepository):
    """health_checks + scheduler_task_log表访问。"""

    async def get_latest_health(self) -> Optional[dict]:
        """获取最新健康检查结果。"""
        row = await self.fetch_one(
            """SELECT check_date, postgresql_ok, redis_ok, data_fresh,
                      factor_nan_ok, disk_ok, celery_ok, all_pass, failed_items
               FROM health_checks
               ORDER BY created_at DESC LIMIT 1""",
        )
        if not row:
            return None
        return {
            "check_date": row[0],
            "postgresql_ok": row[1],
            "redis_ok": row[2],
            "data_fresh": row[3],
            "factor_nan_ok": row[4],
            "disk_ok": row[5],
            "celery_ok": row[6],
            "all_pass": row[7],
            "failed_items": row[8],
        }

    async def get_pipeline_status(self, trade_date: date) -> list[dict]:
        """获取指定日期的管道任务状态。"""
        rows = await self.fetch_all(
            """SELECT task_name, status, error_message, result_json, start_time, end_time
               FROM scheduler_task_log
               WHERE schedule_time::date = :td
               ORDER BY start_time""",
            {"td": trade_date},
        )
        return [
            {
                "task_name": r[0],
                "status": r[1],
                "error": r[2],
                "result": r[3],
                "start_time": r[4],
                "end_time": r[5],
            }
            for r in rows
        ]

    async def get_circuit_breaker_history(
        self, strategy_id: str, days: int = 30
    ) -> list[dict]:
        """获取最近N天的熔断事件。"""
        rows = await self.fetch_all(
            """SELECT schedule_time, status, error_message, result_json
               FROM scheduler_task_log
               WHERE task_name = 'circuit_breaker'
               ORDER BY schedule_time DESC LIMIT :n""",
            {"n": days},
        )
        return [
            {
                "time": r[0],
                "action": r[1],
                "reason": r[2],
                "detail": r[3],
            }
            for r in rows
        ]
