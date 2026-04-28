"""MVP 3.4 batch 2 — Outbox Publisher Worker (event_outbox → Redis Streams).

Celery beat 高频任务 `*/30s`. 每 tick 扫 event_outbox 未 publish 行 (B-Tree partial 索引),
publish 到 Redis Stream `qm:{aggregate_type}:{event_type}`, 成功后 UPDATE published_at.

设计:
  - SKIP LOCKED 并发安全 (多 worker 抢 disjoint batch, 实际 Windows solo×1 单 worker
    但 SKIP LOCKED 仍是正确做法防 lock 等待).
  - max_retries=10 后入 DLQ stream `qm:dlq:outbox` (terminal mark published_at + 高 retries).
  - 失败不 commit 已 publish 行 (publish 已发生 → 即使 update 失败下 tick 重发, consumer 必幂等).

铁律:
  - 32 (Service 不 commit): 本 worker 是 Celery task, 是顶层 commit owner, 自管 tx 边界 (例外).
  - 33 (fail-loud): publish 异常 + retries 达上限 fail-loud 进 DLQ, 不 silent 丢.
  - 17 (DataPipeline) 例外: 同 outbox.py — outbox 是 audit/event 流非业务 facts.

Usage (生产由 Beat 调度, 不需要直接 invoke):
    >>> from app.tasks.outbox_publisher import outbox_publisher_tick
    >>> outbox_publisher_tick.delay()  # 测试用
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.stream_bus import get_stream_bus
from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.outbox_publisher")

# DLQ stream for terminal failures (retries >= MAX_RETRIES)
DLQ_STREAM = "qm:dlq:outbox"

# 默认配置 (可由 settings env 覆盖, batch 4 才接入). 当前用模块常量.
DEFAULT_BATCH_SIZE: int = 100
DEFAULT_MAX_RETRIES: int = 10


class OutboxPublisher:
    """Outbox event 发布器.

    每 batch 流程:
      1. SELECT FOR UPDATE SKIP LOCKED 拿一批 unpublished rows (B-Tree partial 索引)
      2. 逐行 publish 到 Redis Stream
      3. 成功 → UPDATE published_at=NOW(), retries=N (preserved or reset)
      4. 失败 + retries < max → UPDATE retries=retries+1 (留下 tick 重试)
      5. 失败 + retries >= max → publish to DLQ + UPDATE published_at=NOW() (terminal)
      6. commit

    Args:
      conn_factory: Callable 返 psycopg2 connection (默认 get_sync_conn).
      stream_publisher: Callable(stream_name, data_dict, source) -> msg_id|None.
                        默认走 StreamBus.publish_sync.
      max_retries: terminal DLQ 阈值. 默认 10.
      batch_size: 单次 SELECT LIMIT. 默认 100.
    """

    def __init__(
        self,
        conn_factory=None,
        stream_publisher=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        # Lazy import 防 Celery worker 启动期 settings 未就绪
        if conn_factory is None:
            from app.services.db import get_sync_conn
            conn_factory = get_sync_conn
        self._conn_factory = conn_factory

        if stream_publisher is None:
            bus = get_stream_bus()
            stream_publisher = bus.publish_sync
        self._stream_publisher = stream_publisher

        if max_retries < 1:
            raise ValueError(f"max_retries 必须 >=1, got {max_retries}")
        if batch_size < 1:
            raise ValueError(f"batch_size 必须 >=1, got {batch_size}")
        self._max_retries = max_retries
        self._batch_size = batch_size

    def publish_batch(self) -> dict[str, int]:
        """扫一批 unpublished events 并 publish.

        Returns:
            summary dict: {selected, published, retried, dlq, errors}.
        """
        conn = self._conn_factory()
        try:
            return self._publish_batch_inner(conn)
        finally:
            conn.close()

    def _publish_batch_inner(self, conn) -> dict[str, int]:
        """Inner loop with explicit conn (便于测试注入 mock conn)."""
        # 确保事务模式 (psycopg2 默认 autocommit=False, 但显式安全)
        conn.autocommit = False

        selected = 0
        published = 0
        retried = 0
        dlq = 0
        errors = 0

        with conn.cursor() as cur:
            # SKIP LOCKED 多 worker 并发安全; ORDER BY created_at 保 FIFO
            cur.execute(
                """
                SELECT event_id, aggregate_type, aggregate_id, event_type, payload, retries
                FROM event_outbox
                WHERE published_at IS NULL
                ORDER BY created_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (self._batch_size,),
            )
            rows = cur.fetchall()
            selected = len(rows)

            for row in rows:
                event_id, aggregate_type, aggregate_id, event_type, payload, retries = row
                stream_name = f"qm:{aggregate_type}:{event_type}"
                # payload 是 JSONB → psycopg2 默认返 dict, 安全直接传给 publisher
                publish_data: dict[str, Any] = {
                    "event_id": str(event_id),
                    "aggregate_type": aggregate_type,
                    "aggregate_id": aggregate_id,
                    "event_type": event_type,
                    "payload": payload,
                }

                # 尝试 publish — publish_sync 内部 try/except 返 None (StreamBus 设计)
                msg_id = None
                publish_exc: Exception | None = None
                try:
                    msg_id = self._stream_publisher(
                        stream_name, publish_data, source="outbox_publisher"
                    )
                except Exception as e:
                    # 防御深度: 即便 publisher 自己 raise (非 StreamBus 默认行为)
                    publish_exc = e

                if msg_id is not None:
                    # 成功 → 标 published_at, retries 保留 (不重置, 历史可见)
                    cur.execute(
                        "UPDATE event_outbox SET published_at = NOW() WHERE event_id = %s",
                        (str(event_id),),
                    )
                    published += 1
                else:
                    # 失败: retries+1, 达上限 → DLQ + 终结
                    new_retries = retries + 1
                    if new_retries >= self._max_retries:
                        # DLQ publish (best-effort, 失败也终结防 zombie 行)
                        try:
                            self._stream_publisher(
                                DLQ_STREAM,
                                {
                                    **publish_data,
                                    "_dlq_reason": (
                                        f"max_retries={self._max_retries} reached"
                                        if publish_exc is None
                                        else f"exception: {type(publish_exc).__name__}: {publish_exc}"
                                    ),
                                    "_dlq_retries": new_retries,
                                },
                                source="outbox_publisher_dlq",
                            )
                        except Exception:
                            logger.exception(
                                "[outbox_publisher] DLQ publish 也失败 event_id=%s "
                                "(行仍会标 published_at 防 zombie 重试)",
                                event_id,
                            )
                        cur.execute(
                            """UPDATE event_outbox
                               SET published_at = NOW(), retries = %s
                               WHERE event_id = %s""",
                            (new_retries, str(event_id)),
                        )
                        dlq += 1
                        logger.warning(
                            "[outbox_publisher] event_id=%s 进 DLQ (retries=%d): stream=%s",
                            event_id, new_retries, stream_name,
                        )
                    else:
                        cur.execute(
                            "UPDATE event_outbox SET retries = %s WHERE event_id = %s",
                            (new_retries, str(event_id)),
                        )
                        retried += 1
                        logger.info(
                            "[outbox_publisher] event_id=%s publish 失败 retries=%d/%d, "
                            "下 tick 重试",
                            event_id, new_retries, self._max_retries,
                        )

                if publish_exc is not None:
                    errors += 1

        conn.commit()

        return {
            "selected": selected,
            "published": published,
            "retried": retried,
            "dlq": dlq,
            "errors": errors,
        }


# ════════════════════════════════════════════════════════════
# Celery beat task — `*/30s` (高频但 partial 索引 cheap)
# ════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="app.tasks.outbox_publisher.outbox_publisher_tick",
    acks_late=True,
    max_retries=0,  # 失败不重试 — 30s 后下 tick 自动重扫 (event_outbox 是状态机)
    time_limit=60,  # 30s 周期, 60s 硬上限防积压
    soft_time_limit=45,
)
def outbox_publisher_tick(self) -> dict[str, Any]:
    """Outbox publisher beat task — 每 30s 扫 batch publish.

    设计:
      - max_retries=0: 30s 周期 ≪ Celery retry 间隔, 重扫成本低. retry 反致积压.
      - acks_late=True: worker crash 后 Celery 重派发, 至少一次语义 (consumer 必幂等).
      - time_limit=60: 30s 周期内必 finish, 否则 worker 积压.

    Returns:
        summary dict (见 OutboxPublisher.publish_batch).
    """
    t0 = time.time()
    try:
        publisher = OutboxPublisher()
        summary = publisher.publish_batch()
        elapsed = time.time() - t0
        if summary["selected"] > 0:
            logger.info(
                "[outbox_publisher] tick: selected=%d published=%d retried=%d dlq=%d "
                "errors=%d elapsed=%.3fs",
                summary["selected"], summary["published"], summary["retried"],
                summary["dlq"], summary["errors"], elapsed,
            )
        else:
            logger.debug("[outbox_publisher] tick: 0 unpublished events (%.3fs)", elapsed)
        return {**summary, "elapsed_s": round(elapsed, 3)}
    except Exception as exc:
        elapsed = time.time() - t0
        logger.exception(
            "[outbox_publisher] tick 异常 (%.3fs): %s", elapsed, exc,
        )
        # raise 让 Celery acks_late 机制把 task 标 failed (不重派, max_retries=0)
        raise
