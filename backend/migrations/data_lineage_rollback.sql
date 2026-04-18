-- MVP 2.2 Sub2: data_lineage 回滚 (emergency only)
--
-- 使用场景: Lineage schema 设计错误, 需要推倒重来
-- 警告: 会丢失所有已记录的血缘 (本 MVP 无 backfill, 只影响上线后数据)
--
-- 执行:
--   psql -h localhost -p 5432 -U xin -d quantmind_v2 -f backend/migrations/data_lineage_rollback.sql

BEGIN;

DROP INDEX IF EXISTS idx_lineage_jsonb_gin;
DROP INDEX IF EXISTS idx_lineage_created_at;
DROP TABLE IF EXISTS data_lineage;

DO $$
DECLARE
    n_exist INT;
BEGIN
    SELECT COUNT(*) INTO n_exist
    FROM pg_tables WHERE schemaname = 'public' AND tablename = 'data_lineage';
    RAISE NOTICE 'data_lineage dropped: exists=%', n_exist;
END $$;

COMMIT;
