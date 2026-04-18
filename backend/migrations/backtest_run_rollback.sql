-- MVP 2.3 Sub1 · backtest_run ALTER rollback (ADR-007 决策)
--
-- 精确回滚本次 ALTER (3 列 + 1 约束), 不动老表 CREATE / FK / index / 独立 DECIMAL 列.
-- 老 7 行数据 + 4 张 FK 表全保留.
--
-- 执行:
--   psql -h localhost -p 5432 -U xin -d quantmind_v2 -f backend/migrations/backtest_run_rollback.sql

BEGIN;

ALTER TABLE backtest_run
    DROP CONSTRAINT IF EXISTS chk_backtest_run_mode;

ALTER TABLE backtest_run
    DROP COLUMN IF EXISTS extra_decimals,
    DROP COLUMN IF EXISTS lineage_id,
    DROP COLUMN IF EXISTS mode;

DO $$
BEGIN
    RAISE NOTICE 'backtest_run rolled back (3 columns + mode CHECK dropped, 老表 core schema 保留)';
END $$;

COMMIT;
