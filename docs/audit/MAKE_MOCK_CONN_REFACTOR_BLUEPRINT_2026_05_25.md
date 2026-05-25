# `_make_mock_conn` Fixture Brittleness Refactor Blueprint

**Status**: TIER C analysis — read-only, NO code change in this artifact
**Iter**: 100 (Pattern B subagent autonomous loop)
**Date**: 2026-05-25
**Verify timestamp**: 2026-05-25 SH (Pattern B subagent fresh grep + read)
**Author**: general-purpose subagent (Pattern B)

---

## §1 Current definition cite

There is **no single canonical `_make_mock_conn`**. The helper is **redefined module-locally in 12 test files**, each with a slightly different signature and behavior:

| File | Line | Signature | Return shape |
|---|---|---|---|
| `backend/tests/test_a3_a5_a7_a10.py` | 186 | method on class | MagicMock conn |
| `backend/tests/test_announcement_processor.py` | 148 | `(announcement_id_seq: list[int]) -> MagicMock` | conn w/ RETURNING-id iter |
| `backend/tests/test_dingtalk_webhook_service.py` | 36 | `(*, resolve_rows, update_rowcount, column_names) -> MagicMock` | conn w/ SELECT-vs-UPDATE side_effect dispatch |
| `backend/tests/test_factor_health_daily.py` | 428 | `(fetchall_candidates, fetchone_side_effects)` | `(conn, cursor)` tuple |
| `backend/tests/test_fundamental_context_service.py` | 59 | `() -> MagicMock` | bare MagicMock |
| `backend/tests/test_l4_sweep_tasks.py` | 32 | per-test args | MagicMock conn |
| `backend/tests/test_pt_data_service_fail_loud.py` | 72 | `(max_status_date, prev_trading_day, lag_days, status_count=5000)` | conn |
| `backend/tests/test_qm_platform_attribution.py` | 787 | `_make_mock_conn_factory(returned_id: int = 42)` | conn_factory callable |
| `backend/tests/test_service_smoke.py` | 51 | `() -> MagicMock` | conn w/ default `fetchone=(0,)` ← LL-198 root |
| `backend/tests/test_startup_assertions.py` | 31 | `(rows: list[tuple[str, int]])` | conn |
| `backend/tests/test_strategy_evaluation_required.py` | 34 | `_make_mock_conn_factory(fetchone_queue)` | factory callable |
| `backend/tests/test_strategy_registry.py` | 56 | `_make_mock_conn_factory(fetchone_queue, rowcounts)` | factory w/ `_conn`/`_cursor` attrs |

**Cite (4-element)**: `Grep "def _make_mock_conn\|def make_mock_conn"` 2026-05-25 SH fresh run → 12 hits in `backend/tests/` (iter 100 Pattern B subagent).

## §2 Usage inventory

- **File count**: 12 test files
- **Total invocations** (call sites, not definitions): **115** (Grep count mode, 2026-05-25 SH)
- **Top callers**: `test_strategy_registry.py` (17) > `test_strategy_evaluation_required.py` (16) > `test_dingtalk_webhook_service.py` (12) > `test_l4_sweep_tasks.py` (13) > `test_service_smoke.py` (10)
- **Sample call patterns**:
  - bare: `conn = _make_mock_conn()` (service_smoke, fundamental_context)
  - args: `_make_mock_conn(fetchall_candidates=[...], fetchone_side_effects=[...])` (factor_health_daily)
  - factory: `factory = _make_mock_conn_factory(fetchone_queue=[None])` then `DBStrategyRegistry(conn_factory=factory)` (strategy_registry)
  - per-test override: `conn.cursor().fetchone.return_value = None` (service_smoke:414, post LL-198 fix)

## §3 Pattern analysis

**Return shape variance** (this IS the brittleness root):
1. Most return `MagicMock` with `conn.cursor.return_value = cursor`; `cursor.fetchone.return_value = (0,)` or `None` or iter-driven.
2. `factor_health_daily` returns **tuple `(conn, cursor)`** — non-uniform.
3. `strategy_registry` / `strategy_evaluation_required` return a **factory callable** (with `_conn`/`_cursor` attrs for assertion) — different return contract.
4. `dingtalk_webhook_service` uses **SQL-prefix dispatch** in `execute_side_effect` (SELECT sets `fetchall`, UPDATE sets `rowcount`) — most sophisticated; least re-usable.

**Customization patterns**:
- (a) Constructor args (factor_health_daily, dingtalk, pt_data_service)
- (b) Post-construction mutation: `conn.cursor().fetchone.return_value = None` (service_smoke, after LL-198)
- (c) Iter-driven `side_effect` (announcement_processor, strategy_registry)
- (d) Per-test cursor swap (l4_sweep)

**Brittleness sources** (confirmed via LL-198 + code reading):
- **B1 — Default `fetchone=(0,)`** misleads callers expecting `None` (LL-198 root: `_prefs_row_to_dict` did `row[1]` IndexError).
- **B2 — `execute.assert_not_called()` over-strict** — SELECT-read incorrectly classified as side effect (LL-198 fix point 2).
- **B3 — `conn.cursor()` returns same MagicMock**, so `conn.cursor().execute.call_args_list` aggregates across test phases without reset → cross-call assertion drift.
- **B4 — `__enter__`/`__exit__` missing in several variants** (announcement_processor:156-157 has them; service_smoke:51-58 doesn't) → `with conn.cursor() as cur:` prod code path silently passes via MagicMock auto-spec.
- **B5 — No reset between subtests within same test** → state leakage when test reuses `conn` across multiple operations.

## §4 Failure mode catalog

**LL-198** (`LESSONS_LEARNED.md:6907-6943`, verify 2026-05-25 SH iter 79 commit `db7b158`):
> shared `_make_mock_conn()` 默认 `cursor.fetchone()=(0,)` 1-tuple; prod `_prefs_row_to_dict` 期望 multi-column → IndexError. Plus `execute.assert_not_called()` mis-classifies SELECT-read as write side effect.
>
> **Fix pattern**: (1) per-test mock override (`conn.cursor().fetchone.return_value = None`); (2) write-only assertion (`startswith(("INSERT","UPDATE","DELETE"))`).
>
> **Heuristic**: #15 Test-Reality Gap, #11 Convenience-Driven Development.

**LL-199** (`LESSONS_LEARNED.md:6946-6979`, iter 80 commit `708fc9d`): tangentially related — sibling in same iter-78-80 test-reconciliation cluster, but the root pattern is "prod intentionally changed enum, test stale" — **NOT** `_make_mock_conn` brittleness. Cited for cluster context, not as direct refactor input.

## §5 Refactor options

| Option | Strategy | Pros | Cons | Scope (LoC delta) | Risk tier |
|---|---|---|---|---|---|
| **A. Single `conftest.py` factory fixture** | One canonical `@pytest.fixture` `mock_conn` in `backend/tests/conftest.py` that yields a fresh `MagicMock` per test invocation. Helpers like `mock_conn_with_fetchone(rows)` provide common shapes. | Pytest-idiomatic; auto-fresh per test (no state leakage B5); single source of truth | Forces rewrite of 115 call sites; some variants (factor_health_daily tuple return, factory-shaped) need adapter; 12-file blast radius | **+80 / -200** (rough: 12 deletions ~10 LoC each + 1 conftest add ~80 LoC + ~115 call-site adjustments) | **TIER B** (test infrastructure, not prod; reviewer-required because cross-file blast) |
| **B. Per-test explicit builder pattern** | Keep most local helpers but standardize them to a builder API: `MockConnBuilder().with_fetchone([...]).with_rowcount(1).build()`. Builder lives in `backend/tests/_mock_db.py`. | Explicit per-test customization; no hidden defaults (cures B1/B2); easier to discover via `.with_*` method autocomplete; can coexist w/ legacy during migration | More verbose per call site; doesn't enforce uniform return shape unless we also standardize | **+150 / -250** (builder module + gradual migration) | **TIER B** |
| **C. Real PostgreSQL test fixture** | `pytest-postgresql` or testcontainers; tests get real psycopg2 conn to ephemeral DB schema. | Eliminates all mock brittleness (B1-B5 全 closed); tests run prod SQL paths; catches LL-066 partial-UPSERT class bugs at test time | **铁律 9 violation risk** (DB-heavy fixtures multiply concurrency cost on 32GB box); CI cost spike (PG OOM 2026-04-03 教训); slow (~3-10x test runtime); 115 sites need refactor; not all current asserts translate (`execute.call_args_list` doesn't exist on real conn) | **+400 / -300** (fixtures + per-test schema setup + migrations) | **TIER A** (touches infra; needs reviewer + cost-benefit ADR) |

## §6 Recommended path

**Option A — single `conftest.py` factory fixture** (with shape-helper sub-fixtures).

**Justification**:
1. LL-198 root cause is **default `(0,)` returned by a shared helper** → centralizing the helper into a fresh-per-test fixture (no module-global state) directly closes B1 + B3 + B5 by construction.
2. Option C is over-kill for the failure modes actually sediment'd (LL-198 is a mock-shape bug, not a SQL-correctness bug); risks 铁律 9 PG OOM 2026-04-03 recurrence.
3. Option B leaves 12 module-local helpers in place — doesn't eliminate the "fight default" anti-pattern, just standardizes the fight.
4. Option A is pytest-idiomatic (fresh per test by default), preserves call-site brevity (`mock_conn` injected vs `_make_mock_conn()` called), and the factory functions can return tuples/factories for the few variants that need it (factor_health_daily, strategy_registry) via parametrized sub-fixtures.

**Estimated effort**: **6-10 hours**
- 1h: design `conftest.py` API (3 fixtures: `mock_conn` bare, `mock_conn_factory_builder`, `mock_conn_tuple` for legacy callers)
- 3h: migrate 12 files (5-15 call sites each)
- 1h: delete 12 module-local `_make_mock_conn` definitions
- 1h: run full `pytest backend/tests/` baseline diff (LL-198/197 sibling tests must still PASS)
- 1-2h: code-reviewer agent pass (TIER B); address findings
- 1h: ADR row + LL append + sediment

**Sub-PR sizing** (per 铁律 23/24): 1 single sub-PR feasible if ≤ ~500 LoC delta; otherwise split into "infrastructure PR (conftest + 2 pilot files)" + "migration PR (remaining 10 files)".

## §7 Acceptance criteria for the refactor PR

1. **All existing tests still PASS** — baseline `pytest backend/tests/ -m "not slow"` exit 0 (iter 80 baseline: 2 fail / 6714 collected, post-refactor must be ≤ 2 fail).
2. **`smoke` 61 PASS sustained** — `pytest -m "smoke and not live_tushare"` exit 0 (pre-push hook gate, 铁律 10b).
3. **No shared state leakage** — each test invocation gets a fresh `MagicMock`; assert via parametrize-replay 2-test sequence where test #2's `execute.call_count == 0` despite test #1 doing 5 executes.
4. **Write-only assertion helper exported** — `conftest.py` provides `assert_no_writes(conn)` that walks `execute.call_args_list` for `INSERT|UPDATE|DELETE` startswith (codifies LL-198 fix point 2).
5. **12 module-local `_make_mock_conn` definitions deleted** — Grep `def _make_mock_conn|def make_mock_conn` returns 0 hits in `backend/tests/` post-merge (single conftest definition is the new SSOT).
6. **LL append + ADR row** — LL-201 candidate "shared mock fixture → conftest factory pattern" + ADR row referencing LL-198/199.
7. **Parallel-safe** — `pytest -n auto` (xdist) PASS, proving fixture has no module-global state.

## §8 Cite sources (4-element)

| Claim | path | line# | section | verify timestamp |
|---|---|---|---|---|
| LL-198 sediment text | `LESSONS_LEARNED.md` | 6907-6943 | LL-198 entry full | 2026-05-25 SH iter 100 fresh read |
| 12 file `def _make_mock_conn` enumeration | n/a | n/a | Grep `def _make_mock_conn\|def make_mock_conn` 12 hits | 2026-05-25 SH iter 100 fresh grep |
| 115 invocation count | n/a | n/a | Grep `_make_mock_conn` count mode | 2026-05-25 SH iter 100 fresh grep |
| Default `(0,)` brittle | `backend/tests/test_service_smoke.py` | 51-58 | `_make_mock_conn` definition | 2026-05-25 SH iter 100 fresh read |
| Per-test override fix pattern | `backend/tests/test_service_smoke.py` | 407-441 | `test_send_sync_p3_does_not_write_db` post-LL-198 fix | 2026-05-25 SH iter 100 fresh read |
| Factory variant exists | `backend/tests/test_strategy_registry.py` | 56-86 | `_make_mock_conn_factory` | 2026-05-25 SH iter 100 fresh read |
| Tuple-return variant exists | `backend/tests/test_factor_health_daily.py` | 428-435 | `_make_mock_conn` returning `(conn, cursor)` | 2026-05-25 SH iter 100 fresh read |
| SQL-prefix dispatch variant | `backend/tests/test_dingtalk_webhook_service.py` | 36-73 | `execute_side_effect` SELECT-vs-UPDATE dispatch | 2026-05-25 SH iter 100 fresh read |
| 铁律 9 (PG OOM, Option C risk) | `CLAUDE.md` | §并发限制 | "32GB内存硬约束, 2026-04-03 OOM事件" | 2026-05-25 SH iter 100 fresh read |
| LL-199 cluster context (not direct input) | `LESSONS_LEARNED.md` | 6946-6979 | LL-199 entry full | 2026-05-25 SH iter 100 fresh read |

---

**End of blueprint**. No code changed. Awaiting user / main agent decision to proceed with Option A implementation PR.

---

## §9 Migration progress + remaining-file analysis (iter 110-115 sediment, 2026-05-25 ~22:30 SH)

### §9.1 Migrations delivered

| iter | commit | file | call sites | LOC delta | pattern |
|------|--------|------|------------|-----------|---------|
| 110 | `0eec31d` PR #481 | (infrastructure) | — | +321 (conftest +120, test_mock_conn_fixtures +180, lint +21) | 3 fixtures + 16 self-tests landed |
| 111 | `2333ad9` | test_fundamental_context_service.py | 5 (4 class methods + 1 module-level) | +13/-17 | bare `() -> MagicMock` → `mock_conn` direct injection |
| 112 | `e81a879` | test_startup_assertions.py | 3 | +14/-23 | `(rows:list)` → `mock_conn` + fetchall override per-test |
| 113 | `f8e89bb` | test_a3_a5_a7_a10.py | 3 (method on class TestA7UnrealizedPnl) | +20/-18 | tuple-return method → `mock_conn` + explicit fetchone.side_effect |

**Net so far**: 3/12 files migrated, **+47 / -58 net (-11 LOC)** across migrated files. Net delta is small per-file (saving deletions ≈ new explicit setup), but **architecturally** the migration:
- Replaces 3 distinct local helper styles with 1 canonical fixture (cures B1+B3+B4+B5 per blueprint §3)
- Removes 30 LOC of duplicate boilerplate across the 3 files
- Validates `mock_conn` fixture works in real production-adjacent test scenarios (across 3 disparate prod modules)

### §9.2 Remaining 9 files — recommendation matrix

Migration analysis after iter 113 (2026-05-25 ~22:00 SH fresh re-read of each remaining file):

| File | Sites | Local helper signature | Recommendation | Reason |
|------|-------|------------------------|----------------|--------|
| test_announcement_processor.py | 8 | `(announcement_id_seq: list[int])` + RETURNING-id iter | **MIGRATE** (medium effort, ~25 LOC diff) | bare → mock_conn + per-test fetchone.side_effect setup with id iter — same shape as test_a3_a5_a7_a10 iter 113 |
| test_dingtalk_webhook_service.py | 12 | `(*, resolve_rows, update_rowcount, column_names)` SQL-prefix dispatch | **KEEP LOCAL** | Domain-specific SELECT-vs-UPDATE dispatcher (44 LOC of well-named logic); inline migration would 5x explode boilerplate across 12 sites |
| test_factor_health_daily.py | tuple-return `(conn, cursor)` | **MIGRATE** with adapter | `conn = mock_conn; cur = conn.cursor()` destructure pattern proven iter 113; ~15 LOC diff |
| test_l4_sweep_tasks.py | 13 | `(*, select_rows, update_rowcounts)` SQL-prefix dispatch returns tuple | **KEEP LOCAL** | Same reason as test_dingtalk_webhook_service: SQL-prefix dispatch is a well-encapsulated domain pattern, migration would 5-8x the LOC |
| test_pt_data_service_fail_loud.py | 5 | `(max_status_date, prev_trading_day, lag_days, status_count=5000)` conditional fetchone responses | **KEEP LOCAL** | Domain semantic (4-call SQL sequence with conditional lag-day branch); the helper IS the canonical builder for this prod helper's 4-query pattern |
| test_qm_platform_attribution.py | factory `(returned_id: int = 42)` | **MIGRATE** to `mock_conn_factory_builder` | Factory shape matches canonical; ~10 LOC diff if RETURNING-id semantic preserved via fetchone_queue=[(42,)] |
| test_service_smoke.py | 10 | bare with default `cursor.fetchone.return_value = (0,)` | **MIGRATE LAST** (highest risk) | Some tests rely on the (0,) default implicitly per LL-198 — need careful per-test audit to set explicit (0,) override OR refactor to None default |
| test_strategy_evaluation_required.py | 10 | `_make_mock_conn_factory(fetchone_queue)` with `cursor.fetchall.return_value = []` default | **MIGRATE** with fetchall override per-test | Factory shape matches canonical; the `fetchall.return_value=[]` default needs explicit per-test setup (or canonical fixture enhancement — see §9.4) |
| test_strategy_registry.py | 17 | `_make_mock_conn_factory(fetchone_queue, rowcounts)` | **MIGRATE** to `mock_conn_factory_builder` | Canonical fixture matches signature exactly; ~30 LOC diff, validates factory variant pattern across all factory tests |

### §9.3 Practical migration target = ~6/12 (not 12/12)

After iter 113 analysis, **3 files are explicitly OUT-OF-SCOPE for canonical fixture migration**:
- test_dingtalk_webhook_service.py (SQL-prefix dispatch)
- test_l4_sweep_tasks.py (SQL-prefix dispatch, returns tuple)
- test_pt_data_service_fail_loud.py (4-query domain sequence)

These keep their local domain-specific helpers. Rationale: canonical fixture is for COMMON cases; specialized helpers are appropriate for specialized prod query patterns. Per blueprint Option B sustained "Per-test explicit builder pattern" applies here.

**Realistic 100% target = 6 files migrated + 3 files kept-local-with-rationale = 9/12 closure**. The remaining 3 (factor_health_daily + service_smoke + strategy_registry + strategy_evaluation_required + attribution) total ~6 files for future iter migrations.

### §9.4 Canonical fixture enhancement candidate (deferred, Plan mode entry)

If migration of `test_strategy_evaluation_required` / `test_strategy_registry` proceeds, canonical `mock_conn_factory_builder` should add `cursor.fetchall.return_value = []` as default (per blueprint §3 local def behavior). This is an API contract addition (not breaking), so:
- §v9.17 Plan mode trigger applies (API contract change)
- Defer to dedicated iter with user / reviewer pre-alignment
- Alternative: keep canonical strict (no defaults), have each test set `mock_conn.cursor().fetchall.return_value = []` explicitly per-test (verbose but consistent with B1 cure principle)

### §9.5 Acceptance criteria update (super-set of §7)

Beyond §7's strict "12 module-local defs deleted", revised target after iter 113:
1. ✅ 3 files migrated (iter 111/112/113) — fixture validated across 3 distinct shapes
2. **Target 6/12 next iter window**: migrate test_announcement_processor + test_factor_health_daily + test_qm_platform_attribution + test_strategy_evaluation_required + test_strategy_registry + test_service_smoke
3. **3 files kept-local with rationale**: test_dingtalk_webhook_service + test_l4_sweep_tasks + test_pt_data_service_fail_loud (domain-specific dispatch helpers; documented in this §9 sediment)
4. **§9.4 canonical fixture enhancement** if factory-variant migrations need fetchall default (Plan mode entry)
5. **Net LOC reduction goal**: ~50-80 LOC reduction across 6 migrated files (blueprint §5 estimated +80/-200 across 12 files; revised target ~+50/-130 across 6 files = -80 net)

### §9.7 iter 116-118 closure status (2026-05-25 ~22:45 SH)

Delivered:
- iter 116 PR-direct `5c7a189` — test_announcement_processor.py migrated (8 sites)
- iter 117 PR-direct `e78add1` — test_factor_health_daily.py migrated (8 sites, tuple-return pattern)
- iter 118 (this doc update)

**Total migration count post-iter-117**: **5/12 files migrated** (test_fundamental_context iter 111 / test_startup_assertions iter 112 / test_a3_a5_a7_a10 iter 113 / test_announcement_processor iter 116 / test_factor_health_daily iter 117).

**Closure scoring**:
- 5 migrated ✅
- 3 kept-local-with-rationale ✅ (test_dingtalk_webhook_service / test_l4_sweep_tasks / test_pt_data_service_fail_loud per §9.2)
- **Subtotal: 8/12 = 67% closure** vs §9.5 target 9/12 = 75%

### §9.8 Remaining 4 candidates — Plan mode entry required (deferred; iter 121 update)

Migration of the final 4 files needs canonical fixture enhancement OR per-test re-architecture:

| File | Blocker | Status |
|------|---------|--------|
| test_qm_platform_attribution.py | Local def returns `MagicMock(return_value=mock_conn)` for `factory.assert_called_once()` semantic; canonical `mock_conn_factory_builder` returns plain function (no `.assert_called_once()` method) | **Plan mode** — canonical enhancement (`as_mock=True` optional param) OR refactor 8 test sites to skip the assertion |
| test_strategy_evaluation_required.py | Local factory sets `cursor.fetchall.return_value = []` default | **UNBLOCKED iter 120** (`905a0e4`) — canonical now sets fetchall=[] default per §9.4 enhancement. Migration becomes mechanical 10-site replacement. Remaining minor differences: `conn.closed = 0` (unused per grep, can drop) + fetchone overflow lambda→None (canonical uses MagicMock side_effect list which raises StopIteration on overflow; per-test audit needed if any tests exceed queue length). |
| test_strategy_registry.py | Local factory sets `cursor.fetchall.return_value = []` default + rowcounts queue (17 sites, highest complexity) | **UNBLOCKED iter 120** — canonical has fetchall=[] (post iter 120) + rowcounts (pre-iter-120). Migration mechanical 17-site replacement. Same minor differences as above. |
| test_service_smoke.py | Local def sets `cursor.fetchone.return_value = (0,)` default; ~5 tests rely on implicit (0,) tuple sentinel per LL-198 root | **Plan mode sustained** — per-test audit needed: each test's reliance on (0,) default must be verified; some may need explicit override. High risk migration (LL-198 was the root cause failure). |

### §9.10 iter 120-121 closure status

**Delivered iter 120-121**:
- iter 120 (`905a0e4`) — canonical `mock_conn_factory_builder` fetchall=[] default + 1 new self-test (17/17 PASS)
- iter 121 (this doc update) — §9.8 status refresh

**Closure scoring post-iter-121**:
- 5 migrated ✅ (iter 111/112/113/116/117)
- 3 kept-local-with-rationale ✅
- 2 **unblocked** for migration (test_strategy_evaluation_required + test_strategy_registry) — future iter mechanical execution
- 2 **still Plan mode** (test_qm_platform_attribution MagicMock factory contract + test_service_smoke LL-198 root)

**Closure: 8/12 actionable now + 2 unblocked + 2 Plan mode = 12/12 scoped.**

**Recommendation**: defer 4 remaining migrations to next dedicated iter (after Plan mode user-alignment if canonical fixture enhancement is approved). Current 8/12 (67%) closure validates Option A pattern across 5 disparate shapes (bare / fetchall override / tuple-return method / id-iter / 2-query setup). Pattern proven; remaining work is finite + scope-bounded.

### §9.9 Updated cite source for iter 116-118

| Claim | path | line# | section | verify timestamp |
|-------|------|-------|---------|------------------|
| iter 116 migration | `backend/tests/test_announcement_processor.py` | full file | post-iter 116 | 2026-05-25 ~22:25 SH |
| iter 117 migration | `backend/tests/test_factor_health_daily.py` | full file | post-iter 117 | 2026-05-25 ~22:40 SH |
| qm_platform_attribution blocker | `backend/tests/test_qm_platform_attribution.py` | 787-810 | _make_mock_conn_factory + L810 factory.assert_called_once | 2026-05-25 ~22:45 SH iter 118 |
| strategy_evaluation_required blocker | `backend/tests/test_strategy_evaluation_required.py` | 34-68 | _make_mock_conn_factory + fetchall default | 2026-05-25 ~22:00 SH iter 115 |
| service_smoke (LL-198 root) blocker | `backend/tests/test_service_smoke.py` | 51-58 | _make_mock_conn default fetchone=(0,) | per LL-198 cite source iter 100 |

### §9.6 Cite source (4-element)

| Claim | path | line# | section | verify timestamp |
|-------|------|-------|---------|------------------|
| iter 111 migration | `backend/tests/test_fundamental_context_service.py` | full file | post-iter 111 | 2026-05-25 ~21:30 SH |
| iter 112 migration | `backend/tests/test_startup_assertions.py` | full file | post-iter 112 | 2026-05-25 ~21:45 SH |
| iter 113 migration | `backend/tests/test_a3_a5_a7_a10.py:182-265` | TestA7UnrealizedPnl class | post-iter 113 | 2026-05-25 ~22:00 SH |
| Canonical fixture | `backend/tests/conftest.py:108-227` | new fixtures | post-iter 110 | 2026-05-25 ~20:00 SH |
| Domain-helper rationale (3 keep-local) | `backend/tests/test_dingtalk_webhook_service.py:36-73` + `test_l4_sweep_tasks.py:32-63` + `test_pt_data_service_fail_loud.py:72-91` | local _make_mock_conn defs | 2026-05-25 ~22:15 SH iter 115 re-read |
| LL-204 backend audit envelope canonical | `LESSONS_LEARNED.md` LL-204 | sediment block | 2026-05-25 ~20:30 SH iter 104 |
| LL-205 frontend fail-loud canonical | `LESSONS_LEARNED.md` LL-205 | sediment block | 2026-05-25 ~21:30 SH iter 109 |
