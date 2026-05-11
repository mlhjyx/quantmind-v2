--- V3 §S8 L4 STAGED 决策权 — execution_plans DDL (S8 sub-PR 8a, 2026-05-11)
---
--- 用途: STAGED 执行计划存储, 含 L4 状态机 (PENDING_CONFIRM→CONFIRMED/CANCELLED/TIMEOUT_EXECUTED).
---
--- 变更:
---   1. NEW TABLE execution_plans (V3 §7.5 schema)
---   2. TimescaleDB hypertable (chunk 1 day, 180 day retention)
---   3. Index on (status, cancel_deadline) for pending confirm sweep
---
--- Rollback: 2026_05_11_execution_plans_rollback.sql
---
--- 关联: V3 §7.5 / ADR-027 §2 / 铁律 22

BEGIN;

CREATE TABLE IF NOT EXISTS execution_plans (
    plan_id UUID DEFAULT gen_random_uuid(),
    triggered_by_event_id BIGINT,
    CONSTRAINT execution_plans_plan_id_unique UNIQUE (plan_id, created_at),
    mode TEXT NOT NULL CHECK (mode IN ('OFF', 'STAGED', 'AUTO')),
    symbol_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('SELL', 'HOLD', 'BATCH')),
    qty INT NOT NULL CHECK (qty > 0),
    limit_price NUMERIC(10, 4),
    batch_index INT DEFAULT 1,
    batch_total INT DEFAULT 1,
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cancel_deadline TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_CONFIRM'
        CHECK (status IN ('PENDING_CONFIRM', 'CONFIRMED', 'CANCELLED', 'TIMEOUT_EXECUTED', 'EXECUTED', 'FAILED')),
    user_decision TEXT CHECK (user_decision IN ('confirm', 'cancel', 'modify', 'timeout')),
    user_decision_at TIMESTAMPTZ,
    broker_order_id TEXT,
    broker_fill_status INT,
    risk_reason TEXT,
    risk_metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- TimescaleDB hypertable (1-day chunks)
SELECT create_hypertable(
    'execution_plans', 'created_at',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Index for pending confirm sweep (cancel_deadline expiry check)
CREATE INDEX IF NOT EXISTS idx_exec_plans_status_deadline
    ON execution_plans (status, cancel_deadline)
    WHERE status = 'PENDING_CONFIRM';

-- Index for query by symbol + status
CREATE INDEX IF NOT EXISTS idx_exec_plans_symbol_status
    ON execution_plans (symbol_id, status, created_at DESC);

-- 180 day retention
SELECT add_retention_policy(
    'execution_plans', INTERVAL '180 days',
    if_not_exists => TRUE
);

COMMIT;

COMMENT ON TABLE execution_plans IS 'S8 L4 STAGED 执行计划 (V3 §7.5, ADR-027)';
COMMENT ON COLUMN execution_plans.mode IS 'OFF=立即执行 / STAGED=30min 反向决策 / AUTO=全自动(保留)';
COMMENT ON COLUMN execution_plans.status IS 'PENDING_CONFIRM→CONFIRMED/CANCELLED/TIMEOUT_EXECUTED→EXECUTED/FAILED';
COMMENT ON COLUMN execution_plans.cancel_deadline IS 'STAGED 反向决策截止时间, 超时→TIMEOUT_EXECUTED';
COMMENT ON COLUMN execution_plans.risk_reason IS '触发风险原因 (RuleResult.reason 文字)';
COMMENT ON COLUMN execution_plans.risk_metrics IS '触发时刻风险指标 (RuleResult.metrics JSON)';
