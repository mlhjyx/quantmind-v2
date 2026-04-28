"""Framework #6 Signal — ExecutionAuditTrail concrete (StubExecutionAuditTrail + OutboxBackedAuditTrail).

MVP 3.3 batch 3 ✅ Stub: record() logger-only / trace() NotImplementedError.
MVP 3.4 batch 3 ✅ Concrete: OutboxBackedAuditTrail — outbox 写 + 反向 SQL trace.

## 设计 (铁律 39 显式)

- **stub 模式** (StubExecutionAuditTrail): record() 不写 DB / 不发 event_bus, 仅 logger.info.
  保留用途: router.py / pipeline.py 单元测试无 DB 依赖时的 dummy 注入.
- **outbox 模式** (OutboxBackedAuditTrail): record() 走 OutboxWriter.enqueue 写 event_outbox 表,
  自管短 tx (fire-and-forget audit 模式, **vs** OutboxWriter co-tx 模式由 caller 管 tx).
  trace(fill_id) 4 sequential SQL queries 反向 JOIN event_outbox 拼 AuditChain.
- **DI 兼容性**: 两者均实现 ExecutionAuditTrail ABC, PlatformOrderRouter.audit_trail
  注入任一 concrete 不破调用方.

## 双模式互补 (重要架构决策)

| 场景 | 工具 | tx 边界 |
|---|---|---|
| Service 业务表 + outbox 原子 (signal_service / execution_service) | OutboxWriter (batch 1) | caller 管 tx (调用方 commit) |
| Router audit hook (无 caller conn) | OutboxBackedAuditTrail (本批) | self 管短 tx (record() 内 commit) |

OutboxBackedAuditTrail 不 replace OutboxWriter, 是补 SDK 层无 conn 调用方的 audit 路径.
"""
from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from .interface import AuditChain, ExecutionAuditTrail

if TYPE_CHECKING:
    from collections.abc import Callable

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
      # logger.info: 'audit.record event=order.routed payload_keys=...'
      >>> stub.trace('fill-uuid-1')
      Traceback (most recent call last):
        ...
      NotImplementedError: StubExecutionAuditTrail.trace() 不实施 — 待 MVP 3.4 ...
    """

    def __init__(self, log_level: int = logging.INFO) -> None:
        # P2 reviewer (PR #109) 采纳: 拓宽到 5 个标准 logging level (含 ERROR/CRITICAL),
        # 让 production 系统可选 ERROR 级别让 audit 在 Sentry 等聚合器突出.
        valid_levels = (
            logging.DEBUG, logging.INFO, logging.WARNING,
            logging.ERROR, logging.CRITICAL,
        )
        if log_level not in valid_levels:
            raise ValueError(
                f"log_level 必须是标准 logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL), got {log_level}"
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
        # P2 reviewer (PR #109) 采纳: type 验证先于 emptiness 验证, 错误消息对 0/None 等真因.
        if not isinstance(event_type, str):
            raise ValueError(
                f"event_type 必须是 string, got {type(event_type).__name__}: {event_type!r}"
            )
        if not event_type:
            raise ValueError(
                f"event_type 必须是非空 string, got {event_type!r}"
            )
        if not isinstance(payload, dict):
            raise ValueError(
                f"payload 必须是 dict, got {type(payload).__name__}"
            )
        # P2 python-reviewer (PR #109) 采纳: payload values 必须 JSON-serialisable primitives.
        # MVP 3.4 outbox concrete 写 DB 时 json.dumps(payload) 会炸非原始类型 (Decimal/date).
        # __debug__=True (默认) 时 assert; production __debug__=False 跳过 (保性能).
        # 调用方 (e.g. router.py audit hook) 必预序列化: trade_date.isoformat() 等.
        assert all(
            isinstance(v, (str, int, float, bool, type(None)))
            for v in payload.values()
        ), (
            f"payload contains non-JSON-primitive values: "
            f"{ {k: type(v).__name__ for k, v in payload.items()} }"
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
        # P1 python-reviewer (PR #109) 采纳: 不在 exception message 嵌入 fill_id 值
        # (PII / 审计 ID 风险, 流入 Sentry / 聚合 log). 调用方靠 caller-side 上下文知道哪个 fill_id.
        # 静默忽略 fill_id 参数 (无日志记录) 是有意 — 让 NotImplementedError 消息稳定可 grep.
        del fill_id  # silent_ok: 不 log, 防 PII 泄露 (caller 自己有上下文)
        raise NotImplementedError(
            "StubExecutionAuditTrail.trace() 不实施 — "
            "待 MVP 3.4 Event Sourcing outbox concrete (替 stub 类). "
            "interface.py:128 ABC trace() 契约稳定, 替换不破调用方."
        )


# ════════════════════════════════════════════════════════════
# MVP 3.4 batch 3 — OutboxBackedAuditTrail concrete
# ════════════════════════════════════════════════════════════


class OutboxBackedAuditTrail(ExecutionAuditTrail):
    """ExecutionAuditTrail concrete — outbox 写 + SQL 反向 trace.

    record() 走 OutboxWriter.enqueue 写 event_outbox 表, 自管短 tx (fire-and-forget audit).
    trace(fill_id) 4 sequential SQL queries 反向 JOIN event_outbox 拼 AuditChain.

    ## event_type 格式契约 (record 调用方约定)

    event_type 必须为 ``"{aggregate_type}.{event_subtype}"`` 格式:
      - aggregate_type ∈ {signal, order, fill, risk, portfolio} (OutboxWriter 白名单)
      - event_subtype: e.g. ``generated``, ``routed``, ``executed``, ``triggered``, ``rebalanced``

    aggregate_id 从 payload 自动提取: ``payload[f"{aggregate_type}_id"]``
      e.g. event_type=``order.routed`` → ``payload['order_id']`` 必存

    示例:
      >>> trail = OutboxBackedAuditTrail()
      >>> trail.record('order.routed', {'order_id': 'ord-1', 'signal_id': 'sig-1', ...})
      # → INSERT event_outbox(aggregate_type='order', aggregate_id='ord-1',
      #     event_type='routed', payload=<入参 payload>)

    ## trace(fill_id) 反向链

    fill (aggregate_type='fill', aggregate_id=fill_id)
      → payload['order_id']
        → order event (aggregate_type='order', aggregate_id=order_id)
          → payload['signal_id']
            → signal event (aggregate_type='signal', aggregate_id=signal_id)
              → payload['strategy_id'] + payload.get('factor_contributions', {})

    任一环节 0 行 → AuditMissing.

    Args:
      conn_factory: Callable 返 psycopg2 conn (默认 ``app.services.db.get_sync_conn``).
                    每个 record() / trace() 调用获新 conn, 用完 close.

    铁律:
      - 32 (Service 不 commit) 例外: 本类是 SDK 层无 caller conn, 自管短 tx (类似
        outbox_publisher Celery task), docstring 显式声明.
      - 33 (fail-loud): event_type 格式 / aggregate_id 缺失 / 链断 全 raise.
      - 17 (DataPipeline) 例外: 同 outbox.py — outbox 是 audit/event 流非业务 facts.
    """

    def __init__(self, conn_factory: Callable[[], Any] | None = None) -> None:
        if conn_factory is None:
            from app.services.db import get_sync_conn  # noqa: PLC0415
            conn_factory = get_sync_conn
        self._conn_factory = conn_factory

    # ─── ExecutionAuditTrail ABC impl ──────────────────────────────

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        """记录事件 → outbox 表 + commit (短 tx, fire-and-forget).

        Args:
          event_type: ``"{aggregate_type}.{event_subtype}"`` 格式.
          payload: dict, 必含 ``{aggregate_type}_id`` key.

        Raises:
          ValueError: event_type 格式错 / aggregate_type 不在白名单 (OutboxWriter)
                      / payload 缺 aggregate_id key / payload 不可 JSON 序列化.
          TypeError: payload 不是 dict.

        Performance note:
          每次 record() 获新 conn + 短 tx + commit. 单线程 < 100 events/s 无瓶颈
          (psycopg2 conn pool 摊销). 高吞吐调用方 (e.g. bulk order routing 单 tx
          内 1000+ events) 应改走 OutboxWriter co-tx 模式 (caller 持 conn, 与业务
          表 INSERT 同 tx commit), 避 per-event tx 开销. 双模式对比见类 docstring.
        """
        if not isinstance(event_type, str):
            raise ValueError(
                f"event_type 必须 string, got {type(event_type).__name__}: {event_type!r}"
            )
        if "." not in event_type:
            raise ValueError(
                f"event_type 必须为 '{{aggregate_type}}.{{subtype}}' 格式, got {event_type!r}. "
                f"e.g. 'order.routed' / 'signal.generated' / 'fill.executed'."
            )
        if not isinstance(payload, dict):
            raise TypeError(
                f"payload 必须是 dict, got {type(payload).__name__}."
            )

        aggregate_type, event_subtype = event_type.split(".", 1)
        if not aggregate_type or not event_subtype:
            raise ValueError(
                f"event_type 格式错 (空 aggregate_type 或 subtype): {event_type!r}."
            )

        agg_id_key = f"{aggregate_type}_id"
        if agg_id_key not in payload:
            raise ValueError(
                f"payload 必含 {agg_id_key!r} key (aggregate_id 反向 trace 锚点). "
                f"payload keys: {sorted(payload.keys())}."
            )
        aggregate_id = str(payload[agg_id_key])
        if not aggregate_id or not aggregate_id.strip():
            raise ValueError(
                f"payload[{agg_id_key!r}] 必须非空字符串, got {payload[agg_id_key]!r}."
            )

        # Lazy import 防 batch 1 循环依赖 + 让单测可只 mock conn 不需 import outbox
        from qm_platform.observability import OutboxWriter  # noqa: PLC0415

        conn = self._conn_factory()
        try:
            # P1 reviewer 采纳: 显式声明依赖 _TrackedConnection.__setattr__ 转发
            # (backend/app/services/db.py:90 docstring 明保 "__setattr__ 透传写属性").
            # 若未来 wrapper 重构破此契约 → autocommit 默认 True 会触发 OutboxWriter
            # 单 INSERT 即 commit 而非交给本类 commit() 显式控制.
            conn.autocommit = False
            writer = OutboxWriter(conn)
            # event_subtype 而非全 event_type — outbox 表 event_type 列存 subtype,
            # aggregate_type 已独立列存. 反向 trace 时拼回 "{type}.{subtype}".
            writer.enqueue(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_subtype,
                payload=payload,
            )
            conn.commit()
        except Exception:
            # silent_ok: rollback 失败时 close 也会触发清理
            with contextlib.suppress(Exception):
                conn.rollback()
            raise
        finally:
            conn.close()

    def trace(self, fill_id: str) -> AuditChain:
        """反向追溯 fill → order → signal → strategy 链, 返 AuditChain.

        4 sequential queries (1 conn, 不开事务):
          1. fill event (aggregate_type='fill', aggregate_id=fill_id)
          2. order event (取 fill.payload['order_id'])
          3. signal event (取 order.payload['signal_id'])
          4. strategy / factor_contributions 从 signal.payload

        Args:
          fill_id: 成交 ID (字符串).

        Returns:
          AuditChain dataclass (frozen).

        Raises:
          AuditMissing: 链路任一环节 0 行 (fill / order / signal event 不存在).
          ValueError: fill_id 空字符串.
        """
        if not isinstance(fill_id, str) or not fill_id.strip():
            raise ValueError(f"fill_id 必须非空 string, got {fill_id!r}.")

        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                # 1. fill event
                fill_row = self._fetch_event_or_raise(
                    cur, aggregate_type="fill", aggregate_id=fill_id,
                    raise_msg=f"fill event_id={fill_id} 不存在 (链断点 1: fill)",
                )
                fill_payload, fill_created_at = fill_row
                order_id = fill_payload.get("order_id")
                if not order_id:
                    raise AuditMissing(
                        f"fill payload 缺 order_id (event_id={fill_id}, "
                        f"payload keys={sorted(fill_payload.keys())})"
                    )

                # 2. order event
                order_row = self._fetch_event_or_raise(
                    cur, aggregate_type="order", aggregate_id=str(order_id),
                    raise_msg=f"order event_id={order_id} 不存在 (链断点 2: order)",
                )
                order_payload, order_created_at = order_row
                signal_id = order_payload.get("signal_id")
                if not signal_id:
                    raise AuditMissing(
                        f"order payload 缺 signal_id (event_id={order_id}, "
                        f"payload keys={sorted(order_payload.keys())})"
                    )

                # 3. signal event
                signal_row = self._fetch_event_or_raise(
                    cur, aggregate_type="signal", aggregate_id=str(signal_id),
                    raise_msg=f"signal event_id={signal_id} 不存在 (链断点 3: signal)",
                )
                signal_payload, signal_created_at = signal_row
                strategy_id = signal_payload.get("strategy_id")
                if not strategy_id:
                    raise AuditMissing(
                        f"signal payload 缺 strategy_id (event_id={signal_id}, "
                        f"payload keys={sorted(signal_payload.keys())})"
                    )

                # P2 reviewer 采纳: 区分 "key 缺失" (record-quality 退化, warn) vs
                # "key 在但空 dict" (策略合法零因子, silent). silent fallback 会掩盖
                # 真实生产 record() 漏写 factor_contributions 的 schema bug.
                if "factor_contributions" not in signal_payload:
                    _logger.warning(
                        "[OutboxBackedAuditTrail.trace] signal event 缺 factor_contributions "
                        "key (signal_id=%s, strategy_id=%s). 返空 dict 但记录 quality 可疑, "
                        "检查 signal record() 调用方是否漏传此 key.",
                        signal_id, strategy_id,
                    )
                factor_contributions: dict[str, float] = (
                    signal_payload.get("factor_contributions") or {}
                )

                # P3.1 reviewer 采纳: created_at 是 NOT NULL 列 (event_outbox.sql DDL),
                # psycopg2 不会返 None. 移除 `if ts else ""` 死代码 + 简化 reader 阅读.
                return AuditChain(
                    fill_id=fill_id,
                    order_id=str(order_id),
                    signal_trace=signal_payload,
                    strategy_id=str(strategy_id),
                    factor_contributions=factor_contributions,
                    timestamps={
                        "fill": fill_created_at.isoformat(),
                        "order": order_created_at.isoformat(),
                        "signal": signal_created_at.isoformat(),
                    },
                )
        finally:
            conn.close()

    @staticmethod
    def _fetch_event_or_raise(cur, *, aggregate_type: str, aggregate_id: str,
                              raise_msg: str):
        """SELECT payload + created_at WHERE aggregate_type=? AND aggregate_id=?.

        最新一条 (ORDER BY created_at DESC LIMIT 1) — 同 aggregate_id 多事件
        (e.g. order.routed + order.cancelled) 取最新, 反向 trace 通常关心 latest state.

        Returns:
          (payload, created_at) tuple.

        Raises:
          AuditMissing: 0 rows.
        """
        cur.execute(
            """
            SELECT payload, created_at
            FROM event_outbox
            WHERE aggregate_type = %s AND aggregate_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (aggregate_type, aggregate_id),
        )
        row = cur.fetchone()
        if row is None:
            raise AuditMissing(raise_msg)
        return row
