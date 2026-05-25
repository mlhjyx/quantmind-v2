# W14 — PipelineConsole window.prompt 残修 + EMPTY_STATUS fail-loud Plan (2026-05-25)

> **Status**: ✅ **CLOSED iter 107** (PR #480 merged `847e30a`, 2026-05-25 ~21:18 SH). Plan delivered as specified.
> **Source**: FRONTEND_V3_W7_W15_PLAN_2026_05_25.md §3 W14 (~4h solo-safe quick win).
> **Scope**: Pure frontend, 0 backend dep.
> **Iter 107 closure summary** (verify 2026-05-25 ~21:35 SH post-merge):
>   - Plan §2 Changes A-E all applied (EMPTY_STATUS delete / nullable state / fail-loud guard / setStatus(null) on catch / W1-W6 comment reword)
>   - Plan §3 file footprint actual: +238 / -24 LOC across 2 files (vs plan ~25 net LOC + ~120 test LOC → actual aligned)
>   - Plan §4 test plan: 5/5 vitest PASS T1-T5 (1.23s initial run + 0.87s post-reviewer-fix run)
>   - Plan §5 effort: ~2h actual (vs 4h plan budget) — Plan A-E mechanical + tests + reviewer + 2 cleanup commits
>   - Plan §6 risks: 0 materialized; reviewer APPROVE 0 P0/P1 + 1 MED (comment wording, fixed in cleanup commit) + 1 LOW (test mock arg forwarding, fixed)
>   - Post-merge ops: 0 required (frontend pure, no Servy restart, no Beat reschedule)

---

## §1 Current state inventory

| Path | Lines | Anti-pattern | Closure status |
|---|---|---|---|
| `frontend/src/pages/PipelineConsole.tsx` | 252-258, 260-283, 647-658 | `window.prompt` already replaced by ConfirmModal HIGH-tier (W1-W6 closure, comment markers preserved) | ✅ DONE (W1-W6 sediment) |
| `frontend/src/pages/PipelineConsole.tsx` | 50-61 | `EMPTY_STATUS` mock — silent fallback when `getPipelineStatus()` throws | ❌ RESIDUAL (this W14) |
| `frontend/src/pages/PipelineConsole.tsx` | 66 | `useState<PipelineStatus>(EMPTY_STATUS)` initial — also consumes silent default | ❌ RESIDUAL |
| `frontend/src/pages/PipelineConsole.tsx` | 84-94 | `loadStatus` `catch { setError(...) }` keeps stale EMPTY_STATUS in state | ❌ RESIDUAL |

Grep verify (2026-05-25): only 2 occurrences of `window.prompt` repo-wide, both in PipelineConsole.tsx comments (lines 252 + 647) describing the past replacement. No live `window.prompt` callers remain.

---

## §2 Proposed changes

### Change A — Remove EMPTY_STATUS mock (lines 50-61)
- DELETE the `EMPTY_STATUS` constant entirely (~12 lines incl. trailing blank).
- Rationale: mock data masks real backend outage. Per IRONLAWS §14 #33 (silent failure ban), UI must fail-loud.

### Change B — Make `status` nullable (line 66)
- `useState<PipelineStatus>(EMPTY_STATUS)` → `useState<PipelineStatus | null>(null)`.
- Initial value `null` = "not yet loaded" (distinct from empty).

### Change C — Fail-loud render gating (lines ~408-657)
- Top-level guard before tabs:
  - `loadingStatus && !status` → spinner skeleton (current behavior preserved).
  - `!loadingStatus && !status && error` → full-page error card "Pipeline 状态加载失败. 请检查后端 (/api/pipeline/status) 连接." + retry button calling `loadStatus()`.
  - `status` present → existing tabbed UI.
- All `status.xxx` derefs inside guard, so non-null assertion is safe.

### Change D — Update `loadStatus` error path (lines 84-94)
- `setError("无法加载 Pipeline 状态，请检查后端连接")` retained.
- Add `setStatus(null)` on catch so stale mock is never displayed.

### Change E — Preserve W1-W6 closure markers
- KEEP comment at line 252 + 647 (Frontend Design v3 §6 #8 closure markers, LL audit trail).
- Reword from "replace window.prompt" → "reject reason capture (W1-W6 closed window.prompt)".

---

## §3 Files to modify

| File | Line ranges | Change |
|---|---|---|
| `frontend/src/pages/PipelineConsole.tsx` | 50-61 | DELETE EMPTY_STATUS constant |
| `frontend/src/pages/PipelineConsole.tsx` | 66 | Type `PipelineStatus \| null`, init `null` |
| `frontend/src/pages/PipelineConsole.tsx` | 84-94 | Add `setStatus(null)` in catch |
| `frontend/src/pages/PipelineConsole.tsx` | ~288-290 | Insert top-level guard above main `<div>` body |
| `frontend/src/pages/PipelineConsole.tsx` | 252, 647 | Reword comment markers (cosmetic, audit trail) |
| `frontend/src/pages/PipelineConsole.tsx` | 132-143, 155-164, 167-189 | `status.run_id`/`status.is_running` derefs — verify null-safe via guard (no edits if guarded above) |

Total edit footprint: ~25 lines net (-12 delete, +13 add).

---

## §4 Test plan (vitest subset per §v9.29)

Existing infra: `frontend/src/__tests__/pages.test.tsx` (single smoke file). Add a **focused PipelineConsole test file**.

| Test | Vitest case | Asserts |
|---|---|---|
| T1 Skeleton on initial load | `renders skeleton when loadingStatus && !status` | `screen.queryByText(/Pipeline 状态图/)` is null + spinner present |
| T2 Fail-loud on API error | mock `getPipelineStatus` rejects → assert error card visible | `getByText(/Pipeline 状态加载失败/)` + retry button |
| T3 Retry button calls loadStatus | click retry → mocked fetch called twice | spy on `getPipelineStatus`, expect `toHaveBeenCalledTimes(2)` |
| T4 Happy path renders tabs | mock returns valid PipelineStatus → tabs visible | `getByRole("tab", { name: /状态流程/ })` present |
| T5 No EMPTY_STATUS leak | confirm `status` is never mock — assert `nodes.length === 0` does NOT auto-render schedule_cron `"0 20 * * 1-5"` | `queryByText("0 20 * * 1-5")` null on error |

Create new file: `frontend/src/pages/__tests__/PipelineConsole.test.tsx` (~120 LOC).

Test runner: `cd frontend ; npm run test -- PipelineConsole`.

---

## §5 4h estimate breakdown

| Block | Effort | Detail |
|---|---|---|
| Code edit (§2 A-E) | 0.75h | Mechanical delete + null guard + retry button |
| Test scaffold (new __tests__ dir + 5 cases) | 1.5h | Includes vitest mock setup for `api/pipeline` |
| Manual smoke (dev server) | 0.5h | Toggle Servy FastAPI down → confirm error card; up → confirm tabs |
| Lint + format + commit | 0.25h | `npm run build` + commit (per §commit-protocol) |
| Buffer (typescript-reviewer P1/P2 followup) | 1.0h | Independent reviewer pass per `<execution_protocols>` |
| **Total** | **4h** | Solo-safe single-session |

---

## §6 Risk assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Other tabs `status.xxx` deref crashes when null | MED | Top-level guard ensures `status` non-null below render gate |
| WebSocket effect (lines 167-189) depends on `status.run_id` | LOW | Already null-safe (`if (!status.run_id) return`); just ensure null literal also fails the guard |
| Polling interval (line 148) keeps retrying on backend down | LOW | Acceptable — user sees error card; backend recovery auto-flips to good state on next 10s tick |
| Hidden callers expect EMPTY_STATUS export | NONE | `EMPTY_STATUS` is module-local (not exported), zero external coupling — grep confirms |
| Visual regression in error state | LOW | Manual smoke covered (§5 block 3) |
| Backend dep change | NONE | 0 backend edit (per FRONTEND_V3_W7_W15_PLAN §3 W14: "Backend dep: 无") |

Overall risk: **LOW** (pure frontend, well-scoped, single file, existing pattern proven by Execution/index.tsx).

---

## §7 Cite source (4-element)

| Cite | Path | Line# | Section | Verify timestamp |
|---|---|---|---|---|
| W14 scope spec | `docs/audit/FRONTEND_V3_W7_W15_PLAN_2026_05_25.md` | 64-67 | §2 W14 block | 2026-05-25 fresh read (this session) |
| PipelineConsole current source | `frontend/src/pages/PipelineConsole.tsx` | 50-61, 66, 84-94, 252, 647 | top-level + handlers | 2026-05-25 fresh read (this session) |
| ConfirmModal contract (already wired) | `frontend/src/components/ui/ConfirmModal.tsx` | 19-37 | export interface | 2026-05-25 fresh read (this session) |
| Fail-loud iron law | `IRONLAWS.md` | §14 #33 | silent failure ban | per CLAUDE.md §铁律 (T1) line ref |

---

**End W14 plan.** ✅ Closed iter 107 PR #480 merged `847e30a`. See iter 107 closure summary in §0 header.
