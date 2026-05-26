# MVP 5.1 — PT 状态 Page (Tier B Wave 5 sub-MVP 1/5)

> **Status**: iter 196 design doc start (sibling MVP 4.5/4.6/4.7/4.8 pattern)
> **Sprint**: Tier B Wave 5 Operator UI (START SATISFIED 2026-05-25 post Wave 4 close, 33+ days sustained)
> **ADR refs**: ADR-012 D5 (Wave 5 start condition) / ADR-084 (react-query lifecycle pattern) / QPB v1.17 line 7
> **Provenance**: §v9.69 multi-agent fan-out (Explore 25+ files + architect parallel ~248s wallclock iter 196)
> **铁律**: 24 (≤2 pages) / 33 (fail-loud) / 22 (doc follows code)

---

## §1 Purpose & Scope

PT 真账户 0 持仓 + paper-mode sustained 28+ days post 4-29 清仓. 现状: PTGraduation page 答 "are we ready to graduate?" (gate metrics), SystemSettings page 配置查看, **0 operational dashboard 答 "what is current state RIGHT NOW?"**. MVP 5.1 closes this gap.

**Scope** (read-only page, 0 mutations):
- 5 operational questions answerable from single page (lifecycle / trading state / system health / restart blockers / recent task history)
- Complement (not overlap) PTGraduation gate metrics + SystemSettings config view
- Sidebar entry between PTGraduation + SystemSettings under "系统" nav group

**Out of scope** (defer to MVP 5.2+):
- Servy process-level monitoring (FastAPI/Celery individual state)
- Historical trend charts (current state focus)
- Mutation actions (Start/Stop/Restart buttons — separate Wave 5 sub-MVP)

## §2 Architecture

### §2.1 Data Sources (1 NEW endpoint + 4 existing)

| § | User question | Endpoint | Status |
|---|---|---|---|
| S1 | Lifecycle Day X/Y? | `GET /api/system/calendar-info` → `pt_day_counter` | EXISTS (`system.py:407`) |
| S2 | Trading state (positions/cash/mode)? | `GET /api/system/env-state` + `usePortfolio()` hook | EXISTS (`system.py:458` + `useRealtimeData.ts`) |
| S3 | System health (5 services)? | `GET /api/system/health` (PG/Redis/Celery/Disk/Memory) | EXISTS (`system.py:298`) |
| S4 | PT restart blockers? | Composite frontend-derived from S1+S2+S3 | Derived (0 extra fetch) |
| S5 | Recent task history (last 20 rows)? | `GET /api/system/scheduler-task-log?limit=20` | **NEW endpoint** |

**Architectural decisions** (per architect analysis):
1. **1 new endpoint, not 5** — only `scheduler-task-log` rows missing from existing surface; other 4 questions composable from existing endpoints
2. **Frontend composition for S4** — 0 new "blocker analysis" endpoint; derive client-side from S1+S2+S3 data (PTGraduation precedent)
3. **react-query refetchInterval** — canonical EnvStateBanner pattern (`EnvStateBanner.tsx:91-96`); per-section refresh rates (S1=60s / S2=5s reuse cache / S3=30s / S5=60s)
4. **Reuse shared components** — 0 new shared components needed (Card / StatusBadge / PageHeader / MetricMini / PageSkeleton / ErrorBanner all exist from Phase H W1-6)
5. **Complementary to PTGraduation** — same `pt_day_counter` source, different user intent (operational vs graduation gate)

### §2.2 Component Map (`PtStatus.tsx`)

```
PtStatus.tsx (new)
├── PageHeader "PT 状态" + 副 title "运维 dashboard"
├── S1 LifecycleCard       ← fetchCalendarInfo()   (60s)
├── S2 TradingStateCard    ← usePortfolio() + fetchEnvState() (5s reuse)
├── S3 SystemHealthCard    ← fetchSystemHealth()   (30s)
├── S4 RestartChecklistCard ← derived(S1, S2, S3)
└── S5 TaskHistoryTable    ← fetchSchedulerTaskLog() (60s, NEW API)
```

## §3 Chunk Decomposition (5 chunks, sibling MVP 4.8 batched-iter eligible)

| Chunk | Goal | LOC | Iter | Dependencies | Tests |
|---|---|---|---|---|---|
| **C1** | Backend: `GET /api/system/scheduler-task-log` endpoint + 3 tests (empty/populated/limit) | ~60 | 197 | scheduler_task_log table (EXISTS, idx_scheduler_log_date) | pytest backend/tests/test_api_system.py 3 new cases |
| **C2** | Frontend: `PtStatus.tsx` page scaffold + router + sidebar entry + S1 + S2 sections | ~180 | 198 | C1 not required (S1/S2 reuse existing API) | Manual verify: page loads, data renders, PageSkeleton on loading |
| **C3** | Frontend: S3 (health) + S4 (restart checklist derived) sections | ~120 | 199 | C2 page exists | Manual verify: 5 health badges render, checklist derives correctly |
| **C4** | Frontend: S5 (task history table) + `fetchSchedulerTaskLog` wrapper in `api/system.ts` | ~100 | 200 | C1 endpoint + C2 page | Manual verify: table renders, empty state, error banner |
| **C5** | Closure: Sidebar nav order + cross-page smoke + STATUS_REPORT + MVP doc closure | ~40 | 201 | C2+C3+C4 | Full page smoke 3 modes (loading/normal/error) |

**Estimated total**: ~500 LOC backend + frontend + tests, 5 iter sibling MVP 4.7 chunk-per-iter OR 2-3 iter via batched-iter pattern per user efficiency directive (iter 184 sustained).

## §4 Acceptance Criteria

- **C1**: pytest 3/3 PASS on `test_scheduler_task_log_*` — empty / populated / limit param; returns `{tasks: [...], total_count: N}` schema; index-optimized query (<10ms p99)
- **C2**: route `/pt-status` accessible; Sidebar "PT 状态" entry between PTGraduation + SystemSettings; S1 shows `Day X/Y (Z%)` from calendar-info; S2 shows position count + cash from usePortfolio; PageSkeleton on first load
- **C3**: S3 shows 5 health badges (PG/Redis/Celery/Disk/Memory) with StatusBadge color mapping; S4 shows derived checklist ≥4 items (env-safe / health-all-ok / pt-days-sufficient / 0-pending); checklist auto-updates on health/env change
- **C4**: S5 table renders with StatusBadge per row; EmptyState on 0 rows; ErrorBanner on API failure; 60s auto-refresh; columns task_name + status + start_time + duration_sec + error_message
- **C5**: full page load <2s; all 5 sections render with real data; sidebar nav order PTGraduation → PtStatus → SystemSettings; 0 console errors; ErrorBanner on any sub-API failure (fail-loud per 铁律 33); STATUS_REPORT closure sediment

## §5 ADR + LL Cross-Ref

- **ADR-012 D5** — Wave 5 Operator UI start condition (satisfied 2026-05-25 post Wave 4 close, 33+ days sustained)
- **ADR-084 候选** — react-query refetchInterval canonical pattern (EnvStateBanner sibling)
- **LL-181** — calendar SSOT single source (pt_day_counter via calendar-info, no hardcoded "PT Day X/60")
- **LL-183** — silent NOT-GATING prevention (env-state banner reuse pattern)
- **LL-187** — Frontend Redesign v3 W1+2+4+5+6 (Phase H sediment, 5 NEW components ready for reuse)
- **铁律 22** — doc follows code (sidebar nav + SYSTEM_STATUS sync on C5 closure)
- **铁律 24** — MVP design doc ≤2 pages (this doc)
- **铁律 33** — fail-loud on API errors (ErrorBanner, not silent empty state)

## §6 Trade-off Sediment (rejected options)

| Option | Rejected reason |
|---|---|
| New composite `/api/pt-status` single endpoint | Backend coupling + duplicates 4 existing endpoint surfaces + harder isolated test |
| Extend PTGraduation page with operational sections | Overloads gate-metric purpose + mixes "are we ready?" with "what's happening now?" intents |
| Server-side blocker analysis (Q4 endpoint) | Frontend has all S1-S3 data; client-side derivation = 0 extra fetch + simpler test |

**Chosen**: 4-existing + 1-new endpoint composition (sibling architect decision A, validates pattern).

---

**iter 196 ship 三态 per LL-210**: backend-only ✅ doc-sediment (design phase complete).
**iter 197+ next**: C1 backend endpoint impl (1 iter) → C2-C4 batched-iter eligible per MVP 4.8 efficiency directive precedent.
