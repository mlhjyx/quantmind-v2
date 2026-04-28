-- MVP 4.1 batch 2.1 platform_metrics rollback
-- DROP TABLE CASCADE 清理 hypertable chunks + retention job.

DROP INDEX IF EXISTS ix_platform_metrics_type_ts;
DROP INDEX IF EXISTS ix_platform_metrics_name_ts;
DROP TABLE IF EXISTS platform_metrics CASCADE;
