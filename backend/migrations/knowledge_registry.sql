-- MVP 1.4 · Knowledge Registry — 3 张新表
--
-- 创建:
--   1. platform_experiments — 实验记录 (hypothesis / status / author / verdict / artifacts / tags)
--   2. failed_directions — 失败方向库 (direction UNIQUE / reason / evidence / severity / source / tags)
--   3. adr_records — 架构决策记录 (adr_id / title / status / context / decision / related_ironlaws)
--
-- 设计原则:
--   - 幂等 (CREATE TABLE IF NOT EXISTS)
--   - 不动老 `experiments` 表 (0 rows, 保留给 MVP 2.x 清理)
--   - 不动 `mining_knowledge` 表 (GP 挖掘专用, 语义隔离)
--   - 对齐 MVP 1.1 backend/platform/knowledge/interface.py 3 个 Record dataclass
--
-- 关联铁律: 22 (文档跟随代码) / 38 (Blueprint 真相源) / 40 (测试债务不增长)

-- pgcrypto for gen_random_uuid() (PG 13+ 内置, CREATE EXTENSION 幂等)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────
-- 1. platform_experiments — 对齐 ExperimentRecord (interface.py L19)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS platform_experiments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hypothesis   TEXT NOT NULL,
    status       VARCHAR(16) NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'success', 'failed', 'inconclusive')),
    author       VARCHAR(64) NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    verdict      TEXT,
    artifacts    JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX IF NOT EXISTS ix_platform_exp_status
    ON platform_experiments(status, started_at DESC);

CREATE INDEX IF NOT EXISTS ix_platform_exp_tags_gin
    ON platform_experiments USING GIN(tags);

COMMENT ON TABLE platform_experiments IS
    'MVP 1.4 Knowledge Registry — 实验记录 (hypothesis → verdict). 对齐 backend/platform/knowledge/interface.py::ExperimentRecord';

-- ─────────────────────────────────────────────────────────────
-- 2. failed_directions — 对齐 FailedDirectionRecord (interface.py L46)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS failed_directions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    direction   TEXT NOT NULL UNIQUE,
    reason      TEXT NOT NULL,
    evidence    JSONB NOT NULL DEFAULT '[]'::jsonb,
    severity    VARCHAR(16) NOT NULL DEFAULT 'terminal'
                CHECK (severity IN ('terminal', 'conditional')),
    source      VARCHAR(128),  -- "CLAUDE.md" / "docs/research-kb/failed/xxx.md" / "manual"
    tags        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_failed_dirs_severity
    ON failed_directions(severity, recorded_at DESC);

CREATE INDEX IF NOT EXISTS ix_failed_dirs_tags_gin
    ON failed_directions USING GIN(tags);

-- trigger to auto-update updated_at on UPDATE (复用 MVP 1.2 feature_flags 模式)
CREATE OR REPLACE FUNCTION _failed_directions_touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_failed_directions_touch ON failed_directions;
CREATE TRIGGER tr_failed_directions_touch
    BEFORE UPDATE ON failed_directions
    FOR EACH ROW EXECUTE FUNCTION _failed_directions_touch_updated_at();

COMMENT ON TABLE failed_directions IS
    'MVP 1.4 Knowledge Registry — 失败方向库 (防重复踩坑). 对齐 FailedDirectionRecord. 注: mining_knowledge 是 GP 因子级失败, 本表是研究方向级.';

-- ─────────────────────────────────────────────────────────────
-- 3. adr_records — 对齐 ADRRecord (interface.py L65)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS adr_records (
    adr_id           VARCHAR(16) PRIMARY KEY,  -- "ADR-001"
    title            TEXT NOT NULL,
    status           VARCHAR(64) NOT NULL DEFAULT 'accepted',
                     -- proposed / accepted / deprecated / superseded_by:ADR-NNN (拼接串需要空间)
    context          TEXT NOT NULL,
    decision         TEXT NOT NULL,
    consequences     TEXT NOT NULL,
    related_ironlaws INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    file_path        TEXT,  -- "docs/adr/ADR-001-*.md"
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_adr_ironlaws_gin
    ON adr_records USING GIN(related_ironlaws);

CREATE INDEX IF NOT EXISTS ix_adr_status
    ON adr_records(status, recorded_at DESC);

COMMENT ON TABLE adr_records IS
    'MVP 1.4 Knowledge Registry — ADR 索引 (markdown 是权威, DB 用于查询). 对齐 ADRRecord. 补充 Blueprint (铁律 38) 细粒度决策记录.';

-- ─────────────────────────────────────────────────────────────
-- END — 验证: 跑 knowledge_registry_rollback.sql 可完全还原
-- ─────────────────────────────────────────────────────────────
