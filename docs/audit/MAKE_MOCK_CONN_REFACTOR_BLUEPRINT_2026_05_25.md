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
