# L4+R Backlog Re-scan #2 — 2026-05-24

> **Type**: L4+R loop §4.4 backlog re-scan (verification iter, no execute-task increment).
> **Iter**: 16 (pull-forward from iter 17 due — since_last_backlog_rescan=8).
> **Predecessor rescan**: iter 6 (first re-scan, 2026-05-22).
> **main HEAD**: `1970421` (iter 15 ADR-090 sediment).

## §1 Re-scan scope

Per `docs/L4R_LOOP_SPEC.md` §4.4: refresh the backlog by re-grepping authoritative
sources for new XS-cleanup, doc-rot, and orphan candidates. Cross-verify against code
before queueing (RN-001 §6 META-finding — 5x prior session candidates were already
built; mandatory code-grep before any IMPLEMENT verdict).

Sources scanned:
- `docs/API_COVERAGE.md` (§6 + §6.1) — remaining frontend orphans + drift.
- `LESSONS_LEARNED.md` last 8 entries (LL-182 through LL-189).
- `# TODO` / `# FIXME` / `# XXX` in `backend/app/`, `backend/engines/`, `scripts/`.
- Recent git log (post iter 6 rescan = post commit `533a8df`).

## §2 Findings

### §2.1 F-XS-1 (HIGH PRIORITY — smallest, immediate value, 0 risk): `API_COVERAGE.md` §6.1 doc-rot

`docs/API_COVERAGE.md` §6.1 (last touched 2026-05-22 + iter 12 partial) has 3 stale
lines vs current main reality:

| §6.1 claim | Current reality (main HEAD `1970421`) |
|---|---|
| O8 `/pipeline/automation-level` "STILL ORPHAN" | **CLOSED iter 10 PR #450 squash `d26ac2a`** (ADR-087) — GET/PUT endpoints + singleton table + 5 backend pytest + 6 frontend vitest. Frontend `setAutomationLevel` wired through. |
| "Remaining orphans: 10 → 6 (O1, O3, O7, O8, O9, O10)" | **Actual: 1 remaining (O7)** — O1 (iter 5 PR #446) / O3 (iter 12 PR #452) / O8 (iter 10 PR #450) / O9 (iters 3-4 PR #445) / O10 (iter 11 PR #451) all CLOSED. |
| "**NEW finding**: `/pipeline/status` ... contract-shape drift" | **CLOSED iter 15 PR #453 squash `7218496`** (ADR-090) — 8 frontend-aligned keys added; legacy keys retained as 1-sprint backward-compat. |
| "Deferred: O3 / O7 / O8 + the `/pipeline/status` contract reconciliation" | **Only O7 deferred remaining** — others all shipped. |

**Action recommendation**: Single small docs/** direct-to-main commit updating §6.1
table + summary count + Deferred sentence. ~10 lines diff. 0 code change.

### §2.2 F-XS-2 (MEDIUM PRIORITY — gated on dingtalk_alert.py existence verify): `scripts/health_audit_v2.py:259` DingTalk push wire

```
scripts/health_audit_v2.py:259:    # TODO: 真 DingTalk push via backend/app/services/dingtalk_alert.py (待 wire)
```

Comment cites `backend/app/services/dingtalk_alert.py` — needs precondition verify
that file exists + has the expected `push_dingtalk(...)` API. If yes → small wire
(probably <30 lines). If file doesn't exist → larger task (out of scope).

**Action recommendation**: precondition-verify dingtalk_alert.py before queueing.
Defer to iter 17+ once F-XS-1 (smaller + risk-free) ships.

### §2.3 F56 (DEFERRED — gated on D3 BruteForce decision): `bruteforce_engine.py:1072` 铁律 19 violation

```
backend/engines/mining/bruteforce_engine.py:1072:    # TODO(F56): 铁律19要求走ic_calculator, GP管道重启前必须迁移
```

Real 铁律 violation (IC计算未走 ic_calculator engine). But BruteForce engine has 0
production callers (D3 gating decision pending — `run_bruteforce_mining` Celery task
returns `not_implemented` placeholder). 0 production impact. Wait for D3 verdict —
if D3 = ARCHIVE, this TODO becomes deletable; if D3 = IMPLEMENT, this is a
prerequisite that gets bundled into the D3 design.

**Action recommendation**: DEFER. Track as F56 in this re-scan output; revisit on
D3 iter.

### §2.4 Sprint-scoped TODOs (DEFERRED — not L4+R-loop actionable)

Listed for completeness, NOT queued:
- `backend/app/api/backtest.py:1152` — Phase 0 parametric backtest sweep, Celery task wire.
- `backend/app/api/report.py:198` — Sprint 1.24 `generate_performance_report` task.
- `backend/app/services/paper_trading_service.py:313` — Phase 1 `target_return` storage (gated on PT restart per ADR-085).
- `scripts/research/profile_backtest.py:119` + `scripts/run_backtest.py:299` — MVP-2.3 sub3 `BacktestMode.AD_HOC` unimplemented (research scripts).
- `scripts/risk_framework_health_check.py:100` — V3 Beat task list re-populate (sprint scope).

None match L4+R loop §3.1 "clean autonomous work" criteria (each has product/sprint
dependency or known carry-forward owner).

### §2.5 LL-182 through LL-189 review

8 most-recent LL entries scanned — all are sub-major-incident findings (V3 audit /
frontend design / cold-start forensic / Celery memory leak). 0 new XS-cleanup
candidates surfaced from this slice. No action.

### §2.6 Excluded false positives

- `scripts/knowledge/migrate_research_kb.py:178` — `# title: first "# XXX"` is a
  pattern-string in a regex comment, not a TODO. Skip.
- `scripts/archive/slippage_decompose.py:305` — file is under `scripts/archive/`,
  archival path. Skip.

## §3 Iter-17 candidate ranking

Sorted by smallest-first (per L4+R §3.3):

1. **F-XS-1** (API_COVERAGE doc-rot fix) — ~10 lines diff, 0 risk, doc-only direct-to-main.
   **Recommended iter 17 pick.**
2. **F-XS-2** (DingTalk wire) — gated on precondition verify; ~30 lines if ready.
3. **D1 O7** (log-history endpoint) — medium-large, storage decision (file vs DB vs
   sliding-window) + retention policy.
4. **D3 BruteForce gating-design** — largest, may surface architecture decision
   requiring user.

## §4 §6 8-trigger STOP self-check on re-scan output

| # | Trigger | Verdict |
|---|---------|---------|
| 1 | Framework 新加 | NEGATIVE |
| 2 | Architecture 大改 | NEGATIVE |
| 3 | Strategy 改动 | NEGATIVE |
| 4 | 红线 5/5 触碰 | NEGATIVE |
| 5 | PT 重启 gate | NEGATIVE |
| 6 | 新引擎 | NEGATIVE |
| 7 | Beat schedule 改 | NEGATIVE |
| 8 | Self-protection | NEGATIVE |

All NEGATIVE → next iter unblocked.

## §5 Cadence + cumulative effect

- Iter 16 = verification iter (no execute_task_count increment).
- since_last_backlog_rescan: 8 → 0 (RESET).
- since_last_digest: 2 → 3 (digest #4 still due ~iter 18-19).
- implement:archive:defer ratio unchanged (9:2:3, 64%).

## §6 Verdict

**Backlog re-scan complete.** 2 new XS-cleanup candidates surfaced (F-XS-1 + F-XS-2);
1 medium-tech-debt deferred (F56 gated on D3). Iter 17 = F-XS-1 (smallest, immediate
doc-rot fix). User-veto surface: re-direct to D1 O7 / D3 / F-XS-2 if desired.
