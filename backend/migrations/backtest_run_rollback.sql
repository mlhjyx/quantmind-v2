-- MVP 2.3 Sub1 · backtest_run ALTER rollback (ADR-007 决策)
--
-- 精确回滚本次 ALTER (3 列 + 1 约束), 不动老表 CREATE / FK / index / 独立 DECIMAL 列.
-- 老 7 行数据 + 4 张 FK 表全保留.
--
-- 执行:
--   psql -h localhost -p 5432 -U xin -d quantmind_v2 -f backend/migrations/backtest_run_rollback.sql

BEGIN;

-- PR A review fix (database-reviewer P1#1 + P3#5): 显式 DROP 命名 FK + index, 与 forward migration 对称.
-- DROP COLUMN 本会自动级联 drop FK, 但命名后显式 drop 让 rollback 更可审计.
DROP INDEX IF EXISTS idx_backtest_run_lineage_id;

ALTER TABLE backtest_run
    DROP CONSTRAINT IF EXISTS backtest_run_lineage_id_fkey;

ALTER TABLE backtest_run
    DROP CONSTRAINT IF EXISTS chk_backtest_run_mode;

ALTER TABLE backtest_run
    DROP COLUMN IF EXISTS extra_decimals,
    DROP COLUMN IF EXISTS lineage_id,
    DROP COLUMN IF EXISTS mode;

DO $$
BEGIN
    RAISE NOTICE 'backtest_run rolled back (3 columns + mode CHECK + FK + index dropped, 老表 core schema 保留)';
END $$;

COMMIT;
