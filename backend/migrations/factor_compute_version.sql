-- P0-1.5: factor_compute_version 外挂表 (DATA_SYSTEM_V1 §3.6, 决策 D1)
--
-- 目的: 零 schema 变更支持因子版本化/血缘/backfill, 满足铁律15 (回测可复现).
-- 策略: 外挂表, 不动 165GB factor_values 主表.
--
-- 使用:
--   1. 因子计算逻辑改变 → INSERT 新版本 v+1, UPDATE 旧版本 compute_end
--   2. 因子废弃 → 设置 compute_end, 不删历史数据
--   3. Backfill → JOIN 此表识别数据段用的算法版本
--
-- 执行:
--   psql -h localhost -p 5432 -U xin -d quantmind_v2 -f backend/migrations/factor_compute_version.sql

BEGIN;

CREATE TABLE IF NOT EXISTS factor_compute_version (
    factor_name     VARCHAR(60)  NOT NULL,
    version         SMALLINT     NOT NULL DEFAULT 1,
    compute_commit  VARCHAR(40),              -- git commit hash
    compute_start   DATE         NOT NULL,    -- 此版本生效起始交易日
    compute_end     DATE,                     -- NULL = 当前生效
    algorithm_desc  TEXT,                     -- 人工描述变化
    created_at      TIMESTAMP    DEFAULT NOW(),
    PRIMARY KEY (factor_name, version)
);

CREATE INDEX IF NOT EXISTS idx_fcv_factor_active
    ON factor_compute_version (factor_name)
    WHERE compute_end IS NULL;

COMMENT ON TABLE  factor_compute_version IS 'P0 DATA_SYSTEM_V1 D1: 因子版本化元数据, 外挂 factor_values 主表';
COMMENT ON COLUMN factor_compute_version.compute_commit IS 'git rev-parse HEAD, 40-char SHA-1';
COMMENT ON COLUMN factor_compute_version.compute_start IS '此算法版本首次生效的交易日 (inclusive)';
COMMENT ON COLUMN factor_compute_version.compute_end   IS 'NULL=仍生效; 非NULL=此日起被新版本替代 (inclusive)';

-- 初始化: 对 factor_values 中所有 distinct factor_name 写 v1 占位记录
-- compute_commit = 当前 HEAD, compute_start = 该 factor 最早出现日期
-- 跳过已有记录 (ON CONFLICT DO NOTHING)
INSERT INTO factor_compute_version (factor_name, version, compute_commit, compute_start, algorithm_desc)
SELECT
    fv.factor_name,
    1 AS version,
    '446cde566ba9e491056d81a7946de6ddceb46cfa' AS compute_commit,  -- commit at P0-1.5 build time
    MIN(fv.trade_date) AS compute_start,
    'P0-1.5 baseline snapshot (pre-versioning era, retrofitted)' AS algorithm_desc
FROM factor_values fv
GROUP BY fv.factor_name
ON CONFLICT (factor_name, version) DO NOTHING;

-- 验证
DO $$
DECLARE
    n_active INT;
    n_total INT;
BEGIN
    SELECT COUNT(*) INTO n_total FROM factor_compute_version;
    SELECT COUNT(*) INTO n_active FROM factor_compute_version WHERE compute_end IS NULL;
    RAISE NOTICE 'factor_compute_version: total=% active=%', n_total, n_active;
END $$;

COMMIT;
