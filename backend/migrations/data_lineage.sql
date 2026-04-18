-- MVP 2.2 Sub2: data_lineage 通用血缘表 (Blueprint U3 / 铁律 17+30 配套)
--
-- 目的: 跨表统一血缘存储 (factor_values / signals / orders / backtest_run),
--       通过 JSONB 记录源数据引用 + git commit + 计算参数, 支持反向追溯.
-- 策略: 外挂表, 不动 165GB factor_values 主表 (P0-1.5 决策一致).
--       `lineage_data` JSONB 序列化 Lineage dataclass (schema_version=1).
--       反查走 GIN 索引 + JSONB containment operator (@>).
--
-- 不做 (明确推后续):
--   - MVP 2.2 只埋 DataPipeline 通道, signals/orders/backtest_run 走 MVP 3.2/3.3/2.3
--   - backfill 老数据血缘 (工程量爆炸), 只对本 MVP 上线后新数据埋点
--
-- 执行:
--   psql -h localhost -p 5432 -U xin -d quantmind_v2 -f backend/migrations/data_lineage.sql

BEGIN;

CREATE TABLE IF NOT EXISTS data_lineage (
    lineage_id   UUID         PRIMARY KEY,
    lineage_data JSONB        NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lineage_created_at
    ON data_lineage (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lineage_jsonb_gin
    ON data_lineage USING GIN (lineage_data);

COMMENT ON TABLE  data_lineage IS 'MVP 2.2 U3 Data Lineage: 通用血缘表, JSONB 序列化 Lineage dataclass';
COMMENT ON COLUMN data_lineage.lineage_id   IS 'UUID PK (Lineage.lineage_id, 客户端 uuid4 生成)';
COMMENT ON COLUMN data_lineage.lineage_data IS 'Lineage dataclass 序列化 (schema_version/inputs/code/params/timestamp/parent_lineage_ids/outputs)';
COMMENT ON COLUMN data_lineage.created_at   IS '入库时间 (DB 端 NOW(), 与 Lineage.timestamp 计算端时间对照)';

-- 验证
DO $$
DECLARE
    n_rows INT;
BEGIN
    SELECT COUNT(*) INTO n_rows FROM data_lineage;
    RAISE NOTICE 'data_lineage ready: rows=%', n_rows;
END $$;

COMMIT;
