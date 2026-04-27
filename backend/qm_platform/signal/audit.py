"""Framework #6 Signal — StubExecutionAuditTrail (MVP 3.3 batch 3).

ExecutionAuditTrail ABC 的 stub concrete — record() logger-only no-op DB,
trace() raise NotImplementedError 留 MVP 3.4 Event Sourcing outbox concrete 替换.

## 设计 (铁律 39 显式)

- **stub 模式**: record() 不写 DB / 不发 event_bus, 仅 logger.info — 让 PlatformOrderRouter
  audit hook 路径**完整** (record 调用不报错), 但实际持久化等 MVP 3.4 outbox 落地.
- **trace() 不实施**: ABI 占位 raise NotImplementedError, 调用方收到清晰错误 (铁律 33
  fail-loud, 非 silent return None / 空 AuditChain). MVP 3.4 outbox concrete 时替换.
- **DI 兼容性**: 保 ExecutionAuditTrail.record(event_type, payload) 签名稳定, 替换 stub
  → outbox concrete 时 PlatformOrderRouter.audit_trail 注入路径不破.

## 接入点 (后续 MVP)

- MVP 3.3 batch 3 Step 2 (本批): `PlatformOrderRouter` 加 `audit_trail` DI, route() 出
  Order 时 record('order.routed', {...}). 默认 audit_trail=None 跳过 (backward compat).
- MVP 3.4 Event Sourcing: 替换 StubExecutionAuditTrail → DBOutboxAuditTrail, record()
  写 outbox 表 + trace() 反查 audit_chain.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .interface import AuditChain, ExecutionAuditTrail

if TYPE_CHECKING:
    pass

_logger = logging.getLogger(__name__)


class AuditMissing(RuntimeError):  # noqa: N818 — 语义优先 (对齐项目 FlagNotFound 惯例)
    """审计链中断 — 某环节未记录事件 (e.g. signal record 但无 order record).

    StubExecutionAuditTrail.trace() 不实施时 raise NotImplementedError 不是此异常;
    MVP 3.4 outbox concrete 实现 trace() 后, 链路真正中断时 raise AuditMissing.
    """


class StubExecutionAuditTrail(ExecutionAuditTrail):
    """ExecutionAuditTrail stub concrete — record() logger.info / trace() NotImplementedError.

    用途:
      - PlatformOrderRouter audit hook 路径 dummy 注入, route() 不强制依赖 outbox
      - MVP 3.4 outbox 落地前的 placeholder (interface.py L121 ABC + L138 record 契约)

    Args:
      log_level: record() 默认 INFO (生产观察). DEBUG 用于 noisy 调试.

    Usage:
      >>> stub = StubExecutionAuditTrail()
      >>> stub.record('order.routed', {'order_id': 'a1b2', 'strategy_id': 's1'})
      # logger.info: 'audit.record event=order.routed payload={...}'
      >>> stub.trace('fill-uuid-1')
      Traceback (most recent call last):
        ...
      NotImplementedError: trace() 待 MVP 3.4 Event Sourcing outbox concrete 实施
    """

    def __init__(self, log_level: int = logging.INFO) -> None:
        if log_level not in (logging.DEBUG, logging.INFO, logging.WARNING):
            raise ValueError(
                f"log_level 必须是 DEBUG/INFO/WARNING, got {log_level}"
            )
        self._log_level = log_level
        # 计数器供 test 验证 record 调用次数 (无副作用 visibility)
        self._record_count = 0

    @property
    def record_count(self) -> int:
        """累计 record() 调用次数 (test 用)."""
        return self._record_count

    # ─── ExecutionAuditTrail ABC impl ──────────────────────────────

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        """记录一个事件 — stub 仅 logger 不写 DB.

        Args:
          event_type: 事件类型 (e.g. 'signal.composed', 'order.routed', 'fill.received').
          payload: 事件 dict (含 strategy_id / order_id / timestamps 等).

        Raises:
          ValueError: event_type 空或非 string.

        铁律 33: fail-loud — event_type 空必 raise (非 silent skip).
        """
        if not event_type or not isinstance(event_type, str):
            raise ValueError(
                f"event_type 必须是非空 string, got {event_type!r}"
            )
        if not isinstance(payload, dict):
            raise ValueError(
                f"payload 必须是 dict, got {type(payload).__name__}"
            )
        self._record_count += 1
        _logger.log(
            self._log_level,
            "audit.record event=%s payload_keys=%s record_count=%d",
            event_type,
            sorted(payload.keys()),
            self._record_count,
        )

    def trace(self, fill_id: str) -> AuditChain:
        """反向追溯 fill → factor — stub 不实施.

        Raises:
          NotImplementedError: trace() 待 MVP 3.4 Event Sourcing outbox concrete.
            调用方应 catch NotImplementedError 并提示用户 outbox 未落地.

        铁律 23 独立可执行: 本类 stub 不阻塞 batch 3 完工; 升级路径明确 (replace 类).
        """
        raise NotImplementedError(
            f"StubExecutionAuditTrail.trace(fill_id={fill_id!r}) 不实施 — "
            "待 MVP 3.4 Event Sourcing outbox concrete (替 stub 类). "
            "interface.py:128 ABC trace() 契约稳定, 替换不破调用方."
        )
