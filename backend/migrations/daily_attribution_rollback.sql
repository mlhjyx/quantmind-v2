-- MVP 4.2 sub-iter 7 (iter 65) — daily_attribution rollback
-- 配对: daily_attribution.sql
-- 用法: psql -f daily_attribution_rollback.sql (rollback 验证用; production 慎用)

DROP INDEX IF EXISTS idx_daily_attribution_residual_abs;
DROP INDEX IF EXISTS idx_daily_attribution_trade_date;
DROP INDEX IF EXISTS idx_daily_attribution_strategy_date;

DROP TABLE IF EXISTS daily_attribution;
