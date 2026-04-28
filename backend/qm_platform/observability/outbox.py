"""MVP 3.4 batch 1 — OutboxWriter (event_outbox 表 enqueue).

Outbox pattern: 调用方在自己事务内 INSERT event_outbox (业务表 + 事件原子),
commit 后 publisher worker (MVP 3.4 batch 2) 异步发 Redis Streams.

铁律:
  - 32 (Service 内部不 commit): OutboxWriter.enqueue 不 commit, 由调用方 tx 管.
  - 33 (fail-loud): 参数校验失败必 raise (空 aggregate_type / event_type / non-dict payload).
  - 17 *例外* (DataPipeline 入库): outbox 不走 DataPipeline — 是 audit/event 流非业务 facts,
    直 INSERT 是 outbox pattern 标准设计 (调用方 tx 内原子). 与 LL-066 subset-column
    不同, outbox 是单 writer 全列写入.

Usage:
    >>> writer = OutboxWriter(conn)
    >>> event_id = writer.enqueue(
    ...     aggregate_type="signal",
    ...     aggregate_id="sig-2026-04-28-s1",
    ...     event_type="generated",
    ...     payload={"strategy_id": "s1", "trade_date": "2026-04-28", "stock_count": 20},
    ... )
    >>> conn.commit()  # 调用方 tx commit 时 outbox + 业务表原子持久化
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg2.extensions

# Aggregate type 白名单 (防 typo 散乱). MVP 3.4 batch 4 4 域全迁 outbox.
# 新增 aggregate_type 必加此白名单 + 文档说明 (config_guard 启动期可校验, future hook).
_VALID_AGGREGATE_TYPES: frozenset[str] = frozenset({
    "signal",     # 信号生成 (signal_service)
    "order",      # 订单路由 (PlatformOrderRouter)
    "fill",       # 订单成交 (execution_service)
    "risk",       # 风控触发 (risk_engine: PMS / CB / intraday)
    "portfolio",  # 持仓变更 (paper_broker / qmt_data_service)
})


class OutboxWriter:
    """Event outbox enqueue helper.

    每个调用 = 1 个 INSERT 到 event_outbox 表. 不 commit (调用方管 tx 边界).
    调用方典型模式:

        with conn:  # tx
            # 业务表 INSERT/UPDATE
            cur.execute("INSERT INTO signals ...")
            # outbox INSERT (同 tx)
            outbox.enqueue(aggregate_type="signal", aggregate_id=sig_id, event_type="generated", payload={...})
        # conn.__exit__ commits → 业务 + 事件原子持久化

    Args:
      conn: psycopg2 connection. 调用方提供, 不 close, 不 commit.
    """

    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        self._conn = conn

    def enqueue(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        event_id: uuid.UUID | str | None = None,
    ) -> uuid.UUID:
        """Enqueue 1 个事件到 event_outbox. 不 commit.

        Args:
          aggregate_type: 聚合类型 (signal/order/fill/risk/portfolio). 必须在白名单.
          aggregate_id: 聚合 ID 字符串 (e.g. order_id / fill_id / signal_id).
          event_type: 事件类型字符串 (e.g. "generated" / "routed" / "executed").
          payload: JSONB 载荷 dict. 必须 JSON-serializable (json.dumps 校验).
          event_id: 可选指定 event_id (UUID 或字符串). None → 自动 uuid.uuid4.

        Returns:
          event_id (UUID). 调用方可记录此 ID 后续 trace.

        Raises:
          ValueError: aggregate_type 不在白名单 / aggregate_id 空 / event_type 空 /
                      payload 不可 JSON 序列化 / event_id 是非法 UUID 字符串
                      (uuid.UUID() 解析失败).
          TypeError: payload 不是 dict / event_id 不是 UUID/str/None.
        """
        # 参数校验 (铁律 33 fail-loud, 防 silent corrupt 入库)
        if aggregate_type not in _VALID_AGGREGATE_TYPES:
            raise ValueError(
                f"aggregate_type {aggregate_type!r} 不在白名单 "
                f"{sorted(_VALID_AGGREGATE_TYPES)}. 新增类型必先扩展 "
                f"_VALID_AGGREGATE_TYPES (outbox.py)."
            )
        if not aggregate_id or not aggregate_id.strip():
            raise ValueError("aggregate_id 必须非空字符串 (反向 trace 锚点).")
        if not event_type or not event_type.strip():
            raise ValueError("event_type 必须非空字符串 (Redis stream 名组件).")
        if not isinstance(payload, dict):
            raise TypeError(
                f"payload 必须是 dict, got {type(payload).__name__}. "
                f"非 dict 不能保 JSONB schema 稳定."
            )
        # JSON serializability 校验 (避 INSERT 才发现, 早 fail-loud).
        # 不用 default=str fallback — 铁律 33 fail-loud, 静默转 str 隐藏 schema bugs.
        # 调用方需预转换 datetime/Decimal: payload['ts'] = dt.isoformat() / str(decimal_val).
        try:
            payload_json = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"payload 不可 JSON 序列化: {e}. 检查 datetime / Decimal / "
                f"自定义对象, payload 应限基本 JSON 类型 (str/int/float/bool/None/list/dict). "
                f"调用方需预转换: dt.isoformat() / str(decimal_val)."
            ) from e

        # event_id 解析
        if event_id is None:
            resolved_id = uuid.uuid4()
        elif isinstance(event_id, str):
            resolved_id = uuid.UUID(event_id)  # raise ValueError on invalid
        elif isinstance(event_id, uuid.UUID):
            resolved_id = event_id
        else:
            raise TypeError(
                f"event_id 必须是 UUID / str / None, got {type(event_id).__name__}."
            )

        # INSERT (铁律 32: 不 commit).
        # PR #119 reviewer P1.2 采纳: with 包 cursor 防 execute 异常时 cursor leak
        # (psycopg2 long-lived service conn, cursor 累积到 conn 回收).
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_outbox
                    (event_id, aggregate_type, aggregate_id, event_type, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (str(resolved_id), aggregate_type, aggregate_id, event_type, payload_json),
            )
        return resolved_id
