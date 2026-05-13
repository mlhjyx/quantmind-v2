--- V3 §13.2 元监控 risk_metrics_daily 表 — S10 paper-mode 5d 元监控 (2026-05-13)
---
--- 用途: 每日聚合 V3 §13.1 SLA 5 指标 + L0/L1/L2/L4/L5 KPI + 总成本.
--- 由 scripts/v3_paper_mode_5d_extract_metrics.py 日终聚合写入,
--- 由 scripts/v3_paper_mode_5d_verify_report.py 5d 末读取 + 验收 V3 §15.4.
---
--- 变更:
---   1. NEW TABLE risk_metrics_daily (V3 §13.2 schema 1:1)
---   2. Index on date DESC for verify report lookups
---
--- Rollback: 2026_05_13_risk_metrics_daily_rollback.sql
---
--- 关联: V3 §13.1/§13.2/§15.4 + ADR-062 NEW (S10 setup) + 铁律 22

BEGIN;

CREATE TABLE IF NOT EXISTS risk_metrics_daily (
    date DATE PRIMARY KEY,
    -- L0 metrics
    news_ingested_count INT DEFAULT 0,
    news_source_failures JSONB DEFAULT '{}'::jsonb,  -- {source: failure_count}
    fundamental_ingest_success_rate NUMERIC(5, 4),
    -- L1 metrics
    alerts_p0_count INT DEFAULT 0,
    alerts_p1_count INT DEFAULT 0,
    alerts_p2_count INT DEFAULT 0,
    detection_latency_p50_ms INT,
    detection_latency_p99_ms INT,
    -- L2 metrics
    sentiment_calls_count INT DEFAULT 0,
    sentiment_avg_cost NUMERIC(8, 4),
    rag_retrievals_count INT DEFAULT 0,
    -- L4 metrics
    staged_plans_count INT DEFAULT 0,
    staged_executed_count INT DEFAULT 0,
    staged_cancelled_count INT DEFAULT 0,
    staged_timeout_executed_count INT DEFAULT 0,
    auto_triggered_count INT DEFAULT 0,
    -- L5 metrics
    reflector_weekly_completed BOOLEAN DEFAULT FALSE,
    reflector_lessons_added INT DEFAULT 0,
    -- 总成本
    llm_cost_total NUMERIC(8, 4) DEFAULT 0,
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_metrics_date_desc
    ON risk_metrics_daily (date DESC);

COMMIT;

COMMENT ON TABLE risk_metrics_daily IS
    'V3 §13.2 元监控 — 风控系统自身 KPI 日聚合 (S10 paper-mode 5d + 持续元监控)';
COMMENT ON COLUMN risk_metrics_daily.detection_latency_p99_ms IS
    'V3 §13.1 SLA: L1 detection P99 < 5000ms (5s)';
COMMENT ON COLUMN risk_metrics_daily.staged_timeout_executed_count IS
    'V3 §7.5 STAGED 30min cancel_deadline 超时默认执行 (反向决策权)';
COMMENT ON COLUMN risk_metrics_daily.llm_cost_total IS
    'V3 §16.2 月预算 ≤ $50/月 → 日均 ≤ $1.67 (5d 累计 ≤ $8.35)';
