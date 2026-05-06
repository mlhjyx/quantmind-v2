-- Sprint 2 sub-PR 7b.1 rollback: DROP news_classified 表 + COMMENT.
-- 沿用 PR #223 llm_cost_daily_rollback.sql + risk_event_log_rollback.sql 体例 (DROP TABLE IF EXISTS 幂等).
-- 关联: 2026_05_06_news_classified.sql
--
-- ⚠️ Sequential rollback order (FK natural pairing sustained):
--   sub-PR 7b.1 cumulative rollback 真序列:
--   1. news_classified rollback (本 file, FK child, drops first ✅)
--   2. news_raw rollback (FK parent, drops 2nd)
--
--   本 file 走 child 真先 drop, 反 news_raw FK 依赖触发 ERROR.

BEGIN;

DROP TABLE IF EXISTS news_classified;

COMMIT;

-- 验证 (反 silent rollback fail):
DO $$
BEGIN
    SET LOCAL statement_timeout = '30s';   -- 沿用 risk_event_log.sql DO guard 体例
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'news_classified'
    ) THEN
        RAISE EXCEPTION 'news_classified 表 rollback 失败, 表仍存在';
    END IF;
END $$;
