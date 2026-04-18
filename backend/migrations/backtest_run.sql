-- MVP 2.3 Sub1 · backtest_run ALTER 扩展 (ADR-007 决策, 沿用老表 schema)
--
-- 背景:
--   老 `backtest_run` 表已存在 (from docs/QUANTMIND_V2_DDL_FINAL.sql), 7 行研究历史 + 4 张 FK 依赖表
--   (backtest_daily_nav / backtest_holdings / backtest_trades / backtest_wf_windows).
--   MVP 2.3 设计稿 Session 5 末凭印象写新 schema, 实测冲突 → ADR-007 决策沿用老表 ALTER ADD 3 列.
--
-- 本 migration (ALTER 策略):
--   1. ADD COLUMN mode VARCHAR(16) IF NOT EXISTS (BacktestMode enum 执行模式)
--   2. ADD COLUMN lineage_id UUID FK data_lineage(lineage_id) IF NOT EXISTS (MVP 2.2 U3 集成)
--   3. ADD COLUMN extra_decimals NUMERIC[] IF NOT EXISTS (ColumnSpec decimal_array 扩展 metric)
--   4. ADD CONSTRAINT chk_backtest_run_mode (容忍老 7 行 NULL)
--
-- 不做 (明确推 MVP 3.x Clean-up):
--   - RENAME 字段 (config_yaml_hash → config_hash 等), tech debt 记入 ADR-007 Follow-up
--   - metrics JSONB 引入 (沿用老表独立 DECIMAL 列, 扩展走 extra_decimals)
--   - DROP / 重建 (方案 B/C 已在 ADR-007 Alternatives 否决)
--
-- 幂等: 多次执行安全 (IF NOT EXISTS + 约束名 UNIQUE 检查).
--
-- 执行:
--   psql -h localhost -p 5432 -U xin -d quantmind_v2 -f backend/migrations/backtest_run.sql
--
-- 关联铁律: 15 / 17 / 22 / 25 / 36 / 38
-- 关联 ADR: ADR-007 (本 migration 直接实施该决策)

BEGIN;

-- 前置: data_lineage 表必须存在 (MVP 2.2 Sub2)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'data_lineage') THEN
        RAISE EXCEPTION 'data_lineage 表不存在, 请先跑 backend/migrations/data_lineage.sql (MVP 2.2)';
    END IF;
END $$;

-- 前置: backtest_run 表必须存在 (老表, DDL_FINAL 建)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'backtest_run') THEN
        RAISE EXCEPTION 'backtest_run 表不存在, 请先跑 docs/QUANTMIND_V2_DDL_FINAL.sql 建表';
    END IF;
END $$;

-- 1-3. ALTER ADD 3 列 (IF NOT EXISTS 幂等, FK 另外独立守护)
-- PR A review fix (database-reviewer P1#1): lineage_id 不在此处 inline REFERENCES,
-- 避免 "部分状态下 column 已存在 + FK 丢失" 的 idempotency gap. FK 通过独立命名约束 + DO $ 守护.
ALTER TABLE backtest_run
    ADD COLUMN IF NOT EXISTS mode VARCHAR(16),
    ADD COLUMN IF NOT EXISTS lineage_id UUID,
    ADD COLUMN IF NOT EXISTS extra_decimals NUMERIC[];

-- 4. mode CHECK 约束 (独立 ADD, 约束名 UNIQUE 检查确保幂等)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_backtest_run_mode'
          AND conrelid = 'backtest_run'::regclass
    ) THEN
        ALTER TABLE backtest_run
            ADD CONSTRAINT chk_backtest_run_mode
            CHECK (mode IS NULL OR mode IN ('quick_1y', 'full_5y', 'full_12y', 'wf_5fold', 'live_pt'));
    END IF;
END $$;

-- 5. lineage_id FK 约束 (独立命名 + DO $ 守护, 独立幂等; review fix database-reviewer P1#1)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'backtest_run_lineage_id_fkey'
          AND conrelid = 'backtest_run'::regclass
    ) THEN
        ALTER TABLE backtest_run
            ADD CONSTRAINT backtest_run_lineage_id_fkey
            FOREIGN KEY (lineage_id) REFERENCES data_lineage(lineage_id);
    END IF;
END $$;

-- 6. lineage_id 索引 (partial, WHERE IS NOT NULL; review fix database-reviewer P1#2)
-- 项目铁律 "index FK", 防止未来 backtest_run 膨胀 (WF sweep 1000+ rows) + ON DELETE cascade 扫描性能
CREATE INDEX IF NOT EXISTS idx_backtest_run_lineage_id
    ON backtest_run (lineage_id)
    WHERE lineage_id IS NOT NULL;

-- 注释 (COMMENT ON COLUMN 幂等, 相同列多次 COMMENT 会覆盖)
COMMENT ON COLUMN backtest_run.mode           IS
    'MVP 2.3 Sub1 · BacktestMode enum: quick_1y/full_5y/full_12y/wf_5fold/live_pt. 老 7 行 NULL.';
COMMENT ON COLUMN backtest_run.lineage_id     IS
    'MVP 2.3 Sub1 · FK 到 data_lineage (MVP 2.2 U3 血缘追溯). 老 7 行 NULL.';
COMMENT ON COLUMN backtest_run.extra_decimals IS
    'MVP 2.3 Sub1 · 扩展 DECIMAL 指标 (沿用老表独立 DECIMAL 列为主, 本列预留未来 metric). 老 7 行 NULL.';

-- 验证
DO $$
DECLARE
    n_rows        INT;
    has_mode      BOOLEAN;
    has_lineage   BOOLEAN;
    has_extra     BOOLEAN;
BEGIN
    SELECT COUNT(*) INTO n_rows FROM backtest_run;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='backtest_run' AND column_name='mode') INTO has_mode;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='backtest_run' AND column_name='lineage_id') INTO has_lineage;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='backtest_run' AND column_name='extra_decimals') INTO has_extra;
    RAISE NOTICE 'backtest_run extended: rows=%, mode=%, lineage_id=%, extra_decimals=%',
        n_rows, has_mode, has_lineage, has_extra;
END $$;

COMMIT;
