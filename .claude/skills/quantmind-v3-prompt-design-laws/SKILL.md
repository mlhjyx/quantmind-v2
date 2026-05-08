---
name: quantmind-v3-prompt-design-laws
description: V3 实施期 Claude.ai 写 prompt 给 CC 时 + CC 写 prompt 给 subagent / 自身 / 其他 agent 时 prompt 设计 laws — 0 数字 / 0 path / 0 command / 0 hardcoded 决议. 仅写方向 + 目标 + 验收, CC 实测决议具体值 (沿用 memory #19/#20 + anti-pattern v5).
trigger: prompt 设计|prompt 给|0 数字|0 path|0 command|memory #19|memory #20|方向 + 目标 + 验收|CC 实测决议|hardcoded prompt|hardcoded 决议
---

# QuantMind V3 Prompt Design Laws

## §1 触发条件

任 prompt 写出前必 invoke (反 hardcoded prompt → CC silent 沿用 prompt cite, 反 anti-pattern v5):

- Claude.ai 写 prompt 给 CC (跨 system, sub-PR / sprint / step prompt 起手)
- CC 写 prompt 给 subagent (reviewer agent / planner / verifier 等)
- CC 写 prompt 给自身 (sub-PR 内 sub-task self-prompt)
- CC 写 prompt 给其他 plugin agent (OMC tier-0 / superpowers skill 等)

## §2 0 hardcoded 4 类决议 (反 anti-pattern v5)

prompt 必反 4 类 hardcoded (任一 hit → STOP + 反问):

| 类型 | ❌ 反例 (hardcoded) | ✅ 正例 (CC 实测决议) |
|---|---|---|
| **0 数字** | "factor count = 113" / "LL-116" / "ADR-042" / "main HEAD = 0d1f22d" | "factor count CC 真测 grep" / "LL # CC 实测决议 next free 沿用 LL-105 SOP-6" / "main HEAD CC 实测 git log -1" |
| **0 path** | "scripts/run_paper_trading.py:42" / "backend/app/api/news.py" | "CC 真测 ls / glob / find verify path" |
| **0 command** | "python scripts/X --arg=Y" / "git checkout -b fix/specific-name" | "CC 实测决议 command + verb" / "branch fix/* 命名沿用 quantmind 体例 (CC 实测决议)" |
| **0 决议** (Claude.ai 0 决议时机决议) | "立即 do X" / "先做 A 后做 B" hardcoded order | "CC 真测决议 顺序" / "任一 push back 成立 → STOP + 反问" |

## §3 prompt 必含 3 元素 (沿用 memory #19/#20)

prompt 仅写 3 元素 (反 hardcoded 4 类):

| 元素 | 体例 |
|---|---|
| **方向** | "doc-only sub-PR sediment 体例" / "audit grounding 反 silent overwrite" |
| **目标** | "新 4 SKILL.md sediment + 跟现 11 skill 0 命名冲突" / "Constitution v0.2 修订 audit grounding 5 处 misaligned" |
| **验收** | "reviewer agent 0 P0/P1 + AI self-merge" / "5/5 红线 sustained" / "cite 4 元素 verify" |

## §4 7 块 prompt 体例 (沿用 memory #15)

V3 实施期 sub-PR prompt 体例 (Claude.ai 写 prompt 给 CC 时):

| 块 | scope |
|---|---|
| §1 背景 | 项目当前实际状态 + 触发原因 + 红线 sustained cite (CC 必 verify 不假设) |
| §2 强制思考 | ≥10 项 verify 项, 任一答错 STOP + 反问 user |
| §3 主动发现 | 执行中触发 a/b/c 类立 surface (沿用 SESSION_PROTOCOL §3.3 5 类漂移 detect) |
| §4 挑战假设 | ≥5 项 push back 候选, 任一成立 STOP + 反问 |
| §5 硬执行边界 | ✅ 沿用 / ❌ 红线 list |
| §6 输出含 finding + next-prompt + STATUS_REPORT | finding 报告 + 下一 sub-PR prompt 草稿 + STATUS_REPORT 体例 |
| §7 主动思考 | (batch 2 起手新增, 沿用 LL-103 SOP-4 反向) — CC 见解 / scope outside / 长期影响 / governance candidate ≥3 类 (反 silent agreeing) |

## §5 跨 system 沟通 体例 (沿用 LL-103 SOP-4 + LL-104)

Claude.ai vs CC 跨 system 分离 architecture (5-02 SOP-4 sediment):

- Claude.ai 写 prompt 时 0 知 CC 现 conversation state (memory cite / sprint state / fresh main HEAD)
- CC 跑 prompt 时必 fresh verify Claude.ai cite (反信 prompt 单 cite, LL-104 表格 cite 仅看 1 row 不够)
- 任 cross-system claim 必 cross-source verify ≥2 (memory cite / DB row / git log / file grep)

## §6 跟 hook + skill 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/iron_law_enforce.py` (PreToolUse[Edit\|Write] auto fire) | V3 期扩 prompt 设计 0 数字 path command (合并 anti-prompt-design-violation-pretool, 沿用 Constitution §L6.2 现有 hook 扩展决议) |
| `quantmind-v3-anti-pattern-guard` skill (沿用 Constitution §L6.2 anti-pattern-guard 决议) | sub-PR 起手 + sediment 前 v5 (Claude 给具体 → CC 实测决议) check |
| 本 skill (CC 主动 invoke 知识层) | prompt 写出前 CC 主动 cite SOP + 0 hardcoded 4 类 + 3 元素 + 7 块体例 (反仅依赖 hook auto reject + anti-pattern-guard sub-PR 起手 check) |

→ skill 是知识层, hook 是机制层. **互补不替代** (沿用 Constitution §L6.2 prompt-design-laws 决议).

## §7 实证 cite

| 实证 | prompt 设计 violation |
|---|---|
| PR #270 audit prompt (5-08, ~300 行) | Claude.ai cite "9 hook 5 类型 wire" / "~24 COMMIT_MSG_TMP" hardcoded → CC 真测 drift 率 25% |
| PR #271 Constitution v0.2 prompt | Claude.ai 0 hardcoded path, CC 实测决议 branch name fix/v3-constitution-v0-2-invocation-map-skeleton-v0-1 |
| PR #272 batch 1 prompt | Claude.ai 建议 4 skill 候选, CC 真测 cross-verify Constitution v0.2 §L6.2 后决议沿用 |
| memory #25 banned-words HARD BLOCK | 沿用本 skill scope, prompt 出前必 grep 真测 |
