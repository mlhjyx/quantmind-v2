-- V3 governance batch closure sub-PR 11 — announcement_raw 表 (V3§3.1+§11.1 row 5 公告流 L0.4 ingestion 入库表)
--
-- 目标 (V3§11.1 row 5 + ADR-049 sediment):
--   公告流 ingestion (巨潮/交易所 RSS via RSSHub route reuse) AnnouncementProcessor → announcement_raw
--   sub-PR 11b 待办 implement: AnnouncementProcessor service + Beat trading-hours cadence + API
--
-- 设计原则 (沿用 PR #240 news_raw.sql 4-phase pattern):
--   - 幂等 (CREATE TABLE IF NOT EXISTS + DO block guard)
--   - announcement_id BIGSERIAL PK (sustained news_raw 体例, 反 composite PK)
--   - fetched_at TIMESTAMPTZ DEFAULT NOW() — 时间索引列
--   - schema 反 1:1 复用 news_raw — 公告流真**结构性差异** (announcement_type/pdf_url/disclosure_date)
--   - CHECK 反 silent neg (fetch_cost / fetch_latency_ms NUMERIC + INT 反 negative)
--   - announcement_type CHECK (annual_report/quarterly_report/material_event/shareholder_meeting/dividend/other)
--     反 silent enum drift (反 earnings_announcements 207K 行 narrow scope cumulative cite)
--
-- ⚠️ 真值边界 (Finding #2 sediment, ADR-049 §Decision 2):
--   announcement_raw scope = 全公告 (年报/季报/重大事项/股东大会/分红/...) ⊃ earnings_announcements (仅 EPS surprise PEAD subset)
--   announcement_type filter EXCLUDE earnings disclosure (反 dedup with earnings_announcements Tushare path)
--   downstream S5 RealtimeRiskEngine consume announcement_raw (V3§5 announcement context input)
--
-- ⚠️ V3§3.1:350-356 hypertable + compression + retention DEFER S5 paper-mode 5d (sustained news_raw 体例):
--   PG regular table sufficient (~50K rows / 90d 公告流真生产 估计), retention via app-layer cron defer
--
-- ⚠️ Decision 3 RSSHub route reuse (sustained sub-PR 6 RsshubNewsFetcher precedent):
--   AnnouncementProcessor 反 separate fetcher class — 沿用 RsshubNewsFetcher with announcement-specific route_path
--   (e.g. `/cninfo/announcement/{stockCode}` route, sub-PR 11b 待办 verify 真值 endpoint structure)
--
-- Rollback: 2026_05_09_announcement_raw_rollback.sql (DROP TABLE IF EXISTS + DO guard).
-- 关联铁律: 17 (DataPipeline 入库) / 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud DO guard) /
--           38 (Blueprint SSOT) / 41 (timezone TIMESTAMPTZ tz-aware) / 45 (4 doc fresh read SOP)
-- 关联 ADR: ADR-049 (V3 §S2.5 architecture sediment) / ADR-031 (LiteLLMRouter path) / ADR-033 (News 源替换决议) /
--           ADR-043 (News Beat schedule + RSSHub routing 契约) / ADR-048 (V3 §S2 closure)

-- ─────────────────────────────────────────────────────────────
-- Phase 1: CREATE TABLE (BEGIN/COMMIT 原子)
-- ─────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS announcement_raw (
    announcement_id   BIGSERIAL    PRIMARY KEY,
    symbol_id         VARCHAR(20)  NOT NULL,                              -- 公告 必 attached to symbol (反 NULL 大盘公告)
    source            VARCHAR(20)  NOT NULL,                              -- "cninfo"/"sse"/"szse"/"rsshub" (Decision 3 RSSHub route reuse)
    announcement_type VARCHAR(40)  NOT NULL                               -- annual_report/quarterly_report/material_event/shareholder_meeting/dividend/other
                                   CHECK (announcement_type IN (
                                       'annual_report',
                                       'quarterly_report',
                                       'material_event',
                                       'shareholder_meeting',
                                       'dividend',
                                       'other'
                                   )),
    title             TEXT         NOT NULL,
    url               TEXT,                                               -- HTML disclosure portal URL (optional, RSSHub None fallback)
    pdf_url           TEXT,                                               -- PDF URL (optional, 公告 通常 attached PDF)
    disclosure_date   DATE         NOT NULL,                              -- 公告 disclosure date (T 日, 反 fetched_at)
    content_snippet   TEXT,                                               -- 公告 摘要 (optional, 反 full PDF content 性能)
    fetch_cost        NUMERIC(8,4) NOT NULL DEFAULT 0
                                   CHECK (fetch_cost >= 0),
    fetch_latency_ms  INT          NOT NULL DEFAULT 0
                                   CHECK (fetch_latency_ms >= 0),
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE announcement_raw IS
    'V3§3.1+§11.1 row 5 公告流 L0.4 ingestion 入库表. AnnouncementProcessor (sub-PR 11b 待办) → announcement_raw 入库. '
    '反 1:1 复用 news_raw — 公告流 真值 structural divergence (announcement_type/pdf_url/disclosure_date). '
    'announcement_type filter EXCLUDE earnings disclosure (反 dedup with earnings_announcements 207K rows Tushare path). '
    '⚠️ hypertable defer S5 paper-mode 5d (sustained news_raw 体例 + 反 ~50K rows / 90d ROI 弱).';

COMMENT ON COLUMN announcement_raw.announcement_id IS 'BIGSERIAL PK (sustained news_raw 体例, 反 composite PK)';
COMMENT ON COLUMN announcement_raw.symbol_id IS '公告 必 attached to symbol (NOT NULL, 反 大盘公告 unmapped)';
COMMENT ON COLUMN announcement_raw.source IS 'cninfo/sse/szse/rsshub (Decision 3 RSSHub route reuse, sub-PR 11b verify endpoint)';
COMMENT ON COLUMN announcement_raw.announcement_type IS '6 enum: annual_report/quarterly_report/material_event/shareholder_meeting/dividend/other. 反 silent drift (Finding #2 sediment)';
COMMENT ON COLUMN announcement_raw.disclosure_date IS '公告 disclosure date T 日 (反 fetched_at, T 日 vs ingestion 入库 区分)';
COMMENT ON COLUMN announcement_raw.fetched_at IS 'Ingestion 入库时间, 时间索引列 (反 hypertable partition 本 PR scope, defer S5)';

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: 0 hypertable (defer S5 paper-mode 5d period, sustained news_raw 体例)
-- ─────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────────
-- Phase 3: Indexes (sustained news_raw 体例 PG regular indexes)
-- ─────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_announcement_raw_symbol_disclosure
    ON announcement_raw (symbol_id, disclosure_date DESC);

CREATE INDEX IF NOT EXISTS ix_announcement_raw_source_fetched
    ON announcement_raw (source, fetched_at DESC);

CREATE INDEX IF NOT EXISTS ix_announcement_raw_type_disclosure
    ON announcement_raw (announcement_type, disclosure_date DESC);

-- ─────────────────────────────────────────────────────────────
-- Phase 4: Migration fail-loud guard (铁律 33, 沿用 news_raw.sql 体例)
-- ─────────────────────────────────────────────────────────────

DO $$
DECLARE
    col_count INT;
    pk_exists BOOL;
    enum_check_exists BOOL;
BEGIN
    SET LOCAL statement_timeout = '30s';

    -- 核心列存在性 (12 列)
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'announcement_raw'
      AND column_name IN (
          'announcement_id', 'symbol_id', 'source', 'announcement_type',
          'title', 'url', 'pdf_url', 'disclosure_date', 'content_snippet',
          'fetch_cost', 'fetch_latency_ms', 'fetched_at'
      );
    IF col_count < 12 THEN
        RAISE EXCEPTION 'announcement_raw migration incomplete: only % of 12 required columns', col_count;
    END IF;

    -- PRIMARY KEY 验证 (BIGSERIAL PK sustained news_raw 体例)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'announcement_raw' AND constraint_type = 'PRIMARY KEY'
    ) THEN
        RAISE EXCEPTION 'announcement_raw PRIMARY KEY 缺失';
    END IF;

    -- announcement_type CHECK constraint 验证 (反 silent enum drift, Finding #2 sediment)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints
        WHERE constraint_name LIKE '%announcement_type%'
    ) THEN
        RAISE EXCEPTION 'announcement_raw announcement_type CHECK constraint 缺失 — 反 silent enum drift (Finding #2 sediment)';
    END IF;
END $$;
