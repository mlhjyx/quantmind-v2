# MVP 5.0 — Operator UI 总纲 + 框架选型 + API Surface (Tier B Wave 5 retroactive design)

> **Status**: iter 229 RETROACTIVE design doc (sibling MVP 5.1-5.5 5 sub-MVPs shipped iter 196-216 without explicit MVP 5.0 first; this doc codifies emergent canonical patterns for future Operator UI work)
> **Sprint**: Tier B Wave 5 Operator UI (QPB v1.17 L1149, originally "1 周" target, retroactively shipped through Wave 5 emergent patterns)
> **ADR refs**: ADR-012 D5 (Wave 5 start) / ADR-084 候选 (react-query refetchInterval canonical) / LL-035 (api/ layer) / LL-187 (Phase H W1-6 reuse) / LL-213 (type drift design-time verify)
> **铁律**: 22 (doc-follows-code) / 24 (≤2 pages) / 25 (改什么读什么) / 33 (fail-loud) / 35 (LL-035 api-layer) / 42 (AI reviewer mandate)

---

## §1 Purpose & Scope

QPB v1.17 L1149 originally specified MVP 5.0 as Wave 5's first sub-MVP for "UI 总纲 + 框架选型 + API surface". Implementation proceeded directly with MVP 5.1-5.5 without explicit MVP 5.0 because Phase H W1-6 (LL-187, iter 130-138) had already provided the shared component framework. iter 229 codifies the emergent canonical patterns that drove 5 successful sub-MVPs in 21-iter span (iter 196-216).

**Scope** (retroactive doc, 0 new implementation work):
- Canonical Operator UI page structure (proven 5/5 Wave 5 pages per iter 225 audit)
- Standard component stack (Phase H W1-6 + shared utils)
- API wrapper conventions (LL-035 enforcement + LL-213 type drift verify)
- react-query patterns (refetchInterval canonical + namespaced queryKey)
- Sibling pattern policy (each MVP designs reference prior MVP STATUS_REPORT)

**Out of scope**:
- New page implementation (Wave 5 = 5/5 ✅ complete)
- Mutation interactions (read-only dashboard model sustained)

## §2 Canonical Architecture (Proven 5×)

### §2.1 Page Structure Template

Sustained across PtStatus / IcMonitoring / BacktestCompare / SchedulerDashboard / RiskEventTracePanel:

```tsx
import { useQuery } from "@tanstack/react-query";
import { PageSkeleton } from "@/components/ui/PageSkeleton";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { statusBadgeClasses } from "@/utils/statusBadgeClasses";  // iter 226 shared util
import { fetchX, fetchY, type X, type Y } from "@/api/{domain}";

// Page root
export default function PageName() {
  const xQ = useQuery({
    queryKey: ["page-name", "x-data"],  // namespaced tuple
    queryFn: fetchX,
    refetchInterval: 60_000,  // canonical 60s (5s for env-state)
  });
  // ... more queries

  if (anyLoading && !anyData) return <PageSkeleton />;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <header>... PageHeader ...</header>
      {firstError && <ErrorBanner message={...} />}
      <Section1 data={xQ.data} />
      <Section2 data={yQ.data} />
      // ... typically 4-5 sections per page
    </div>
  );
}
```

### §2.2 Component Stack (Phase H W1-6 + Wave 5 utils)

| Component | Source | Reuse Count (Wave 5) |
|---|---|---|
| `PageSkeleton` | `components/ui/PageSkeleton.tsx` (Phase H) | 5/5 pages |
| `ErrorBanner` | `components/ui/ErrorBanner.tsx` (Phase H) | 5/5 pages |
| `Card` + `CardHeader` | `components/shared` (Phase H) | sustained pages |
| `PageHeader` | `components/shared` | sustained pages |
| `TabButtons` | `components/shared` | RiskManagement (multi-tab) |
| `statusBadgeClasses` | `utils/statusBadgeClasses.ts` (iter 226 extracted) | 2 pages (PtStatus + SchedulerDashboard) |
| `MetricMini` | `components/shared` | various |

### §2.3 API Wrapper Conventions (LL-035 + LL-213)

**Per LL-035 (sustained iter 203 reviewer enforcement)**:
- ALL `apiClient.get/post` calls reside in `frontend/src/api/{domain}.ts`
- 0 inline `apiClient.get` calls in page components
- Wrapper functions return typed promises with explicit response shape

**Per LL-213 (iter 218 codification, 4 cases caught iter 198/211/215/227)**:
- TS types declared alongside wrappers in api/ layer
- Reviewer agent design-time verifies TS type matches actual backend response shape
- Cross-browser datetime parsing: normalize `' '` → `'T'` for `TIMESTAMPTZ::text` (Safari compatibility)

**Domain modules**:
- `api/system.ts` — system / scheduler / health / env-state / calendar / settings
- `api/factors.ts` — factor library / IC monitoring / health / correlation
- `api/backtest.ts` — backtest run / nav / trades / compare
- `api/risk.ts` — risk events / rule-ids (NEW iter 215)
- `api/dashboard.ts` — main dashboard summary / NAV / portfolio
- `api/client.ts` — apiClient instance singleton (SSOT)

### §2.4 react-query Patterns (Canonical)

| Pattern | Convention |
|---|---|
| refetchInterval | 60_000ms (60s) DEFAULT; 5_000ms (5s) for env-state; per-fetch (no interval) for one-shot |
| queryKey shape | `["page-namespace", "data-name", ...args]` tuple — page-scoped prevents cross-page collision (sibling iter 203 reviewer P2 fix) |
| staleTime | DEFAULT (0); 5min for immutable-list endpoints (e.g. ruleIds, completed-runs nav) |
| error handling | destructure `error` from useQuery + render ErrorBanner top + per-section red text fallback (铁律 33 fail-loud) |
| initial load | `<PageSkeleton />` only when no data yet (stale-while-revalidate sustained) |

### §2.5 ECharts Patterns (Factor Domain Canonical)

| Use | Pattern |
|---|---|
| Time-series bar/line charts | `echarts-for-react` ReactECharts component (8/8 factor-domain consistent) |
| Heatmaps | ECharts `series.type: "heatmap"` OR Tailwind grid for simple color cells |
| Multi-series overlay | useMemo on option object + stable deps; per-datum itemStyle (sibling iter 211 reviewer P1 fix avoids closure-based color callback) |
| dataZoom | `[{ type: "inside" }, { type: "slider", height: 18, bottom: 5 }]` (sibling BacktestResults pattern) |
| Date strings | normalize `' '` → `'T'` before `new Date()` (LL-213 Safari fix iter 215) |

## §3 Sibling Pattern Policy (Sustained Cross-MVP)

Each MVP design doc references prior MVP STATUS_REPORT explicitly:
- MVP 5.1 design ref Phase H W1-6 (LL-187) + iter 195 §v9.49
- MVP 5.2 design ref MVP 5.1 closure + iter 198 SystemHealth type drift fix
- MVP 5.3 design ref MVP 5.1/5.2 closures + Option C Hybrid pattern
- MVP 5.4 design ref MVP 5.1/5.2/5.3/5.5 closures + 7th tab Option A
- MVP 5.5 design ref MVP 5.1/5.2/5.3 closures + LL-209 §v9.49 catch #11

**Emergent benefit**: per iter 225 audit, this sibling-reference pattern produced **cross-page consistency 5/5 ✅** without explicit cross-cutting audit overhead. Each MVP's reviewer cycle caught localized issues but cumulative effect → uniform canonical patterns.

## §4 AI Reviewer 铁律 42 Mandate (Sustained 10 Cycles)

Per LL-098 + iter 198 user correction:
- Every backend PR MUST spawn AI reviewer BEFORE PR open (not after auto-merge)
- Every frontend PR MUST spawn AI reviewer BEFORE PR open
- REQUEST_CHANGES findings P1+P2 fixed SAME-ITER per §v9.39
- P3 declined with concurrence

**Cumulative ROI** (10 cycles × 5 MVPs):
- ~85% cycle catch rate
- ~8 production bugs prevented
- 1 case of reviewer recommendation REJECTED with concurrence (iter 210 — CC pushed back when reviewer was incorrect on lazy-import patch target)

## §5 Acceptance Criteria (Retroactive)

This doc is retroactive sediment — acceptance = "all 5 Wave 5 sub-MVPs adhere to canonical patterns documented above":

| MVP | iter | Pattern Adherence |
|---|---|---|
| 5.1 PtStatus | 196-199 | ✅ 4-section page + 4 react-query hooks + Phase H reuse + LL-035 |
| 5.2 IcMonitoring | 201-204 | ✅ 5-section + ECharts S1 + LATERAL JOIN endpoint + LL-035 |
| 5.3 BacktestCompare | 205-208 | ✅ 5-section + useQueries parallel + URL-shareable state + LL-035 |
| 5.5 SchedulerDashboard | 209-212 | ✅ 5-section + ECharts S5 + §v9.49 #11 wrapper fix + LL-035 |
| 5.4 RiskEventTracePanel | 213-216 | ✅ 7th-tab on existing page + chain JOIN + cross-browser datetime + LL-035 |

**iter 225 cross-page audit verdict**: 5/5 CONSISTENT ✅.

## §6 ADR + LL Cross-Ref

- **ADR-012 D5** — Wave 5 Operator UI start condition (satisfied iter 51 post Wave 4 close)
- **ADR-084 候选** — react-query refetchInterval canonical pattern
- **LL-035** — API calls routed via api/ layer (parent rule)
- **LL-098** — AI 自动驾驶 detection (parent to 铁律 42)
- **LL-187** — Phase H W1-6 component reuse (sustained 5 MVPs)
- **LL-209 / LL-210 / LL-211 / LL-212 / LL-213** — §v9.49 SOP family (codified through Wave 5 work)
- **铁律 22 / 24 / 25 / 33 / 35 / 41 (Asia/Shanghai) / 42** — sustained across all 5 MVPs

---

**iter 229 ship 三态 per LL-210**: backend-only ✅ doc-sediment (retroactive canonical pattern codification).

**Purpose for future Claude**: when new Operator UI work begins (Wave 6+ or post-Servy-restart UX iterations), this doc codifies the proven canonical patterns to follow. Sibling-faithful adherence → cross-page consistency without explicit audit overhead (validated iter 225).
