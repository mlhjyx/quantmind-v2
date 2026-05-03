-- S2.2 sub-task PR (governance/s2-2-budget-guardrails): LLM 月度预算 daily aggregate
--
-- 目标 (V3 §20.1 #6 + ADR-031 §6 sediment):
--   月度 $50 LLM 预算 daily 聚合 → BudgetGuard 月聚合查询 + UPSERT 当日 row.
--   day PRIMARY KEY 自然按日切, 0 reset cron 必要 (CC plan-mode 确认).
--
-- 设计原则 (沿用 risk_event_log.sql 4-phase pattern):
--   - 幂等 (CREATE TABLE IF NOT EXISTS + DO block guard)
--   - 0 hypertable (年行数 <366, 体积 <1MB/年, 0 partition 必要)
--   - 0 retention (跨年累计保留, 月度 review V3 §16.2 + 年度审计依赖)
--   - CHECK 约束反 silent neg value (沿用 risk_event_log shares >= 0 体例)
--   - updated_at NOW() 反 silent stale row
--
-- BudgetGuard 消费 (backend/qm_platform/llm/budget.py):
--   - check(): SELECT SUM(cost_usd_total) WHERE day BETWEEN month_start AND today
--   - record_cost(): INSERT ... ON CONFLICT (day) DO UPDATE SET cost_usd_total = ... + EXCLUDED.cost_usd_total
--
-- Rollback: 2026_05_03_llm_cost_daily_rollback.sql (DROP TABLE IF EXISTS)
-- 关联铁律: 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud DO guard) / 34 (Config SSOT 走 Settings env var) / 38 (Blueprint)

-- ─────────────────────────────────────────────────────────────
-- Phase 1: CREATE TABLE (BEGIN/COMMIT 原子)
-- ─────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS llm_cost_daily (
    day            DATE        NOT NULL PRIMARY KEY,
    cost_usd_total NUMERIC(10, 4) NOT NULL DEFAULT 0  CHECK (cost_usd_total >= 0),
    call_count     INTEGER     NOT NULL DEFAULT 0     CHECK (call_count >= 0),
    fallback_count INTEGER     NOT NULL DEFAULT 0     CHECK (fallback_count >= 0),
    capped_count   INTEGER     NOT NULL DEFAULT 0     CHECK (capped_count >= 0),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE llm_cost_daily IS
    'S2.2 LLM 月度预算 daily aggregate. V3 §20.1 #6 ($50/月 + 80% warn + 100% Ollama fallback). '
    'BudgetGuard 走 INSERT ... ON CONFLICT(day) DO UPDATE 原子 UPSERT (沿用 feature_flag.py 体例). '
    'day PK 自然按日切 row, 0 reset cron 必要. 关联 ADR-031 + docs/LLM_IMPORT_POLICY.md §10.6.';

COMMENT ON COLUMN llm_cost_daily.cost_usd_total IS
    'NUMERIC(10,4): 上限 999,999.9999 USD, 远超 $50/月 × 12 月 × 100 倍 安全边际';
COMMENT ON COLUMN llm_cost_daily.fallback_count IS
    '走 qwen3-local fallback 真次数 (含 capped 强制 + provider 真异常 cascade)';
COMMENT ON COLUMN llm_cost_daily.capped_count IS
    '当日内 budget capped 状态触发计数 (state=CAPPED_100 进入 record_cost 时自增)';

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: 0 hypertable (S2.2 plan-mode 决议 — 行数 <366/年 不 partition)
-- Phase 3: 0 额外 index (day PK 自然 cover)
-- ─────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────────
-- Phase 4: Migration fail-loud guard (铁律 33, 沿用 risk_event_log.sql 体例)
-- ─────────────────────────────────────────────────────────────

DO $$
DECLARE
    col_count INT;
BEGIN
    SET LOCAL statement_timeout = '30s';

    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'llm_cost_daily'
      AND column_name IN ('day', 'cost_usd_total', 'call_count', 'fallback_count', 'capped_count', 'updated_at');
    IF col_count < 6 THEN
        RAISE EXCEPTION 'llm_cost_daily migration incomplete: only % of 6 required columns', col_count;
    END IF;

    -- PRIMARY KEY 验证 (UPSERT ON CONFLICT(day) 真依赖)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'llm_cost_daily' AND constraint_type = 'PRIMARY KEY'
    ) THEN
        RAISE EXCEPTION 'llm_cost_daily PRIMARY KEY 缺失 — UPSERT ON CONFLICT 真依赖';
    END IF;
END $$;
