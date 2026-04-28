-- MVP 4.1 Observability Framework — batch 1 alert_dedup table
-- Cross-process alert dedup (replaces in-memory NotificationThrottler for schtask scripts).
-- 17 schtask + Celery scripts 各自进程, 内存 throttler 永久失效, 必须 PG 持久化.
-- 铁律: 32 (Service 不 commit, 表本身无其他表级约束) / 33 (fail-loud) / 34 (config SSOT)
--
-- Volume estimate: 17 scripts × ~5 alert categories/script × few fires/day
--   = sub-thousand rows/day, max ~100K rows/year. 远低于 hypertable 阈值, 用普通表.
-- Cleanup strategy: 单独 cleanup task 删除 suppress_until < now() - 30d (留 30d audit).

CREATE TABLE IF NOT EXISTS alert_dedup (
    dedup_key       TEXT PRIMARY KEY,
    severity        TEXT NOT NULL,
    source          TEXT NOT NULL,
    last_fired_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    suppress_until  TIMESTAMP WITH TIME ZONE NOT NULL,
    fire_count      BIGINT NOT NULL DEFAULT 1,
    last_title      TEXT,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE alert_dedup IS
    'MVP 4.1 PlatformAlertRouter cross-process dedup. dedup_key 由 caller 显式提供, '
    '替代 in-memory NotificationThrottler (跨 schtask 进程失效). 7d 上限对齐 Blueprint #7.';

COMMENT ON COLUMN alert_dedup.dedup_key IS
    'Caller 显式 dedup 键, e.g. "factor_lifecycle:dv_ttm:warning". 显式 > 隐式, 避免 title '
    '微小变化导致 dedup miss.';
COMMENT ON COLUMN alert_dedup.severity IS
    '告警级别 p0/p1/p2/info (qm_platform._types.Severity). 用于审计 + cleanup 策略, 不影响 '
    'dedup 逻辑 (dedup 只看 dedup_key + suppress_until).';
COMMENT ON COLUMN alert_dedup.source IS
    '发源模块 (e.g. "factor_lifecycle_monitor"). 审计用.';
COMMENT ON COLUMN alert_dedup.last_fired_at IS
    '最近一次实际发送 (非被 dedup 抑制) 时间.';
COMMENT ON COLUMN alert_dedup.suppress_until IS
    '抑制窗口结束时间. fire(...) 调用时若 NOW() < suppress_until 即 dedup. '
    'caller 通过 suppress_minutes 参数控制窗口长度, 默认 severity 驱动 (P0=5min/P1=30min/P2=60min).';
COMMENT ON COLUMN alert_dedup.fire_count IS
    '同 dedup_key 累计触发次数 (含被 dedup 的). 用于审计 / 风暴检测.';
COMMENT ON COLUMN alert_dedup.last_title IS
    '最近一次 alert title (审计用, 便于复盘什么内容触发).';

-- 索引: cleanup 查询 (suppress_until 早于 30d 的归档/删除)
CREATE INDEX IF NOT EXISTS idx_alert_dedup_suppress_until
    ON alert_dedup (suppress_until);

-- 索引: source 维度审计 (查某模块过去 24h alert 频次)
CREATE INDEX IF NOT EXISTS idx_alert_dedup_source_fired
    ON alert_dedup (source, last_fired_at DESC);
