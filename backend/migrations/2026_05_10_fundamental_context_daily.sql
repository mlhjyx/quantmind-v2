-- V3 governance batch closure sub-PR 14 — fundamental_context_daily 表 (V3 §S4 (minimal) sediment per ADR-053)
--
-- 目标 (V3 §3.3 line 395-426 + ADR-053):
--   8 维 fundamental context daily ingestion (valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards/announcements)
--   sub-PR 14 (minimal) — 1 source AKShare valuation 维 only, 其余 7 维 NULL by design (sub-PR 15+ minimal→完整 expansion per LL-115 capacity expansion 体例)
--
-- 设计原则 (沿用 sub-PR 11a announcement_raw 4-phase pattern):
--   - 幂等 (CREATE TABLE IF NOT EXISTS + DO block guard)
--   - composite PK (symbol_id, date) — V3 §3.3 line 411 cite (反 BIGSERIAL, time-series natural key)
--   - 8 JSONB cols (valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards/announcements) — V3 §3.3 line 403-410 cite
--   - PG regular table — sub-PR 14 minimal, hypertable + retention deferred to sub-PR 15+ (沿用 sub-PR 11a defer 体例)
--
-- ⚠️ 真值边界 (ADR-053 §1 Decision 1):
--   sub-PR 14 minimal scope = 8 维 schema CREATE + 1 source AKShare ingest valuation 维 only
--   其余 7 维 (growth/earnings/institution/capital_flow/dragon_tiger/boards/announcements) NULL by design
--   sub-PR 15+ candidate (LL-115 capacity expansion 真值 silent overwrite anti-pattern reverse 体例 sustained)
--
-- ⚠️ TimescaleDB hypertable + retention DEFER sub-PR 15+ (sustained announcement_raw 体例):
--   PG regular table sufficient for sub-PR 14 minimal scope (~10K-100K rows / 1y 估计 1 source)
--   sub-PR 15+ candidate: SELECT create_hypertable + add_retention_policy when 8 维 expansion + multi-source ingest accumulates
--
-- Rollback: 2026_05_10_fundamental_context_daily_rollback.sql (DROP TABLE IF EXISTS + DO guard).
-- 关联铁律: 17 (DataPipeline 入库) / 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud DO guard) /
--           38 (Blueprint SSOT) / 41 (timezone date — ingestion local trade date, sustained klines_daily 体例) / 45 (4 doc fresh read SOP)

BEGIN;

CREATE TABLE IF NOT EXISTS fundamental_context_daily (
    symbol_id           VARCHAR(20)               NOT NULL,
    date                DATE                      NOT NULL,
    valuation           JSONB,                                  -- {pe_ttm, pe_static, pb, peg, pcf, ps, market_cap_total, market_cap_float} (sub-PR 14 minimal — AKShare stock_value_em 1 source)
    growth              JSONB,                                  -- {revenue_yoy, profit_yoy, eps_3y_cagr} (V3 §3.3 cite, sub-PR 15+ NULL by design sub-PR 14)
    earnings            JSONB,                                  -- {roe, roa, gross_margin, ocf_to_profit, mismatch_flag} (V3 §3.3 cite, sub-PR 15+)
    institution         JSONB,                                  -- {fund_holding_pct, private_pct, northbound_pct, top10_change} (V3 §3.3 cite, sub-PR 15+)
    capital_flow        JSONB,                                  -- {main_5d, main_10d, main_20d, northbound_buy_sell} (V3 §3.3 cite, sub-PR 15+)
    dragon_tiger        JSONB,                                  -- {count_30d, net_buy, top_seats} (V3 §3.3 cite, sub-PR 15+)
    boards              JSONB,                                  -- {concept_themes, limit_up_days, board_height} (V3 §3.3 cite, sub-PR 15+)
    announcements       JSONB,                                  -- {recent_count, types, urgency_max} (V3 §3.3 cite, sub-PR 15+; 关联 announcement_raw sub-PR 11a/13)
    fetched_at          TIMESTAMP WITH TIME ZONE  NOT NULL DEFAULT now(),  -- ingestion 入库时间 (反 V3 §3.3 spec, but 时间索引列 必备 audit)
    fetch_cost          NUMERIC(8, 4)             NOT NULL DEFAULT 0 CHECK (fetch_cost >= 0),
    fetch_latency_ms    INTEGER                   NOT NULL DEFAULT 0 CHECK (fetch_latency_ms >= 0),
    PRIMARY KEY (symbol_id, date)
);

COMMENT ON TABLE fundamental_context_daily IS 'V3 §3.3 fundamental_context 8 维 daily ingestion (sub-PR 14 minimal — 1 source AKShare valuation, 7 others NULL by design sub-PR 15+)';
COMMENT ON COLUMN fundamental_context_daily.symbol_id IS 'Stock code (NOT NULL, V3 §3.3 line 401 cite)';
COMMENT ON COLUMN fundamental_context_daily.date IS 'Trade date (NOT NULL, V3 §3.3 line 402 cite, composite PK)';
COMMENT ON COLUMN fundamental_context_daily.valuation IS 'sub-PR 14 minimal AKShare stock_value_em: {pe_ttm, pe_static, pb, peg, pcf, ps, market_cap_total, market_cap_float}. V3 §3.3 spec {pe, pb, ps, ev_ebitda, industry_pctile} — ev_ebitda + industry_pctile defer sub-PR 15+ (LL-115)';
COMMENT ON COLUMN fundamental_context_daily.growth IS 'V3 §3.3 {revenue_yoy, profit_yoy, eps_3y_cagr} — NULL by design sub-PR 14, sub-PR 15+ candidate Tushare fina_indicator';
COMMENT ON COLUMN fundamental_context_daily.earnings IS 'V3 §3.3 {roe, roa, gross_margin, ocf_to_profit, mismatch_flag} — NULL by design sub-PR 14, sub-PR 15+ candidate Tushare fina_indicator';
COMMENT ON COLUMN fundamental_context_daily.institution IS 'V3 §3.3 {fund_holding_pct, private_pct, northbound_pct, top10_change} — NULL by design sub-PR 14, sub-PR 15+ candidate Tushare top10_holders + hk_hold';
COMMENT ON COLUMN fundamental_context_daily.capital_flow IS 'V3 §3.3 {main_5d, main_10d, main_20d, northbound_buy_sell} — NULL by design sub-PR 14, sub-PR 15+ candidate Tushare moneyflow';
COMMENT ON COLUMN fundamental_context_daily.dragon_tiger IS 'V3 §3.3 {count_30d, net_buy, top_seats} — NULL by design sub-PR 14, sub-PR 15+ candidate AKShare 龙虎榜';
COMMENT ON COLUMN fundamental_context_daily.boards IS 'V3 §3.3 {concept_themes, limit_up_days, board_height} — NULL by design sub-PR 14, sub-PR 15+ candidate pywencai';
COMMENT ON COLUMN fundamental_context_daily.announcements IS 'V3 §3.3 {recent_count, types, urgency_max} — NULL by design sub-PR 14, sub-PR 15+ candidate aggregate from announcement_raw (sub-PR 11a/13)';
COMMENT ON COLUMN fundamental_context_daily.fetched_at IS 'Ingestion 入库时间 (audit, sub-PR 14 sediment 反 V3 §3.3 strict spec but 必备 audit trail)';
COMMENT ON COLUMN fundamental_context_daily.fetch_cost IS 'AKShare free $0 sub-PR 14 minimal (NUMERIC(8,4) sustained 体例)';
COMMENT ON COLUMN fundamental_context_daily.fetch_latency_ms IS 'Per-fetch elapsed ms (audit + SLA tracking sub-PR 15+)';

COMMIT;

-- Indexes (post COMMIT, 沿用 announcement_raw 4-phase pattern)
CREATE INDEX IF NOT EXISTS ix_fundamental_context_daily_symbol_date
    ON fundamental_context_daily (symbol_id, date DESC);

CREATE INDEX IF NOT EXISTS ix_fundamental_context_daily_fetched_at
    ON fundamental_context_daily (fetched_at DESC);

-- Fail-loud DO guard verify (沿用 sub-PR 11a 4-phase pattern + 铁律 33)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'fundamental_context_daily'
    ) THEN
        RAISE EXCEPTION '[fail-loud] fundamental_context_daily CREATE TABLE 失败 (sub-PR 14 sediment guard)';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'ix_fundamental_context_daily_symbol_date'
    ) THEN
        RAISE EXCEPTION '[fail-loud] ix_fundamental_context_daily_symbol_date CREATE INDEX 失败';
    END IF;
    RAISE NOTICE '[OK] fundamental_context_daily DDL applied (sub-PR 14 minimal, 8 JSONB cols, 2 indexes, audit trail)';
END $$;
