-- MVP 1.3a: factor_registry schema 扩展
-- 加 pool (生命周期池) + ic_decay_ratio (MVP A factor_lifecycle 需要)
--
-- 幂等: IF NOT EXISTS 保护
-- 回滚: 见 backend/migrations/factor_registry_v2_rollback.sql
--
-- 关联:
--   - Blueprint Part 2 Framework #2 Factor
--   - MVP 1.1 interface.py FactorMeta 对齐
--   - MVP 1.2a DAL read_registry SQL 依赖

ALTER TABLE factor_registry
    ADD COLUMN IF NOT EXISTS pool VARCHAR(30) NOT NULL DEFAULT 'CANDIDATE';

ALTER TABLE factor_registry
    ADD COLUMN IF NOT EXISTS ic_decay_ratio NUMERIC(6, 4);

COMMENT ON COLUMN factor_registry.pool IS
    'MVP 1.3a 生命周期池: CORE(PT生产)/PASS(候选)/CANDIDATE(新提交)/INVALIDATED(证伪)/DEPRECATED(退役)/LEGACY(遗留)';
COMMENT ON COLUMN factor_registry.ic_decay_ratio IS
    'MVP 1.3a 近期 IC / 历史 IC 绝对值比 (factor_lifecycle 衰减判定用, <0.5 → WARNING)';

CREATE INDEX IF NOT EXISTS idx_factor_registry_pool
    ON factor_registry (pool);

CREATE INDEX IF NOT EXISTS idx_factor_registry_status
    ON factor_registry (status);
