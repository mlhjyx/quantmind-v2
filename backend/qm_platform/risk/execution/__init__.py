"""L4 执行优化层 — STAGED 决策权 + Execution Planner (S8).

L4ExecutionPlanner: 接收 RealtimeRiskEngine 输出 → 生成 ExecutionPlan,
管理 STAGED 状态机 (PENDING_CONFIRM → CONFIRMED/CANCELLED/TIMEOUT_EXECUTED).
broker sell wire 由调用方注入 (BrokerProtocol), 平台层 0 直调 broker_qmt.
"""

from .planner import ExecutionMode, ExecutionPlan, L4ExecutionPlanner, PlanStatus

__all__ = [
    "ExecutionMode",
    "ExecutionPlan",
    "L4ExecutionPlanner",
    "PlanStatus",
]
