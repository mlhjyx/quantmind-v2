# MVP 5.3 — 回测结果对比页 (Tier B Wave 5 sub-MVP 3/5)

> **Status**: iter 205 design doc start (sibling MVP 5.1/5.2 pattern, 4-iter chain target)
> **Sprint**: Tier B Wave 5 Operator UI (QPB v1.17 L1152, 3-5 days effort)
> **ADR refs**: ADR-012 D5 (Wave 5 start) / ADR-084 候选 (react-query) / 铁律 15 (reproducibility)
> **Provenance**: §v9.69 multi-agent fan-out (Explore + architect parallel ~217s wallclock iter 205)
> **铁律**: 15 (reproducibility) / 22 (doc follows code) / 24 (≤2 pages) / 33 (fail-loud) / 42 (AI reviewer mandate sustained)

---

## §1 Purpose & Scope

Existing `BacktestResults.tsx` `TabCompare` (line 548-610) is a primitive 1v1 UUID-input compare showing 4 metrics. **Gap**: no dedicated multi-run comparison page with overlay charts + trade diff + reproducibility seal. MVP 5.3 closes this gap with shareable URL state.

**Scope** (read-only page, 0 mutations):
- 5 sections: run selector (max 3) + metric table + NAV overlay + drawdown overlay + trade diff + reproducibility seal
- URL-shareable via `?runs=uuid1,uuid2,uuid3` query params
- Sibling pattern to MVP 5.1 PtStatus + MVP 5.2 IcMonitoring (pool-level monitoring)
- Existing `TabCompare` becomes link to new page (backward compat preserved)

**Out of scope** (defer):
- Server-side trade diff join (client-side approximation acceptable)
- WF-fold-level comparison (whole-run comparison only)
- Statistical significance test (paired bootstrap separate to deep-dive)

## §2 Architecture

### §2.1 Data Sources (1 endpoint EXTEND + 3 existing reuse — Option C Hybrid)

| § | User question | Endpoint | Status |
|---|---|---|---|
| S1 | Pick 2-3 runs from history | `GET /api/backtest/history` | EXISTS (`backtest.py:264`) |
| S2 | Side-by-side metrics + seal | `POST /api/backtest/compare` | **EXTEND** — add 7 fields (config_yaml_hash / git_commit / factor_list / annual_turnover / sortino_ratio / start_date / end_date) |
| S3 | NAV overlay 2-3 lines | `GET /api/backtest/{run_id}/nav` × N | EXISTS (`backtest.py:429`) parallel fetch via `Promise.all` |
| S4 | Drawdown overlay | Same NAV endpoint (drawdown column) | EXISTS (shares S3 fetch) |
| S5 | Trade list diff | `GET /api/backtest/{run_id}/trades` × N | EXISTS (`backtest.py:469`) lazy-on-expand |

**Architectural decisions** (per architect analysis):
1. **Option C Hybrid**: extend `/compare` (6-line change, +7 fields from existing `SELECT *`) vs monolithic server-side NAV/trades join. NAV/trades remain per-run independently cacheable
2. **5-7 HTTP calls via `Promise.all`** parallel fetches (no waterfall)
3. **URL query param state** `?runs=uuid1,uuid2,uuid3` (shareable, max 3 enforced)
4. **ECharts multi-series overlay** for NAV+drawdown (sibling BacktestResults `series[]` pattern line 86-134)
5. **Lazy trade diff on expand** (avoid upfront 12yr trade load × N runs)
6. **TabCompare deprecation soft path**: existing TabCompare in BacktestResults adds "Open full comparison →" link to `/backtest/compare?runs=currentRunId`
7. **Reuse Phase H W1-6** components (PageSkeleton / ErrorBanner / Card / StatusBadge)
8. **AI reviewer mandate sustained** (铁律 42 + 9-step PR workflow) — cycle BEFORE PR open both backend (C1) + frontend (C2+C3+C4)

### §2.2 Component Map (`BacktestCompare.tsx`)

```
BacktestCompare.tsx (new) — route /backtest/compare
├── PageHeader "回测对比" + 副 title "regression + WF + 实验 多 run 对比"
├── S0 RunSelector              ← fetchBacktestHistory()         (one-time, completed filter)
│   └── Multi-select dropdown (max 3) + sync URL query param ?runs=
├── S1 MetricComparisonTable    ← compareBacktests([runIds])    (extended /compare)
│   └── Sharpe / MDD / Annual Return / Calmar / Turnover / Sortino per run side-by-side
├── S2 ReproducibilitySeal      ← same compare endpoint
│   └── config_yaml_hash + git_commit + start_date + end_date + factor_list (铁律 15)
├── S3 NavOverlayChart          ← Promise.all(runIds.map(getNavSeries))  (parallel fetch)
│   └── ECharts multi-series: 2-3 strategy lines + benchmark dashed + dataZoom slider
├── S4 DrawdownOverlayChart     ← same NAV data (drawdown column)
│   └── ECharts area series (underwater curve per run)
└── S5 TradeListDiff (lazy)     ← Promise.all(runIds.map(getTrades))   (on-expand)
    └── 3-column tables side-by-side + top-10 divergent positions client-summary
```

## §3 Chunk Decomposition (4 chunks, batched-iter eligible)

| Chunk | Goal | LOC | Iter | Dependencies | Tests |
|---|---|---|---|---|---|
| **C1** | Backend: extend `POST /api/backtest/compare` response with +7 fields (config_yaml_hash / git_commit / factor_list / annual_turnover / sortino_ratio / start_date / end_date) from existing `_get_run_or_404` SELECT * | ~40 | 206 | backtest.py:1097-1122 existing | pytest 2 new (seal fields present / factor_list array) |
| **C2** | Frontend: `BacktestCompare.tsx` scaffold + route `/backtest/compare` + sidebar "回测对比" entry under 策略 group + RunSelector (multi-select dropdown from `/history`, max 3) + MetricComparisonTable + ReproducibilitySeal | ~280 | 207 | C1 (extended compare) | Manual: page loads, run selector works, metric+seal renders |
| **C3** | Frontend: NavOverlayChart (ECharts multi-series, 2-3 lines + benchmark) + DrawdownOverlayChart (sibling area series) + `getNavSeries` API wrapper if not exist | ~220 | 208 | C2 scaffold | Manual: 2 runs overlay correctly, dataZoom works, tooltip shows all |
| **C4** | Frontend: TradeListDiff (lazy-on-expand, per-run table side-by-side) + top-10 divergent positions client-summary + TabCompare → link soft-deprecation + closure STATUS_REPORT | ~200 | 209 | C2 + C3 | Manual: lazy fetch works, divergence summary correct |

**Batched-iter eligible**: C2+C3+C4 batchable in 1-2 iter per user efficiency directive + sibling MVP 5.2 iter 203 4-chunk-in-1-iter precedent. Target: **3-iter ship** (C1 / C2+C3+C4 batched / closure).

## §4 Acceptance Criteria

- **C1**: pytest 2/2 PASS on `test_compare_*_seal_fields_present` + `test_compare_factor_list_array`; existing compare tests unbroken; AI reviewer cycle 1 PASS (铁律 42); ruff clean
- **C2**: route `/backtest/compare` accessible; sidebar "回测对比" entry between 策略库 + 因子库 in 策略 group; run selector loads completed runs from `/history`; max 3 selection enforced; metric table 7 columns (Sharpe/MDD/Annual/Calmar/Turnover/Sortino) per run; seal shows config_yaml_hash + git_commit + start/end date + factor_list per run; PageSkeleton + ErrorBanner; URL `?runs=...` reactive
- **C3**: NAV overlay 2-3 lines with distinct colors + benchmark dashed; drawdown overlay below with area fill; date range auto-aligns to union; ECharts dataZoom + tooltip multi-value
- **C4**: trade tables lazy-load on expand (sibling pattern, avoid upfront fetch); top-10 divergent positions computed client-side from last-shared-rebalance-date holdings; full page load <3s for 2 runs; 0 console errors; STATUS_REPORT closure sediment

## §5 ADR + LL Cross-Ref

- **ADR-012 D5** — Wave 5 Operator UI start (satisfied 2026-05-25)
- **ADR-084 候选** — react-query refetchInterval canonical (sibling PtStatus / IcMonitoring)
- **LL-035** — API response format via api/ layer (no inline apiClient.get in page, sustained iter 203 reviewer enforcement)
- **LL-187** — Phase H W1-6 component reuse
- **LL-212** — §v9.49 SOP extension to ALL backlog items + verdict taxonomy (LL-209 parent)
- **铁律 15** — Reproducibility: config_yaml_hash + git_commit per run (DDL backtest_run:592-593)
- **铁律 22** — Doc follows code (sidebar nav + SYSTEM_STATUS sync on C4 closure)
- **铁律 24** — MVP design doc ≤2 pages
- **铁律 33** — Fail-loud on API errors (ErrorBanner, not silent empty)
- **铁律 42** — AI reviewer mandate sustained iter 198 user correction (both C1 + C2+ MUST review before PR open)

## §6 Trade-off Sediment (rejected options)

| Option | Rejected reason |
|---|---|
| **A**: Server-side composite `/compare` with NAV+trades inline | Monolithic 12k+ row response; breaks per-run cache; complex pagination for embedded trades |
| **B**: Pure client-side composition (no `/compare` extend) | No reproducibility seal without extending `/compare`; misses 铁律 15 requirement |
| **C** (chosen): Hybrid +7 field extend + parallel `Promise.all` | 5-7 HTTP calls (vs 1 monolithic OR 7-9 sequential); per-run NAV/trades independently cacheable; minimal backend change |
| Extend existing BacktestResults TabCompare in place | Mixes "view one result" vs "compare N results" intents; routing conflict with `:runId/result` |

**Chosen**: Option C + dedicated page + TabCompare soft-link migration (validates architect decision).

---

**iter 205 ship 三态 per LL-210**: backend-only ✅ doc-sediment (design phase complete) + §v9.49 reality cycle implicit (rolled into design doc as 10th cumulative app per iter 204 STATUS_REPORT §4).
**iter 206+ next**: C1 backend `/compare` extend (1 iter w/ reviewer) → C2+C3+C4 frontend batched (1-2 iter w/ reviewer) → closure (1 iter). Target **3-iter MVP 5.3 ship**.
