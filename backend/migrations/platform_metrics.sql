-- MVP 4.1 Observability Framework — batch 2.1 platform_metrics hypertable
--
-- 目标:
--   PostgresMetricExporter 后端存储. 17 schtask scripts 迁 SDK (批 3) 后, gauge/counter/histogram
--   全经此表. 替代散落 print + log, 提供时间序列查询能力 (Wave 5 UI dashboard 数据源).
--
-- 设计:
--   - 幂等 (CREATE/IF NOT EXISTS + create_hypertable if_not_exists=TRUE)
--   - TimescaleDB hypertable, 按 ts 周度 partition (chunk_time_interval=7d)
--   - 30 天 retention (Wave 5 UI 月度趋势够用, 长期归档留 future MVP 4.x)
--   - labels JSONB (灵活打标签), name TEXT (dotted: pt.signal.count / factor_lifecycle.warning_count)
--   - metric_type 列 ('gauge' / 'counter' / 'histogram') 启用类型校验 + 查询过滤
--
-- Volume estimate:
--   17 scripts × ~3 metrics × ~5 fires/day = ~250 rows/day (schtask)
--   + qmt_data_service heartbeat 60s × 24h = 1440 rows/day
--   + 其他持续 metric ~500 rows/day
--   = ~2200 rows/day × 30d = ~66K active rows. 大量低于 hypertable 阈值, 性能不敏感.
--
-- 关联铁律:
--   - 17 (DataPipeline 入库): MetricExporter 是 Platform-internal writer, 不走 DataPipeline.
--                            类似 outbox.py + alert_dedup, 是基础设施表非业务事实.
--   - 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud migration) / 41 (UTC tz-aware)
--
-- TimescaleDB 事务语义 (PR #55 reviewer P0 教训): create_hypertable / add_retention_policy
-- 是 non-transactional catalog ops, 不能包在 BEGIN/COMMIT 内. 采用 partial-transaction pattern.
--
-- Rollback: platform_metrics_rollback.sql (DROP TABLE CASCADE 清理 chunks + retention job).

-- ─────────────────────────────────────────────────────────────
-- Phase 1: CREATE TABLE (原子事务)
-- ─────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS platform_metrics (
    name         TEXT NOT NULL
                 CHECK (char_length(name) BETWEEN 1 AND 256),
    value        DOUBLE PRECISION NOT NULL,
    metric_type  TEXT NOT NULL
                 CHECK (metric_type IN ('gauge', 'counter', 'histogram')),
    labels       JSONB NOT NULL DEFAULT '{}'::jsonb,
    ts           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    -- TimescaleDB hypertable: PK 必含 partition 列 ts. 单 metric 同 ts 多次 emit 合理
    -- (e.g. counter 多次 increment), 不强制 UNIQUE.
    -- Append-only 写入, no PK / UNIQUE — 避免 hypertable 跨 chunk 唯一性约束开销.
    -- 时间序列重复 row 不视为 bug (counter 多次写 + aggregation in query).
    CHECK (value = value)  -- NaN 防护 (NaN != NaN, fail CHECK), 铁律 29 防 NaN 入库
);

COMMENT ON TABLE platform_metrics IS
    'MVP 4.1 PostgresMetricExporter backend. Append-only time-series metrics, '
    'TimescaleDB hypertable + 30d retention. Replaces 17 schtask scripts print/log scatter.';
COMMENT ON COLUMN platform_metrics.name IS
    'Dotted metric name, e.g. "pt.signal.count" / "factor_lifecycle.warning_count".';
COMMENT ON COLUMN platform_metrics.metric_type IS
    'gauge (瞬时值, e.g. current_nav) / counter (递增, e.g. orders_filled_total) / '
    'histogram (分布, e.g. signal_generation_latency_ms).';
COMMENT ON COLUMN platform_metrics.labels IS
    'Free-form JSONB labels (e.g. {"strategy":"S1","trade_date":"2026-04-29"}). '
    'Wave 5 UI dashboard query 用. 当前无 GIN index, 视使用频率后加.';

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: Hypertable 转换 + retention (non-transactional)
-- ─────────────────────────────────────────────────────────────

SET statement_timeout = '60s';

SELECT create_hypertable(
    'platform_metrics', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 30 天 retention. metric 是低价值高频数据, 30d 足够 Wave 5 UI 月度趋势.
SELECT add_retention_policy(
    'platform_metrics',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

SET statement_timeout = DEFAULT;

-- ─────────────────────────────────────────────────────────────
-- Phase 3: Indexes (TimescaleDB 自动传播至 chunks)
-- ─────────────────────────────────────────────────────────────

-- 主查询: 按 metric name + 时间范围 (Wave 5 UI 时间序列)
CREATE INDEX IF NOT EXISTS ix_platform_metrics_name_ts
    ON platform_metrics (name, ts DESC);

-- 辅查询: 按 metric_type 聚合 (e.g. 列出所有 counter)
CREATE INDEX IF NOT EXISTS ix_platform_metrics_type_ts
    ON platform_metrics (metric_type, ts DESC);

-- ─────────────────────────────────────────────────────────────
-- Phase 4: Migration fail-loud guard (铁律 33)
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
    WHERE table_name = 'platform_metrics'
      AND column_name IN ('name', 'value', 'metric_type', 'labels', 'ts');
    IF col_count < 5 THEN
        RAISE EXCEPTION 'platform_metrics migration incomplete: only % of 5 required columns', col_count;
    END IF;

    -- hypertable 已转换
    SELECT EXISTS(
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'platform_metrics'
    ) INTO hypertable_exists;
    IF NOT hypertable_exists THEN
        RAISE EXCEPTION 'platform_metrics hypertable conversion failed';
    END IF;

    -- retention policy 已注册
    SELECT COUNT(*) INTO retention_job_count
    FROM timescaledb_information.jobs
    WHERE hypertable_name = 'platform_metrics'
      AND proc_name = 'policy_retention';
    IF retention_job_count < 1 THEN
        RAISE EXCEPTION 'platform_metrics retention policy not registered';
    END IF;
END $$;
