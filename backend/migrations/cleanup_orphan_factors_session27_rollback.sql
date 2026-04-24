-- Session 27 Task B rollback for cleanup_orphan_factors_session27.sql
--
-- 仅当 cleanup migration 导致意外问题时使用. 配套前向 SQL 行 DELETE/UPDATE 的
-- 逆操作 (恢复 mf_momentum_divergence 1 行 + UPDATE 10 行回原 status/pool).
--
-- ⚠️ 注意: 本 rollback 仅恢复 factor_registry 行, 不恢复代码侧同步 (已由 git
-- revert 对应 commit 处理). 正确顺序: 1) git revert commit; 2) 跑本 rollback SQL.

BEGIN;

-- ── 恢复 mf_momentum_divergence (类别 A) ──────────────────────
-- 依据 Session 27 pre-cleanup DB state (2026-04-24).
-- 若字段与 DDL 不一致 (新增列), 需按 DDL 对齐 — created_at/updated_at 用 NOW()
-- 保守, expression/hypothesis/source/lookback_days 使用 backfill_factor_registry
-- Layer 2 推断值.
INSERT INTO factor_registry
    (name, category, direction, expression, hypothesis, source,
     lookback_days, status, pool, created_at, updated_at)
VALUES (
    'mf_momentum_divergence',
    'moneyflow',
    -1,
    NULL,
    '[AUTO_BACKFILL] mf_momentum_divergence: hardcoded direction=-1 from _constants.py/signal_engine.py',
    'builtin',
    60,
    'deprecated',
    'INVALIDATED',
    NOW(),
    NOW()
)
ON CONFLICT (name) DO NOTHING;  -- 若已存在则不覆盖

-- ── 恢复 10 条 UPDATE (类别 B) ────────────────────────────────
UPDATE factor_registry
SET status = 'warning',
    pool = 'PASS',
    updated_at = NOW()
WHERE name IN (
    'pead_q1',
    'earnings_surprise_car',
    'eps_acceleration',
    'gross_margin_delta',
    'net_margin_delta',
    'revenue_growth_yoy',
    'roe_delta',
    'debt_change',
    'days_since_announcement',
    'reporting_season_flag'
  )
  AND status = 'deprecated'
  AND pool = 'DEPRECATED';

DO $$
DECLARE
    restored_count INT;
BEGIN
    SELECT COUNT(*)
    INTO restored_count
    FROM factor_registry
    WHERE name IN (
        'mf_momentum_divergence', 'pead_q1', 'earnings_surprise_car',
        'eps_acceleration', 'gross_margin_delta', 'net_margin_delta',
        'revenue_growth_yoy', 'roe_delta', 'debt_change',
        'days_since_announcement', 'reporting_season_flag'
    );
    RAISE NOTICE 'Post-rollback restored count (expected 11): %', restored_count;
END $$;

COMMIT;
