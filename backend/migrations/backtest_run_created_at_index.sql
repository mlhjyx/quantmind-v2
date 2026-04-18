-- MVP 2.3 Sub1 PR B review P1-C · idx_backtest_run_created_at
--
-- 背景: DBBacktestRegistry.list_recent 走 `SELECT ... ORDER BY created_at DESC LIMIT N`.
--       老 `idx_backtest_strategy (strategy_id, created_at DESC)` 不覆盖 strategy_id=NULL
--       (研究脚本跑的 run 无 strategy 绑定, 占 backtest_run 主流量).
--       Sweep 场景 1000+ rows 后 → seq scan + in-memory sort 瓶颈.
--
-- 修: 加独立 partial index (strategy_id IS NULL 的 run 也走 index) + DESC 对齐 LIMIT.
--
-- 幂等: CREATE INDEX IF NOT EXISTS.
--
-- 执行:
--   psql -h localhost -p 5432 -U xin -d quantmind_v2 -f backend/migrations/backtest_run_created_at_index.sql
--
-- 关联 PR B review: database-reviewer P1-C
-- 关联铁律: 22 (文档跟随代码) / 42 (review P1 必修)

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema='public' AND table_name = 'backtest_run') THEN
        RAISE EXCEPTION 'backtest_run 表不存在';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_backtest_run_created_at
    ON backtest_run (created_at DESC);

DO $$
DECLARE
    has_idx BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname='public'
          AND tablename='backtest_run'
          AND indexname='idx_backtest_run_created_at'
    ) INTO has_idx;
    RAISE NOTICE 'idx_backtest_run_created_at ready: %', has_idx;
END $$;

COMMIT;
