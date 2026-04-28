-- MVP 3.5.1 — strategy_evaluations append-only history table
-- update_status(LIVE) 守门读最新 passed=True 行 + freshness check 防止
-- 跳过评估直接升 LIVE (跨 PR Follow-up from MVP 3.5 batch 3, 2026-04-28)
--
-- 依赖: strategy_registry (MVP 3.2 batch 1, strategy_registry.sql)
-- 配对: strategy_evaluations_rollback.sql

CREATE TABLE IF NOT EXISTS strategy_evaluations (
    id               BIGSERIAL PRIMARY KEY,

    -- ON DELETE RESTRICT: 评估历史是审计资产, 与 strategy_status_log 同等. 物理删除
    -- 策略前必先手工 clear evaluations + status_log.
    strategy_id      UUID NOT NULL REFERENCES strategy_registry(strategy_id) ON DELETE RESTRICT,

    -- Verdict.passed (PlatformStrategyEvaluator 输出 / G1'+G2'+G3' 全过)
    passed           BOOLEAN NOT NULL,

    -- Verdict.blockers (string array, 未过 Gate ID e.g. ["G1prime_sharpe_bootstrap"])
    blockers         JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Verdict.p_value (paired bootstrap p, 可空若评估非统计类)
    p_value          DOUBLE PRECISION,

    -- Verdict.details (full report e.g. evaluation_years / decision / gate-level details)
    details          JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 评估器 class name (审计 + 未来支持多评估器并存)
    evaluator_class  TEXT NOT NULL,

    -- 评估时间 (timestamptz, 铁律 41 — UTC 内部存储)
    evaluated_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE strategy_evaluations IS
    'MVP 3.5.1 — Strategy 评估历史 append-only. update_status(LIVE) 守门读最新行 + freshness check (默认 30 天). PR cross-follow-up from MVP 3.5 batch 3.';
COMMENT ON COLUMN strategy_evaluations.strategy_id IS 'FK strategy_registry.strategy_id, ON DELETE RESTRICT 保审计';
COMMENT ON COLUMN strategy_evaluations.passed IS 'Verdict.passed — True 当且仅当 G1prime+G2prime+G3prime 全过';
COMMENT ON COLUMN strategy_evaluations.blockers IS 'JSONB string array, 未过 Gate ID 列表 (e.g. ["G1prime_sharpe_bootstrap","G3prime_regression_max_diff"])';
COMMENT ON COLUMN strategy_evaluations.p_value IS 'paired bootstrap p, NULL 若评估非统计类 (e.g. sim_to_real_check)';
COMMENT ON COLUMN strategy_evaluations.details IS 'Verdict.details JSONB — 含 evaluation_years / decision / per-gate breakdown';
COMMENT ON COLUMN strategy_evaluations.evaluator_class IS '评估器 class name, e.g. PlatformStrategyEvaluator';
COMMENT ON COLUMN strategy_evaluations.evaluated_at IS 'UTC timestamp, 铁律 41 — 内部存 UTC, 展示层转 Asia/Shanghai';

-- 主查询: "拿 strategy_id X 最新评估" — WHERE strategy_id=? ORDER BY evaluated_at DESC, id DESC LIMIT 1
-- (id DESC 是 evaluated_at 同毫秒 tie-breaker)
CREATE INDEX IF NOT EXISTS idx_strategy_evaluations_strategy_latest
    ON strategy_evaluations (strategy_id, evaluated_at DESC, id DESC);

-- 验证 (注释, 迁移后手工跑) ─────────────────────────────────────
-- SELECT COUNT(*) FROM strategy_evaluations;  -- 预期 0 rows (首次 migration 后)
-- \d+ strategy_evaluations
-- EXPLAIN (ANALYZE) SELECT passed, blockers, evaluated_at
--   FROM strategy_evaluations WHERE strategy_id = '...'
--   ORDER BY evaluated_at DESC, id DESC LIMIT 1;
