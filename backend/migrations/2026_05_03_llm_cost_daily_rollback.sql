-- S2.2 rollback: DROP llm_cost_daily 表 + COMMENT.
-- 沿用 risk_event_log_rollback.sql 体例 (DROP TABLE IF EXISTS 幂等).
-- 关联: 2026_05_03_llm_cost_daily.sql

BEGIN;

DROP TABLE IF EXISTS llm_cost_daily;

COMMIT;

-- 验证 (反 silent rollback fail):
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'llm_cost_daily'
    ) THEN
        RAISE EXCEPTION 'llm_cost_daily 表 rollback 失败, 表仍存在';
    END IF;
END $$;
