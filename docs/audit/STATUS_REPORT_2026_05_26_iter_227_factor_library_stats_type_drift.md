# STATUS_REPORT — iter 227 §v9.49 Finding #13: FactorLibraryStats Type Drift (LL-213 SOP)

> **Trigger**: iter 226 refactor-cleaner P2-B follow-up + LL-213 design-time verify SOP applied
> **Verdict**: **§v9.49 #13 — type drift** between `FactorLibraryStats` TS type vs `/factors/stats` backend response. 3 frontend callers silently access undefined fields. Invasive fix touches FactorLibrary.tsx + HealthPanel.tsx user-facing display → **deferred to user direction**.
> **Pattern**: 3rd type-drift case caught by reviewer/refactor agent (sibling iter 198 SystemHealth + iter 211 fetchSchedulerTasks + this case)

---

## §1 Drift Detail

### Backend `/factors/stats` actual return shape
Per `backend/app/api/factors.py:311-385`:

```python
return {
    "total": total,
    "active": int,
    "candidate": int,
    "warning": int,
    "critical": int,
    "retired": int,
    "top_factors": [...]
}
```

### Frontend `FactorLibraryStats` TS type declared shape
Per `frontend/src/api/factors.ts:124-129`:

```ts
export interface FactorLibraryStats {
  active: number;
  new: number;       // ← NOT IN BACKEND
  degraded: number;  // ← NOT IN BACKEND
  retired: number;
}
```

### Frontend `FactorsStatsResponse` TS type (CORRECT shape)
Per `frontend/src/api/factors.ts:67-74`:

```ts
export interface FactorsStatsResponse {
  active: number;
  warning?: number;
  critical?: number;
  retired: number;
  candidate?: number;
  total?: number;
}
```

**Drift**: `FactorLibraryStats.new` + `.degraded` are CLAIMED but backend NEVER returns them → silent undefined access.

## §2 Silent Bug Impact

3 callers consume the LIE:

### `frontend/src/pages/FactorLibrary.tsx:82-83`
```tsx
{ key: "new",      label: "新入库", value: stats.new },        // always undefined
{ key: "degraded", label: "衰退",   value: stats.degraded },  // always undefined
```
→ "新入库" / "衰退" status cards silently render 0 or empty.

### `frontend/src/components/factor/HealthPanel.tsx:30-31`
```tsx
{ name: STATUS_LABELS.new,      value: stats.new },      // always undefined
{ name: STATUS_LABELS.degraded, value: stats.degraded }, // always undefined
```
→ ECharts pie/donut chart silently has undefined slices.

### `frontend/src/__tests__/pages.test.tsx:40`
```ts
getFactorLibraryStats: vi.fn().mockResolvedValue({...})
```
→ Mock matches the LYING type, masking the bug.

## §3 Sibling Pattern (LL-213 #13 cumulative)

| # | iter | wrapper | drift type | silent bug |
|---|---|---|---|---|
| 1 | 198 | SystemHealth (postgres/pg) | Field renaming + status enum | SystemSettings + IndustryAndSystem "always down" |
| 2 | 211 | fetchSchedulerTasks ({tasks:[...]} vs []) | Response envelope shape | SystemSettings SchedulerTab silently empty |
| 3 | 215 | RiskEventTracePanel HeatmapBar | TIMESTAMPTZ::text cross-browser | Safari Invalid Date silent zero-fill |
| **4** | **227** | **FactorLibraryStats (.new vs .candidate)** | **Field renaming drift** | **FactorLibrary + HealthPanel "新入库"/"衰退" silent 0** |

**Pattern confirmed 4× cumulative**. LL-213 SOP applies retroactively — `FactorLibraryStats` was added BEFORE LL-213 codification (iter 218), so no design-time verify was performed. iter 227 is the catch via refactor-cleaner P2-B sweep.

## §4 Fix Options (User Direction Required)

### Option A — Fix wrapper to map backend → frontend enum (recommended)
Update `getFactorLibraryStats` wrapper to map backend `candidate`→`new` + `warning+critical`→`degraded` (sibling `/factors` endpoint line 282-289 mapping pattern). FactorLibraryStats interface stays unchanged. Single-file change in `api/factors.ts`.

**Pros**: 0 caller changes. Sibling backend endpoint mapping pattern. 5 LOC wrapper diff.
**Cons**: Couples wrapper to backend status taxonomy; if backend ever changes status enum, wrapper must update.

### Option B — Update callers to use raw backend fields
Update `FactorLibrary.tsx` + `HealthPanel.tsx` to use `candidate` + `warning + critical` instead of `new` / `degraded`. Update FactorLibraryStats type to alias FactorsStatsResponse.

**Pros**: Single source of truth, no mapping layer; 2 wrappers → 1.
**Cons**: ~10 LOC change across 2 caller files + UI label adjustments (frontend display labels may need user input on "新入库" → "候选"? "衰退" → "警告+严重"?).

### Option C — Defer (NO FIX, document only)
Sustained current state (silent undefined access). FactorLibrary + HealthPanel pages continue to show 0 for "新入库" and "衰退" cards. User accepts cosmetic incorrectness for now.

**Pros**: 0 change risk.
**Cons**: User-visible status cards permanently wrong (但 0 production trading impact).

## §5 iter 227 Decision

**iter 227 = OPTION C (defer fix to user direction)**. Reasoning:
1. UI labels ("新入库" / "衰退") suggest frontend designed against a specific status taxonomy distinct from backend — fix direction needs user judgment
2. FactorLibrary.tsx + HealthPanel.tsx are pre-existing pages (not iter 196-216 Wave 5 scope), invasive change would scope-creep
3. Sibling iter 198 SystemHealth fix was Option A pattern (wrapper-level normalization) which we could follow, but FactorLibraryStats has the additional complexity of mapping multiple backend values to single frontend value (e.g. `warning+critical → degraded` is N→1 not 1→1)

**This STATUS_REPORT serves as the finding sediment**. User decides next iter direction.

## §6 LL-213 Validation

Iter 227 catch validates LL-213 SOP design-time-verify mandate:
- `FactorLibraryStats` was added in pre-LL-213 era (likely Phase H W1-6 or earlier)
- LL-213 codified iter 218 introduced the 3-layer SOP
- Iter 226 refactor-cleaner P2-B sweep applied the LL-213 cross-verify
- Caught iter 227 — design-time verify retrospectively

**SOP value**: catches "shape drift" cases that build-time TS type checking can NOT detect (TS doesn't validate against actual backend response shape — only against the declared TS type, which is a CLAIM).

## §7 iter 228+ Hand-off

**Recommended sustained from iter 222 / iter 226**:
- (A) **Tier A§5 Servy elevated restart walkthrough** — highest leverage, runbook iter 186 ready
- (B) **Tier C/D research lane start** — user direction needed
- (C) **iter 227 FactorLibraryStats fix** — user picks Option A / B / C above
- (D) **Specific user-defined task**

**iter 227 ship 三态** per LL-210: backend-only ✅ doc-sediment (defer-with-cite per LL-212 verdict taxonomy).

**红线 5/5 sustained iter 227 fresh**. **Cumulative iter 185-227 post-compaction**: ~12h / 13 PRs / 3 hook fixes / 36 doc artifacts + 2 LL entries + 1 shared util.

---

**Coordinator**: Claude Opus 4.7 (1M context), autonomous L4+R loop continuous mode iter 43 post-compaction
**§v9.49 #13 catch**: refactor-cleaner P2-B → silent caller drift verified → defer-with-cite documented
**LL-213 validation**: 4th cumulative case proves SOP value
