-- MVP 3.4 batch 1 — event_outbox ROLLBACK (emergency)
--
-- 还原 event_outbox.sql 创建的表 + 索引 + 注释.
-- ⚠️  警告: 会丢失所有 event_outbox 数据 (publisher worker 未发 Redis 的事件全失).
-- 使用前建议先备份:
--   pg_dump -U xin -t event_outbox quantmind_v2 > /tmp/mvp34_event_outbox_backup.sql
--
-- 关联:
--   - 正向 migration: backend/migrations/event_outbox.sql
--   - MVP 3.4 batch 1 spec

DROP INDEX IF EXISTS ix_event_outbox_aggregate;
DROP INDEX IF EXISTS ix_event_outbox_unpublished;

DROP TABLE IF EXISTS event_outbox;
