-- D1 O8 — automation-level persistence (PN-001 iter 10, 2026-05-23)
-- 铁律 32: 调用方管事务, 表本身无 FK/CASCADE
--
-- 依赖: 无
-- 回滚: pipeline_settings_rollback.sql (配对)
-- 设计: docs/design/PN_001_automation_level_persistence.md

-- ── Singleton 表 — pipeline 运行时 UI 设置 ──────────────────────

CREATE TABLE IF NOT EXISTS pipeline_settings (
    -- Singleton enforce: CHECK (id = 1) + PRIMARY KEY → 只允许 1 row
    id               INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),

    -- 自动化级别 (L4R spec L0-L4 enum)
    automation_level VARCHAR(8) NOT NULL DEFAULT 'L0'
                        CHECK (automation_level IN ('L0','L1','L2','L3','L4')),

    -- 最后更新时间 (trigger 自动维护)
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- 更新者 (默认 NULL, 待 auth/RBAC 接入后填充, PN-001 §6 out-of-scope)
    updated_by       VARCHAR(64)
);

COMMENT ON TABLE pipeline_settings IS 'Singleton 表 — pipeline 运行时 UI 设置 (D1 O8 iter 10, PN-001)';
COMMENT ON COLUMN pipeline_settings.id IS 'Singleton enforce: CHECK (id = 1) + PK → 仅 1 row 合法';
COMMENT ON COLUMN pipeline_settings.automation_level IS '用户选定的自动化级别 (L4R spec L0-L4). L0=手动, L4=完全自主';
COMMENT ON COLUMN pipeline_settings.updated_by IS 'NULL 直至 auth/RBAC 引入 (PN-001 §6 显式 out-of-scope)';

-- 自动维护 updated_at (沿用 strategy_registry trigger 体例).
-- 注: PostgreSQL ON CONFLICT DO UPDATE 路径触发 BEFORE UPDATE row trigger
-- (DO UPDATE 在 trigger 语义上等同于普通 UPDATE), 所以 UPSERT 也会刷新 updated_at.
CREATE OR REPLACE FUNCTION _pipeline_settings_touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pipeline_settings_touch ON pipeline_settings;
CREATE TRIGGER trg_pipeline_settings_touch
    BEFORE UPDATE ON pipeline_settings
    FOR EACH ROW EXECUTE FUNCTION _pipeline_settings_touch_updated_at();

-- ── Singleton seed (idempotent) ───────────────────────────────────

INSERT INTO pipeline_settings (id, automation_level)
VALUES (1, 'L0')
ON CONFLICT (id) DO NOTHING;

-- ── D1 O3 — Pause gate (PN-003 iter 12, 2026-05-23/24) ────────────
-- Gate-at-entry semantics: paused_at IS NOT NULL → POST /trigger 409
-- + Beat run_gp_mining / run_bruteforce_mining skip-and-log. Mid-run
-- cooperative abort is OUT OF SCOPE (deferred to future iter).

ALTER TABLE pipeline_settings
    ADD COLUMN IF NOT EXISTS paused_at      TIMESTAMP WITH TIME ZONE NULL,
    ADD COLUMN IF NOT EXISTS paused_reason  TEXT NULL;

COMMENT ON COLUMN pipeline_settings.paused_at IS
    'NULL = active; NOT NULL = paused since this timestamp (gate-at-entry only, mid-run not aborted)';
COMMENT ON COLUMN pipeline_settings.paused_reason IS
    '可选暂停理由 (≤500 字), UI 显示用 (PN-003 §3)';

-- ── 验证 (注释, 迁移后手工跑) ──────────────────────────────────
-- SELECT * FROM pipeline_settings;  -- 预期 1 row (id=1, automation_level='L0', paused_at=NULL)
-- SELECT column_name, data_type, is_nullable, column_default
--   FROM information_schema.columns WHERE table_name='pipeline_settings' ORDER BY ordinal_position;
