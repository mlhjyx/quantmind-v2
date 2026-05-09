-- Rollback for 2026_05_10_fundamental_context_daily.sql (V3 governance batch closure sub-PR 14 sediment per ADR-053)
--
-- 注意: DROP TABLE 会丢失 fundamental_context_daily 全部 ingest 数据.
-- 仅在 sub-PR 14 mistake / sub-PR 15+ schema migration 时使用.

BEGIN;

DROP INDEX IF EXISTS ix_fundamental_context_daily_fetched_at;
DROP INDEX IF EXISTS ix_fundamental_context_daily_symbol_date;
DROP TABLE IF EXISTS fundamental_context_daily;

COMMIT;

-- Fail-loud DO guard verify (沿用 sub-PR 11a 4-phase pattern + 铁律 33)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'fundamental_context_daily'
    ) THEN
        RAISE EXCEPTION '[fail-loud] fundamental_context_daily DROP TABLE 失败 (sub-PR 14 rollback guard)';
    END IF;
    RAISE NOTICE '[OK] fundamental_context_daily rollback applied';
END $$;
