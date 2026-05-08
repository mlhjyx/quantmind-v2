---
name: quantmind-v3-fresh-read-sop
description: V3 实施期 sub-PR / step / cross-session resume 起手 8 doc fresh read SOP. 反 4 doc 整 session 0 fresh verify 累计 ~3-4x 真值漂移 (LL-106 sediment, 5-02→5-06 实证).
trigger: 起手|sub-PR 起手|step 起手|cross-session resume|新 session|fresh read|前置 verify|8 doc fresh read|reality grounding
---

# QuantMind V3 Fresh Read SOP

## §1 触发条件

任一发生 → 必走 8 doc fresh read SOP, 不凭印象 / 不沿用上一 session memory cite:

- 新 sub-PR 起手 (任 V3 sprint 起步 / chunked sub-PR 起步)
- step 起手 (V3 6 件套 step 1-6 各自起步)
- cross-session resume (compaction 后 / 新 conversation 起步)
- 用户 explicit "fresh read" / "起手 verify" / "reality grounding" 指令

## §2 8 doc 清单 (沿用 Constitution §L1.1 SSOT)

详见 `docs/V3_IMPLEMENTATION_CONSTITUTION.md` §L1.1 表. 8 committed (post PR #271, V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md sediment 后, 全 8 doc 已 main HEAD active):

| Doc | 状态 |
|---|---|
| `CLAUDE.md` | committed |
| `IRONLAWS.md` | committed (v3.0 SSOT) |
| `LESSONS_LEARNED.md` | committed (LL append-only) |
| `SYSTEM_STATUS.md` | committed |
| `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` | committed (V3 main spec) |
| `docs/V3_IMPLEMENTATION_CONSTITUTION.md` | committed (v0.2 post-audit grounding) |
| `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` | committed (v0.1 skeleton) |
| `docs/adr/REGISTRY.md` | committed (ADR # SSOT, LL-105 SOP-6) |

## §3 fresh verify SOP (沿用 SESSION_PROTOCOL §1.3 + §3.1)

每 doc fresh read 必走:

1. **fresh ls / Read** — 不凭 memory cite, 实测 file mtime + 头部 frontmatter / 元信息
2. **cite source 锁定 4 元素** — path + line# + section + fresh verify timestamp
3. **section anchor verify** — section heading 确实存在 (反 phantom section cite)
4. **mtime 漂移 detect** — 跟上一 session memory cite 比对, 若 mtime drift → trust fresh read

## §4 5 类漂移 detect (沿用 SESSION_PROTOCOL §3.3)

每 sub-PR 起手 + sediment 前 detect:

| 类型 | 示例 |
|---|---|
| 数字漂移 | "T1=8 vs 起点 T1=31" |
| 编号漂移 | "LL-120 vs 起点 LL next free = LL-X" |
| 存在漂移 | "已存在拆分 vs 真值 0 存在" |
| mtime 漂移 | "4 doc 起手 mtime vs 真值 0/4 起手" |
| cross-reference 漂移 | "doc A cite doc B 'Y' vs 真值 0 cite" |

## §5 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/session_context_inject.py` v2 (SessionStart auto fire) | 自动 inject 4 root doc + Blueprint + sprint state frontmatter description (audit row 11 真测 wired) |
| 本 skill (CC 主动 invoke 知识层) | sub-PR / step 起手 时 CC 主动 cite SOP + 8 doc 全清单 fresh read 强制 (反仅依赖 hook auto inject 的 4 doc subset) |

→ skill 是知识层, hook 是机制层. **互补不替代** (沿用 Constitution v0.2 §L6.2 fresh-read-sop 决议).

## §6 反 anti-pattern (沿用 LL-106)

❌ 整 session 仅 1 次起手 fresh read (4 doc 起手后 0 fresh verify, 累计 ~3-4x 真值漂移 5-02→5-06 实证)
❌ 凭 memory cite / sprint_state frontmatter cite 起手 (反 LL-101 + LL-116 — 信 cite ≠ 真测 verify)
❌ 跳过 8 doc 中 V3 doc / Constitution / invocation map / REGISTRY (audit §8 真值 — 8 doc 是 V3 实施期 minimum)

✅ 每 sub-PR 起手 8 doc fresh read 全走 (即使 cumulative session 内多 sub-PR — 沿用 Constitution §L0.3 step 1 强制)
✅ fresh verify 时间戳记 sub-PR commit message + STATUS_REPORT (沿用 PR #270 + #271 体例)
