-- MVP 1.2 Config Management — FeatureFlag 存储
-- 铁律 32 约束: 调用方管事务, 表本身无其他表级约束

CREATE TABLE IF NOT EXISTS feature_flags (
    name          TEXT PRIMARY KEY,
    enabled       BOOLEAN NOT NULL DEFAULT FALSE,
    removal_date  DATE NOT NULL,
    description   TEXT NOT NULL,
    created_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE feature_flags IS 'MVP 1.2 FeatureFlag storage (single-user binary on-off + removal_date enforcement)';
COMMENT ON COLUMN feature_flags.removal_date IS 'Flag 必须在此日期前移除; 过期后 is_enabled() raise FlagExpired (防永久 flag 债)';

CREATE INDEX IF NOT EXISTS idx_feature_flags_removal_date ON feature_flags (removal_date);

-- 自动维护 updated_at
CREATE OR REPLACE FUNCTION _feature_flags_touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_feature_flags_touch ON feature_flags;
CREATE TRIGGER trg_feature_flags_touch
    BEFORE UPDATE ON feature_flags
    FOR EACH ROW EXECUTE FUNCTION _feature_flags_touch_updated_at();
