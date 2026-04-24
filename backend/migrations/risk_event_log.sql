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
-- TimescaleDB 事务语义 (PR #55 reviewer P0 指出):
--   create_hypertable / add_retention_policy 是 non-transactional catalog ops,
--   不能包在 BEGIN/COMMIT 内. 采用 partial-transaction pattern:
--     BEGIN/COMMIT 包 CREATE TABLE (原子); hypertable 转换 + retention 在其外;
--     末尾 DO block guard 检查三者齐全, 缺失 RAISE EXCEPTION 触发人工 rollback.
--
-- Rollback: risk_event_log_rollback.sql (DROP TABLE CASCADE 清理所有 chunks + retention job).
-- 关联铁律: 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud migration) / 38 (Blueprint 真相源)

-- pgcrypto 已由 knowledge_registry.sql 启用 (PG 13+ 内置, CREATE EXTENSION 幂等)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────
-- Phase 1: CREATE TABLE (原子事务, 失败自动 ROLLBACK)
-- ─────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS risk_event_log (
    id               UUID NOT NULL DEFAULT gen_random_uuid(),
    strategy_id      UUID NOT NULL,                                 -- reviewer P1-1: UUID 对齐 signals/trade_log/position_snapshot (非 VARCHAR)
    execution_mode   VARCHAR(10) NOT NULL
                     CHECK (execution_mode IN ('paper', 'live')),   -- ADR-008 namespace
    rule_id          VARCHAR(50) NOT NULL,                          -- "pms_l1" / "intraday_p3" / "cb_l2"
    severity         VARCHAR(10) NOT NULL
                     CHECK (severity IN ('p0', 'p1', 'p2', 'info')),
    triggered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code             VARCHAR(12) NOT NULL DEFAULT '',               -- "" = 组合级 (intraday_portfolio_drop), 批 2 前评估改 sentinel/NULL
    shares           INTEGER NOT NULL DEFAULT 0
                     CHECK (shares >= 0),                           -- reviewer P2-1: sell 动作股数 / alert_only=0 / 禁负
    reason           TEXT NOT NULL,                                  -- 人类可读触发原因
    context_snapshot JSONB NOT NULL,                                -- positions + prices + NAV 完整快照
    action_taken     VARCHAR(30) NOT NULL
                     CHECK (action_taken IN ('sell', 'alert_only', 'bypass')),
    action_result    JSONB,                                          -- broker fill / alert response (可 NULL 如 action 失败)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- PK 含 triggered_at (TimescaleDB hypertable 硬要求: partition 列必在 UNIQUE 索引中)
    -- reviewer P1-3 建议"UNIQUE INDEX on id" 实测被 TimescaleDB 拒绝 (ERROR: cannot create
    -- a unique index without the column "triggered_at" used in partitioning). hypertable 设计
    -- 强制 uniqueness 必含 partition 列, 本设计接受: id 通过 gen_random_uuid() UUID v4
    -- 全局唯一 (概率意义), 点查需传 triggered_at 时间窗或 strategy_id (有 ix_risk_event_strategy_time).
    -- 未来 FK 引用若需指 risk_event_log 行, 用 composite FK (id, triggered_at) 或 application-layer
    -- 同日 triggered_at 窗口 lookup. 本 PR 无 FK 引用需求.
    PRIMARY KEY (id, triggered_at)
);

COMMENT ON TABLE risk_event_log IS
    'MVP 3.1 Risk Framework — 统一风控事件日志. 替代 position_monitor + intraday_monitor_log + circuit_breaker_log. 对齐 backend/platform/risk/engine.py::PlatformRiskEngine._log_event (PR 2 创建). 90 天 TimescaleDB retention.';

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: Hypertable 转换 + retention (non-transactional, 必在 BEGIN/COMMIT 外)
-- reviewer P2-5: statement_timeout guard 防 catalog 锁 hang
-- ─────────────────────────────────────────────────────────────

SET statement_timeout = '60s';

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

SET statement_timeout = DEFAULT;

-- ─────────────────────────────────────────────────────────────
-- Phase 3: Indexes (reviewer P1-2: 必在 hypertable 转换后, TimescaleDB 自动传播至所有 chunks)
-- ─────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_risk_event_strategy_time
    ON risk_event_log (strategy_id, execution_mode, triggered_at DESC);

CREATE INDEX IF NOT EXISTS ix_risk_event_rule_time
    ON risk_event_log (rule_id, triggered_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Phase 4: Migration fail-loud guard (铁律 33)
-- verified on TimescaleDB 2.26.0 + pgcrypto 1.3 (Session 28 2026-04-24)
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

    -- retention policy 已注册 (proc_name='policy_retention' verified on TimescaleDB 2.26)
    SELECT COUNT(*) INTO retention_job_count
    FROM timescaledb_information.jobs
    WHERE hypertable_name = 'risk_event_log'
      AND proc_name = 'policy_retention';
    IF retention_job_count < 1 THEN
        RAISE EXCEPTION 'risk_event_log retention policy not registered';
    END IF;
END $$;
