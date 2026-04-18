-- MVP 2.3 Sub1 PR B review P1-C · idx_backtest_run_created_at rollback

BEGIN;

DROP INDEX IF EXISTS idx_backtest_run_created_at;

DO $$
BEGIN
    RAISE NOTICE 'idx_backtest_run_created_at dropped';
END $$;

COMMIT;
