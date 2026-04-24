-- Session 27 Task B rollback for cleanup_orphan_factors_session27.sql
--
-- 仅当 cleanup migration 导致意外问题时使用. 配套前向 SQL 行 DELETE/UPDATE 的
-- 逆操作 (恢复 mf_momentum_divergence 1 行 + UPDATE 10 行回原 status/pool).
--
-- ⚠️ 注意: 本 rollback 仅恢复 factor_registry 行, 不恢复代码侧同步 (已由 git
-- revert 对应 commit 处理). 正确顺序: 1) git revert commit; 2) 跑本 rollback SQL.

BEGIN;

-- ── 恢复 mf_momentum_divergence (类别 A) ──────────────────────
-- DDL 对齐 (Session 27 reviewer P2.1 database 采纳, 2026-04-24 实测
-- information_schema.columns):
--   id              uuid    NOT NULL DEFAULT gen_random_uuid()  → 省略可用 default
--   category        varchar NOT NULL (no default)               → 必填 'moneyflow'
--   direction       smallint NOT NULL DEFAULT 1                 → 提供 -1
--   pool            varchar NOT NULL DEFAULT 'CANDIDATE'        → 提供 INVALIDATED
--   gate_*, code_content, expression, hypothesis, status, ic_decay_ratio → NULL OK
--   source/lookback_days DEFAULT 'builtin' / 60                 → 提供对齐 backfill
--   created_at/updated_at DEFAULT now()                         → 提供 NOW() 保守
--
-- 依据 Session 27 pre-cleanup DB state. source/hypothesis/lookback_days 使用
-- backfill_factor_registry Layer 2 推断值 (对齐 _SIGNAL_ENGINE_DIRECTION 推断).
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
-- Reviewer P1 (code) 采纳: ON CONFLICT DO UPDATE 保证多次 rollback/re-apply
-- 幂等. 原 DO NOTHING 对遗留错状态行静默, 导致 "rollback 表面成功但 status/pool
-- 仍是错值". UPDATE SET 强制对齐关键字段.
ON CONFLICT (name) DO UPDATE
    SET pool = EXCLUDED.pool,
        status = EXCLUDED.status,
        direction = EXCLUDED.direction,
        category = EXCLUDED.category,
        updated_at = NOW();

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
