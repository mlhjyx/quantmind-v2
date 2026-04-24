-- Session 27 Task B: factor_registry orphan 清理 (Task A+B 同 Session)
--
-- 背景: audit_orphan_factors 识别出 11 个 factor_registry 条目在 factor_values
-- 无任何数据 (SELECT DISTINCT factor_name FROM factor_values 缺, Layer3 = 空).
-- 分两类:
--   A. INVALIDATED 历史证伪 (1): mf_momentum_divergence
--      (v3.4 证伪 IC=-2.27% 非宣称 9.1%, docs/research-kb failed_directions 已记)
--   B. PEAD/earnings ghost (10): 研究阶段通过 G1-G8 PASS 但无生产 pipeline,
--      factor_engine/pead.py 仅有 calc_pead_q1_from_announcements, 其他 9 个无 calc.
--
-- 影响 (不清理 → 每日 compute_daily_ic + compute_ic_rolling 以 status IN
-- ('active','warning') 查询, 这 11 条持续 SELECT 出然后 SKIP 产生噪声 log).
--
-- 清理方案:
--   - 1 行 DELETE (mf_momentum_divergence, 无数据 + 无代码 + failed_directions 已记)
--   - 10 行 UPDATE (status warning→deprecated, pool PASS→DEPRECATED)
--     * 对齐现有 4 条 `status=deprecated + pool=DEPRECATED` 惯例
--     * deprecated 状态脱离 daily IC/rolling 的 IN 过滤
--     * 保留 registry 行本身 (未来 Phase X PEAD 生产化再 UPDATE 回 active)
--
-- 配套代码同步 (同 PR, 防 backfill_factor_registry.py 重跑 revert):
--   - scripts/registry/backfill_factor_registry.py 删 2 条 _HARDCODED_DIRECTIONS
--   - backend/engines/factor_engine/_constants.py 删 PEAD/FUNDAMENTAL*_META 11 条
--   - backend/engines/signal_engine.py 删 FACTOR_DIRECTION 2 条
--
-- 回滚: cleanup_orphan_factors_session27_rollback.sql (配对)

BEGIN;

-- ── 类别 A: DELETE 1 条 ────────────────────────────────────────
-- mf_momentum_divergence: INVALIDATED + deprecated + 0 rows
-- 原 INSERT values (若 rollback 需要):
--   name='mf_momentum_divergence', category='moneyflow', direction=-1,
--   status='deprecated', pool='INVALIDATED',
--   source='builtin', lookback_days=60
DELETE FROM factor_registry
WHERE name = 'mf_momentum_divergence';

-- ── 类别 B: UPDATE 10 条 ──────────────────────────────────────
-- 所有 10 条 before: status='warning', pool='PASS'
-- after: status='deprecated', pool='DEPRECATED'
UPDATE factor_registry
SET status = 'deprecated',
    pool = 'DEPRECATED',
    updated_at = NOW()
WHERE name IN (
    'pead_q1',                -- factor_engine/pead.py 有 calc 但无 daily pipeline
    'earnings_surprise_car',  -- ghost: signal_engine.FACTOR_DIRECTION 有 direction 但无 calc
    'eps_acceleration',       -- ghost: _constants.FUNDAMENTAL_DELTA_META 有 meta 但无 calc
    'gross_margin_delta',     -- ghost: 同上
    'net_margin_delta',       -- ghost: 同上
    'revenue_growth_yoy',     -- ghost: 同上
    'roe_delta',              -- ghost: 同上
    'debt_change',            -- ghost: 同上
    'days_since_announcement',-- ghost: _constants.FUNDAMENTAL_TIME_META 有 meta 但无 calc
    'reporting_season_flag'   -- ghost: 同上
  )
  AND status = 'warning'      -- idempotency guard: 若已 deprecated 不重复更新
  AND pool = 'PASS';

-- ── 验证 ──────────────────────────────────────────────────────
-- 预期: UPDATE 10 rows, DELETE 1 row. 后 factor_registry 286 条 (287-1).
-- 预期: status IN ('active', 'warning') 过滤少 10 (实际 11 - pead_q1 本已 warning).
DO $$
DECLARE
    remaining_orphan INT;
BEGIN
    -- orphan = 在 factor_registry 但 factor_values 无数据的 non-deprecated 行
    SELECT COUNT(*)
    INTO remaining_orphan
    FROM factor_registry fr
    WHERE fr.status IN ('active', 'warning')
      AND NOT EXISTS (
          SELECT 1 FROM (SELECT DISTINCT factor_name FROM factor_values) fv
          WHERE fv.factor_name = fr.name
      );
    -- 预期 = 0 (清理成功)
    RAISE NOTICE 'Post-cleanup orphan count (active/warning but no factor_values): %', remaining_orphan;
    IF remaining_orphan > 0 THEN
        RAISE WARNING 'Still % orphan factor(s) remain — investigate!', remaining_orphan;
    END IF;
END $$;

COMMIT;
