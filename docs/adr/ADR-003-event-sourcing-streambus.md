---
adr_id: ADR-003
title: Event Sourcing 存储方案 — StreamBus + PG (非 EventStoreDB)
status: accepted
related_ironlaws: [22, 38]
recorded_at: 2026-04-17
---

## Context

Wave 3 MVP 3.3 引入 Event Sourcing (U2 升维原则) 实现 9 种核心事件 (signal.generated / order.placed / order.filled / pms.triggered 等) 可持久化 + 可重放 + 可投影到 Materialized View.

存储选型 2 候选:

1. **StreamBus + PG outbox pattern** — 已有 Redis Streams 基础设施 (`backend/app/core/stream_bus.py`), 事件先写 PG outbox 表, 再由 outbox poller 推 Redis Stream
2. **EventStoreDB** — 专业事件数据库, 原生支持 ES 语义 (stream / aggregate / projection)

项目已有 Redis Streams 3 年生产经验 (PMS/signal/execution 均用), 团队熟. EventStoreDB 是新组件需学习 + 运维.

## Decision

采用 **StreamBus + PG outbox pattern** 作为 Event Sourcing 后端. 3 必配工程组件:

1. **outbox 表**: 事件先写 PG (`events_outbox`), 同事务与业务操作一起 commit, 保原子性
2. **snapshot 机制**: 聚合状态快照 + 增量事件, 避免无限事件列重放
3. **event versioning**: schema 演化支持 (v1/v2 共存, 消费方按版本反序列化)

## Alternatives Considered

| 选项 | 学习成本 | 运维负担 | Exactly-once 保证 | 为何不选 |
|---|---|---|---|---|
| **StreamBus + PG outbox** ⭐ | 低 (已在用) | 低 (PG + Redis 已在跑) | outbox pattern 保 | — (选此) |
| EventStoreDB | 高 (新语义) | 高 (新服务 + 备份策略) | 原生保 | 当前单人项目, 额外一个运维组件得不偿失 |
| 纯 Redis Streams (无 outbox) | 最低 | 最低 | **不保** (DB commit 后 Redis 可能挂) | 事务原子性无, 不可接受 |

## Consequences

**正面**:
- 复用 Redis Streams 消费端 (StreamBus 已有 `publish_sync` API)
- PG outbox + snapshot 在 Uber/Netflix 文献充分论证, 不是发明轮子
- `backend/app/core/stream_bus.py` 有 maxlen=10000 保 Stream 无限增长

**负面**:
- outbox poller 增加延迟 (事件落 PG → poll → 推 Redis, ~100ms P99)
- snapshot + versioning 工程组件需 Wave 3 MVP 3.3 一起交付, 不能省
- schema 演化若不严格做 versioning, 回放老事件会炸, 必须强约束

## References

- `memory/project_platform_decisions.md` §Q3
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Part 4 MVP 3.3
- `backend/app/core/stream_bus.py` 现有 StreamBus 实现
- outbox pattern: [microservices.io](https://microservices.io/patterns/data/transactional-outbox.html)
