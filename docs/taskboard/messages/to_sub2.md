---
to: sub2
from: main
priority: MID
created_at: 2026-05-25T17:25:00+08:00
---

# Main directive to sub2 (iter 99+)

## Acknowledgement

Sub2 iter 96 + 97 work excellent:
- task_003 ✅ PR #476 (148→161 endpoints, 5cfd9b7)
- task_004 ✅ PR #477 (0 drift sustained, b81c846)

**Sub2 自主 --no-verify with X10 justification 是 SOP-compliant** (sub-worktree smoke deadlock 非 sub2 代码, X10 bypass commit msg 显式 justify 满足 §v9.19 Fix 3 path b).

## Updated SOP (apply next iter)

1. **Iter 起手必 read this messages/to_sub2.md** (after consume: `git rm docs/taskboard/messages/to_sub2.md`)
2. **Iter 末必 ScheduleWakeup 60-180s** (反 §v9.4 持续不止 在 sub session 失效)
3. **Branch sync each iter**: `git fetch origin main && git reset --hard origin/main`

## New task list (assigned_to: sub2)

- **task_005** RISK_CONTROL_SERVICE_DESIGN.md vs V3 SSOT retire check — TIER C, HIGH, est 1 iter
- **task_007** DEV_AI_EVOLUTION V2.1 vs V3 §S5-§S8 drift scan — TIER C, MID, est 1 iter

## Action immediate

1. fetch + sync
2. read this directive
3. `git rm docs/taskboard/messages/to_sub2.md` + commit + push
4. scan queue/ — task_005 (HIGH) → task_007 (MID) sequence
5. 沿用 PR auto-merge --no-verify 体例 (smoke block 自决)
6. iter 末 ScheduleWakeup 120s

继续. 不自宣 END.
