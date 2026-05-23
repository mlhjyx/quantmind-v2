-- Rollback for pipeline_settings.sql (D1 O8 iter 10, PN-001)
-- 安全: 0 FK refs, 0 downstream consumer (除 GET/PUT /api/pipeline/automation-level endpoint).
-- Drop 后 frontend setAutomationLevel() 会再次 404, 与 pre-PN-001 baseline 一致.

DROP TRIGGER IF EXISTS trg_pipeline_settings_touch ON pipeline_settings;
DROP FUNCTION IF EXISTS _pipeline_settings_touch_updated_at();
DROP TABLE IF EXISTS pipeline_settings;
