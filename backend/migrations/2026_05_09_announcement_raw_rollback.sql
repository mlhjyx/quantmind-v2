-- V3 governance batch closure sub-PR 11 — announcement_raw 表 ROLLBACK
--
-- Pair: 2026_05_09_announcement_raw.sql
-- 用途: emergency rollback (沿用 news_raw_rollback 体例)
-- 关联 ADR: ADR-049 (V3 §S2.5 architecture sediment) / ADR-022 (反 silent overwrite)
-- 关联铁律: 33 (fail-loud DO guard) / 38 (Blueprint SSOT)

-- ─────────────────────────────────────────────────────────────
-- Phase 1: DROP TABLE (BEGIN/COMMIT 原子, IF EXISTS 幂等)
-- ─────────────────────────────────────────────────────────────

BEGIN;

DROP INDEX IF EXISTS ix_announcement_raw_type_disclosure;
DROP INDEX IF EXISTS ix_announcement_raw_source_fetched;
DROP INDEX IF EXISTS ix_announcement_raw_symbol_disclosure;

DROP TABLE IF EXISTS announcement_raw;

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: Rollback fail-loud guard (铁律 33, 验证 DROP 真生效)
-- ─────────────────────────────────────────────────────────────

DO $$
BEGIN
    SET LOCAL statement_timeout = '10s';

    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'announcement_raw'
    ) THEN
        RAISE EXCEPTION 'announcement_raw rollback failed — table still exists';
    END IF;
END $$;
