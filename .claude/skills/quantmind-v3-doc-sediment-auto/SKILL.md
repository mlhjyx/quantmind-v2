---
name: quantmind-v3-doc-sediment-auto
description: V3 实施期 sub-PR 闭后 documentation sediment SOP — LL append candidate / ADR row sediment / STATUS_REPORT sediment / memory `project_sprint_state.md` handoff sediment 4 类 documentation sediment 同步 SOP. 反 silent skip + 反 forward-progress (沿用 LL-098 X10 + 铁律 37 sub-PR 闭后 handoff).
trigger: sub-PR 闭|sediment append|LL append|ADR row|STATUS_REPORT|handoff|memory sprint state|sub-PR 收口|merge complete|squash merge|post-merge|铁律 37
---

# QuantMind V3 Doc Sediment Auto SOP

## §1 触发条件

每 sub-PR 闭后 (squash merge / merge complete / post-merge) 必 invoke (反 silent skip):

- sub-PR squash merge 后 (CC fresh `gh pr merge --squash` + main HEAD post verify)
- sub-PR scope 含 governance candidate 候选 (LL/ADR/STATUS_REPORT/handoff/ROADMAP append candidate)
- sub-PR 收口决议 (sprint 收口决议 user 介入类 — 沿用 Constitution §L8.1 (a) (c))
- 跨 sub-PR cumulative governance debt sediment (含 V3 governance batch closure 体例)

## §2 4 类 sediment append candidate SOP (沿用 Constitution §0.3 + §L6.2 + 铁律 37)

每 sub-PR 闭后必 verify 全 4 类 (任一漂移 → STOP + 反问 user):

| # | sediment type | SSOT cite | sediment 体例 |
|---|---|---|---|
| (a) | LL append candidate | `LESSONS_LEARNED.md` LL # registry SSOT (沿用 LL-105 SOP-6 cross-verify) | next-free LL # cite + lesson body + cite source 4 元素 (path + section + timestamp) |
| (b) | ADR row sediment candidate | `docs/adr/REGISTRY.md` + `docs/adr/ADR-DRAFT.md` ADR # registry SSOT | next-free ADR # row + 决议 body + 关联 LL/铁律 cite |
| (c) | STATUS_REPORT sediment | `docs/handoff_template.md` §3 cite SOP + sub-PR PR description | sub-PR closure status + reviewer findings cite + post-PR HEAD verify |
| (d) | memory sprint state handoff | `C:\\Users\\hd\\.claude\\projects\\D--quantmind-v2\\memory\\project_sprint_state.md` (铁律 37) | sub-PR cite + main HEAD pre/post + sediment cite + LL/ADR candidate sediment status + 红线 5/5 sustained verify |

## §3 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/sediment_poststop.py` (Stop matcher, V3 step 4 sub-PR 3 sediment) — Phase 1 narrowed scope (recent-commit detect → reminder) | sub-PR 闭后 auto-fire WARN reminder, 反 silent skip |
| 本 skill (CC 主动 invoke 知识层) | sub-PR 闭后 4 类 sediment SOP active CC invoke + 反 silent skip enforce |

→ skill 是 SOP 知识, hook 是 mechanism layer auto-fire reminder. **互补不替代** — 沿用 ADR-022 反 abstraction premature (hook 反 own sediment workflow logic; skill 是 SOP source).

## §4 跟现 19 skill + 11 hook + 7 charter 三层 SSOT 锚点

| 层 | 机制 |
|---|---|
| sibling skill `quantmind-v3-cite-source-lock` | cite 4 元素 verify (4 类 sediment 各自 cite source 锁定) |
| sibling skill `quantmind-v3-anti-pattern-guard` | 反 silent agreeing + 反 forward-progress + 反 stylized commentary (sediment 体例 enforce) |
| sibling skill `quantmind-v3-sprint-closure-gate` | sprint 闭后 closure criteria 机器可验证清单 (含 sediment 体例 enforce) |
| sibling charter `quantmind-cite-source-verifier` | 独立 process spawn cross-source cite verify (4 类 sediment 各自 cite source 锁定) |
| sibling charter `quantmind-v3-sprint-closure-gate-evaluator` | sprint 闭后 closure gate evidence-gathering (含 sediment 体例 verify) |

→ 三层 (skill / hook / charter) 0 scope 重叠 — 沿用 PR #277-#280 cumulative 体例 sustained.

## §5 反 anti-pattern v1-v5 + 反 silent skip enforce

| anti-pattern | 守门 |
|---|---|
| v1 凭空数字 | 必 cite source 4 元素 (沿用 quantmind-v3-cite-source-lock skill §2) |
| v2 凭空 path/file | 必 ls / glob / Read verify |
| v3 信 user GUI cite | 必 CC SQL / script / log cross-check |
| v4 静态 grep ≠ 真测 verify | 必 run command + output cite |
| v5 Claude 给具体 → CC 实测决议 | prompt 仅写方向 / 目标 / 验收, CC 实测 path / SQL / command |
| **silent skip sediment** | 必 4 类 sediment 全 verify (任一漂移 → STOP + 反问 user) |
| **forward-progress sediment** | 反 silent auto-trigger 下一 sub-PR (沿用 LL-098 X10 + sustained user 介入 sprint 收口决议) |

## §6 实证 cite (5-08+5-09 session cumulative)

| 实证 | scope |
|---|---|
| PR #270-#280 + 5-09 双 audit cycle (smoke verify + drift rate audit) | 11 sub-PR + 2 cycle cumulative — 每 sub-PR 闭后 4 类 sediment verify (LL append candidate cumulative + ADR-DRAFT row candidate cumulative + STATUS_REPORT sediment + memory handoff sediment) |
| 沿用 PR #279 batch b APPROVE regress recovery 体例 | sustained PR #278 P1 fix lessons without repeat regression — sediment 体例反 silent sustained APPROVE 心态 (第 8 项 prompt 升级 enforce) |
| 沿用 5-09 ≥24h drift 修订实证 | immediate sediment append candidate (反 ≥24h sediment cycle drift) — sustained 第 10 项 prompt 升级 enforce |
| 沿用 5-09 drift rate audit (D) sustain V3 governance batch closure 决议 | sustained sediment append candidate cumulative — V3 governance batch closure 体例 (反 (B) 立即 v0.3 修订) |
