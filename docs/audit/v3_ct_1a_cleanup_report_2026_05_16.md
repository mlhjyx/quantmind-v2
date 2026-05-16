# V3 CT-1a — DB Stale Snapshot Cleanup Report (ADR-081 partial)

**Run date**: 2026-05-16
**Status**: ⏳ PENDING USER 显式 APPLY TRIGGER (per Plan §A 红线 SOP)
**Main HEAD at PR creation**: `d18b8d1` (post IC-3d closure)
**Branch**: `v3-pt-cutover-ct-1a`

**Scope**: V3 Plan v0.4 §A CT-1a — first non-zero-mutation sprint cleanup
of stale DB rows that survived 4-29 emergency_close cascade. Mutation type
= DB row DELETE on production tables (NOT .env / yaml / broker).

---

## §1 Phase 0 active discovery — 3 cite-drift findings + 1 data-quality finding

Per LL-159 amended preflight + LL-172 lesson 1 multi-directory grep SOP,
Phase 0 SQL verify 2026-05-16 surfaced sediment-narrative cite-drift across
Plan v0.4 §A + SHUTDOWN_NOTICE §9.2:

| # | Plan §A / SHUTDOWN_NOTICE claim | Phase 0 SQL truth | Action |
|---|---|---|---|
| 1 | Table = `cb_state` | Actual: `circuit_breaker_state` | Plan §A cite fix (本 PR) |
| 2 | `cb_state` reset to ¥993,520 (pending) | `circuit_breaker_state.live` **already reset** 2026-04-30 19:48 (`trigger_reason="PT restart gate cleanup 2026-04-30"`, `nav=993520.16`) | NO action — pre-existing closed |
| 3 | "4-28 stale snapshot 19 股" | position_snapshot 4-28 = 0 rows; actual stale = **114 rows** across **6 dates** `[2026-04-20, 04-21, 04-22, 04-23, 04-24, 04-27]` × 19; performance_series 4-28 = 1 row stale; broader scope = 7 performance_series rows | DELETE 114 + 7 = 121 stale rows |
| 4 | 19 snapshot vs 17 emergency_close (data quality) | 17 sold + 1 跌停 cancel (688121.SH) + **1 missing sell row** (000012.SZ, snapshot qty=10700 but NO sell row in trade_log post-4-27) | Data quality finding sediment for ADR-081 (§5) |

**Critical takeaway**: 4-29 narrative "17 emergency_close + 1 trapped" is
真值; but 000012.SZ has a snapshot qty without subsequent sell row — silent
F-D3A-1-like drift. xtquant 0-持仓 ground truth sustains (cash=¥993,520.66),
so this is a TRADE_LOG completeness gap NOT a real-position gap. Out of
CT-1a scope; recorded for future trade_log F-D3A-1 cleanup audit.

---

## §2 ADR-081 selection criteria (sustained ADR-080 体例)

Mutation scope criteria for CT-1a:

1. **Real production tables**: position_snapshot + performance_series rows
   on `execution_mode='live'` with `strategy_id='28fc37e5-...'` (CORE3+dv_ttm
   WF PASS strategy).
2. **Phase 0 SQL evidence**: exact row count + per-date verification.
3. **Pre-DELETE snapshot capture**: JSON snapshot to
   `docs/audit/v3_ct_1a_rollback_snapshot_2026_05_16.json` for ADR-022
   reversibility.
4. **Assertion-guarded SQL**: pre-DELETE + post-DELETE row count assertions
   in DO blocks; FAIL-LOUD on count drift.
5. **User 显式 trigger required**: per Plan §A 红线 SOP "user 显式 SQL
   DELETE trigger required". 3-step gate: PR creation → reviewer review
   → user "同意 apply" → CC executes `--apply`.
6. **Rollback safety**: `--rollback` flag reads JSON snapshot + re-INSERTs;
   manual fallback documented in rollback SQL companion files.

**Rejected candidates** (criteria 1 not satisfied):
- `circuit_breaker_state.live` NAV reset: pre-closed 2026-04-30 (Plan §A
  cite was stale; no action this PR).
- 000012.SZ trade_log missing sell row: production table mutation NOT in
  cleanup scope (out of CT-1a; would require INSERT NOT DELETE).
- `risk_event_log` 4-28 rows + `execution_plans` 4-28 rows: not stale-state
  (operational records, sustained as evidence).

---

## §3 Cleanup deliverables

### §3.1 SQL migrations (assertion-guarded)

| File | Operation | Rows | Safety |
|---|---|---|---|
| `backend/migrations/2026_05_16_ct_1a_cleanup_stale_position_snapshot.sql` | DELETE position_snapshot | 114 (6 dates × 19) | pre + post DO block assertions; trade_date IN explicit list; execution_mode='live' + strategy_id filter |
| `backend/migrations/2026_05_16_ct_1a_cleanup_stale_position_snapshot_rollback.sql` | rollback docstring | n/a | references JSON snapshot + Python --rollback runner |
| `backend/migrations/2026_05_16_ct_1a_cleanup_stale_performance_series.sql` | DELETE performance_series | 7 (4-20 ~ 4-28) | extra `position_count = 19` filter as belt-and-suspenders |
| `backend/migrations/2026_05_16_ct_1a_cleanup_stale_performance_series_rollback.sql` | rollback docstring | n/a | references JSON snapshot |

### §3.2 Apply runner

`scripts/v3_ct_1a_apply_cleanup.py` — 3 modes:
- `--dry-run` (default): Phase 0 preflight + verify SQL semantics; 0 DB
  mutation. Safe to run multiple times.
- `--apply`: BLOCKED until user 显式 trigger. Full pipeline (preflight +
  snapshot capture + DELETE + post-verify).
- `--rollback`: re-INSERT from JSON snapshot.

Pipeline (--apply):
1. Preflight verify (red-line invariants + count match)
2. Snapshot capture → JSON (atomic write)
3. Execute migrations (transactional, COMMIT on success / ROLLBACK on failure)
4. Post-verify (stale rows == 0 + circuit_breaker_state untouched +
   latest performance_series untouched)

### §3.3 Tests

`backend/tests/test_v3_ct_1a_apply_cleanup.py` — 25 PURE tests (0 DB hit):
- 5 constant invariants (strategy_id, dates, counts)
- 5 migration file content checks (assertions, position_count=19 guard,
  rollback file existence)
- 3 _PreflightResult shape tests
- 4 _verify_preflight tests with _MockCursor (success + 3 drift scenarios
  + env-check block)
- 3 snapshot capture + atomic write tests
- 2 rollback re-INSERT tests
- 3 Phase 0 invariant tests

---

## §4 Apply procedure (user reference for "同意 apply" trigger)

When user is ready to apply (post-review, post-redline-guardian invocation):

```powershell
# Step 1: Pre-apply preflight (re-verify, no mutation)
python scripts/v3_ct_1a_apply_cleanup.py --dry-run
# Expect: "ALL PREFLIGHT CHECKS ✅ PASS"

# Step 2: Apply (mutation)
python scripts/v3_ct_1a_apply_cleanup.py --apply
# Expect: "POST-VERIFY PASS: stale rows deleted, ..."

# Step 3: Verify JSON snapshot captured
ls docs/audit/v3_ct_1a_rollback_snapshot_2026_05_16.json
```

Rollback (if needed post-apply):
```powershell
python scripts/v3_ct_1a_apply_cleanup.py --rollback
```

---

## §5 Data quality finding (out of CT-1a scope, sediment for future)

**000012.SZ trade_log completeness gap**:
- position_snapshot 4-27: qty=10700, avg_cost=4.52, mv=47615
- trade_log buy rows: 4-14 (10700 @4.52) + 4-16 (10700 @4.4919) = 2 buy rows
- trade_log sell rows: **NONE** for 000012.SZ
- xtquant真账户: 0 持仓 (per SHUTDOWN_NOTICE §2 实测)

→ Either (a) 000012.SZ was sold in xtquant via path outside trade_log
recording, OR (b) the 2 buy rows for 4-14 + 4-16 represent same position
(double-recorded due to F19-like reject_reason recovery cascade). Sustained
F-D3A-1 silent drift pattern (LL-141 lesson candidate). NOT addressed in
CT-1a (CT-1a is DELETE-only; this would require INSERT or careful audit
trail reconstruction).

**Recommended future scope**: separate trade_log F-D3A-1-style audit PR
to reconstruct missing sell row for 000012.SZ OR confirm via xtquant API
that position was actually exited via legacy path.

---

## §6 Methodology + 红线 sustained

- **Phase 0 active discovery** (LL-172 lesson 1 amended preflight):
  multi-directory grep + SQL data presence verify surfaced 4 sediment-cite
  drifts BEFORE any mutation; demonstrates Phase 0 SOP value as antibody
  against false-premise narratives (LL-173 lesson 2 sustained — 4-29 was
  user-liquidation not crash, CT-1a 'cb_state' was stale cite).
- **3-step user trigger gate** (PR + reviewer + 同意 apply): sustained
  LL-098 X10 + Plan §A 红线 SOP.
- **Assertion-guarded SQL**: pre + post DO blocks raise on count drift;
  belt-and-suspenders filters (execution_mode='live' + strategy_id +
  position_count=19 for performance_series).
- **JSON snapshot rollback**: ADR-022 reversibility — pre-DELETE rows
  captured atomically; `--rollback` flag inverts.

**红线 5/5 sustained throughout CT-1a (mutation pending user trigger)**:
cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper /
QMT_ACCOUNT_ID=81001102. Mutation type = DB row DELETE on stale-only rows;
0 broker / 0 .env / 0 yaml / 0 production code mutation.

---

## §7 关联

- V3 Plan v0.4 §A CT-1 row + §B row 7 (DB DELETE 误删 mitigation)
- ADR-022 (rollback discipline) / ADR-077 reserved (Plan v0.4 closure cumulative) /
  ADR-080 (IC-3 closure 3-family green CT-1 prerequisite) /
  ADR-081 候选 (CT-1 closure — 本 partial, full sediment at CT-1b)
- 铁律 22 / 24 / 25 / 33 (fail-loud) / 35 (.env secrets) / 41 (UTC tz-aware) /
  42 (backend/ + scripts/ PR体例)
- LL-098 X10 / LL-159 (4-step preflight + multi-directory grep amended via
  LL-172 lesson 1) / LL-168/169 (verify-heavy classification — CT-1a is
  verify-heavy: 0 net new code; SQL + runner + tests around assertion-guard
  + rollback safety) / LL-170 (V3-as-island detection — Plan-cite drift
  pattern continues, code-level closed but doc-level continues to surface
  cite-drift findings via Phase 0 SOP) / LL-173 lesson 2 (Phase 0
  meta-finding catches false premise narrative — 4 cite-drifts surfaced
  this PR)
- SHUTDOWN_NOTICE_2026_04_30.md §3 (DB drift NAV diff) + §9.2 (DB cleanup
  prereq, cite drift Plan §A "cb_state" → actual "circuit_breaker_state")
