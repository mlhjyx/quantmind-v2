---
ADR: 095
Title: Multi-CLI sub session → Pattern B Task agent in-process spawn pivot
Status: Accepted
Date: 2026-05-25
Related ADRs: ADR-086 (L4R loop spec)
Related LL: LL-200
---

# ADR-095 — Multi-CLI sub session → Pattern B Task agent in-process spawn pivot

## Context

Multi-CLI Claude Code sub session 架构 (Pattern A) — main CC + N 独立 CLI sub sessions on git worktrees `worker/subN` — 实证遇到核心架构限制 (iter 82-99, 2026-05-25):

- Sub session **Stop event → process death**: 任何 STATUS_REPORT halt / smoke fail / blocked-on-user pause 都让 sub process 真死.
- **无 IPC channel**: main 无法 revive 已死 sub. L4R Loop Spec §v9.4 "持续不止" 仅在 active session 进程内生效, process exit 后 spec 无效.
- **多 process 抢同一 repo**: sub1/sub2 + main concurrent git push → PR race + main cherry-pick + smoke block + push reject 循环.
- **user keep-alive 隐性需求**: Pattern A 真 autonomy ≠ 真 autonomy, user 必须手动 keep-alive each CLI session → 非 user-离开-也跑 spec.

## 决议

**Default Pattern B** for "multi-process Claude Code 协作" 需求:

- **Pattern B = single main CC + Task tool subagent in-process spawn**. Subagent 持 isolated context window, 返回 ≤300 word final report. Main 收集 + commit + push.
- **Pattern A (multi-CLI)** 仅在 truly needed 时使用: 真强 process isolation (独立 process tree / 不共享 cache / 真独立 context), 且 user 显式接受 keep-alive 责任.
- 默认 1 main + N parallel Task subagent → 真 parallel in-process / isolated context / user-离开-也跑.

## 实证

- **Pattern A iter 82-99 ~2h wasted**: sub1 STATUS_REPORT halt (smoke baostock env-block 卡 indefinite, no main IPC revive) + sub2 git push race (PR cherry-pick + smoke block + push reject 循环) + main 反复 unblock attempts.
- **Pattern B iter 99 batched 4 audits in 2 minutes**: 4 parallel Task agents in-process, 4 audit docs sediment, 60x speedup vs Pattern A.

## Consequences

- `docs/L4R_LOOP_SPEC.md` §v9.37 multi-session SOP 标 **DEPRECATED** (架构层 obsolete, 沉淀历史 marker, do not extend).
- sub1/sub2 git worktree **abandoned** — retain worktree directory for archive reference, no longer active dispatch target.
- 未来 "multi-process Claude Code 协作" 需求 **默认 Pattern B** — `docs/taskboard/queue/task_NNN_*.md` 直接走 Task tool spawn, 非 worktree dispatch.
- Anti-pattern guard sustain — fresh main spawn Task agent 时仍走 v1-v5 check (LL-201 实证 agent 拒绝 fabricated cite, Pattern B 内 skill enforcement 真有效).
- L4R §v9.4 "持续不止" scope 显式标注 = active session 内 only, 不跨 process boundary.

## Cite source (4-element)

- main commit `266a363` 2026-05-25 iter 99 — Pattern B pivot decision (sediment record)
- main commit `828aa0b` 2026-05-25 iter 99 — 4 audits via 4 parallel Task agents (2min completion 实证)
- main commit `2af38b7` / `1a55401` / `8762831` 2026-05-25 iter 99 — Pattern B execution chain (sediment cascade)
- [LESSONS_LEARNED.md:6983 (LL-200)](../../LESSONS_LEARNED.md) — Pattern essence + 3 类典型反例 (sub session halt / PR race / spec literal-read)
- [docs/audit/STATUS_REPORT_2026_05_25_sub1_iter1_smoke_block.md §2](../audit/STATUS_REPORT_2026_05_25_sub1_iter1_smoke_block.md) — Pattern A sub1 halt 实证 evidence chain
- 9 audit docs in `docs/audit/` (2026-05-25 iter 99 batch) — Pattern B output proof
