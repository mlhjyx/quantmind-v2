-- MVP 3.5.1 rollback — strategy_evaluations 紧急退役
-- 配对: strategy_evaluations.sql
--
-- ⚠️ 警告: 删除审计历史. 仅用于 schema 不可挽回错误时. 生产前必先 backup.
-- 正常流程: update_status(LIVE) 守门只读, 删表会让所有 LIVE 升迁失败 (fail-loud,
-- 符合 MVP 3.5.1 设计意图 — 没评估表就不能升 LIVE).

DROP INDEX IF EXISTS idx_strategy_evaluations_strategy_latest;
DROP TABLE IF EXISTS strategy_evaluations;
