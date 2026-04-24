-- MVP 3.1 Risk Framework — risk_event_log ROLLBACK (emergency)
--
-- 还原 risk_event_log.sql 创建的表 + index + hypertable + retention policy.
-- ⚠️  警告: 会丢失所有 risk_event_log 数据.
-- 使用前建议先备份:
--   pg_dump -U xin -t risk_event_log quantmind_v2 > /tmp/mvp31_b1_backup.sql
--
-- TimescaleDB hypertable DROP TABLE 自动清理 chunks + retention policy,
-- 无需手动 remove_retention_policy.

DROP INDEX IF EXISTS ix_risk_event_strategy_time;
DROP INDEX IF EXISTS ix_risk_event_rule_time;

DROP TABLE IF EXISTS risk_event_log CASCADE;

-- pgcrypto 扩展不回滚 (其他表仍在用: knowledge_registry 3 表 / feature_flags / factor_registry).
