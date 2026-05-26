# MVP 5.2 — IC 监控 + 因子衰减可视化 (Tier B Wave 5 sub-MVP 2/5)

> **Status**: iter 201 design doc start (sibling MVP 5.1 pattern, 4-iter chain target)
> **Sprint**: Tier B Wave 5 Operator UI (QPB v1.17 L1151, 3-5 days effort estimate)
> **ADR refs**: ADR-012 D5 (Wave 5 start) / ADR-084 候选 (react-query lifecycle) / 铁律 11 (factor_ic_history SSOT)
> **Provenance**: §v9.69 multi-agent fan-out (Explore + architect parallel ~215s wallclock iter 201)
> **铁律**: 11 (IC SSOT) / 22 (doc follows code) / 24 (≤2 pages) / 33 (fail-loud)

---

## §1 Purpose & Scope

113 active factors in `factor_ic_history` table updated daily via `compute_daily_ic.py` + rolling averages `compute_ic_rolling.py` + lifecycle status `factor_lifecycle.py`. Existing per-factor deep-dive: FactorEvaluation (`/factors/:id`, 6 tabs). Existing catalog browse: FactorLibrary (`/factors`). **Gap**: no pool-level monitoring page answering "how healthy is the overall factor pool RIGHT NOW?".

**Scope** (read-only page, 0 mutations):
- 5 sections answering 5 pool-level questions (IC time series per factor / decay heatmap / health summary / CORE3+dv_ttm quick-access / decay alerts)
- Sidebar entry under "因子" nav group between FactorLibrary + FactorLab
- Sibling pattern to PtStatus (MVP 5.1): pool-level monitoring vs per-factor deep-dive (PTGraduation vs PtStatus precedent)

**Out of scope** (defer to future MVP):
- Factor mutations (archive/promote — separate Wave 5 sub-MVP or AI闭环)
- Individual factor deep-dive (link to existing FactorEvaluation)
- GP/mining (separate FactorLab page)

## §2 Architecture

### §2.1 Data Sources (1 NEW + 3 existing endpoints)

| § | User question | Endpoint | Status |
|---|---|---|---|
| S1 | IC trend for factor X last N days? | `GET /api/factors/{name}?start_date=&end_date=` | EXISTS (`factors.py:478`) |
| S2 | Which factors are decaying? (113-factor heatmap) | `GET /api/factors/ic-monitoring` | **NEW** |
| S3 | How many active/warning/retired? | `GET /api/factors/stats` | EXISTS (`factors.py:310`) |
| S4 | CORE3+dv_ttm current state? | `GET /api/factors/ic-monitoring` (filtered pool=CORE) | NEW (same endpoint as S2) |
| S5 | Which active factors have IC decay >50%? | `GET /api/factors/health` (client-filter `decay_warning=true`) | EXISTS (`factors.py:58`) |

**Architectural decisions** (per architect analysis):
1. **1 new endpoint, not 5** — only the multi-factor heatmap data missing from existing API surface
2. **Single LATERAL JOIN query for new endpoint** — O(1) SQL, not N+1; uses `factor_ic_history` PK index for last-row lookup per factor; <50ms p99 for 113 factors
3. **ECharts (not recharts)** — 100% factor-domain consistency (8/8 existing factor components use echarts-for-react); native `heatmap` series + `visualMap` support
4. **New page `/factors/monitoring`** — distinct user intent (pool monitoring) vs FactorEvaluation (single-factor deep-dive); follows PtStatus/PTGraduation separation precedent
5. **Period selector pattern** — sibling NAVChart.tsx PERIODS array + onPeriodChange callback (60d / 180d / 365d)
6. **Reuse existing components** — PageSkeleton + ErrorBanner + GlassCard + MetricCard + StatusBadge from Phase H W1-6
7. **react-query refetchInterval** — canonical PtStatus pattern (S2/S3/S5 60s, S1 per-fetch on dropdown/period change)

### §2.2 Component Map (`IcMonitoring.tsx`)

```
IcMonitoring.tsx (new)
├── PageHeader "IC 监控" + 副 title "因子衰减可视化 — Wave 5 MVP 5.2"
├── S1 IcTimeSeriesSection      ← getFactorDetail(name)         (per-fetch on selector change)
│   ├── Factor dropdown (default: turnover_mean_20, CORE3+dv_ttm priority)
│   ├── Period selector: 60d / 180d / 365d
│   └── ECharts: IC bar + ic_ma20 line overlay (sibling TabICAnalysis pattern)
├── S2 DecayHeatmapSection      ← fetchIcMonitoring()            (60s refetch)
│   └── ECharts heatmap: rows=113 factors, color=decay_level (normal=green / warning=amber / critical=red)
├── S3 FactorHealthSummary      ← getFactorsStats()              (60s refetch)
│   └── 3 MetricCards: active count / warning count / retired count
├── S4 CoreFactorPanel          ← fetchIcMonitoring() filtered pool=CORE
│   └── 4 GlassCards (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm): ic_ma20 value + decay badge + link → /factors/{name}
└── S5 DecayAlertTable          ← getFactorsHealth() filtered decay_warning=true (client-side)
    └── Table: factor / ic_30d / ic_90d / ratio / trend badge
```

## §3 Chunk Decomposition (4 chunks, sibling MVP 5.1 batched-iter eligible)

| Chunk | Goal | LOC | Iter | Dependencies | Tests |
|---|---|---|---|---|---|
| **C1** | Backend: `GET /api/factors/ic-monitoring` endpoint (LATERAL JOIN factor_registry + factor_ic_history last row, filterable `?pool=CORE`) + 3 TDD tests (empty/populated/CORE filter) | ~80 | 202 | factor_registry + factor_ic_history (EXIST per DDL_FINAL.sql:245-298) | pytest 3 new + reviewer cycle |
| **C2** | Frontend: `IcMonitoring.tsx` page scaffold + router `/factors/monitoring` + sidebar "IC监控" entry under 因子 group + S3 HealthSummary (existing getFactorsStats) + S5 DecayAlertTable (existing getFactorsHealth + client filter) | ~200 | 203 | C1 not required (S3/S5 reuse existing) | Manual: page loads, counts render, alert table filters |
| **C3** | Frontend: S1 IcTimeSeriesSection (factor dropdown + period selector + ECharts IC bar + ma20 line) + S4 CoreFactorPanel (4 mini-cards from ic-monitoring endpoint) | ~250 | 204 | C1 endpoint + C2 scaffold | Manual: chart renders, period switch works, CORE cards show |
| **C4** | Frontend: S2 DecayHeatmapSection (ECharts heatmap from ic-monitoring endpoint) + closure STATUS_REPORT + smoke verify | ~180 | 205 | C1 + C2 + C3 | Manual: heatmap renders, tooltip + color mapping correct, 0 console |

**Batched-iter eligible**: C2+C3+C4 frontend chunks can batch in 1 iter per user efficiency directive (sibling MVP 5.1 iter 198 precedent). Target: **3-iter MVP 5.2 ship** (iter 202 backend / iter 203 frontend batched / iter 204 closure).

## §4 Acceptance Criteria

- **C1**: pytest 3/3 PASS on `test_factors_ic_monitoring_*`; response schema `{decay_heatmap: [{name, status, pool, ic_decay_ratio, ic_ma20, ic_ma60, decay_level}], core_factors: [...4 items]}`; single SQL query (no N+1); index-optimized via factor_ic_history PK
- **C2**: route `/factors/monitoring` accessible; Sidebar "IC监控" entry between FactorLibrary + FactorLab in 因子 group; S3 shows 3 MetricCards (active=N / warning=M / retired=K); S5 shows table filtered to `decay_warning=true` rows; PageSkeleton on first load; ErrorBanner on API failure (铁律 33)
- **C3**: S1 factor dropdown lists all active factors (default: turnover_mean_20); period selector 60d/180d/365d switches `start_date`/`end_date` params; ECharts IC bar chart + ic_ma20 overlay renders (sibling TabICAnalysis); S4 shows 4 CORE factor cards (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm) with ic_ma20 + decay badge + clickable link to `/factors/{name}`
- **C4**: S2 heatmap renders 113 factors (y-axis) × decay_level color (visualMap normal=green / warning=amber / critical=red); tooltip shows factor name + ic_ma20 + ic_ma60 + decay_level; full page load <2s all 5 sections; 0 console errors; refetchInterval=60s on S2+S3+S5; STATUS_REPORT closure sediment

## §5 ADR + LL Cross-Ref

- **ADR-012 D5** — Wave 5 Operator UI start condition (satisfied 2026-05-25, MVP 5.1 ✅ iter 199)
- **ADR-084 候选** — react-query refetchInterval canonical pattern (PtStatus sibling)
- **LL-187** — Phase H W1-6 component reuse (GlassCard/MetricCard/PageSkeleton/ErrorBanner)
- **LL-181** — calendar SSOT pattern (factor_ic_history is IC truth per 铁律 11, equivalent SSOT)
- **铁律 11** — IC must have traceable DB record (factor_ic_history sole source)
- **铁律 22** — doc follows code (sidebar nav + SYSTEM_STATUS sync on C4 closure)
- **铁律 24** — MVP design doc ≤2 pages
- **铁律 33** — fail-loud on API errors (ErrorBanner, not silent empty)
- **铁律 42** — AI reviewer mandate for backend code PR (sustained from iter 198 user correction)

## §6 Trade-off Sediment (rejected options)

| Option | Rejected reason |
|---|---|
| Extend FactorEvaluation with monitoring tab | Single-factor scoped (`useParams<{id}>`); pool-level tab breaks conceptual model + routing conflict |
| Extend FactorLibrary with monitoring section | Catalog/browse page; adding charts + heatmap overloads purpose |
| Reuse existing /health + /stats endpoints only | /health does N+1 queries per factor; no access to decay_level/ic_ma20/ic_ma60 columns; missing heatmap data |
| Recharts instead of ECharts | No native heatmap; breaks factor-domain consistency (8/8 existing use echarts); would need custom SVG |

**Chosen**: new page + 1 new endpoint + ECharts (sibling architect decision validates pattern).

---

**iter 201 ship 三态 per LL-210**: backend-only ✅ doc-sediment (design phase complete).
**iter 202+ next**: C1 backend endpoint impl (1 iter) → C2+C3+C4 frontend batched (1 iter) → closure (1 iter). Target **3-iter MVP 5.2 ship** per user efficiency directive.
