--- V3 §5.4 Risk Memory RAG (Tier B) — risk_memory DDL (TB-3a foundation)
---
--- 用途: 每个 risk_event_log 触发后, 经 RiskReflectorAgent (Tier B TB-4) 反思后
---       sediment lesson + context_snapshot + outcome + BGE-M3 embedding 入此表.
---       L1 触发时 RiskMemoryRAG.retrieve (TB-3c) 走 vector similarity search 取相似
---       历史事件 → push 内容含 "类似情况 N 次, 做 X 动作, 平均结果 Y" 决策辅助.
---
--- 变更:
---   1. NEW TABLE risk_memory (V3 §5.4 line 693-708 schema 1:1)
---   2. ivfflat index for embedding cosine similarity search (pgvector v0.8.2)
---      lists=100 conservative default — pgvector docs recommend lists = sqrt(N)
---      for N rows; 100 hits ~10000 rows sweet spot. Re-tune at TB-5 if needed.
---   3. composite index on (event_type, event_timestamp DESC) for time-range
---      filtered retrieval per V3 §5.4 line 707.
---
--- Rollback: 2026_05_14_risk_memory_rollback.sql
---
--- 关联: V3 §5.4 line 693-708 (Risk Memory RAG DDL spec) +
---       ADR-022 (反 retroactive edit) / ADR-064 D2 (BGE-M3 1024 维 sustained) /
---       ADR-067 (TB-2 closure cumulative) / ADR-068 候选 (TB-3 sprint)
--- 铁律 17 (DataPipeline 入库) / 22 (doc 跟随代码) / 41 (timezone TIMESTAMPTZ)
--- Prereq: pgvector v0.8.2 installed 2026-05-14 (Session 53+19 Phase B closure).

BEGIN;

-- Verify pgvector extension is loaded (defensive — should be installed per
-- Session 53+19 Phase B). 反 silent table creation without vector type support.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension not installed — run CREATE EXTENSION vector first '
                        '(see docs/runbook/cc_automation/v3_tb_3_pgvector_bge_m3_prereq_install.md)';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS risk_memory (
    memory_id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    symbol_id VARCHAR(20),
    event_timestamp TIMESTAMPTZ NOT NULL,
    context_snapshot JSONB NOT NULL,
    action_taken VARCHAR(50),
    outcome JSONB,
    lesson TEXT,
    embedding VECTOR(1024),  -- BGE-M3 1024-dim per ADR-064 D2 + Session 53+19 smoke verified
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_event_type_non_empty
        CHECK (event_type IS NOT NULL AND length(event_type) > 0),
    CONSTRAINT chk_action_taken_vocab
        CHECK (action_taken IS NULL OR action_taken IN (
            'STAGED_executed', 'STAGED_cancelled', 'STAGED_timeout_executed',
            'manual_sell', 'no_action', 'reentry'
        )),
    -- Reviewer-fix (PR pending #339 MEDIUM 1): defense-in-depth length CHECK
    -- mirroring chk_event_type_non_empty + chk_action_taken_vocab patterns.
    -- Python-side validation (interface.py RiskMemory.__post_init__) covers
    -- TB-3a repository writes, but raw SQL / future ETL bypass paths benefit
    -- from DB-level enforcement.
    CONSTRAINT chk_lesson_max_length
        CHECK (lesson IS NULL OR length(lesson) <= 500)
);

-- ivfflat index for vector cosine similarity search (V3 §5.4 line 706).
-- lists=100 conservative default — pgvector recommends sqrt(N) for N rows;
-- 100 ≈ sweet-spot for first 10K rows. Re-tune at TB-5c if needed.
-- WHERE embedding IS NOT NULL: partial index excludes pre-embedded rows
-- (e.g. rows inserted before TB-3b BGE-M3 wire, or batch-pending rows).
CREATE INDEX IF NOT EXISTS idx_risk_memory_embedding
    ON risk_memory
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100)
    WHERE embedding IS NOT NULL;

-- Composite index for event-type filtered + time-range retrieval per V3 §5.4 line 707.
CREATE INDEX IF NOT EXISTS idx_risk_memory_event_type
    ON risk_memory (event_type, event_timestamp DESC);

-- Symbol-filtered queries (e.g. retrieve memory for specific stock).
CREATE INDEX IF NOT EXISTS idx_risk_memory_symbol_ts
    ON risk_memory (symbol_id, event_timestamp DESC)
    WHERE symbol_id IS NOT NULL;

-- Reviewer sustained ADR-062 体例: COMMENT inside BEGIN/COMMIT
-- 反 partial migration state if DDL fails between COMMIT and COMMENT.
COMMENT ON TABLE risk_memory IS
    'V3 §5.4 Risk Memory RAG — sediment risk event lessons + BGE-M3 1024-dim embedding for similarity retrieval';
COMMENT ON COLUMN risk_memory.event_type IS
    'V3 §5.4 line 696: LimitDown/RapidDrop/IndustryCorrelated/GapDownOpen/VolumeSpike/etc. Open vocab — RAG retrieval filters by exact match.';
COMMENT ON COLUMN risk_memory.symbol_id IS
    'Symbol code (e.g. 600519.SH). NULL for market-wide events (CorrelatedDrop / regime shift).';
COMMENT ON COLUMN risk_memory.context_snapshot IS
    'V3 §5.4 line 699: 触发时刻 L0+L1+L2 完整 snapshot (sentiment_24h / fundamental / regime / market_indicators / position / etc).';
COMMENT ON COLUMN risk_memory.action_taken IS
    'V3 §5.4 line 700 CHECK constrained 6 values: STAGED_executed/STAGED_cancelled/STAGED_timeout_executed/manual_sell/no_action/reentry. NULL = pre-action sediment (still pending RiskReflectorAgent review).';
COMMENT ON COLUMN risk_memory.outcome IS
    'V3 §5.4 line 701 JSONB: {1d_pnl, 5d_pnl, 30d_pnl, retrospective_correctness}. Backfilled by TB-4 RiskReflectorAgent post-event.';
COMMENT ON COLUMN risk_memory.lesson IS
    'TB-4 RiskReflectorAgent V4-Pro 5 维反思 sediment text (≤ 500 chars). Drives RAG retrieval semantic similarity ranking.';
COMMENT ON COLUMN risk_memory.embedding IS
    'BGE-M3 1024-dim vector of `lesson || context_summary` (TB-3b TB-3c). Populated post-RiskReflectorAgent reflection; NULL pre-embedding (excluded from ivfflat partial index).';

COMMIT;
