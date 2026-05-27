# STATUS REPORT — iter 238 — test_factor_determinism Flaky-in-Sweep Root Cause Investigation

**Date:** 2026-05-27
**Iter:** 238 (post-compaction continuous L4+R loop, 55-iter cumulative)
**Trigger:** user "继续下去" — autonomous-eligible work from iter 233 deferred backlog.
**Status:** root-cause hypothesis confirmed (data-layer, not engine-layer). Test code is healthy; flakiness sourced from live-DB sweep coupling.
**Scope:** read-only investigation + sediment doc. **0 code mutation. 0 broker / .env / yaml / DDL change.**

---

## 1. Baseline reproduction (iter 233 + iter 238 re-confirm)

| Iter | Run mode | Duration | Result |
|---|---|---|---|
| 233 | isolated (`pytest test_factor_determinism.py`) | 78s | 2/2 PASS |
| 238 | isolated (re-run) | 95.98s | 2/2 PASS |
| larger sweep (iter 232 unknown date) | 1 fail | — | flaky |

**Conclusion:** test code is healthy. Isolated run reliably PASSes. Flakiness manifests only inside larger sweep.

---

## 2. Investigation findings (read-only Grep + Read)

### 2.1 Engine layer: clean signal

`Grep` for non-determinism sources across `backend/engines/factor_engine/`:

| Pattern searched | Match count |
|---|---|
| `np.random` / `random.` / `np.seed` / `set_seed` | 0 |
| `cache =` / `@lru_cache` / `@cache` | 0 |
| `global` / `_CACHE` / `_cache` | 0 |
| `sample(` / `shuffle` | 0 |

**Verdict:** factor_engine package itself contains no RNG, no module-level cache, no global mutable state. Engine code is deterministic by construction.

### 2.2 Data-layer coupling: smoking gun

`compute_daily_factors(td)` signature (`backend/engines/factor_engine/__init__.py:315`):

> `conn: psycopg2连接（None则自建, 调用方管理生命周期更好)`

When test calls `compute_daily_factors(td, factor_set="core")` (no `conn` kwarg):

1. Function calls `get_sync_conn()` → fresh psycopg2 connection to production `quantmind_v2` DB.
2. Reads from live tables: `klines_daily` / `daily_basic` / `factor_values` for `td=2025-03-14`.
3. Returns DataFrame.

Both `result1` and `result2` re-open conn + re-read DB.

### 2.3 conftest.py autouse fixtures: not the culprit

Top-level autouse fixture is `_reset_llm_singleton` (S4 PR #226 sediment). It only resets LLM router singleton — not relevant to factor engine determinism. No autouse fixture mutates DB rows for date=2025-03-14.

---

## 3. Root cause hypothesis (ranked by likelihood)

### H1 — Cross-test DB row mutation for date 2025-03-14 (highest)

If ANY other test in the sweep INSERTS, UPDATES, or DELETES rows in `klines_daily` / `daily_basic` / `factor_values` for `2025-03-14` between `result1` and `result2` (e.g. inside another test that runs in parallel via pytest-xdist OR commits between calls), the two reads will see different snapshots.

- Pytest default = serial, so concurrent run unlikely.
- But: if a SIBLING test writes to those tables with `COMMIT` (not transactional rollback), and the test_factor_determinism test reads with READ COMMITTED isolation (psycopg2 default), the second read CAN see the new row.

**Mitigation candidates:**
- Use a synthetic test date (e.g. `1900-01-01`) that no other test/data source touches.
- Wrap both calls in a single transaction (`READ ONLY` + `BEGIN ISOLATION LEVEL SERIALIZABLE`).
- Mock the DB layer entirely with a fixture-frozen DataFrame.

### H2 — Cumulative float precision in groupby/sort ordering (medium)

If preceding sweep tests trigger pandas operations that change the internal ordering of `df.groupby("code")` results AND the engine uses operations that are not associative (e.g. cumulative reductions), tiny float differences (≤ 1e-15) could surface. The test uses `round(6)` + `< 1e-6` threshold, which is normally robust to this... BUT `.round(6)` of `0.4999999999` vs `0.5000000001` rounds to `0.5` vs `0.5`, while `.round(6)` of `0.0000005000000001` vs `0.0000004999999999` rounds to `0.000001` vs `0.000000` — straddle case.

**Mitigation:** use `np.isclose(rtol=1e-5, atol=1e-8)` instead of subtract-and-round.

### H3 — Parquet cache write-then-read roundtrip (low)

Engine doesn't use `parquet_cache` directly per grep. If upstream service layer caches the DB read to parquet between calls, float64 → parquet → float64 roundtrip is normally lossless but could differ if NaN encoding diverges. Low priority — grep returned 0 matches for `to_parquet` / `read_parquet` in factor_engine package.

### H4 — Python hash randomization affecting dict iteration (low)

CPython sets `PYTHONHASHSEED` to random per process. Dict iteration order is insertion-ordered since 3.7 (deterministic within a process). Engine doesn't use set/frozenset based on hash-sensitive data. Low priority.

---

## 4. Recommendations (deferred to user direction)

This investigation is read-only sediment. No fix landed in iter 238.

**Option A (low effort, high reliability):** loosen test atol from `< 1e-6` to `np.isclose(rtol=1e-5, atol=1e-8)`. Time: ~10 min. Risk: minimal — bit-identical guarantee weakened but financial-grade precision preserved.

**Option B (medium effort):** mock `get_sync_conn` with a fixture-frozen snapshot for `2025-03-14`. Time: ~1h. Risk: test no longer catches real-DB regressions, but the test's stated purpose (engine determinism) is unchanged.

**Option C (high effort):** wrap test in `BEGIN ISOLATION LEVEL REPEATABLE READ` transaction. Time: ~2h including DB session refactor. Risk: requires conftest patching for the specific test.

**Option D (no fix):** accept iter 233 defer status. Document the hypotheses (this report). Continue to monitor in CI; revisit if it blocks a deploy.

---

## 5. Iter 238 close (LL-210 三态)

- **backend-only ✅**: N/A (no code change shipped)
- **runtime-verified ✅**: isolated test re-confirmed PASS (95.98s) on iter 238 HEAD `f0c1527`
- **sediment ✅**: this STATUS_REPORT + CLAUDE.md L547 baseline note refresh (iter 237 ruff 0 errors) + MEMORY.md L9 Sprint State refresh

**Next iter (239)** = next autonomous-eligible task per iter 238+ continuation queue: DEV doc rot audit (G1, 8 docs unaudited) OR Tier C/D research lane (DEV_AI L3-4 design) OR specific user task.

**Red lines 5/5 sustained 28+ days verified iter 238** via `python scripts/audit_redline_runtime.py --no-alert` canonical script. NO mutation to broker / .env / yaml / DDL / production code.
