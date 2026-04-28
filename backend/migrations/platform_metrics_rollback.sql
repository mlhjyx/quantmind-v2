-- MVP 4.1 batch 2.1 platform_metrics rollback
-- DROP TABLE CASCADE 清理 hypertable chunks. 显式 remove retention policy 防 orphan job.
--
-- reviewer P2.1 (database-reviewer HIGH) 采纳: TimescaleDB 2.x 部分版本 DROP TABLE CASCADE
-- 可能不自动 cleanup `timescaledb_information.jobs` 中的 retention 策略 row, 留 orphan
-- job 干扰下次 add_retention_policy. 显式 `remove_retention_policy(if_not_exists=>TRUE)`
-- 幂等清理.

-- Phase 1: remove retention policy job (idempotent, if_exists 防 table 已 dropped 时 raise)
DO $$
BEGIN
    -- if_not_exists=TRUE 在 hypertable 已不存在时也安全 (返 NULL 不 raise)
    PERFORM remove_retention_policy('platform_metrics', if_not_exists => TRUE);
EXCEPTION
    WHEN undefined_table THEN
        -- table 已不存在 (rollback 重跑场景), 跳过
        RAISE NOTICE 'platform_metrics not found, skipping retention removal';
END $$;

-- Phase 2: drop indexes + table (CASCADE 清理 hypertable chunks)
DROP INDEX IF EXISTS ix_platform_metrics_type_ts;
DROP INDEX IF EXISTS ix_platform_metrics_name_ts;
DROP TABLE IF EXISTS platform_metrics CASCADE;
