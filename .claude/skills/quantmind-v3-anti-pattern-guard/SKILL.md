---
name: quantmind-v3-anti-pattern-guard
description: V3 实施期 sub-PR 起手 + sediment 前 + 任 CC write file 前 v1-v5 anti-pattern check 强制. 反凭空数字/path / 反 silent overwrite / 反 fail-soft silent (沿用 LL-101/103/104/106/116 cumulative).
trigger: anti-pattern|凭空|凭印象|silent overwrite|sediment 前|sub-PR 起手|sub-PR 闭前|v1-v5|SSOT|fail-loud|reality grounding|grounding gap
---

# QuantMind V3 Anti-Pattern Guard SOP

## §1 触发条件

任一发生 → 必走 v1-v5 anti-pattern check:

- sub-PR 起手 (Phase 0 fresh verify 后, 主体执行前)
- sub-PR 闭前 (sediment 前最后 verify)
- 任 CC write file 前 (Write / Edit / large refactor 前 cite source verify)
- 任 cite source surface 时 (任 数字 / 编号 / 路径 cite 出现时)

## §2 v1-v5 anti-pattern check (沿用 Constitution §L1.3 SSOT)

详见 `docs/V3_IMPLEMENTATION_CONSTITUTION.md` §L1.3 表. 每次 invoke 必走 5 项 check:

| anti-pattern | 守门方式 | 反例 → action |
|---|---|---|
| **v1 凭空数字** | 必 cite source 4 元素 (path + section + timestamp + 真值) | 缺任一元素 → STOP + cite 补全 |
| **v2 凭空 path/file** | 必 ls / glob / Read 真测 verify | 文件 0 真测 → STOP + 实测 |
| **v3 信 user GUI cite** | 必 CC SQL / script / log / xtquant API cross-check | 仅信 user 单 cite → STOP + cross-source verify ≥2 |
| **v4 静态 grep ≠ 真测 verify** | 必 run command + output cite, 0 grep / cat / static 推断 | 仅静态分析 → STOP + 真测 cli / SQL / process spawn |
| **v5 Claude 给具体 → CC 实测决议** | prompt 仅写方向 / 目标 / 验收, CC 实测 path / SQL / command | Claude.ai prompt 含 hardcoded 数字 / path / command → STOP + 反问 |

## §3 反 silent overwrite (沿用 ADR-022)

任 sediment / write 必反 silent overwrite, 沿用 append-only 体例:

| ❌ silent overwrite | ✅ append-only |
|---|---|
| LESSONS_LEARNED.md 改 LL-N (反向) | LL append-only — 新 LL append 末尾, 0 改 LL-N 历史 |
| ADR-XXX 重写 | ADR-DRAFT.md row 候选 + ADR-XXX (committed) 沿用 SSOT |
| Constitution 整文件 overwrite | v0.X 修订 + version history append (沿用 PR #271 v0.2 体例) |
| handoff 改写 sprint state frontmatter | memory `project_sprint_state.md` 顶部 prepend 新 session sediment |

## §4 反 fail-soft silent (沿用铁律 33)

任 except / try / fail-handler 必显式声明 fail-loud / fail-safe / silent_ok 三选一:

| 方式 | 体例 |
|---|---|
| **fail-loud** (默认) | raise / log.error / DingTalk push, 反 silent suppression |
| **fail-safe** (受控) | except 后 default fallback, 必 log.warn + 沉淀 candidate |
| **silent_ok** (例外) | except: pass 必带 `# silent_ok: <reason>` 注释 (沿用 IRONLAWS §13 铁律 33) |

## §5 反 abstraction premature (沿用 ADR-022)

任 abstraction (新 hook / 新 skill / 新 subagent / 新 layer) 沿用以下顺序决议:

| 优先级 | 体例 |
|---|---|
| (1) | 复用现有组件 (扩 现 hook / 现 skill, 沿用 Constitution §L6.2 4 现有 hook 扩展决议) |
| (2) | 借 plugin 体例 (借 OMC / superpowers / mattpocock, 沿用 Constitution §L6.2 3 借 OMC subagent extend) |
| (3) | 全新创建 (反 v0.1 8 全新 sediment 倾向, 必 audit grounding 论证 0 OMC equivalent) |

## §6 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/iron_law_enforce.py` (PreToolUse[Edit\|Write] auto fire) | 现 wired — 铁律 enforcement, V3 期扩 V3 invariant + prompt 设计 0 数字 path command (合并 anti-prompt-design-violation-pretool, 沿用 Constitution §L6.2 现有 hook 扩展决议) |
| 本 skill (CC 主动 invoke 知识层) | sub-PR 起手 + sediment 前 CC 主动 cite v1-v5 + ADR-022 + 铁律 33 + abstraction premature 守门 (反仅依赖 hook auto fire) |

→ skill 是知识层, hook 是机制层. **互补不替代** (沿用 Constitution §L6.2 anti-pattern-guard 决议).

## §7 实证 cite

| 实证 | anti-pattern 类型 |
|---|---|
| LL-101 (5-02 audit cite 数字 SQL/git/log 真测 verify) | v1 凭空数字 守门 |
| LL-103 SOP-4 (5-02 Claude.ai vs CC 跨 system 分离) | v3 信 user 单 cite 守门 |
| LL-104 (5-02 表格 cite 仅看 1 row 不够) | v1 + v4 cumulative |
| LL-106 (5-06 4 root doc 整 session 0 fresh verify) | v2 凭印象 守门 |
| LL-116 (5-08 PR #270 Claude.ai cite drift 率 25%) | v1 + v2 + v3 cumulative |
| PR #270/#271/#272 sediment | v5 Claude 给方向 / CC 实测决议 |
