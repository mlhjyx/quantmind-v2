-- S2.3 rollback: DROP llm_call_log 表 + 验证.
-- 沿用 2026_05_03_llm_cost_daily_rollback.sql + risk_event_log_rollback.sql 体例 (DROP TABLE IF EXISTS 幂等).
-- 关联: 2026_05_03_llm_call_log.sql

BEGIN;

DROP TABLE IF EXISTS llm_call_log CASCADE;

COMMIT;

-- 验证 (反 silent rollback fail):
DO $$
BEGIN
    SET LOCAL statement_timeout = '30s';   -- 沿用 risk_event_log_rollback.sql DO guard 体例
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'llm_call_log'
    ) THEN
        RAISE EXCEPTION 'llm_call_log 表 rollback 失败, 表仍存在';
    END IF;
END $$;
