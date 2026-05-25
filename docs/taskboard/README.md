# Multi-Session Taskboard — MVP POC

> 2 session 协作 POC: 1 main (orchestrator) + 1 sub1 (worker). 沿用 docs/L4R_LOOP_SPEC.md §v9 全部规则.
> 创建时间: 2026-05-25 post iter 81 + v9 Addendum sediment.
> 状态: MVP — 跑 3-5 iter 看真实 race / failure mode, 再扩 P0-P4 20 项 + sub2.

---

## 目录结构

```
docs/taskboard/
├── README.md           ← 本文件 (SSOT for SOP)
├── sessions/
│   ├── main.md         ← main session 心跳 + 状态
│   └── sub1.md         ← sub1 session 心跳 + 状态
├── queue/              ← 待领任务 (main 写)
├── in_progress/        ← 已领任务 (sub atomic git mv)
├── review/             ← 完成, 等 main 审核
└── done/               ← 已合并
```

---

## Task 文件格式

文件名: `task_NNN_<short_desc>.md` (NNN = 3 位序号, 单调增).

```markdown
---
task_id: 001
priority: HIGH | MID | LOW
domain: backend | frontend | docs | tests | memory
tier: A | B | C        # 沿用 §v9.1 PR 分级
estimated_iter: 1-5
branch: fix/iter-XX-... | feat/iter-XX-... | docs/iter-XX-...
created_by: main | user
created_at: 2026-05-25T15:00:00+08:00
assigned_to: sub1 | sub2 | any   # main 派单约束 (any=自由领)
depends_on: []         # task_id list (空=无依赖)
---

## Description
<具体做什么, 单一焦点>

## Root cause / motivation
<为什么做这个>

## Acceptance
<明确 PASS 条件>
- pytest backend/tests/test_X.py PASS
- ruff clean
- smoke 61 PASS (pre-push hook 自动)
- TIER A/B: PR + reviewer P0/P1 cleared
- cite 4-element in commit

## Cite source (4-element)
- <path>:<line#> §<section> (verify YYYY-MM-DD HH:MM SH)

## Constraints
- 红线 5/5 sustained (任 .env / broker / DB row 改 → STOP)
- branch: <branch name>
```

---

## Main session SOP (沿用 §v9.4 持续不止)

每 iter:

1. **fresh state scan**: `git pull` + ls `queue/` `in_progress/` `review/` `done/` 文件名
2. **review/ 处理** (优先级最高):
   - for each task in `review/`:
     - `gh pr view <PR#>` 看 PR diff + CI status
     - spawn `oh-my-claudecode:code-reviewer` Task agent (独立 process, 反 self-approve §v9.2)
     - reviewer 返回 P0/P1/P2/P3 findings
     - **P0/P1 found** → 写 `## Reviewer notes` 段到 task file + `git mv review/X in_progress/X` (退回 sub 改)
     - **PASS** → `gh pr merge --squash --delete-branch --auto` + `git mv review/X done/X__merged_PR-N.md` + push
3. **queue/ 维护**: 如果 `queue/` <3 个 → 候选发现 (§v9.30 cross-domain HIGH) → write 3-5 个 task file → push
4. **dashboard 更新**: edit `sessions/main.md` 心跳 (iter id + last action + queue/in_progress/review/done count)
5. **主线推进**: 主 session 也可做自己域任务 (backend root / docs / cross-domain coord)
6. **下 iter continue** (§v9.4 持续, 不 ScheduleWakeup)

## Sub1 session SOP

每 iter:

1. **fresh state scan**: `git pull` + ls taskboard 状态
2. **PAUSE 检查**: 如果 `docs/taskboard/PAUSE` 存在 → STOP (§v9 P2 #66 kill switch sustained)
3. **CI 自检**: 如果上 iter 推过 PR → `gh pr status` 看 own PR CI 状态
   - CI fail → 修 + push amend
   - CI pass + 已 main merge → 进入下 task
4. **当前无任务时领新单**:
   - scan `queue/` for `assigned_to: sub1` OR `assigned_to: any`, 按 priority HIGH → MID → LOW
   - atomic claim: `git mv queue/task_NNN.md in_progress/task_NNN__sub1.md`
   - `git add -A && git commit -m "claim(taskboard): sub1 claims task_NNN" && git push`
   - **push fail (race)** → `git pull --rebase` + 试下一 task
5. **有任务**:
   - 按 task file Description + Acceptance 执行 (§v9 全套: TIER routing / cite 4-element / 红线 5/5 sustained)
   - TIER A/B: feature branch + PR + reviewer 等待
   - TIER C: direct push
   - 完成: edit task file 加 `## Result` + PR# + smoke result
6. **Submit review**:
   - `git mv in_progress/task_NNN__sub1.md review/task_NNN__sub1__PR-NNN.md`
   - `git push`
7. **心跳更新**: edit `sessions/sub1.md` (iter id + current task + status)
8. **下 iter continue**

---

## Heartbeat 格式 (`sessions/<id>.md`)

```markdown
---
session_id: main | sub1 | sub2
worktree: D:\quantmind-v2 | D:\quantmind-v2-sub1
last_heartbeat: 2026-05-25T15:00:00+08:00
iter_id: 82
status: idle | working_on_task_NNN | reviewing | compacting
---

## Last action
<short summary>

## Current focus
<what's being worked on>
```

---

## Atomic claim race resolution

多 sub 同时 claim 同 task → `git push` 后到者会 reject.

后到者 SOP:
1. `git pull --rebase` 拉 first-claim
2. 看 in_progress/ 里那个 task 已被谁 claim
3. 跳过, 试下一 task

---

## Stale task auto-reclaim (P0 #46, MVP 暂不自动)

heartbeat >1h stale (sub crash / 离线) → in_progress task 卡住.

**MVP 阶段**: user 手动 git mv back to queue/.
**未来**: main session 每 N iter 扫 heartbeat + 自动 reclaim.

---

## Kill switch (P2 #66)

紧急停全部 session: 在 main worktree `touch docs/taskboard/PAUSE` + commit + push (sub 下 iter `git pull` 才感知).

各 session iter 起手 `git pull` + 检查 `docs/taskboard/PAUSE` 存在; 存在 → 立即 STOP.

恢复: `git rm docs/taskboard/PAUSE` + commit + push.

---

## User override channel (P2 #65)

user 想插队 / 改 priority / 给特定 sub 分派:
- 直接 edit `queue/task_NNN.md` 改 `priority` 或 `assigned_to`
- 或 write `user_directives.md` 在本目录, 各 session 起手 fresh read

---

## 关联 spec

- docs/L4R_LOOP_SPEC.md §v9 Addendum (主 spec)
- §v9.1 PR 分级 routing matrix
- §v9.2 Reviewer agent SOP
- §v9.4 持续不止 (no session END)
- §v9.13 concurrent git safety
- §v9.20 merge conflict SOP
- §v9.21 PR body 5 段 template
- §v9.22 Reviewer agent prompt template

POC 验证后 sediment §v9.37-§v9.40 + P0-P4 20 项扩展回 spec.
