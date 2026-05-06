-- Sprint 2 sub-PR 7b.1 — news_raw 表 (V3§3.1 News 多源接入 L0.1 ingestion 入库表)
--
-- 目标 (V3§3.1:336-356 + ADR-033 sediment):
--   6 源 ingestion (智谱+Tavily+Anspire+GDELT+Marketaux+RSSHub) DataPipeline 入库 (sub-PR 7a #239 sediment)
--   sub-PR 7b.2 NewsClassifierService consume → news_classified (V3§3.2 sediment, sub-PR 7b.2 PR scope)
--
-- 设计原则 (沿用 PR #223 llm_cost_daily.sql + risk_event_log.sql 4-phase pattern):
--   - 幂等 (CREATE TABLE IF NOT EXISTS + DO block guard)
--   - news_id BIGSERIAL PK (V3§3.1:337 sustained, 反 composite PK)
--   - fetched_at TIMESTAMPTZ DEFAULT NOW() — 时间索引列, 反 hypertable partition (本 PR scope)
--   - NewsItem schema 1:1 align (sub-PR 1-6 sediment + base.py:37-64 dataclass)
--   - CHECK 反 silent neg (fetch_cost / fetch_latency_ms NUMERIC + INT 反 negative)
--
-- ⚠️ V3§3.1:350-356 hypertable + compression + retention DEFER Sprint 3+ separate migration:
--   V3 spec internal conflict — `news_id BIGSERIAL PRIMARY KEY` (single-col, line 337) +
--   `create_hypertable('news_raw', 'fetched_at')` (line 350) — TimescaleDB constraint
--   "all unique/PK indexes must include partitioning columns" (沿用 risk_event_log.sql:52-59
--   precedent: composite PK `(id, triggered_at)` 解决方案).
--
--   本 PR 决议**保 V3§3.1:337 PK spec sustained** + **defer hypertable Sprint 3+** 真因:
--   - 保 V3§3.2:366 FK `REFERENCES news_raw(news_id)` simple ✅ (反 composite FK cascade)
--   - 反 ~130K rows / 90d (~260MB) hypertable 真生产 ROI 弱 (PG regular table sufficient)
--   - Retention via app-layer cron defer Sprint 3+ (反 sub-PR 7b.1 scope leak sustained)
--   - 沿用真讽刺案例 #4-#9 cumulative lesson sustained (反 silent V3 spec violation cascade)
--
-- DataPipeline (sub-PR 7a #239) consume:
--   - DataPipeline.fetch_all() returns list[NewsItem]
--   - sub-PR 7b.3 (defer Sprint 3) wire DataPipeline → DataContract → news_raw 入库 (铁律 17)
--
-- Rollback: 2026_05_06_news_raw_rollback.sql (DROP TABLE IF EXISTS + DO guard).
-- 关联铁律: 17 (DataPipeline 入库) / 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud DO guard) /
--           38 (Blueprint 真相源) / 41 (timezone TIMESTAMPTZ tz-aware) / 45 (4 doc fresh read SOP)

-- ─────────────────────────────────────────────────────────────
-- Phase 1: CREATE TABLE (BEGIN/COMMIT 原子)
-- ─────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS news_raw (
    news_id          BIGSERIAL    PRIMARY KEY,
    symbol_id        VARCHAR(20),                                        -- NULL = 大盘/行业 news (V3§3.1:338)
    source           VARCHAR(20)  NOT NULL,                              -- "zhipu"/"tavily"/"anspire"/"gdelt"/"marketaux"/"rsshub"
    timestamp        TIMESTAMPTZ  NOT NULL,                              -- 文章发布时间 (NewsItem.timestamp, 铁律 41)
    title            TEXT         NOT NULL,                              -- NewsItem.title required (base.py:58)
    content          TEXT,                                               -- NewsItem.content optional
    url              TEXT,                                               -- NewsItem.url optional (RSSHub None URL fallback)
    lang             VARCHAR(10)  NOT NULL DEFAULT 'zh',                 -- NewsItem.lang default "zh"
    fetch_cost       NUMERIC(8,4) NOT NULL DEFAULT 0
                                  CHECK (fetch_cost >= 0),               -- USD, 反 negative
    fetch_latency_ms INT          NOT NULL DEFAULT 0
                                  CHECK (fetch_latency_ms >= 0),         -- 反 negative
    fetched_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()                 -- ingestion 入库时间 (V3§3.1:347)
);

COMMENT ON TABLE news_raw IS
    'V3§3.1 News 多源接入 L0.1 ingestion 入库表. 6 源 (智谱+Tavily+Anspire+GDELT+Marketaux+RSSHub) '
    'DataPipeline (sub-PR 7a) → DataContract (sub-PR 7b.3) → news_raw 入库. '
    'sub-PR 7b.2 NewsClassifierService consume → news_classified (FK news_id). '
    '⚠️ V3§3.1:350 hypertable defer Sprint 3+ (BIGSERIAL PK + hypertable conflict, '
    '沿用 risk_event_log:52-59 precedent + 沿用 PG regular table 真生产 ROI sufficient).';

COMMENT ON COLUMN news_raw.news_id IS 'BIGSERIAL PK (V3§3.1:337 sustained), 反 composite PK';
COMMENT ON COLUMN news_raw.symbol_id IS 'NULL = 大盘/行业 news (V3§3.1:338)';
COMMENT ON COLUMN news_raw.source IS '6 源标识: zhipu/tavily/anspire/gdelt/marketaux/rsshub (sub-PR 1-6 sediment)';
COMMENT ON COLUMN news_raw.timestamp IS '文章发布时间 (NewsItem.timestamp tz-aware UTC, 铁律 41)';
COMMENT ON COLUMN news_raw.fetched_at IS 'Ingestion 入库时间, 时间索引列 (V3§3.1:347, 反 hypertable partition 本 PR scope)';

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: 0 hypertable (defer Sprint 3+, 真因详 header)
-- ─────────────────────────────────────────────────────────────

-- ─────────────────────────────────────────────────────────────
-- Phase 3: Indexes (沿用 V3§3.1:351-352 真预约 sediment, regular PG indexes)
-- ─────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_news_raw_symbol_time
    ON news_raw (symbol_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS ix_news_raw_source_time
    ON news_raw (source, fetched_at DESC);

-- ─────────────────────────────────────────────────────────────
-- Phase 4: Migration fail-loud guard (铁律 33, 沿用 risk_event_log.sql 体例)
-- ─────────────────────────────────────────────────────────────

DO $$
DECLARE
    col_count INT;
    pk_exists BOOL;
BEGIN
    SET LOCAL statement_timeout = '30s';

    -- 核心列存在性 (10 列, NewsItem schema 1:1 align + fetched_at)
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'news_raw'
      AND column_name IN (
          'news_id', 'symbol_id', 'source', 'timestamp', 'title',
          'content', 'url', 'lang', 'fetch_cost', 'fetch_latency_ms', 'fetched_at'
      );
    IF col_count < 11 THEN
        RAISE EXCEPTION 'news_raw migration incomplete: only % of 11 required columns', col_count;
    END IF;

    -- PRIMARY KEY 验证 (V3§3.1:337 BIGSERIAL PK sustained, FK news_classified 真依赖)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'news_raw' AND constraint_type = 'PRIMARY KEY'
    ) THEN
        RAISE EXCEPTION 'news_raw PRIMARY KEY 缺失 — news_classified FK 真依赖';
    END IF;
END $$;
