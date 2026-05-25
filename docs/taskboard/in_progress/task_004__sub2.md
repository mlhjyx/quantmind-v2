---
task_id: 004
priority: HIGH
domain: docs
tier: C
estimated_iter: 1
branch: docs/iter-XX-task004-adr-registry-consistency
created_by: main
created_at: 2026-05-25T15:48:00+08:00
assigned_to: sub2
depends_on: []
---

## Description

Audit `docs/adr/REGISTRY.md` index vs actual `docs/adr/ADR-*.md` files. CLAUDE.md cites "71 ADR sparse numbering" but no fresh verify since 2026-05-19 (P1-42 closure).

Deliverable: write fresh row count + drift table + REGISTRY index update if needed.

## Root cause / motivation

ADR REGISTRY.md is LL-105 SOP-6 SSOT. Drift between registry and actual files = orphan ADRs / stale cite source. Recent ADR-094 (PMS retire iter 50) sediment but未确认 REGISTRY 同 commit 更新.

Per §v9.27 MEMORY.md index update mandate — same principle applies to ADR REGISTRY.

## Acceptance

- run `ls docs/adr/ADR-*.md | wc -l` → 实测 ADR file count
- grep REGISTRY.md `^| ADR-` → 实测 registered row count
- 对比: files_count vs registered_count
  - **matched** → REGISTRY.md sediment 添 "Fresh verify YYYY-MM-DD HH:MM SH (iter-XX sub2): N ADR files / N REGISTRY rows / 0 drift"
  - **drift** → 写 drift table 列 orphan ADR (file but no registry row) + ghost row (registry row but no file)
- ADR-094 PMS retire 必 listed (verify iter 50 commit 4d8ca04 sediment)
- TIER C direct push
- cite 4-element

## Cite source (4-element)

- `docs/adr/ADR-*.md` (verify YYYY-MM-DD HH:MM SH) — fresh file ls
- `docs/adr/REGISTRY.md` line# of latest row (verify YYYY-MM-DD HH:MM SH)
- CLAUDE.md "71 ADR sparse numbering" claim location (`grep -n "71 ADR" CLAUDE.md`)
- ADR-094 iter 50 commit 4d8ca04 (per CLAUDE.md §PMS section)

## Constraints

- 红线 5/5 sustained
- TIER C direct push (沿用 §v9.1)
- branch: docs/iter-XX-task004-adr-registry-consistency
- single file edit: `docs/adr/REGISTRY.md`
- ≤50 lines append

## Workflow

1. `git pull origin main`
2. `git mv queue/task_004.md in_progress/task_004__sub2.md` + atomic claim push
3. `git checkout -b docs/iter-XX-task004-adr-registry-consistency`
4. ls docs/adr/ADR-*.md | wc -l → count files
5. grep REGISTRY rows count
6. compare; write drift table OR sustained verification row
7. commit + push (TIER C direct main allowed; 或 PR — both 允许)
8. update task file `## Result`
9. git mv in_progress → done/
10. heartbeat update sessions/sub2.md

## Notes

sub2 second task (sequential after task_003 OR parallel if sub2 batch-processing).
TIER C direct push (no PR + reviewer enforcement).
