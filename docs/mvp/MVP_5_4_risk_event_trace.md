# MVP 5.4 — 风控事件链路追踪 (Tier B Wave 5 sub-MVP 4/5, FINAL Wave 5)

> **Status**: iter 213 design doc start (sibling MVP 5.1/5.2/5.3/5.5 pattern, 3-iter chain target)
> **Sprint**: Tier B Wave 5 Operator UI — LAST piece (QPB v1.17 L1153, 1 week effort)
> **ADR refs**: ADR-012 D5 (Wave 5 start) / ADR-010 D3+D4 (risk_event_log unified table) / ADR-084 候选 (react-query)
> **Provenance**: §v9.69 multi-agent fan-out (architect ~255s wallclock iter 213)
> **铁律**: 22 / 24 (≤2 pages) / 33 (fail-loud) / 42 (AI reviewer mandate sustained 8 cycles → +2 = 10)

---

## §1 Purpose & Scope

Completes Wave 5 to **5/5 ✅ 100%** as the last sub-MVP. Current `/risk` page has 6 tabs (overview / 状态历史 / 压力测试 / 限额监控 / 紧急控制 / 实时事件 SSE-only). **Gap**: no historical query / filter / chain trace on risk events. SSE stream is push-only — can't query past events by severity / rule_id / time window. MVP 5.4 adds 7th tab "事件追踪" closing this gap.

**Scope** (7th tab on existing `/risk` page, 0 new routes):
- 4 sections: FilterBar + EventListTable + 24h HeatmapBar + inline Chain drill-down
- Reuse existing `risk_event_log` table (13 core + 4 realtime columns) + `execution_plans.triggered_by_event_id` chain FK
- 1 NEW endpoint: `GET /api/risk/events?severity=&rule_id=&hours=&include_chain=` + `GET /api/risk/events/rule-ids`
- Live "实时事件" tab sustained as-is (push-only complement)

**Out of scope** (defer):
- Mutations (acknowledge/resolve — separate ops MVP)
- Cross-strategy correlation (single strategy_id scope)
- trade_log FK chain (no FK exists, date-range heuristic not robust)

## §2 Architecture

### §2.1 Data Sources (1 NEW endpoint + 2 existing)

| § | User question | Endpoint | Status |
|---|---|---|---|
| S0 | Filter bar (severity + rule_id + time window + code) | client-side state | 0 endpoint |
| S1 | Recent events (filtered, paginated) | `GET /api/risk/events?severity=&rule_id=&hours=&limit=&offset=&include_chain=` | **NEW** |
| S1b | Rule_id discovery (filter dropdown) | `GET /api/risk/events/rule-ids` | **NEW** (companion) |
| S2 | Event chain (inline drill-down) | Same /events response when `include_chain=true` (LEFT JOIN execution_plans on triggered_by_event_id) | NEW (same endpoint) |
| S3 | 24h heatmap (events per hour) | Derived client-side from S1 data | 0 endpoint |
| (existing) | Live event stream | `GET /api/sse/risk-events` | EXISTS (sse.py:159, sustained) |

**Architectural decisions** (per architect analysis):
1. **1 new endpoint with LEFT JOIN** (not separate /chain endpoint) — `include_chain=true` param adds execution_plans JOIN inline; saves 2nd round-trip on drill-down
2. **New tab on existing /risk page** (Option A, not new page) — 7 tabs manageable; risk events belong contextually with RiskManagement
3. **Client-side heatmap** — ~3 events/day makes group-by-hour trivially fast in browser
4. **Dynamic rule_id dropdown** — query SELECT DISTINCT rule_id (cached on tab mount) vs hardcoding 20+ rule_ids (PMS / CB / intraday / 10 realtime / etc)
5. **Index-optimized**: `ix_risk_event_rule_time` (rule_id, triggered_at DESC) + `ix_risk_event_strategy_time` for severity-only filter; <10ms p99 query
6. **AI reviewer 铁律 42 mandate** sustained — both C1 backend + C2+ frontend cycle before PR open

### §2.2 Component Map (new tab on RiskManagement.tsx)

```
RiskManagement.tsx (existing) — 7th tab "事件追踪"
└── RiskEventTrace (rendered on tab select)
    ├── S0 FilterBar
    │   ├── SeverityDropdown (p0/p1/p2/info)
    │   ├── RuleIdDropdown (dynamic from /rule-ids)
    │   ├── TimeWindowSelect (1h / 6h / 24h / 7d / 30d)
    │   └── SearchInput (code filter, optional)
    ├── S3 HeatmapBar (24 hourly slots, last 24h, color = max severity)
    ├── S1 EventListTable (paginated, sorted by triggered_at DESC)
    │   └── Columns: triggered_at | severity pill | rule_id | code | action_taken | reason
    │   └── Click row → expand S2 inline
    └── S2 EventChainPanel (inline expand on row click)
        ├── Full reason + context_snapshot key metrics
        ├── execution_plan chain (plan_id, status, action, qty, user_decision, broker_order_id)
        └── detection_latency_ms badge (if realtime cadence)
```

## §3 Chunk Decomposition (3 chunks, batched-iter eligible)

| Chunk | Goal | LOC | Iter | Tests |
|---|---|---|---|---|
| **C1** | Backend: `GET /api/risk/events` endpoint (severity / rule_id / hours / limit / offset / include_chain LEFT JOIN execution_plans) + `GET /api/risk/events/rule-ids` companion + 6 TDD tests | ~120 backend | 214 | pytest 6: empty / populated / severity filter / rule_id filter / chain JOIN / pagination |
| **C2** | Frontend: 7th tab "事件追踪" + FilterBar + EventListTable + HeatmapBar (S0+S1+S3) + `fetchRiskEvents` + `fetchRuleIds` API wrappers | ~280 | 215 | Manual: tab loads, filters work, heatmap renders, table paginated |
| **C3** | Frontend: S2 EventChainPanel inline drill-down (row expand + context metrics + latency badge) + closure STATUS_REPORT + Wave 5 100% verify | ~150 | 216 | Manual: drill-down expands, chain shows execution_plan link, latency badge |

**Batched-iter eligible**: C2+C3 batchable per user efficiency directive. Target: **2-3 iter MVP 5.4 ship** completing Wave 5 to **5/5 ✅ 100%**.

## §4 Acceptance Criteria

- **C1**: pytest 6/6 PASS; `/events` returns `{events: [...], total_count, rule_ids_available}` shape; severity/rule_id filter; LEFT JOIN execution_plans when `include_chain=true`; pagination offset+limit; index-optimized <10ms p99; ruff clean; AI reviewer cycle PASS
- **C2**: "事件追踪" 7th tab visible in RiskManagement; FilterBar 4 controls render; HeatmapBar 24 hourly slots with color = max severity per slot; EventListTable severity pill color coding (p0=red, p1=orange, p2=yellow, info=gray); pagination controls; 60s react-query refetchInterval; PageSkeleton + ErrorBanner
- **C3**: row click → inline expand shows full reason + context_snapshot key metrics; chain section shows execution_plan when triggered_by_event_id matches, "无关联执行计划" when null; detection_latency_ms badge for realtime cadence events; full page load <2s; 0 console errors; STATUS_REPORT closure documenting **Wave 5 = 5/5 ✅ 100% milestone**

## §5 ADR + LL Cross-Ref

- **ADR-012 D5** — Wave 5 Operator UI start (MVP 5.4 closes Wave 5 to 5/5 100%)
- **ADR-010 D3+D4** — risk_event_log unified event table (MVP 3.1 batch 1 sediment)
- **ADR-084 候选** — react-query refetchInterval canonical (sibling sustained)
- **LL-035** — API wrapper response shape via api/ layer
- **LL-081** — PMSRule zombie fail-loud (visible in event chain)
- **LL-187** — Phase H W1-6 component reuse
- **LL-209 / LL-212** — §v9.49 reality re-grounding + verdict taxonomy
- **铁律 22 / 24 / 33 / 42 reviewer mandate sustained 8+ cycles**

## §6 Trade-off Sediment (rejected options)

| Option | Rejected reason |
|---|---|
| Separate /risk-event-trace page | Fragments risk surface, RiskManagement is contextual home |
| Enhance "实时事件" SSE tab with filters | SSE is push-only, can't query history, filtering SSE client-side wastes bandwidth |
| Server-side heatmap endpoint | ~3 events/day → client-side groupby trivially fast |
| trade_log FK JOIN in chain | No FK, date-range heuristic not robust, defer to future MVP |
| Separate /risk-events/:id route for drill-down | Route proliferation, inline expand lighter (sibling MVP 5.5 TaskDrillDown pattern) |

**Chosen**: 7th tab + 1 new endpoint + LEFT JOIN inline + client-side heatmap + inline drill-down. Architect Option A validated.

---

**iter 213 ship 三态 per LL-210**: backend-only ✅ doc-sediment (design phase complete).
**iter 214+ next**: C1 backend events endpoint + 6 TDD + reviewer (1 iter) → C2+C3 frontend batched (1-2 iter) → closure (1 iter). Target **3-iter MVP 5.4 ship completing Wave 5 to 5/5 ✅ 100%**.
