---
task_id: 003
priority: HIGH
domain: docs
tier: C
estimated_iter: 1
branch: docs/iter-XX-task003-api-coverage-audit
created_by: main
created_at: 2026-05-25T15:45:00+08:00
assigned_to: sub2
depends_on: []
---

## Description

Fresh audit `docs/API_COVERAGE.md` vs actual backend FastAPI routes + frontend axios consumer state. 5d+ stale per CLAUDE.md §下一步 mention.

3 deliverable sections in updated doc:
1. **Backend route inventory** — grep `backend/app/api/*.py` for `@router.get/post/put/delete/patch`; output full path list
2. **Frontend consumer inventory** — grep `frontend/src/api/*.ts` for axios calls; map to backend routes
3. **Drift table** — Backend route × Frontend consumer matrix: 4 状态 (✅ matched / ⚠️ backend has + frontend missing / ⚠️ frontend has + backend missing / 🚧 mismatch params)

## Root cause / motivation

API contract drift is silent regression risk. Last refresh ≥5d stale, real production routes may have moved since (Wave 4 batch 3.x SDK migration / V3 §S5-S8 implementation 等可能 加新 endpoint).

API_COVERAGE.md 是 docs/ 域 SSOT, 跨 frontend↔backend coordination 真值. 任何 drift 应明确标记, 留 future iter 修.

## Acceptance

- `docs/API_COVERAGE.md` 含 3 deliverable sections (实测数字 + cite 4-element)
- Backend route count ≥ 100 (per recent Wave 4 expansion)
- Frontend axios consumer count ≥ 10
- Drift table 含至少 5 个 cell (matched / missing 各类样例)
- 末尾 sediment timestamp `Fresh verify YYYY-MM-DD HH:MM SH (iter-XX sub2)`
- 不超 200 lines new content
- TIER C → direct push (无 PR)
- cite 4-element in commit message

## Cite source (4-element)

- `backend/app/api/*.py` (verify YYYY-MM-DD HH:MM SH) — backend route grep
- `frontend/src/api/*.ts` (verify YYYY-MM-DD HH:MM SH) — frontend consumer grep
- `docs/API_COVERAGE.md` 上次更新日期 (`git log -1 docs/API_COVERAGE.md` 取 timestamp)

## Constraints

- 红线 5/5 sustained (任 .env / broker / DB row 改 → STOP — 本 task 不触, 纯 doc)
- TIER C: direct push (沿用 §v9.1)
- branch: docs/iter-XX-task003-api-coverage-audit (XX = sub2 实际 iter_id)
- 单 file edit: docs/API_COVERAGE.md
- 不超 200 lines new content

## Workflow

1. `git pull origin main` 拿最新
2. `git mv queue/task_003.md in_progress/task_003__sub2.md` + commit + push (atomic claim)
3. `git checkout -b docs/iter-XX-task003-api-coverage-audit`
4. grep backend route count + frontend consumer count + drift analysis
5. write `docs/API_COVERAGE.md` (overwrite OR append per existing structure)
6. commit + push (TIER C 可 direct main push 或 PR — both 允许)
7. update task file 加 `## Result` (counts + cite + commit SHA)
8. `git mv in_progress/task_003__sub2.md done/task_003__sub2__merged_<SHA8>.md` + push
9. heartbeat sessions/sub2.md 更新

## Notes

sub2 first task. TIER C direct push (无 PR + reviewer 强制), 跑通 sub2 atomic claim + work + done lifecycle. 
后续 task 升 TIER B 测 frontend vitest gating (§v9.29) 或 TIER A PR flow.
