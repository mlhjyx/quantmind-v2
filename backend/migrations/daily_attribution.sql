-- MVP 4.2 sub-iter 7 (iter 65) — Performance Attribution daily row persistence
-- Backs DailyAttribution dataclass (backend/qm_platform/eval/attribution.py).
-- Daily Beat task `daily-attribution-compute` writes one row per
-- (trade_date, strategy_id, execution_mode) tuple after PT signal/exec phase.
--
-- 配对: daily_attribution_rollback.sql
-- 设计稿: docs/mvp/MVP_4_2_attribution.md §2 dataclass spec + §4 sub-iter 7
-- 沿用体例: strategy_evaluations.sql (BIGSERIAL pk + JSONB + idx + DEFENSIVE ALTER)

CREATE TABLE IF NOT EXISTS daily_attribution (
    id                     BIGSERIAL PRIMARY KEY,

    -- Composite uniqueness (trade_date, strategy_id, execution_mode) supports
    -- paper/live parallel rows for same strategy.
    trade_date             DATE NOT NULL,
    strategy_id            VARCHAR(64) NOT NULL,
    execution_mode         VARCHAR(16) NOT NULL DEFAULT 'paper'
        CHECK (execution_mode IN ('paper', 'live')),

    -- DailyAttribution.nav_change_pct (decimal fraction, 0.012 = 1.20%)
    nav_change_pct         DOUBLE PRECISION NOT NULL,

    -- DailyAttribution.by_factor / by_sector / by_cost (dict[str, float]) → JSONB
    -- DailyAttribution.by_regime (RegimeInfo dataclass) → JSONB
    by_factor_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    by_sector_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    by_regime_json         JSONB,
    by_cost_json           JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- alpha_vs_benchmark (excess vs CSI300/CSI500/等权)
    alpha_vs_benchmark     DOUBLE PRECISION NOT NULL DEFAULT 0.0,

    -- unexplained_residual (sentinel for AlertRouter dispatch — fire_residual_alert)
    unexplained_residual   DOUBLE PRECISION NOT NULL DEFAULT 0.0,

    -- Row creation timestamp (UTC, 铁律 41).
    created_at             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- UPSERT key: same (trade_date, strategy_id, execution_mode) re-write
    -- (e.g. mid-day re-compute after data correction) updates same row.
    UNIQUE (trade_date, strategy_id, execution_mode)
);

COMMENT ON TABLE daily_attribution IS
    'MVP 4.2 — Daily performance attribution one row per (trade_date, strategy_id, execution_mode). Beat task daily-attribution-compute writes after PT exec phase (16:30 Mon-Fri).';
COMMENT ON COLUMN daily_attribution.execution_mode IS 'paper or live (V3 红线 namespace).';
COMMENT ON COLUMN daily_attribution.nav_change_pct IS 'Decimal fraction NAV change (0.012 = 1.20%, 12 bps).';
COMMENT ON COLUMN daily_attribution.by_factor_json IS 'Per-factor Brinson contributions (compute_by_factor output).';
COMMENT ON COLUMN daily_attribution.by_sector_json IS 'Per-sector industry contributions (compute_by_sector output).';
COMMENT ON COLUMN daily_attribution.by_regime_json IS 'HMM 3-state RegimeInfo (compute_by_regime output): {detected, expected_perf_bps, actual_perf_bps}.';
COMMENT ON COLUMN daily_attribution.by_cost_json IS 'Per-cost-category contributions (compute_by_cost output, negative values).';
COMMENT ON COLUMN daily_attribution.alpha_vs_benchmark IS 'Excess return vs CSI300/CSI500/等权 (default 0.0 until benchmark wired).';
COMMENT ON COLUMN daily_attribution.unexplained_residual IS 'Model-unexplained variance (fire_residual_alert threshold = 20 bps default).';
COMMENT ON COLUMN daily_attribution.created_at IS 'UTC timestamp, 铁律 41.';

-- Primary query: "latest N trade_dates for strategy X"
--   WHERE strategy_id=? AND execution_mode=? ORDER BY trade_date DESC LIMIT 30
CREATE INDEX IF NOT EXISTS idx_daily_attribution_strategy_date
    ON daily_attribution (strategy_id, execution_mode, trade_date DESC);

-- Time-range query: "all rows for trade_date X" (cross-strategy snapshot)
CREATE INDEX IF NOT EXISTS idx_daily_attribution_trade_date
    ON daily_attribution (trade_date DESC);

-- Residual alert tail query (top high-residual days)
CREATE INDEX IF NOT EXISTS idx_daily_attribution_residual_abs
    ON daily_attribution (ABS(unexplained_residual) DESC)
    WHERE ABS(unexplained_residual) > 0.002;  -- > 20 bps (default threshold)

-- ── Defensive ALTER (幂等, 沿用 strategy_evaluations.sql 体例) ──
DO $$
BEGIN
    -- execution_mode CHECK constraint (升级旧环境)
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'daily_attribution'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%execution_mode%paper%live%'
    ) THEN
        ALTER TABLE daily_attribution
            ADD CONSTRAINT daily_attribution_execution_mode_check
            CHECK (execution_mode IN ('paper', 'live'));
    END IF;
END $$;

-- 验证 (注释, migration 后手工跑) ─────────────────────────────────────
-- SELECT COUNT(*) FROM daily_attribution;  -- 预期 0 rows (首次)
-- \d+ daily_attribution
-- EXPLAIN (ANALYZE) SELECT trade_date, nav_change_pct, unexplained_residual
--   FROM daily_attribution
--   WHERE strategy_id = 'paper-strategy-uuid' AND execution_mode = 'paper'
--   ORDER BY trade_date DESC LIMIT 30;
