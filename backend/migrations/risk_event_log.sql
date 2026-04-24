-- MVP 3.1 批 1 · Risk Framework — risk_event_log 统一事件表
--
-- 目标 (ADR-010 D4 + MVP 3.1 Batch 1 Plan §4):
--   替代 position_monitor + intraday_monitor_log + circuit_breaker_log 三表
--   (老表在批 3 完成后 DROP, 保留 1 sprint 作回滚锚点).
--
-- 设计原则:
--   - 幂等 (CREATE TABLE/INDEX IF NOT EXISTS + create_hypertable if_not_exists=TRUE)
--   - TimescaleDB hypertable, 按 triggered_at 月度 partition
--   - 90 天 retention (对齐 event_outbox 7d / log_rotate 7d 平衡, 触发事件回溯足够)
--   - 仅触发事件写入 (evaluations 不 log, 避免 55 次/日 × 11 规则 = 152K 行/年空 row 爆表)
--   - JSONB context_snapshot 单行 ~5-10KB (20+ positions + prices + portfolio state)
--     预计 ~1000 触发 rows/年 ≈ ~10MB/年, 90 天 ~2.5MB 活跃区
--
-- Rollback: risk_event_log_rollback.sql
-- 关联铁律: 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud migration) / 38 (Blueprint 真相源)

-- pgcrypto 已由 knowledge_registry.sql 启用 (PG 13+ 内置, CREATE EXTENSION 幂等)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────
-- risk_event_log — Risk Framework 统一事件日志
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS risk_event_log (
    id               UUID NOT NULL DEFAULT gen_random_uuid(),
    strategy_id      VARCHAR(100) NOT NULL,
    execution_mode   VARCHAR(10) NOT NULL
                     CHECK (execution_mode IN ('paper', 'live')),  -- ADR-008 namespace
    rule_id          VARCHAR(50) NOT NULL,                          -- "pms_l1" / "intraday_p3" / "cb_l2"
    severity         VARCHAR(10) NOT NULL
                     CHECK (severity IN ('p0', 'p1', 'p2', 'info')),
    triggered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code             VARCHAR(12) NOT NULL DEFAULT '',               -- "" = 组合级 (intraday_portfolio_drop)
    shares           INTEGER NOT NULL DEFAULT 0,                    -- sell 动作股数, alert_only=0
    reason           TEXT NOT NULL,                                  -- 人类可读触发原因
    context_snapshot JSONB NOT NULL,                                -- positions + prices + NAV 完整快照
    action_taken     VARCHAR(30) NOT NULL
                     CHECK (action_taken IN ('sell', 'alert_only', 'bypass')),
    action_result    JSONB,                                          -- broker fill / alert response (可 NULL 如 action 失败)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- PK 含 triggered_at (TimescaleDB hypertable 硬要求: partition 列必在 UNIQUE 索引中)
    PRIMARY KEY (id, triggered_at)
);

CREATE INDEX IF NOT EXISTS ix_risk_event_strategy_time
    ON risk_event_log (strategy_id, execution_mode, triggered_at DESC);

CREATE INDEX IF NOT EXISTS ix_risk_event_rule_time
    ON risk_event_log (rule_id, triggered_at DESC);

COMMENT ON TABLE risk_event_log IS
    'MVP 3.1 Risk Framework — 统一风控事件日志. 替代 position_monitor + intraday_monitor_log + circuit_breaker_log. 对齐 backend/platform/risk/engine.py::PlatformRiskEngine._log_event. 90 天 TimescaleDB retention.';

-- ─────────────────────────────────────────────────────────────
-- TimescaleDB hypertable + retention (幂等)
-- ─────────────────────────────────────────────────────────────

SELECT create_hypertable(
    'risk_event_log', 'triggered_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

-- add_retention_policy: TimescaleDB 2.x 签名, if_not_exists 幂等
SELECT add_retention_policy(
    'risk_event_log',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

-- ─────────────────────────────────────────────────────────────
-- Migration fail-loud guard (铁律 33)
-- ─────────────────────────────────────────────────────────────

DO $$
DECLARE
    col_count INT;
    hypertable_exists BOOL;
    retention_job_count INT;
BEGIN
    SET LOCAL statement_timeout = '30s';

    -- 核心列存在性
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'risk_event_log'
      AND column_name IN (
          'id', 'strategy_id', 'execution_mode', 'rule_id', 'severity',
          'triggered_at', 'code', 'shares', 'reason', 'context_snapshot',
          'action_taken', 'action_result', 'created_at'
      );
    IF col_count < 13 THEN
        RAISE EXCEPTION 'risk_event_log migration incomplete: only % of 13 required columns', col_count;
    END IF;

    -- hypertable 已转换
    SELECT EXISTS(
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'risk_event_log'
    ) INTO hypertable_exists;
    IF NOT hypertable_exists THEN
        RAISE EXCEPTION 'risk_event_log hypertable conversion failed';
    END IF;

    -- retention policy 已注册
    SELECT COUNT(*) INTO retention_job_count
    FROM timescaledb_information.jobs
    WHERE hypertable_name = 'risk_event_log'
      AND proc_name = 'policy_retention';
    IF retention_job_count < 1 THEN
        RAISE EXCEPTION 'risk_event_log retention policy not registered';
    END IF;
END $$;
