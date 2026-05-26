# MVP 5.5 — 调度任务 Dashboard (Tier B Wave 5 sub-MVP 5/5, schtask + Beat)

> **Status**: iter 209 design doc start (sibling MVP 5.1/5.2/5.3 pattern, 3-iter chain target)
> **Sprint**: Tier B Wave 5 Operator UI (QPB v1.17 L1154, 3-5 days effort)
> **ADR refs**: ADR-012 D5 (Wave 5 start) / ADR-084 候选 (react-query)
> **Provenance**: §v9.69 multi-agent fan-out (architect ~264s wallclock iter 209)
> **铁律**: 22 (doc follows code) / 24 (≤2 pages) / 25 (改什么读什么) / 33 (fail-loud) / 42 (AI reviewer mandate sustained 6 cycles) / 44 X9 (Beat schedule restart awareness — read-only dashboard, 0 X9 risk)

---

## §1 Purpose & Scope

Wave 5 last operational dashboard (sub-MVP 5/5). Consolidates scheduling visibility into single page showing Windows schtask QM-* + Celery Beat schedule + scheduler_task_log execution history. **§v9.49 catch #11 surfaced during design**: existing `fetchSchedulerTasks` wrapper has type drift (backend returns `{tasks:[...]}` object, wrapper types as `SchedulerTask[]` array) → SystemSettings SchedulerTab silently renders empty. C1 fixes this side-effect.

**Scope** (read-only page, 0 mutations):
- 5 sections: HealthSummary derived + schtask list + Beat schedule + recent history + per-task drill-down
- Sidebar entry under "系统" group between PT状态 + 系统设置
- Side-effect fix: `fetchSchedulerTasks` wrapper type drift (also fixes SystemSettings silent empty bug)

**Out of scope** (defer):
- Mutation actions (enable/disable Beat / run-now / cancel — separate ops MVP)
- Per-Beat-task cron edit UI (config file SSOT, not UI-editable per ADR)

## §2 Architecture

### §2.1 Data Sources (2 existing + 1 NEW)

| § | User question | Endpoint | Status |
|---|---|---|---|
| S1 | Today's task fire/fail/overdue counts | Derived(S3+S4+S2) client-side | 0 endpoint |
| S2 | Windows schtask QM-* list | `GET /api/system/scheduler` | EXISTS (system.py:418, **wrapper bug fix in C1**) |
| S3 | Celery Beat schedule + last fire | `GET /api/system/beat-schedule` | **NEW C1** |
| S4 | Last 50 execution rows | `GET /api/system/scheduler-task-log?limit=50` | EXISTS (iter 197 PR #511) |
| S5 | Per-task drill-down 20 rows + duration trend | `GET /api/system/scheduler-task-log?limit=20&task_name=X` | EXISTS (same endpoint, task_name filter) |

**Architectural decisions** (per architect analysis):
1. **Server-side Beat introspection** (vs client-side hardcode) — read `CELERY_BEAT_SCHEDULE` dict from live config (27 entries currently), 0 hardcoded drift risk
2. **Single LATERAL JOIN** for beat-schedule endpoint — cross-ref `scheduler_task_log` latest row per task_name (sibling MVP 5.2 ic-monitoring pattern)
3. **fetchSchedulerTasks wrapper fix mandatory** (C1) — current wrapper returns empty array silently due to type drift; SystemSettings SchedulerTab side-effect always-empty bug fixed by same change
4. **S5 inline drill-down** (vs separate route) — click task name → expand section with ECharts duration bar + error log
5. **react-query refetchInterval=60s** sustained pattern (sibling PtStatus / IcMonitoring / BacktestCompare)
6. **Reuse Phase H W1-6** + sibling TaskHistoryTable from PtStatus

### §2.2 Component Map (`SchedulerDashboard.tsx`)

```
SchedulerDashboard.tsx (new) — route /scheduler
├── PageHeader "调度 Dashboard"
├── S1 HealthSummaryBar         ← derived(S3 + S4 + S2)             (client-side)
│   └── 3 MetricCards: tasks_today / failed_today / overdue_count
├── S2 SchtaskListSection       ← fetchSchedulerTasks() [FIXED]      (60s refetch)
│   └── GlassCard per QM-* task: name + status + last_run + next_run
├── S3 BeatScheduleSection      ← fetchBeatSchedule() [NEW]          (60s refetch)
│   └── Table: beat_key / task_name / crontab_display / last_fire / status
├── S4 RecentHistoryTable       ← fetchSchedulerTaskLog(50)          (60s refetch, sibling PtStatus)
│   └── Table: task_name + status pill + start_time + duration + error
│   └── Filter dropdown: task_name (from S4 distinct names)
└── S5 TaskDrillDown (on-click) ← fetchSchedulerTaskLog(20, taskName) (per-click)
    └── ECharts duration trend + error log list
```

## §3 Chunk Decomposition (3 chunks, batched-iter eligible)

| Chunk | Goal | LOC | Iter | Tests |
|---|---|---|---|---|
| **C1** | Backend: NEW `GET /api/system/beat-schedule` endpoint (read CELERY_BEAT_SCHEDULE dict + LATERAL JOIN scheduler_task_log latest per task) + frontend `fetchSchedulerTasks` wrapper fix (destructure .tasks + map field names) + `fetchBeatSchedule` wrapper | ~80 backend + ~40 frontend wrapper | 210 | pytest 4 new (empty / 27 entries / last_fire cross-ref / fetchSchedulerTasks fix) |
| **C2** | Frontend: `SchedulerDashboard.tsx` page scaffold + router `/scheduler` + sidebar Clock icon "调度" entry + S1 HealthSummary + S2 SchtaskListSection + S3 BeatScheduleSection + S4 RecentHistoryTable | ~300 | 211 | Manual: page loads, all sections render, refetchInterval works |
| **C3** | Frontend: S5 TaskDrillDown (click → expand inline + ECharts duration bar) + closure STATUS_REPORT + sibling cross-page smoke verify | ~150 | 212 | Manual: drill-down expands, chart renders, error log shows |

**Batched-iter eligible**: C2+C3 batchable per user efficiency directive (sibling MVP 5.2/5.3 precedent). Target: **2-iter ship** if reviewer cycles pass cleanly (C1 backend / C2+C3 batched frontend).

## §4 Acceptance Criteria

- **C1**: pytest 4/4 PASS; beat-schedule returns 27 entries from CELERY_BEAT_SCHEDULE; last_fire cross-ref correct (sibling LATERAL JOIN); `fetchSchedulerTasks` returns SchedulerTask[] correctly (was empty due to type drift); ruff clean; AI reviewer cycle PASS (铁律 42)
- **C2**: route `/scheduler` accessible; sidebar "调度" entry between PT状态 + 系统设置 in 系统 group; S1-S4 all render with real data; PageSkeleton + ErrorBanner; 60s auto-refresh on S2/S3/S4
- **C3**: S5 drill-down expands on click; ECharts duration bar chart renders; error log shows latest failures; full page load <2s; 0 console errors; STATUS_REPORT closure sediment; SystemSettings SchedulerTab no longer empty (side-effect verify)

## §5 ADR + LL Cross-Ref

- **ADR-012 D5** — Wave 5 start (Wave 5 = 4/5 ✅ post-MVP 5.5)
- **ADR-084 候选** — react-query refetchInterval (PtStatus / IcMonitoring / BacktestCompare sibling)
- **LL-035** — API response format via api/ layer (fetchSchedulerTasks fix validates lesson)
- **LL-187** — Phase H W1-6 component reuse
- **LL-209 / LL-212** — §v9.49 reality re-grounding 11th application (fetchSchedulerTasks silent empty bug caught design-time)
- **铁律 22 / 24 / 25 / 33 / 42 / 44 X9 (read-only no X9 risk)**

## §6 Trade-off Sediment (rejected options)

| Option | Rejected reason |
|---|---|
| Client-side hardcoded Beat list | 27 entries drift on every Beat PR; no last_fire visibility |
| Extend PtStatus with scheduler sections | Mixes "PT state NOW?" vs "ALL scheduled tasks?" intents |
| Extend SystemSettings SchedulerTab in place | Settings-context vs operational-dashboard intent; SystemSettings has the type drift bug making it empty |
| Separate `/scheduler/:taskName` route for drill-down | Route proliferation; inline expand is lighter |

**Chosen**: dedicated page + 1 new endpoint + fix existing wrapper as side-effect.

---

**iter 209 ship 三态 per LL-210**: backend-only ✅ doc-sediment (design phase complete) + §v9.49 catch #11 documented (fetchSchedulerTasks wrapper bug, fix in C1).
**iter 210+ next**: C1 backend + wrapper fix (1 iter w/ reviewer) → C2+C3 batched frontend (1 iter w/ reviewer) → closure (1 iter). Target **2-3 iter MVP 5.5 ship** completing Wave 5 80%.
