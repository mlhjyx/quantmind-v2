-- V3 Plan v0.4 CT-1a — DELETE 6-date stale position_snapshot rows
--
-- Phase 0 active discovery 2026-05-16 (sustained LL-159 step 2 + LL-172
-- lesson 1 amended preflight via _ct1a_phase0_db_verify.py SQL evidence):
--   - Plan §A 'cb_state' cite drift: actual table = circuit_breaker_state,
--     `live` row already reset to ¥993,520.16 on 2026-04-30 (cited
--     trigger_reason="PT restart gate cleanup 2026-04-30"). NO action this PR.
--   - Plan §A '4-28 stale' cite drift: position_snapshot 4-28 = 0 rows
--     (Beat paused before 4-28 close). Actual stale dates =
--     [2026-04-20, 04-21, 04-22, 04-23, 04-24, 04-27] × 19 rows = 114 rows.
--     Sustained user 决议 (D1) 2026-05-16 — DELETE all 6 dates.
--   - Strategy: 28fc37e5-2d32-4ada-92e0-41c11a5103d0 (CORE3+dv_ttm WF PASS).
--   - execution_mode='live' (PT 真账户 stale; paper-mode rows out of scope).
--
-- Safety guards:
--   - Explicit trade_date IN (...) list (NOT range) — avoid accidental
--     DELETE of pre-2026-04 or post-2026-04-27 rows.
--   - execution_mode='live' filter — paper-mode rows preserved.
--   - strategy_id filter — other strategies preserved.
--   - rollback SQL file companion (2026_05_16_ct_1a_*_rollback.sql) +
--     pre-DELETE snapshot captured by apply runner to JSON.
--
-- Apply via: scripts/v3_ct_1a_apply_cleanup.py --apply (user 同意 trigger
-- required per Plan §A 红线 SOP "user 显式 SQL DELETE trigger required").
--
-- Expected DELETE count: exactly 114 rows. Verify post-apply via:
--   SELECT COUNT(*) FROM position_snapshot
--   WHERE trade_date IN ('2026-04-20','2026-04-21','2026-04-22','2026-04-23',
--                        '2026-04-24','2026-04-27')
--   AND execution_mode='live' AND strategy_id='28fc37e5-...'
--   → expected 0

-- NOTE (code-reviewer P1 fix, 2026-05-16): removed inline BEGIN/COMMIT —
-- transaction boundary managed by `scripts/v3_ct_1a_apply_cleanup.py`
-- runner so position_snapshot DELETE + performance_series DELETE commit
-- atomically together. Partial-failure scenario (position_snapshot
-- committed + performance_series fails) is now impossible.

SELECT 'CT-1a stale position_snapshot cleanup starting' AS audit_marker,
       NOW() AS started_at;

-- Pre-DELETE row count assertion (FAIL-LOUD if drift since Phase 0 verify).
DO $$
DECLARE
    pre_count INT;
BEGIN
    SELECT COUNT(*) INTO pre_count
    FROM position_snapshot
    WHERE trade_date IN ('2026-04-20', '2026-04-21', '2026-04-22',
                         '2026-04-23', '2026-04-24', '2026-04-27')
      AND execution_mode = 'live'
      AND strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0';
    IF pre_count != 114 THEN
        RAISE EXCEPTION
            'CT-1a precondition failed: expected 114 rows to delete, got %. '
            'DB state has drifted from Phase 0 verify 2026-05-16. '
            'Re-run scripts/v3_ct_1a_apply_cleanup.py --dry-run first.',
            pre_count;
    END IF;
END $$;

-- DELETE 114 stale rows.
DELETE FROM position_snapshot
WHERE trade_date IN ('2026-04-20', '2026-04-21', '2026-04-22',
                     '2026-04-23', '2026-04-24', '2026-04-27')
  AND execution_mode = 'live'
  AND strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0';

-- Post-DELETE assertion (must equal 0 for cleaned dates).
DO $$
DECLARE
    post_count INT;
BEGIN
    SELECT COUNT(*) INTO post_count
    FROM position_snapshot
    WHERE trade_date IN ('2026-04-20', '2026-04-21', '2026-04-22',
                         '2026-04-23', '2026-04-24', '2026-04-27')
      AND execution_mode = 'live'
      AND strategy_id = '28fc37e5-2d32-4ada-92e0-41c11a5103d0';
    IF post_count != 0 THEN
        RAISE EXCEPTION
            'CT-1a post-DELETE assertion failed: expected 0 rows remaining, '
            'got %. ROLLBACK initiated.', post_count;
    END IF;
END $$;

-- NOTE (code-reviewer P1 fix): runner-managed transaction boundary —
-- conn.commit() invoked AFTER both migration files succeed.

-- 关联: V3 Plan v0.4 §A CT-1 row + 铁律 22/33/42 + LL-098 X10 +
--   LL-159/172 (4-step preflight + multi-directory grep amended) +
--   SHUTDOWN_NOTICE §9.2 (DB cleanup prereq) + ADR-081 候选 (CT-1 closure)
