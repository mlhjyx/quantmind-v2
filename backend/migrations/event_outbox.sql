-- MVP 3.4 Event Sourcing — event_outbox 表 (批 1)
--
-- Outbox pattern 持久化业务事件, publisher worker 异步发 Redis Streams.
-- 调用方在自己 tx 内 INSERT (业务表 + outbox 原子), commit 后 publisher 异步分发.
--
-- 幂等: IF NOT EXISTS 保护
-- 回滚: 见 backend/migrations/event_outbox_rollback.sql
--
-- 关联:
--   - Blueprint Part 2 Framework #7 Observability + U2 Event Sourcing
--   - MVP 3.4 batch 1 spec (docs/mvp/MVP_3_4_event_sourcing_outbox.md)
--   - 取代 MVP 3.3 StubExecutionAuditTrail 的 logger.info-only 占位
--   - MVP 3.4 batch 2 publisher worker 消费此表

CREATE TABLE IF NOT EXISTS event_outbox (
    event_id        UUID PRIMARY KEY,
    aggregate_type  TEXT NOT NULL,           -- 'signal' / 'order' / 'fill' / 'risk' / 'portfolio'
    aggregate_id    TEXT NOT NULL,           -- e.g. order_id / signal_id / fill_id (非 UUID 也可)
    event_type      TEXT NOT NULL,           -- e.g. 'generated' / 'routed' / 'executed' / 'triggered'
    payload         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ,             -- NULL = 未 publish (publisher worker 扫描)
    retries         INT NOT NULL DEFAULT 0   -- publisher 重试计数 (max_retries=10 → DLQ)
);

-- B-Tree partial index 加速 publisher 扫 unpublished events.
-- (PR #119 reviewer P1.1 修正: 原 BRIN 设计错 — published_at 非 monotonic,
--  从 NULL → 后续 UPDATE 写时戳, BRIN 无法 efficient 定位散布的 NULL 行;
--  partial B-Tree on created_at 可让 publisher "oldest unpublished N rows"
--  query 走 index, 表 published_at IS NULL 行被 publish 后自动 shrink.)
-- 实测要求 (MVP 3.4 batch 2): EXPLAIN ANALYZE 验索引使用 + batch query <50ms.
CREATE INDEX IF NOT EXISTS ix_event_outbox_unpublished
    ON event_outbox (created_at)
    WHERE published_at IS NULL;

-- aggregate 反向 trace 索引 (MVP 3.4 batch 3 ExecutionAuditTrail.trace 用)
CREATE INDEX IF NOT EXISTS ix_event_outbox_aggregate
    ON event_outbox (aggregate_type, aggregate_id, created_at DESC);

COMMENT ON TABLE event_outbox IS
    'MVP 3.4 outbox pattern. 业务 tx 内 INSERT (调用方 commit 时业务+事件原子), publisher worker 异步发 Redis Streams qm:{aggregate_type}:{event_type}. at-least-once 语义 — consumer 必须按 event_id 幂等去重.';
COMMENT ON COLUMN event_outbox.event_id IS
    'UUID PK, 调用方生成 (uuid.uuid4) 或自动. consumer Redis SET NX dedup TTL 7 日.';
COMMENT ON COLUMN event_outbox.aggregate_type IS
    '聚合类型: signal/order/fill/risk/portfolio. Redis stream 名: qm:{aggregate_type}:{event_type}.';
COMMENT ON COLUMN event_outbox.aggregate_id IS
    '聚合 ID (反向 trace 用): order_id / fill_id / signal_id. 非 UUID 字符串也可.';
COMMENT ON COLUMN event_outbox.event_type IS
    '事件类型: e.g. generated/routed/executed/triggered. 跟 aggregate_type 拼成 stream 名.';
COMMENT ON COLUMN event_outbox.payload IS
    'JSONB 业务载荷. e.g. {"order_id": "abc", "strategy_id": "s1", "code": "600519.SH"}.';
COMMENT ON COLUMN event_outbox.created_at IS
    'Outbox INSERT 时戳 (调用方 tx 时点). publisher 按此扫描 + 串 audit chain.';
COMMENT ON COLUMN event_outbox.published_at IS
    'NULL = 未 publish (worker 待扫描). NOT NULL = 已发 Redis. retention 90 日 cron job (Wave 4+).';
COMMENT ON COLUMN event_outbox.retries IS
    'Publisher 重试计数. 失败 retry exponential backoff, max=10 → DLQ qm:dlq:outbox.';
