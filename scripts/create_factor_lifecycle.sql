-- Factor Lifecycle Management Table (Sprint 1.5)
CREATE TABLE IF NOT EXISTS factor_lifecycle (
    factor_name VARCHAR(50) PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'active', 'monitoring', 'warning', 'retired')),
    entry_date DATE,
    entry_ic DECIMAL(8,4),
    entry_t_stat DECIMAL(8,4),
    rolling_ic_12m DECIMAL(8,4),
    rolling_ic_updated DATE,
    warning_date DATE,
    retired_date DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE factor_lifecycle IS 'Factor lifecycle management - Sprint 1.5';
COMMENT ON COLUMN factor_lifecycle.status IS 'Status: candidate/active/monitoring/warning/retired';
COMMENT ON COLUMN factor_lifecycle.entry_ic IS 'IC at entry (Spearman rank correlation)';
COMMENT ON COLUMN factor_lifecycle.entry_t_stat IS 'IC t-statistic at entry';
COMMENT ON COLUMN factor_lifecycle.rolling_ic_12m IS 'Rolling 12-month average IC';
COMMENT ON COLUMN factor_lifecycle.rolling_ic_updated IS 'Last update date of rolling IC';
COMMENT ON COLUMN factor_lifecycle.warning_date IS 'Date entered warning status';
COMMENT ON COLUMN factor_lifecycle.retired_date IS 'Date retired';

-- Insert 5 Active factors (v1.1 baseline)
INSERT INTO factor_lifecycle (factor_name, status, entry_date, entry_ic, entry_t_stat, notes)
VALUES
    ('turnover_mean_20', 'active', '2026-03-20', -0.0643, -7.31, 'v1.1 Active, IR=-0.73, 7/7 year consistent'),
    ('volatility_20',    'active', '2026-03-20', -0.0690, -6.37, 'v1.1 Active, |IC| largest, 7/7 year consistent'),
    ('reversal_20',      'active', '2026-03-20',  0.0386,  3.50, 'v1.1 Active, 6/7 year consistent'),
    ('amihud_20',        'active', '2026-03-20',  0.0215,  2.69, 'v1.1 Active, liquidity factor'),
    ('bp_ratio',         'active', '2026-03-20',  0.0523,  6.02, 'v1.1 Active, strongest value factor')
ON CONFLICT (factor_name) DO UPDATE SET
    status = EXCLUDED.status,
    entry_date = EXCLUDED.entry_date,
    entry_ic = EXCLUDED.entry_ic,
    entry_t_stat = EXCLUDED.entry_t_stat,
    notes = EXCLUDED.notes,
    updated_at = CURRENT_TIMESTAMP;

SELECT factor_name, status, entry_ic, entry_t_stat FROM factor_lifecycle ORDER BY factor_name;
