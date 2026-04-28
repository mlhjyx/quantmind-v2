"""MVP 4.1 batch 2.2 — B6 Framework `.health()` endpoint 规范.

Blueprint Future Spec B6: 每个 Framework 提供标准 health() 接口, FastAPI `/health`
聚合后给 dashboard 一眼看 12 Framework 状态.

设计原则:
  - HealthReport 是 frozen dataclass, 跨 Framework 共享值对象
  - status Literal["ok", "degraded", "down"] (3 档, 简单)
  - last_check_ts UTC tz-aware (铁律 41)
  - 默认 ABC 提供 fallback 实现 (返 ok), concrete 可 override 加业务逻辑
  - check_health 不抛 — 自身错误必转 status="down" + message=str(e) (避免 health endpoint 自杀)

关联铁律:
  - 41 (UTC): timestamp 全 UTC tz-aware
  - 33 (fail-loud) 反向: health check 不能 fail-loud, 否则 health endpoint 永远 500.
                       check_health 内部捕异常转 down 状态, 但保留 traceback 在 details.
  - 24 (单一职责): HealthReport 只描述状态, 不含恢复逻辑
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

HealthStatus = Literal["ok", "degraded", "down"]


@dataclass(frozen=True)
class HealthReport:
    """Framework health 标准报告.

    Args:
      framework: Framework 名 (e.g. "alert_router", "metric_exporter")
      status: ok / degraded / down
      message: 简短状态描述 (可空, status=ok 时通常空)
      last_check_ts: UTC tz-aware 检查时间戳 (铁律 41)
      details: 详细上下文 (dict, e.g. {"latency_ms": 12, "queue_depth": 0})
    """

    framework: str
    status: HealthStatus
    message: str = ""
    last_check_ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly 序列化 (FastAPI /health endpoint 用)."""
        return {
            "framework": self.framework,
            "status": self.status,
            "message": self.message,
            "last_check_ts": self.last_check_ts.isoformat(),
            "details": dict(self.details),
        }


def safe_check(
    framework: str,
    check_fn: Callable[[], HealthReport],
) -> HealthReport:
    """check_fn 包装器: 异常自动转 status=down, 防 /health endpoint 自杀.

    用例:
        report = safe_check("alert_router", lambda: my_router.health())

    捕获策略:
      - check_fn 返 HealthReport → 直接返
      - check_fn raise → 返 down + traceback 摘要进 details (审计用)
    """
    try:
        report = check_fn()
        if not isinstance(report, HealthReport):
            raise TypeError(
                f"check_fn must return HealthReport, got {type(report).__name__}"
            )
        return report
    except Exception as e:  # noqa: BLE001  intentional broad catch
        logger.exception("[Health] %s health check raised", framework)
        return HealthReport(
            framework=framework,
            status="down",
            message=f"{type(e).__name__}: {e}",
            details={"traceback": traceback.format_exc(limit=10)},
        )


def aggregate_status(reports: list[HealthReport]) -> HealthStatus:
    """多 Framework reports 聚合: 任一 down → down, 任一 degraded → degraded, 全 ok → ok.

    用例: FastAPI /health endpoint 返回整体系统状态:
        reports = [r1, r2, r3, ...]
        overall = aggregate_status(reports)  # "ok" / "degraded" / "down"
    """
    if not reports:
        # 空列表视为 down (无 Framework 注册, 异常)
        return "down"
    statuses = {r.status for r in reports}
    if "down" in statuses:
        return "down"
    if "degraded" in statuses:
        return "degraded"
    return "ok"


__all__ = [
    "HealthReport",
    "HealthStatus",
    "safe_check",
    "aggregate_status",
]
