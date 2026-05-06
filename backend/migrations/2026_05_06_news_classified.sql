-- Sprint 2 sub-PR 7b.1 — news_classified 表 (V3§3.2 NewsClassifier V4-Flash L0.2 output 表)
--
-- 目标 (V3§3.2:359-393 sediment):
--   sub-PR 7b.2 NewsClassifierService (defer 7b.1 prerequisite ready 后起手) consume news_raw
--   → V4-Flash routing (RiskTaskType.NEWS_CLASSIFY enum sustained types.py:31)
--   → JSON output (sentiment/category/urgency/confidence/profile + classifier_model + version + cost)
--   → news_classified 入库 (本 PR scope sediment, FK news_raw)
--
-- 设计原则 (沿用 PR #223 llm_cost_daily.sql + news_raw.sql 体例):
--   - 幂等 (CREATE TABLE IF NOT EXISTS + DO block guard)
--   - news_id BIGINT PRIMARY KEY REFERENCES news_raw(news_id) — V3§3.2:366 FK sustained
--   - 1:1 mapping (单 news_raw → 单 news_classified, NewsClassifier 真 idempotent classify)
--   - CHECK 沿用 V3§3.2:367-371 (sentiment_score [-1,1] / confidence [0,1] / 4 category / 4 profile / P0-P3 urgency)
--
-- NEWS_STRATEGY_PROFILE 4 档 (V3§3.2:381-386):
--   ultra_short (intraday P0 push) / short (1-5d P1) / medium (1-4w P2) / long (1Q+ P3)
--
-- 4 category (V3§3.2:368): 利好/利空/中性/事件驱动
--
-- 4 urgency (V3§3.2:369): P0/P1/P2/P3
--
-- Prompt 沉淀 (V3§3.2:388-391): prompts/risk/news_classifier_v1.yaml
--   defer sub-PR 7b.2 (本 PR scope = DDL only, 反 yaml prompt sediment)
--
-- Rollback: 2026_05_06_news_classified_rollback.sql (DROP TABLE IF EXISTS + DO guard).
-- 关联铁律: 17 (DataPipeline 入库) / 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud DO guard) /
--           38 (Blueprint 真相源) / 41 (timezone TIMESTAMPTZ) / 45 (4 doc fresh read SOP)

-- ─────────────────────────────────────────────────────────────
-- Phase 1: CREATE TABLE (BEGIN/COMMIT 原子)
-- ─────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS news_classified (
    news_id                    BIGINT       PRIMARY KEY
                                            REFERENCES news_raw(news_id) ON DELETE CASCADE,  -- V3§3.2:366 FK + CASCADE 沿用 90d retention 时清理 child
    sentiment_score            NUMERIC(5,4) NOT NULL
                                            CHECK (sentiment_score BETWEEN -1 AND 1),    -- V3§3.2:367 [-1, 1]
    category                   VARCHAR(20)  NOT NULL
                                            CHECK (category IN ('利好', '利空', '中性', '事件驱动')),  -- V3§3.2:368
    urgency                    VARCHAR(4)   NOT NULL
                                            CHECK (urgency IN ('P0', 'P1', 'P2', 'P3')), -- V3§3.2:369
    confidence                 NUMERIC(5,4) NOT NULL
                                            CHECK (confidence BETWEEN 0 AND 1),          -- V3§3.2:370 [0, 1]
    profile                    VARCHAR(20)  NOT NULL
                                            CHECK (profile IN ('ultra_short', 'short', 'medium', 'long')),  -- V3§3.2:371
    classifier_model           VARCHAR(50)  NOT NULL,                                    -- "deepseek-chat" / "qwen3.5:9b" / etc
    classifier_prompt_version  VARCHAR(10)  NOT NULL,                                    -- "v1" 沿用 prompts/risk/news_classifier_v1.yaml
    classifier_cost            NUMERIC(8,4)
                                            CHECK (classifier_cost IS NULL OR classifier_cost >= 0),  -- USD, NULL = Ollama fallback
    classified_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()                       -- 分类入库时间 (铁律 41)
);

COMMENT ON TABLE news_classified IS
    'V3§3.2 NewsClassifier V4-Flash L0.2 output 表. sub-PR 7b.2 NewsClassifierService '
    '(defer 7b.1 prerequisite ready 后) consume news_raw → V4-Flash → JSON parse → 本表 入库. '
    '4 category (利好/利空/中性/事件驱动) + 4 urgency (P0-P3) + 4 profile (ultra_short/short/medium/long). '
    'FK news_raw(news_id) ON DELETE CASCADE — 沿用 news_raw 90d retention 真生产体例 (defer Sprint 3+).';

COMMENT ON COLUMN news_classified.news_id IS
    'V3§3.2:366 FK REFERENCES news_raw(news_id), ON DELETE CASCADE 真保证 1:1 mapping + retention 联动';
COMMENT ON COLUMN news_classified.sentiment_score IS 'V3§3.2:367 [-1, 1] — 利空 -1 / 中性 0 / 利好 +1';
COMMENT ON COLUMN news_classified.profile IS
    'V3§3.2 4 档: ultra_short (intraday P0 push) / short (1-5d P1) / medium (1-4w P2) / long (1Q+ P3)';
COMMENT ON COLUMN news_classified.classifier_cost IS
    'NUMERIC(8,4) USD, NULL = Ollama fallback (qwen3.5:9b 真本地 0 cost) 沿用 ADR-031 §6 Ollama 灾备';

COMMIT;

-- ─────────────────────────────────────────────────────────────
-- Phase 2: Index (按 profile + classified_at 真生产 query 模式)
-- ─────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_news_classified_profile_time
    ON news_classified (profile, classified_at DESC);

CREATE INDEX IF NOT EXISTS ix_news_classified_urgency_time
    ON news_classified (urgency, classified_at DESC)
    WHERE urgency IN ('P0', 'P1');  -- partial index, P0/P1 真热查询 (intraday push 路径)

-- ─────────────────────────────────────────────────────────────
-- Phase 3: Migration fail-loud guard (铁律 33, 沿用 news_raw.sql 体例)
-- ─────────────────────────────────────────────────────────────

DO $$
DECLARE
    col_count INT;
    fk_exists BOOL;
BEGIN
    SET LOCAL statement_timeout = '30s';

    -- 核心列存在性 (10 列, V3§3.2:365-376 真预约 sustained)
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'news_classified'
      AND column_name IN (
          'news_id', 'sentiment_score', 'category', 'urgency', 'confidence',
          'profile', 'classifier_model', 'classifier_prompt_version',
          'classifier_cost', 'classified_at'
      );
    IF col_count < 10 THEN
        RAISE EXCEPTION 'news_classified migration incomplete: only % of 10 required columns', col_count;
    END IF;

    -- FK news_raw(news_id) 验证 (V3§3.2:366 sustained)
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
        WHERE tc.table_name = 'news_classified'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND ccu.table_name = 'news_raw'
          AND ccu.column_name = 'news_id'
    ) INTO fk_exists;
    IF NOT fk_exists THEN
        RAISE EXCEPTION 'news_classified FK news_raw(news_id) 缺失 — V3§3.2:366 真依赖';
    END IF;
END $$;
