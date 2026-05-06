-- Sprint 2 sub-PR 7b.1 rollback: DROP news_raw 表 + COMMENT.
-- 沿用 PR #223 llm_cost_daily_rollback.sql + risk_event_log_rollback.sql 体例 (DROP TABLE IF EXISTS 幂等).
-- 关联: 2026_05_06_news_raw.sql
--
-- ⚠️ Sequential rollback order (FK natural pairing sustained):
--   sub-PR 7b.1 cumulative rollback 真序列:
--   1. news_classified rollback (FK child, drops first)
--   2. news_raw rollback (本 file, FK parent, drops 2nd)
--
--   反 sequence → DROP news_raw 时 news_classified FK 真依赖 → ERROR (除非 CASCADE).
--   本 file DROP TABLE IF EXISTS news_raw — 真依赖 user 走 7b.1 cumulative sequential rollback.

BEGIN;

DROP TABLE IF EXISTS news_raw;

COMMIT;

-- 验证 (反 silent rollback fail):
DO $$
BEGIN
    SET LOCAL statement_timeout = '30s';   -- 沿用 risk_event_log.sql DO guard 体例
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'news_raw'
    ) THEN
        RAISE EXCEPTION 'news_raw 表 rollback 失败, 表仍存在 (检查 news_classified FK 是否已 drop)';
    END IF;
END $$;
