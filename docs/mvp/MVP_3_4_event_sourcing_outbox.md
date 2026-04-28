# MVP 3.4 Event Sourcing & Outbox Pattern (统一事件总线 + 反向审计链)

> **ADR**: Platform Blueprint §4.7 / Framework #7 Observability+EventBus / U2 Event Sourcing 升维
> **Sprint**: Wave 3 4/5 (Session 38+ 起, post MVP 3.3 SignalPipeline + OrderRouter merged)
> **前置**: MVP 3.3 Signal-Exec ✅ (SignalPipeline + OrderRouter + AuditChain stub) / 现有 Redis Streams 基础设施 (qm:{domain}:{event_type}) ✅

## Context

**问题**: 当前事件机制**碎片化** + **审计链中断**:
- Redis Streams `qm:signal:generated` / `qm:pms:protection_triggered` / `qm:qmt:status` 等已存, 但 **publish 与 DB tx 分离** (publish 后 DB rollback → event 已发但状态未持久化, 反向不一致).
- `risk_event_log` (MVP 3.1) 表已落 risk 域事件, 但**仅 risk** — signal/order/fill/portfolio 四域无统一事件表.
- MVP 3.3 ExecutionAuditTrail.trace() 是 stub (NotImplementedError), 反向审计链 fill→order→signal→strategy→factor 不可达.
- 部分 Service 写 DB 后忘记发 event (silent fail), 部分 Service 发 event 后 DB 失败 (publish 已发, dedup 难).

**Precondition 实测发现** (Session 38+ 开工前需复核, 当前 Session 36 末状态):
- ✅ `risk_event_log`: 0 rows (clean slate, MVP 3.1 Monday 4-27 首次 emit), 表 schema 可作 outbox 模板
- ✅ Redis Streams 已运行: `qm:signal:generated` 等多个 stream 活跃 (StreamBus 模块)
- ❌ **outbox 表不存在**: `event_outbox` 需 migration, 含 (event_id PK / aggregate_id / event_type / payload JSONB / created_at / published_at NULL)
- ⚠️ MVP 3.3 AuditChain.record() 当前 logger.info-only stub, 本 MVP 替换为 outbox + Redis publish

## Scope (~3-4 周, 4 批交付, 串行)

**进度** (Session 41 末 2026-04-28 18:30):
- ✅ 批 1: PR #119 merged main `2a9c01a` (event_outbox 表 + OutboxWriter + B-Tree partial 索引 + 14 tests, EXPLAIN 0.070ms)
- ✅ 批 2: PR #120 merged main `3358150` (OutboxPublisher 30s Celery beat + SKIP LOCKED + DLQ + 16 tests, 真 DB integration ✓)
- ✅ 批 3: PR #121 merged main `4929f39` (OutboxBackedAuditTrail concrete + record + 4 SQL trace + 23 tests, 双模式互补)
- ⬜ 批 4: 4 域事件迁 outbox + 7 日 dual-write — Session 42+

### 批 1 ✅: event_outbox 表 + Outbox 写路径 (~1 周)

**交付物**:
1. `backend/migrations/event_outbox.sql` ⭐ 新 ~40 行
   - `event_outbox` 表: event_id UUID PK / aggregate_type TEXT / aggregate_id TEXT / event_type TEXT / payload JSONB / created_at TIMESTAMPTZ / published_at TIMESTAMPTZ NULL / retries INT DEFAULT 0
   - Index: `(published_at) WHERE published_at IS NULL` (BRIN 加速 publisher worker scan)
2. `backend/qm_platform/observability/outbox.py` ⭐ 新 ~180 行
   - `OutboxWriter`: `enqueue(aggregate_type, aggregate_id, event_type, payload)` — 在调用方事务内 INSERT, **铁律 32 不 commit** (调用方 commit 时 event + 业务表原子)
3. `backend/qm_platform/observability/__init__.py` ⚠️ MODIFY: 导出 `OutboxWriter`
4. `backend/tests/test_event_outbox.py` ⭐ 新 ~150 行 ~12 tests (含原子性 + 索引使用)

### 批 2 ✅: Outbox Publisher Worker → Redis Streams (~1 周)

**交付物**:
1. `backend/app/tasks/outbox_publisher.py` ⭐ 新 ~150 行
   - Celery beat task `outbox_publisher_tick` `*/30 seconds` (高频但 BRIN 索引 cheap)
   - SELECT batch (LIMIT 100, FOR UPDATE SKIP LOCKED) → publish to `qm:{aggregate_type}:{event_type}` Redis Stream → UPDATE published_at
   - retry: max_retries=10 + exponential backoff, 超时 → DLQ Redis Stream `qm:dlq:outbox`
2. `backend/app/tasks/beat_schedule.py` ⚠️ MODIFY: 加 outbox_publisher_tick (3 行 delta)
3. `backend/tests/test_outbox_publisher.py` ⭐ 新 ~200 行 ~15 tests (并发 SKIP LOCKED + retry + DLQ)
4. `backend/tests/smoke/test_mvp_3_4_batch_2_live.py` ⭐ 新 (铁律 10b)

### 批 3 ✅: ExecutionAuditTrail concrete + AuditChain.trace() 真实现 (~1 周)

**交付物**:
1. `backend/qm_platform/signal/audit.py` ⚠️ REPLACE stub
   - `OutboxBackedAuditTrail(ExecutionAuditTrail)` concrete (replace MVP 3.3 stub)
   - `record(event_type, payload)`: 调 OutboxWriter.enqueue (复用批 1)
   - `trace(fill_id)`: 反向 SQL JOIN event_outbox 串 fill→order→signal→strategy 链, 返 AuditChain dataclass
2. `backend/qm_platform/signal/router.py` ⚠️ MODIFY (~10 行 delta): wire OutboxBackedAuditTrail 替换 stub
3. `backend/tests/test_audit_outbox_concrete.py` ⭐ 新 ~250 行 ~18 tests (含 trace 整链 + AuditMissing 异常)

### 批 4: 4 域事件迁 outbox + retire ad-hoc Redis publish (~1 周)

**交付物**:
1. `backend/app/services/risk_control_service.py` ⚠️ MODIFY: PMS / circuit_breaker 写路径迁 outbox (替原 ad-hoc StreamBus.publish)
2. `backend/app/services/signal_service.py` ⚠️ MODIFY: signal.generated 走 outbox
3. `backend/app/services/execution_service.py` ⚠️ MODIFY: order.routed / fill.executed 走 outbox
4. `backend/qm_platform/risk/engine.py` ⚠️ MODIFY: risk_event_log 写入同时 enqueue outbox (双写迁移期, 批 5 才 deprecate risk_event_log 直写)
5. `backend/tests/test_outbox_4domain_integration.py` ⭐ 新 ~300 行 ~20 tests
6. 7 日 dual-write 观察: outbox + 老 stream 比对一致, 无丢失

## Out-of-scope (明确排除, 铁律 23)

- ❌ **删除 `risk_event_log`** (MVP 3.5 Eval Gate 后 Sunset, 本 MVP 双写迁移)
- ❌ **删除老 Redis Streams** (PMS / qmt / streamBus 老路径保留, 7 日观察后跨 PR 退役)
- ❌ **Event replay / time-travel** (调用 outbox 历史重放 portfolio state, 留 Wave 4+ Observability)
- ❌ **CQRS 全套读写分离** (本 MVP 仅 outbox + audit chain, CQRS query side 留 MVP 4.x)
- ❌ **Event versioning / schema evolution** (V1 schema 即可, V2 留 Wave 4+)
- ❌ **Cross-database transactions** (单 PG 即可, sharding 留 Wave 4+)

## 关键架构决策 (铁律 39 显式)

### Outbox 而非 2PC
- 选择: 调用方事务内 INSERT event_outbox + 业务表 → commit 后 publisher worker 异步发 Redis
- 理由: 单 PG 事务保业务+事件原子性, 比 XA/2PC 简单 + 不依赖 broker XA 支持
- 风险缓解: publisher worker 独立 task, retry + DLQ + at-least-once 语义 (consumer 必须幂等)

### 双写迁移 (批 4) 而非一刀切
- 选择: 4 域事件先 outbox + 老 StreamBus 双写 7 日, 比对无丢失再退役老路径
- 理由: 老 stream 已有 consumer (前端 + monitoring), 直接切断会破坏下游
- 退役路径: 跨 PR Follow-up (1) consumer 改读 outbox→stream / (2) 老 publish 行删除

### published_at NULL 索引 BRIN vs B-Tree
- 选择: BRIN partial index `WHERE published_at IS NULL`
- 理由: outbox 表预计高写入低读取 (publisher 只查 unpublished), BRIN 写开销 << B-Tree
- 验证: 批 2 PR 加 `EXPLAIN ANALYZE` 验证索引使用, retries=0 batch query <50ms

### at-least-once + consumer 幂等
- 选择: publisher worker 失败 retry, consumer 必须按 event_id 幂等去重
- 理由: 网络分区时 publish 已发但 update published_at 失败 → 重试可能 dup. 强 exactly-once 复杂度 >> 收益
- 实施: 每个 event payload 含 event_id UUID, consumer side 用 Redis SET NX dedup (TTL 7 日)

### outbox tx 内同步写 vs 异步队列
- 选择: 调用方在自己 tx 内 INSERT outbox, **不引入第二个 in-process queue**
- 理由: in-process queue 重复 outbox 模式且不持久化, 进程崩溃会丢
- 风险: tx 内多 INSERT 增写延迟 ~1ms / event, 可接受

## LL-059 9 步闭环 (4 批 = 4 PR, 串行)

批 1 `feat/mvp-3-4-batch-1-event-outbox` → 批 2 `feat/mvp-3-4-batch-2-publisher-worker` → 批 3 `feat/mvp-3-4-batch-3-audit-trail-concrete` → 批 4 `feat/mvp-3-4-batch-4-4domain-migration`

## 验证 (硬门, 铁律 10b + 40)

```bash
# 批 1
pytest backend/tests/test_event_outbox.py -v  # ~12 PASS
psql -c "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM event_outbox WHERE published_at IS NULL LIMIT 100"
  # 验 BRIN 索引使用 + buffers cached

# 批 2
pytest backend/tests/test_outbox_publisher.py -v  # ~15 PASS
celery -A app.tasks beat --schedule=...  # outbox_publisher_tick 30s 周期触发

# 批 3
pytest backend/tests/test_audit_outbox_concrete.py -v  # ~18 PASS
python -c "from qm_platform.signal.audit import OutboxBackedAuditTrail; t = OutboxBackedAuditTrail(...); print(t.trace('fill_xxx'))"

# 批 4
pytest backend/tests/test_outbox_4domain_integration.py -v  # ~20 PASS
# Dual-write 观察 (7 日 in production)
```

## 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| outbox 表写入延迟拖慢业务 tx | latency 上升 | 单 INSERT <1ms, 加 BRIN 索引保 publisher scan 不阻塞 |
| publisher worker 死锁 / 永久 backlog | event 堆积 | retries=10 + DLQ + monitoring 告警 (depth > 1000 钉钉) |
| 老 StreamBus consumer 与 outbox stream 不兼容 | 前端 / monitoring 中断 | 双写 7 日 + consumer 改读迁移文档 + Follow-up PR |
| `event_outbox` 历史无限增长 | 表膨胀 | published_at IS NOT NULL + retention 90 日 cron job (Wave 4+) |
| at-least-once 致 consumer dup | 业务幂等性 bug | event_id Redis SET NX (TTL 7 日) + consumer 测试 dup tolerance |

## Follow-up (跨 PR, 不在本 plan)

1. 老 StreamBus publish 路径退役 (4 域 7 日双写观察后, ~MVP 3.4.1)
2. Risk_event_log 退役并入 event_outbox 单源 (MVP 3.5 后)
3. Event replay / time-travel API (Wave 4 Observability)
4. CQRS query side projections (MVP 4.x)
5. ADR-013 Event Sourcing 契约稳定性 (MVP 3.4 完工后, 锁 outbox schema 防 Wave 4+ 破坏)
