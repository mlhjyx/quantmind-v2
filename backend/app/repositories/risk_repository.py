"""风控状态Repository — circuit_breaker_state + circuit_breaker_log 表访问。

Sprint 1.1: 4级熔断状态机持久化。
遵循CLAUDE.md: async/await + 类型注解 + Google docstring(中文)。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from app.repositories.base_repository import BaseRepository

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────
# DDL — 首次运行时自动建表
# ─────────────────────────────────────────────

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id            UUID NOT NULL,
    execution_mode         VARCHAR(10) NOT NULL DEFAULT 'paper',
    current_level          SMALLINT NOT NULL DEFAULT 0,
    entered_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entered_date           DATE NOT NULL DEFAULT CURRENT_DATE,
    trigger_reason         TEXT,
    trigger_metrics        JSONB,
    recovery_streak_days   INT DEFAULT 0,
    recovery_streak_return DECIMAL(12,8) DEFAULT 0,
    position_multiplier    DECIMAL(4,2) DEFAULT 1.0,
    approval_id            UUID,
    updated_at             TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_id, execution_mode)
);
COMMENT ON TABLE circuit_breaker_state
    IS '熔断状态机当前状态(每策略一行, 覆盖更新)';

CREATE TABLE IF NOT EXISTS circuit_breaker_log (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id       UUID NOT NULL,
    execution_mode    VARCHAR(10) NOT NULL DEFAULT 'paper',
    trade_date        DATE NOT NULL,
    prev_level        SMALLINT NOT NULL,
    new_level         SMALLINT NOT NULL,
    transition_type   VARCHAR(10) NOT NULL,
    reason            TEXT NOT NULL,
    metrics           JSONB,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cb_log_strategy_date
    ON circuit_breaker_log(strategy_id, trade_date DESC);
COMMENT ON TABLE circuit_breaker_log
    IS '熔断状态变更历史(只追加, 用于审计和复盘)';
"""


class RiskRepository(BaseRepository):
    """风控状态DB访问层。

    管理 circuit_breaker_state 和 circuit_breaker_log 两张表。
    """

    async def ensure_tables(self) -> None:
        """确保风控相关表存在（幂等）。

        asyncpg不支持单次execute多条语句，需逐条执行。
        """
        for stmt in _CREATE_TABLES_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                await self.execute(stmt)
        logger.info("[RiskRepo] circuit_breaker 表已就绪")

    # ── circuit_breaker_state ──

    async def get_state(
        self,
        strategy_id: UUID,
        execution_mode: str,
    ) -> dict[str, Any] | None:
        """获取当前熔断状态。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。

        Returns:
            状态字典，不存在返回None。
        """
        row = await self.fetch_one(
            """SELECT id, strategy_id, execution_mode, current_level,
                      entered_at, entered_date, trigger_reason, trigger_metrics,
                      recovery_streak_days, recovery_streak_return,
                      position_multiplier, approval_id, updated_at
               FROM circuit_breaker_state
               WHERE strategy_id = :strategy_id
                 AND execution_mode = :execution_mode""",
            {"strategy_id": str(strategy_id), "execution_mode": execution_mode},
        )
        if not row:
            return None
        return _state_row_to_dict(row)

    async def upsert_state(
        self,
        strategy_id: UUID,
        execution_mode: str,
        current_level: int,
        entered_date: date,
        trigger_reason: str,
        trigger_metrics: dict[str, Any] | None,
        recovery_streak_days: int,
        recovery_streak_return: Decimal,
        position_multiplier: Decimal,
        approval_id: UUID | None,
    ) -> dict[str, Any]:
        """插入或更新熔断状态（UPSERT）。

        每个 (strategy_id, execution_mode) 只保留一行当前状态。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            current_level: 当前熔断级别 0-4。
            entered_date: 进入当前状态的交易日。
            trigger_reason: 触发原因。
            trigger_metrics: 指标快照(JSONB)。
            recovery_streak_days: L3恢复连续盈利天数。
            recovery_streak_return: L3恢复累计收益。
            position_multiplier: 仓位系数。
            approval_id: L4审批ID。

        Returns:
            更新后的状态字典。
        """
        import json

        row = await self.fetch_one(
            """INSERT INTO circuit_breaker_state
                   (strategy_id, execution_mode, current_level,
                    entered_at, entered_date, trigger_reason, trigger_metrics,
                    recovery_streak_days, recovery_streak_return,
                    position_multiplier, approval_id, updated_at)
               VALUES
                   (:strategy_id, :execution_mode, :current_level,
                    NOW(), :entered_date, :trigger_reason, :trigger_metrics::jsonb,
                    :recovery_streak_days, :recovery_streak_return,
                    :position_multiplier, :approval_id, NOW())
               ON CONFLICT (strategy_id, execution_mode)
               DO UPDATE SET
                    current_level = EXCLUDED.current_level,
                    entered_at = CASE
                        WHEN circuit_breaker_state.current_level != EXCLUDED.current_level
                        THEN NOW()
                        ELSE circuit_breaker_state.entered_at
                    END,
                    entered_date = CASE
                        WHEN circuit_breaker_state.current_level != EXCLUDED.current_level
                        THEN EXCLUDED.entered_date
                        ELSE circuit_breaker_state.entered_date
                    END,
                    trigger_reason = EXCLUDED.trigger_reason,
                    trigger_metrics = EXCLUDED.trigger_metrics,
                    recovery_streak_days = EXCLUDED.recovery_streak_days,
                    recovery_streak_return = EXCLUDED.recovery_streak_return,
                    position_multiplier = EXCLUDED.position_multiplier,
                    approval_id = EXCLUDED.approval_id,
                    updated_at = NOW()
               RETURNING id, strategy_id, execution_mode, current_level,
                         entered_at, entered_date, trigger_reason, trigger_metrics,
                         recovery_streak_days, recovery_streak_return,
                         position_multiplier, approval_id, updated_at""",
            {
                "strategy_id": str(strategy_id),
                "execution_mode": execution_mode,
                "current_level": current_level,
                "entered_date": entered_date,
                "trigger_reason": trigger_reason,
                "trigger_metrics": json.dumps(trigger_metrics) if trigger_metrics else None,
                "recovery_streak_days": recovery_streak_days,
                "recovery_streak_return": recovery_streak_return,
                "position_multiplier": position_multiplier,
                "approval_id": str(approval_id) if approval_id else None,
            },
        )
        return _state_row_to_dict(row)

    async def update_recovery_streak(
        self,
        strategy_id: UUID,
        execution_mode: str,
        streak_days: int,
        streak_return: Decimal,
    ) -> None:
        """更新L3恢复追踪字段（不改变其他状态）。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            streak_days: 连续盈利天数。
            streak_return: 连续盈利累计收益。
        """
        await self.execute(
            """UPDATE circuit_breaker_state
               SET recovery_streak_days = :streak_days,
                   recovery_streak_return = :streak_return,
                   updated_at = NOW()
               WHERE strategy_id = :strategy_id
                 AND execution_mode = :execution_mode""",
            {
                "strategy_id": str(strategy_id),
                "execution_mode": execution_mode,
                "streak_days": streak_days,
                "streak_return": streak_return,
            },
        )

    # ── circuit_breaker_log ──

    async def insert_log(
        self,
        strategy_id: UUID,
        execution_mode: str,
        trade_date: date,
        prev_level: int,
        new_level: int,
        transition_type: str,
        reason: str,
        metrics: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """追加熔断状态变更日志。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            trade_date: 变更交易日。
            prev_level: 变更前级别。
            new_level: 变更后级别。
            transition_type: "escalate" / "recover" / "manual"。
            reason: 变更原因。
            metrics: 触发时指标快照。

        Returns:
            新日志记录字典。
        """
        import json

        row = await self.fetch_one(
            """INSERT INTO circuit_breaker_log
                   (strategy_id, execution_mode, trade_date,
                    prev_level, new_level, transition_type, reason, metrics)
               VALUES
                   (:strategy_id, :execution_mode, :trade_date,
                    :prev_level, :new_level, :transition_type, :reason, :metrics::jsonb)
               RETURNING id, strategy_id, execution_mode, trade_date,
                         prev_level, new_level, transition_type, reason,
                         metrics, created_at""",
            {
                "strategy_id": str(strategy_id),
                "execution_mode": execution_mode,
                "trade_date": trade_date,
                "prev_level": prev_level,
                "new_level": new_level,
                "transition_type": transition_type,
                "reason": reason,
                "metrics": json.dumps(metrics) if metrics else None,
            },
        )
        return _log_row_to_dict(row)

    async def get_logs(
        self,
        strategy_id: UUID,
        execution_mode: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取熔断变更历史（最新在前）。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。
            limit: 最大返回条数。

        Returns:
            变更历史列表。
        """
        rows = await self.fetch_all(
            """SELECT id, strategy_id, execution_mode, trade_date,
                      prev_level, new_level, transition_type, reason,
                      metrics, created_at
               FROM circuit_breaker_log
               WHERE strategy_id = :strategy_id
                 AND execution_mode = :execution_mode
               ORDER BY trade_date DESC, created_at DESC
               LIMIT :limit""",
            {
                "strategy_id": str(strategy_id),
                "execution_mode": execution_mode,
                "limit": limit,
            },
        )
        return [_log_row_to_dict(r) for r in rows]

    async def count_escalations(
        self,
        strategy_id: UUID,
        execution_mode: str,
    ) -> int:
        """统计历史升级次数。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。

        Returns:
            升级总次数。
        """
        count = await self.fetch_scalar(
            """SELECT COUNT(*) FROM circuit_breaker_log
               WHERE strategy_id = :strategy_id
                 AND execution_mode = :execution_mode
                 AND transition_type = 'escalate'""",
            {
                "strategy_id": str(strategy_id),
                "execution_mode": execution_mode,
            },
        )
        return count or 0

    async def get_last_escalation_date(
        self,
        strategy_id: UUID,
        execution_mode: str,
    ) -> date | None:
        """获取最近一次升级日期。

        Args:
            strategy_id: 策略UUID。
            execution_mode: "paper" 或 "live"。

        Returns:
            最近升级日期，无记录返回None。
        """
        val = await self.fetch_scalar(
            """SELECT trade_date FROM circuit_breaker_log
               WHERE strategy_id = :strategy_id
                 AND execution_mode = :execution_mode
                 AND transition_type = 'escalate'
               ORDER BY trade_date DESC
               LIMIT 1""",
            {
                "strategy_id": str(strategy_id),
                "execution_mode": execution_mode,
            },
        )
        return val

    # ── approval_queue 查询（L4恢复用）──

    async def get_approval_status(self, approval_id: UUID) -> str | None:
        """查询审批记录状态。

        Args:
            approval_id: approval_queue记录ID。

        Returns:
            状态字符串 ('pending'/'approved'/'rejected'), 不存在返回None。
        """
        val = await self.fetch_scalar(
            "SELECT status FROM approval_queue WHERE id = :id",
            {"id": str(approval_id)},
        )
        return val


# ─────────────────────────────────────────────
# 行转换辅助函数
# ─────────────────────────────────────────────

def _state_row_to_dict(row: Any) -> dict[str, Any]:
    """将 circuit_breaker_state 行转为字典。"""
    return {
        "id": str(row[0]),
        "strategy_id": str(row[1]),
        "execution_mode": row[2],
        "current_level": row[3],
        "entered_at": row[4].isoformat() if isinstance(row[4], datetime) else str(row[4]),
        "entered_date": row[5].isoformat() if isinstance(row[5], date) else str(row[5]),
        "trigger_reason": row[6],
        "trigger_metrics": row[7],
        "recovery_streak_days": row[8] or 0,
        "recovery_streak_return": Decimal(str(row[9])) if row[9] is not None else Decimal("0"),
        "position_multiplier": Decimal(str(row[10])) if row[10] is not None else Decimal("1.0"),
        "approval_id": str(row[11]) if row[11] else None,
        "updated_at": row[12].isoformat() if isinstance(row[12], datetime) else str(row[12]),
    }


def _log_row_to_dict(row: Any) -> dict[str, Any]:
    """将 circuit_breaker_log 行转为字典。"""
    return {
        "id": str(row[0]),
        "strategy_id": str(row[1]),
        "execution_mode": row[2],
        "trade_date": row[3].isoformat() if isinstance(row[3], date) else str(row[3]),
        "prev_level": row[4],
        "new_level": row[5],
        "transition_type": row[6],
        "reason": row[7],
        "metrics": row[8],
        "created_at": row[9].isoformat() if isinstance(row[9], datetime) else str(row[9]),
    }
