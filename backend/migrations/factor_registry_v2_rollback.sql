-- MVP 1.3a rollback: 撤销 factor_registry schema 扩展
-- 只在 emergency 需要时手动跑. 正常流程不调.
--
-- 影响: 删 pool / ic_decay_ratio 两字段 + 2 个索引
-- 注意: 如果这两列已有业务数据, 此 rollback 会永久丢数据.

DROP INDEX IF EXISTS idx_factor_registry_pool;
DROP INDEX IF EXISTS idx_factor_registry_status;

ALTER TABLE factor_registry DROP COLUMN IF EXISTS pool;
ALTER TABLE factor_registry DROP COLUMN IF EXISTS ic_decay_ratio;
