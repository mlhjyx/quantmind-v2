-- MVP 1.4 Knowledge Registry — ROLLBACK (emergency)
--
-- 还原 knowledge_registry.sql 创建的 3 张表 + trigger + function.
-- ⚠️  警告: 会丢失所有 platform_experiments / failed_directions / adr_records 数据.
-- 使用前建议先备份:
--   pg_dump -U xin -t platform_experiments -t failed_directions -t adr_records quantmind_v2 > /tmp/mvp14_backup.sql

DROP TRIGGER IF EXISTS tr_failed_directions_touch ON failed_directions;
DROP FUNCTION IF EXISTS _failed_directions_touch_updated_at();

DROP INDEX IF EXISTS ix_platform_exp_status;
DROP INDEX IF EXISTS ix_platform_exp_tags_gin;
DROP INDEX IF EXISTS ix_failed_dirs_severity;
DROP INDEX IF EXISTS ix_failed_dirs_tags_gin;
DROP INDEX IF EXISTS ix_adr_ironlaws_gin;
DROP INDEX IF EXISTS ix_adr_status;

DROP TABLE IF EXISTS platform_experiments;
DROP TABLE IF EXISTS failed_directions;
DROP TABLE IF EXISTS adr_records;

-- pgcrypto 扩展不回滚 (可能被其他表用, 如 factor_registry / feature_flags)
