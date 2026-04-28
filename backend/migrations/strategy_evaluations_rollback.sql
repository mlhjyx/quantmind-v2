-- MVP 3.5.1 rollback — strategy_evaluations 紧急退役
-- 配对: strategy_evaluations.sql
--
-- ⚠️ 警告: 删除审计历史. 仅用于 schema 不可挽回错误时. 生产前必先 backup.
-- 正常流程: update_status(LIVE) 守门只读, 删表会让所有 LIVE 升迁失败 (fail-loud,
-- 符合 MVP 3.5.1 设计意图 — 没评估表就不能升 LIVE).

-- 叶子表确认 (reviewer P2 2026-04-28 PR #126):
-- strategy_evaluations 是审计 leaf 表, 无下游 FK 依赖 (没有其他表 REFERENCES strategy_evaluations).
-- 故 DROP TABLE 不需 CASCADE — 下面顺序 (DROP INDEX → DROP TABLE) 干净安全.
-- 若未来新增子表 FK 到本表, 此 rollback 须升级为 DROP TABLE ... CASCADE 或显式 DROP 子表.

DROP INDEX IF EXISTS idx_strategy_evaluations_strategy_latest;
DROP TABLE IF EXISTS strategy_evaluations;
