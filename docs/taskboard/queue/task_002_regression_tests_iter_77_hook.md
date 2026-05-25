---
task_id: 002
priority: HIGH
domain: tests
tier: B
estimated_iter: 1-2
branch: feat/iter-XX-task002-verify-hook-regression-tests
created_by: main
created_at: 2026-05-25T15:30:00+08:00
assigned_to: sub1
depends_on: [001]   # task_001 LL sediment 先完成提供 context
---

## Description

Add 3 regression tests to `backend/tests/test_verify_completion_hook.py` defending against silent regression of iter 77 hook fix (commit 80aa815).

The 3 tests guard against accidentally reverting any of these key reconciliation properties:
1. **ensure_ascii=False preservation** — Chinese chars must stay unescaped in JSON stdout
2. **COMPLETION CHECKLIST marker** — additionalContext field must contain this marker substring
3. **Trailing newline preservation** — checklist string must end with `\n` (formatting contract)

## Root cause / motivation

iter 77 fix (commit 80aa815) reconciled silent-UI directive vs test contract via:
- `json.dumps(output, ensure_ascii=False)` — Chinese preserved
- `additionalContext` carrying full checklist (UI silent, tests see via substring)
- Trailing `\n` preserved in checklist string

If a future iter accidentally reverts to `ensure_ascii=True` (default), Chinese gets escaped to `\u` sequences and 4 of the existing 8 tests fail again (iter 77 实证).

No existing test asserts these 3 properties directly — they're indirect / fragile.

This adds explicit regression guards. 1 file changed, ~50-60 lines added (3 test functions + brief docstrings). **>20 lines = TIER B PR flow forced** (§v9.1 soft tier).

## Acceptance

- 3 new test functions added to `backend/tests/test_verify_completion_hook.py`:
  - `test_chinese_chars_unescaped_in_stdout` — assert "4 元素" / "完成" present unescaped (no `三` etc)
  - `test_additional_context_starts_with_marker` — parse JSON, assert additionalContext.startswith("COMPLETION CHECKLIST")
  - `test_checklist_trailing_newline` — assert additionalContext.endswith("\n")
- 11/11 tests in test_verify_completion_hook.py PASS (8 existing + 3 new)
- ruff check + ruff format clean
- pre-push smoke 61 PASS
- TIER B PR path:
  - branch: feat/iter-XX-task002-verify-hook-regression-tests
  - `gh pr create --base main --title "test(verify-hook): regression tests for iter 77 silent-UI reconciliation"`
  - PR body 5 段 (§v9.21): Summary / Root cause / Test plan / Risk assessment / Cite source 4-element
  - 等 main session spawn `oh-my-claudecode:code-reviewer` (§v9.2 强制 TIER B PR)
  - P0/P1 findings 必修 (push amend); P2/P3 commit message reference
  - reviewer PASS → `gh pr merge --squash --delete-branch --auto`
- cite 4-element in commit body

## Cite source (4-element)

- `.claude/hooks/verify_completion.py:178-188` §main() Stop event JSON output + ensure_ascii=False (verify 2026-05-25 14:00 SH iter 77)
- `backend/tests/test_verify_completion_hook.py:33-50` §_run_hook helper + 8 existing tests (verify 2026-05-25 14:00 SH iter 77)
- commit 80aa815 (verify 2026-05-25 14:00 SH iter 77)

## Constraints

- 红线 5/5 sustained (任 .env / broker / DB row 改 → STOP — 本 task 不触, 纯 test add)
- TIER B PR path (§v9.1 sub-PR + reviewer 强制)
- branch: feat/iter-XX-task002-verify-hook-regression-tests (XX = sub1 actual iter_id)
- 单 file edit: backend/tests/test_verify_completion_hook.py
- 不超 60 lines append (≥30 lines append → PR 流程 forced soft TIER B)

## Workflow (sub1 SOP 应用)

1. `git pull origin main` 拿最新 (task_001 done 后)
2. `git mv queue/task_002.md in_progress/task_002__sub1.md` + claim commit + push
3. `git checkout -b feat/iter-XX-task002-verify-hook-regression-tests`
4. edit `backend/tests/test_verify_completion_hook.py` 加 3 new tests
5. `pytest backend/tests/test_verify_completion_hook.py -v` → 11 PASS verify
6. `ruff check .claude/hooks/ backend/tests/test_verify_completion_hook.py`
7. `ruff format ...`
8. commit + push branch
9. `gh pr create --base main --title "..." --body "$(cat <<'EOF' ... EOF)"` per §v9.21 5 段
10. edit task file 加 `## Result` 段 (PR# + 11 tests PASS + smoke result)
11. `git mv in_progress/task_002__sub1.md review/task_002__sub1__PR-NNN.md` + push
12. 等 main spawn reviewer + 审 PR
13. P0/P1 found → main 退回 in_progress, sub1 修 + push amend + 重 submit
14. PASS → main `gh pr merge --squash --auto` + git mv → done/
15. heartbeat sub1.md 更新
16. 下 iter scan queue/ 领下一 task

## Notes

This is **TIER B PR flow POC** — 真测 §v9.1 (PR 分级) + §v9.2 (reviewer spawn) + §v9.21 (PR body 5 段) + §v9.22 (reviewer prompt template) 全 mechanism.

main session 将 spawn `oh-my-claudecode:code-reviewer` 独立 Task agent review PR diff; reviewer prompt 沿用 §v9.22:

```
PR #<N>: test(verify-hook): regression tests for iter 77 silent-UI reconciliation
Branch: feat/iter-XX-task002-verify-hook-regression-tests
Base: main HEAD <sha>

Files changed: backend/tests/test_verify_completion_hook.py (only)
Key changes: 3 new regression tests for ensure_ascii / marker / newline

Findings expected format:
- [P0|P1|P2|P3] path:line# - <issue> - <suggested fix>

Apply 铁律 N reminder + cite 4-element verify + cross-layer impact check.
```
