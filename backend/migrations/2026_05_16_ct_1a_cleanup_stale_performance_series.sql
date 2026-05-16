-- V3 Plan v0.4 CT-1a — DELETE 7-row stale performance_series
--
-- Phase 0 active discovery 2026-05-16: performance_series 4-20 ~ 4-28 has
-- 7 stale rows (one per trading day in the window) with stale-state signature:
--   - position_count = 19 (NOW 0 持仓 真值)
--   - nav ≈ ¥1.01M (NOW ¥993,520.66)
--   - execution_mode = 'live'
--   - strategy_id = 28fc37e5-2d32-4ada-92e0-41c11a5103d0
--
-- Note: performance_series 4-28 DOES have a row (NAV=1011714.08, pos_count=19)
-- but position_snapshot 4-28 has 0 rows — Beat 14:30 likely ran for one
-- table but not the other on 4-28 (paused-Beat-era cascade artifact, see
-- SHUTDOWN_NOTICE §3-5).
--
-- Sustained user 决议 (T1) 2026-05-16 — performance_series + position_snapshot
-- cleanup in same PR (NAV continuity restoration).
--
-- Apply via: scripts/v3_ct_1a_apply_cleanup.py --apply (user 同意 trigger
-- required per Plan §A 红线 SOP).

-- NOTE (code-reviewer P1 fix, 2026-05-16): removed inline BEGIN/COMMIT —
-- transaction boundary managed by `scripts/v3_ct_1a_apply_cleanup.py`
-- runner so position_snapshot + performance_series commit atomically.

SELECT 'CT-1a stale performance_series cleanup starting' AS audit_marker,
       NOW() AS started_at;

-- Pre-DELETE row count assertion (FAIL-LOUD if drift since Phase 0 verify).
DO $$
DECLARE
    pre_count INT;
BEGIN
    SELECT COUNT(*) INTO pre_count
    FROM performance_series
    WHERE trade_date BETWEEN '2026-04-20' AND '2026-04-28'
      AND execution_mode = 'live'
      AND strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0'
      AND position_count = 19;
    IF pre_count != 7 THEN
        RAISE EXCEPTION
            'CT-1a precondition failed: expected 7 performance_series rows '
            'to delete, got %. DB state drifted from Phase 0 verify '
            '2026-05-16. Re-run scripts/v3_ct_1a_apply_cleanup.py --dry-run '
            'first.', pre_count;
    END IF;
END $$;

-- DELETE 7 stale rows. Constrain via position_count=19 as additional safety
-- (ensures we never touch a non-stale row even if date filter were off).
DELETE FROM performance_series
WHERE trade_date BETWEEN '2026-04-20' AND '2026-04-28'
  AND execution_mode = 'live'
  AND strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0'
  AND position_count = 19;

-- Post-DELETE assertion.
DO $$
DECLARE
    post_count INT;
BEGIN
    SELECT COUNT(*) INTO post_count
    FROM performance_series
    WHERE trade_date BETWEEN '2026-04-20' AND '2026-04-28'
      AND execution_mode = 'live'
      AND strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0'
      AND position_count = 19;
    IF post_count != 0 THEN
        RAISE EXCEPTION
            'CT-1a post-DELETE assertion failed: expected 0 stale '
            'performance_series rows remaining, got %. ROLLBACK initiated.',
            post_count;
    END IF;
END $$;

-- NOTE: runner-managed transaction boundary.

-- 关联: V3 Plan v0.4 §A CT-1 row + 铁律 22/33/42 + LL-098 X10 +
--   LL-159/172 + SHUTDOWN_NOTICE §3 (DB drift NAV diff -1.8%) +
--   ADR-081 候选 (CT-1 closure) + user 决议 T1 2026-05-16
