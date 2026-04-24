-- MVP 3.2 Strategy Framework — strategy_registry + strategy_status_log 建表
-- 铁律 32 约束: 调用方管事务, 表本身无其他表级约束
-- 批 1 (2026-04-24 Session 33 Part 1)
--
-- 依赖: 无 (MVP 1.4 已有 feature_flags 同模式参照)
-- 回滚: strategy_registry_rollback.sql (配对)

-- ── 1. strategy_registry — 策略注册表 ───────────────────────────────

CREATE TABLE IF NOT EXISTS strategy_registry (
    -- UUID PK 复用当前 live UUID '28fc37e5-2d32-4ada-92e0-41c11a5103d0' 保 position_snapshot 历史不 orphan
    strategy_id      UUID PRIMARY KEY,

    -- 人类可读标识, UNIQUE. e.g. 's1_monthly_ranking' / 's2_pead_event'
    name             TEXT NOT NULL UNIQUE,

    -- 调仓频率, 对应 RebalanceFreq Enum (platform/strategy/interface.py)
    rebalance_freq   TEXT NOT NULL CHECK (rebalance_freq IN ('daily','weekly','monthly','event')),

    -- 策略状态, 对应 StrategyStatus Enum. 生产 PT 只跑 'live'.
    status           TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','backtest','dry_run','live','paused','retired')),

    -- 依赖因子清单 (JSONB array of string). e.g. ["turnover_mean_20","volatility_20","bp_ratio","dv_ttm"]
    factor_pool      JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 策略配置 (JSONB). pt_live.yaml 内容序列化到此, 如 top_n / industry_cap / size_neutral_beta 等
    config           JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 人类描述 (optional)
    description      TEXT NOT NULL DEFAULT '',

    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE strategy_registry IS 'MVP 3.2 Strategy Framework — 策略注册表 (支持 multi-strategy 一等公民, ADR-002)';
COMMENT ON COLUMN strategy_registry.strategy_id IS 'UUID PK. S1 必须用 28fc37e5-2d32-4ada-92e0-41c11a5103d0 (复用现 live position_snapshot 历史 UUID 避 orphan)';
COMMENT ON COLUMN strategy_registry.rebalance_freq IS 'RebalanceFreq enum: daily/weekly/monthly/event. event 对应 PEAD 事件驱动策略';
COMMENT ON COLUMN strategy_registry.status IS 'StrategyStatus enum: draft/backtest/dry_run/live/paused/retired. 生产 PT daily_pipeline 只跑 live';
COMMENT ON COLUMN strategy_registry.factor_pool IS 'JSONB array of factor_name. 所有元素必须在 factor_registry 中 status IN (active, warning)';
COMMENT ON COLUMN strategy_registry.config IS 'JSONB 策略配置: top_n / industry_cap / size_neutral_beta / rebalance_day / 等. pt_live.yaml 序列化形态';

CREATE INDEX IF NOT EXISTS idx_strategy_registry_status ON strategy_registry (status);
CREATE INDEX IF NOT EXISTS idx_strategy_registry_name ON strategy_registry (name);

-- 自动维护 updated_at
CREATE OR REPLACE FUNCTION _strategy_registry_touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_strategy_registry_touch ON strategy_registry;
CREATE TRIGGER trg_strategy_registry_touch
    BEFORE UPDATE ON strategy_registry
    FOR EACH ROW EXECUTE FUNCTION _strategy_registry_touch_updated_at();

-- ── 2. strategy_status_log — 状态变更审计日志 ──────────────────────

CREATE TABLE IF NOT EXISTS strategy_status_log (
    id               BIGSERIAL PRIMARY KEY,
    strategy_id      UUID NOT NULL REFERENCES strategy_registry(strategy_id) ON DELETE CASCADE,
    old_status       TEXT,
    new_status       TEXT NOT NULL,
    reason           TEXT NOT NULL,
    changed_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE strategy_status_log IS 'MVP 3.2 Strategy Framework — 策略状态变更审计 (update_status(reason) 必 insert 行)';
COMMENT ON COLUMN strategy_status_log.old_status IS 'NULL 表示首次 register (status=draft 或首次 insert)';

CREATE INDEX IF NOT EXISTS idx_strategy_status_log_strategy_id ON strategy_status_log (strategy_id);
CREATE INDEX IF NOT EXISTS idx_strategy_status_log_changed_at ON strategy_status_log (changed_at DESC);

-- ── 验证 (注释, 迁移后手工跑) ──────────────────────────────
-- SELECT COUNT(*) FROM strategy_registry;  -- 预期 0 rows (首次 migration 后)
-- SELECT column_name, data_type, is_nullable, column_default
--   FROM information_schema.columns WHERE table_name='strategy_registry' ORDER BY ordinal_position;
