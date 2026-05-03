-- S2.3 · LLM Audit Trail — llm_call_log 单行 per call audit log
--
-- 目标 (V3 §16.2 + ADR-031 §6 + 决议 4 沿用):
--   每次 BudgetAwareRouter.completion 真 1 INSERT 真 audit row, decision_id chain 真复现性
--
-- 设计原则:
--   - 幂等 (CREATE TABLE/INDEX IF NOT EXISTS + create_hypertable if_not_exists=TRUE)
--   - TimescaleDB hypertable, 按 triggered_at 月度 partition
--   - 180 天 retention (决议 4 沿用 — 5-10 年累计 ~200K-550K rows / ~40-110MB)
--   - 14 字段 (含 id auto-gen UUID + decision_id NULL 允许 — 决议 6 反 break 老 caller)
--   - prompt_hash sha256 truncated 16 hex (决议 5 反 md5 collision)
--
-- 沿用体例:
--   - risk_event_log.sql (4-phase + DO guard + composite PK)
--   - 决议 6: decision_id NULL 允许 (反 break)
--   - 决议 7: error_class NULL on success / class name on failure (铁律 33 fail-loud)
--
-- TimescaleDB 事务语义 (沿用 risk_event_log.sql reviewer P0):
--   create_hypertable / add_retention_policy 真 non-transactional catalog ops,
--   不能包在 BEGIN/COMMIT 内. 沿用 partial-transaction pattern.
--
-- Rollback: 2026_05_03_llm_call_log_rollback.sql (DROP TABLE CASCADE).
-- 关联铁律: 22 (文档跟随代码) / 33 (fail-loud migration) / 41 (timezone)

-- pgcrypto 已由 risk_event_log.sql + knowledge_registry.sql 启用 (PG 13+ 内置, 幂等)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────
-- Phase 1: CREATE TABLE (原子事务, 失败自动 ROLLBACK)
-- ─────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS llm_call_log (
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- task CHECK constraint 真**保留** (沿用 reviewer Chunk B P2-1 修真意图 cite):
    -- (a) fail-loud DB-level (反 application-layer silent invalid INSERT, 沿用铁律 33)
    -- (b) 7 task 真 V3 §5.5 sediment + RiskTaskType StrEnum SSOT
    --     (backend/qm_platform/llm/types.py::RiskTaskType, value 真**lowercase 已对齐**)
    -- (c) 加新 task 真**重大架构改动** (跟 V3 §5.5 真协同), ALTER TABLE 真**ADR 真审议** 通过.
    -- 反 risk_event_log.code (无 CHECK, application 验证) — 真**两 SOC**:
    --   risk_event_log.code 真**应用层多变** (rule_id sustained) → 走 application 验证;
    --   llm_call_log.task 真**架构层 stable** (V3 §5.5 真 7 enum sediment) → 走 DB CHECK.
    task            VARCHAR(40) NOT NULL
                    CHECK (task IN (
                        'news_classify',
                        'fundamental_summarize',
                        'bull_agent',
                        'bear_agent',
                        'judge',
                        'risk_reflector',
                        'embedding'
                    )),
    primary_alias   VARCHAR(40) NOT NULL,           -- TASK_TO_MODEL_ALIAS cite
    actual_model    VARCHAR(80) NOT NULL,           -- LiteLLM 真返 model 名
    is_fallback     BOOLEAN NOT NULL DEFAULT FALSE,
    -- budget_state 真值跟 BudgetState StrEnum SSOT 对齐 (沿用 reviewer Chunk B P2-2 修):
    --   backend/qm_platform/llm/budget.py::BudgetState (value 'normal'/'warn_80'/'capped_100' lowercase)
    --   StrEnum.value 真**lowercase 已实测** (PR #223 sediment, 38 tests verify).
    budget_state    VARCHAR(12) NOT NULL
                    CHECK (budget_state IN ('normal', 'warn_80', 'capped_100')),
    tokens_in       INTEGER NOT NULL DEFAULT 0
                    CHECK (tokens_in >= 0),
    tokens_out      INTEGER NOT NULL DEFAULT 0
                    CHECK (tokens_out >= 0),
    cost_usd        NUMERIC(8,4) NOT NULL DEFAULT 0
                    CHECK (cost_usd >= 0),
    latency_ms      INTEGER,                        -- NULL 允许
    decision_id     VARCHAR(64),                    -- NULL 允许 (决议 6, 反 break 老 caller)
    prompt_hash     VARCHAR(64),                    -- NULL 允许 (决议 5, sha256 truncated 16 hex)
    error_class     VARCHAR(40),                    -- NULL on success / class name on failure (铁律 33)

    -- PK 含 triggered_at (TimescaleDB hypertable 硬要求, 沿用 risk_event_log.sql 体例)
    -- id 通过 gen_random_uuid() 全局唯一 (UUID v4 概率意义)
    PRIMARY KEY (id, triggered_at)
);

COMMENT ON TABLE llm_call_log IS
    'S2.3 LLM Audit Trail — runtime audit log per BudgetAwareRouter.completion. 13 字段含 decision_id chain 真复现性. 180 天 TimescaleDB retention. 关联 backend/qm_platform/llm/audit.py::LLMCallLogger.';

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: Hypertable 转换 + retention (non-transactional, 必在 BEGIN/COMMIT 外)
-- 沿用 risk_event_log.sql reviewer P2-5: statement_timeout guard 防 catalog 锁 hang
-- ─────────────────────────────────────────────────────────────

SET statement_timeout = '60s';

SELECT create_hypertable(
    'llm_call_log', 'triggered_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

-- add_retention_policy: 180 天 (决议 4 — 5-10 年累计 ~40-110MB, 季度审计 + 月度 review backref)
SELECT add_retention_policy(
    'llm_call_log',
    INTERVAL '180 days',
    if_not_exists => TRUE
);

SET statement_timeout = DEFAULT;

-- ─────────────────────────────────────────────────────────────
-- Phase 3: Indexes (必在 hypertable 转换后, TimescaleDB 自动传播至所有 chunks)
-- ─────────────────────────────────────────────────────────────

-- 按 task 分桶时间序列查询 (daily aggregate report 真主路径)
CREATE INDEX IF NOT EXISTS ix_llm_call_log_task_time
    ON llm_call_log (task, triggered_at DESC);

-- decision_id chain trace (LL-103 SOP-5 #4 caller traceable, partial 反 NULL 噪声)
CREATE INDEX IF NOT EXISTS ix_llm_call_log_decision_id
    ON llm_call_log (decision_id)
    WHERE decision_id IS NOT NULL;

-- budget_state 时间序列查询 (WARN_80 / CAPPED_100 命中分布分析)
CREATE INDEX IF NOT EXISTS ix_llm_call_log_budget_state
    ON llm_call_log (budget_state, triggered_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Phase 4: Migration fail-loud guard (铁律 33)
-- 沿用 risk_event_log.sql Phase 4 体例
-- ─────────────────────────────────────────────────────────────

DO $$
DECLARE
    col_count INT;
    hypertable_exists BOOL;
    retention_job_count INT;
BEGIN
    SET LOCAL statement_timeout = '30s';

    -- 核心列存在性 (14 列, 沿用 reviewer Chunk B P1 修)
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'llm_call_log'
      AND column_name IN (
          'id', 'triggered_at', 'task', 'primary_alias', 'actual_model',
          'is_fallback', 'budget_state',
          'tokens_in', 'tokens_out', 'cost_usd', 'latency_ms',
          'decision_id', 'prompt_hash', 'error_class'
      );
    IF col_count < 14 THEN
        RAISE EXCEPTION 'llm_call_log migration incomplete: only % of 14 required columns', col_count;
    END IF;

    -- hypertable 已转换
    SELECT EXISTS(
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'llm_call_log'
    ) INTO hypertable_exists;
    IF NOT hypertable_exists THEN
        RAISE EXCEPTION 'llm_call_log hypertable conversion failed';
    END IF;

    -- retention policy 已注册 (proc_name='policy_retention' verified on TimescaleDB 2.26)
    SELECT COUNT(*) INTO retention_job_count
    FROM timescaledb_information.jobs
    WHERE hypertable_name = 'llm_call_log'
      AND proc_name = 'policy_retention';
    IF retention_job_count < 1 THEN
        RAISE EXCEPTION 'llm_call_log retention policy not registered';
    END IF;
END $$;
