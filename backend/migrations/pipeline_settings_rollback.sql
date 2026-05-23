-- Rollback for pipeline_settings.sql (D1 O8 iter 10, PN-001 + D1 O3 iter 12, PN-003)
-- 安全: 0 FK refs, 0 downstream consumer (除 GET/PUT /api/pipeline/automation-level
-- endpoint + POST /api/pipeline/pause + /resume endpoints).
-- Drop 后 frontend setAutomationLevel() / pausePipeline() / resumePipeline() 会再次 404.

-- D1 O3 (PN-003 iter 12) — pause columns rollback first (partial rollback safe)
ALTER TABLE IF EXISTS pipeline_settings
    DROP COLUMN IF EXISTS paused_reason,
    DROP COLUMN IF EXISTS paused_at;

-- D1 O8 (PN-001 iter 10) — full table rollback
DROP TRIGGER IF EXISTS trg_pipeline_settings_touch ON pipeline_settings;
DROP FUNCTION IF EXISTS _pipeline_settings_touch_updated_at();
DROP TABLE IF EXISTS pipeline_settings;
