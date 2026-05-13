--- V3 §5.3 Bull/Bear regime detection (Tier B) — market_regime_log DDL (TB-2a foundation)
---
--- 用途: 每日 3 次 (9:00 / 14:30 / 16:00) Bull/Bear V4-Pro × 3 agent debate 输出
---       regime label (Bull/Bear/Neutral/Transitioning) + confidence + arguments + judge reasoning.
---       由 MarketRegimeService (Tier B TB-2b/c) 写入, DynamicThresholdEngine (TB-2d) 读取做 L3 阈值调整.
---
--- 变更:
---   1. NEW TABLE market_regime_log (V3 §5.3 schema 1:1, BIGSERIAL PK)
---   2. hypertable timestamp partition 1 month chunk (V3 §5.3 line 681 sustained)
---   3. 2 indexes for query patterns:
---      - PRIMARY KEY (regime_id, timestamp) — TimescaleDB hypertable 要求 timestamp 入 PK
---      - idx_market_regime_log_ts_desc — latest regime fetch (DynamicThresholdEngine read)
---      - idx_market_regime_log_regime_ts — regime-filtered queries (e.g. bear period audit)
---   4. CHECK constraints on regime label + confidence range [0, 1]
---
--- Rollback: 2026_05_14_market_regime_log_rollback.sql
---
--- 关联: V3 §5.3 + V3 §11.2 line 1227 (MarketRegimeService) + ADR-029/036/064 + ADR-066 (Tier B context)
--- 铁律 17 (DataPipeline 入库) / 22 (doc 跟随代码) / 41 (timezone TIMESTAMPTZ)

BEGIN;

CREATE TABLE IF NOT EXISTS market_regime_log (
    regime_id BIGSERIAL NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    regime VARCHAR(20) NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    bull_arguments JSONB,        -- 3-arg structure: [{"argument": "...", "evidence": "...", "weight": 0.x}, ...]
    bear_arguments JSONB,        -- same shape
    judge_reasoning TEXT,
    market_indicators JSONB,     -- 输入 snapshot: {sse_return, hs300_return, breadth_up, breadth_down, north_flow_cny, iv_50etf}
    cost_usd NUMERIC(8, 4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- TimescaleDB hypertable requires partition key (timestamp) in PRIMARY KEY.
    PRIMARY KEY (regime_id, timestamp),
    CONSTRAINT chk_regime_label
        CHECK (regime IN ('Bull', 'Bear', 'Neutral', 'Transitioning')),
    CONSTRAINT chk_confidence_range
        CHECK (confidence >= 0 AND confidence <= 1)
);

-- TimescaleDB hypertable: 1 month chunk per V3 §5.3 line 681
-- if_not_exists guards re-run (沿用 risk_metrics_daily 体例).
SELECT create_hypertable(
    'market_regime_log',
    'timestamp',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

-- Read patterns (sustained DynamicThresholdEngine TB-2d):
-- (a) latest regime: SELECT * FROM market_regime_log ORDER BY timestamp DESC LIMIT 1
-- (b) regime-filtered: SELECT * WHERE regime='Bear' AND timestamp >= ...
CREATE INDEX IF NOT EXISTS idx_market_regime_log_ts_desc
    ON market_regime_log (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_market_regime_log_regime_ts
    ON market_regime_log (regime, timestamp DESC);

-- Reviewer P1 sustained (ADR-062 体例): COMMENT inside BEGIN/COMMIT
-- 反 partial migration state if DDL fails between COMMIT and COMMENT.
COMMENT ON TABLE market_regime_log IS
    'V3 §5.3 Bull/Bear regime detection — 每日 3 次 V4-Pro × 3 agent debate 输出';
COMMENT ON COLUMN market_regime_log.regime IS
    'V3 §5.3 label: Bull/Bear/Neutral/Transitioning (CHECK constrained, ADR-036 V4-Pro Judge 输出)';
COMMENT ON COLUMN market_regime_log.bull_arguments IS
    'JSONB array of 3 看多 arguments per Bull Agent V4-Pro (ADR-036)';
COMMENT ON COLUMN market_regime_log.bear_arguments IS
    'JSONB array of 3 看空 arguments per Bear Agent V4-Pro (ADR-036)';
COMMENT ON COLUMN market_regime_log.market_indicators IS
    'JSONB 输入 snapshot: {sse_return, hs300_return, breadth_up, breadth_down, north_flow_cny, iv_50etf} — field names align MarketIndicators dataclass per backend/qm_platform/risk/regime/interface.py';
COMMENT ON COLUMN market_regime_log.confidence IS
    'V3 §5.3 Judge confidence ∈ [0, 1] (CHECK chk_confidence_range). NUMERIC(5,4) = 4 decimal precision sufficient for Judge weighted vote — higher precision is LLM stochastic noise.';
COMMENT ON COLUMN market_regime_log.cost_usd IS
    'V3 §16.2 月预算 ≤ $50/月 — Bull/Bear/Judge 3 calls × 3 daily × 30 days = 270 calls (V4-Pro ~$0.39/月 per ADR-036)';

COMMIT;
