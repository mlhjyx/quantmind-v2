---
name: quantmind-v3-active-discovery
description: V3 实施期 sub-PR Phase 0 起手 + 闭前 active discovery 强制. 必产 finding ≥1 (3 类 STOP 触发 — 和我假设不同 / prompt 没让做但应该做 / prompt 让做但顺序错). 沿用 LL-098 X10 + LL-115 + LL-116.
trigger: Phase 0|finding|主动发现|和我假设不同|prompt 没让做|顺序错|reality grounding|挑战假设
---

# QuantMind V3 Active Discovery SOP

## §1 触发条件

每 sub-PR Phase 0 起手 + 闭前必产 finding ≥1, 反 forward-progress default:

- sub-PR 起手 fresh read 后 (8 doc 真测后 finding ≥1 必 surface)
- sub-PR 主体执行中段 (任一 3 类 STOP 触发立 surface)
- sub-PR 闭前 (sediment 前 reality drift 最后 verify)

## §2 3 类 STOP 触发标准 (沿用 Constitution §L5.3)

| 类型 | 触发条件 | 处理 |
|---|---|---|
| **(a) "和我假设不同"** | prompt cite / Claude.ai cite / memory cite 跟 fresh verify 真值漂移 (任一数字 / 编号 / 存在 / mtime / cross-reference 类) | **立即 surface** (反 silent 沿用 prompt cite 推进) — cite 漂移类型 + 真值 + 修正 scope |
| **(b) "prompt 没让做但应该做"** | sub-PR scope 外但 reality 暴露 candidate (e.g. 关联 file stale / cross-doc cite drift / 工程债 surface) | 列扩展候选 (反 silent 加 scope) — sediment 候选清单, 实施时 user 决议是否纳入 |
| **(c) "prompt 让做但顺序错 / 有更好做法"** | prompt 顺序与 reality 真值矛盾 (e.g. 先做 X 后做 Y, 但 Y 是 X 前置依赖) | **先 STOP** + 反问 user (反 silent re-order 自决) |

## §3 finding sediment 体例

每 finding 必含 cite source 4 元素 (沿用 SESSION_PROTOCOL §3.1 SSOT — skill 实施详见 Constitution §L6.2):

```
finding #N: [类型 (a)/(b)/(c)]
- prompt cite: "X" (path + line# 或 prompt 段落 cite)
- fresh verify 真值: "Y" (path:line# + section + timestamp)
- 真值修正 scope: "起点 A / patch = B / 编号 next = C"
- 处理: surface / 候选清单 / STOP+反问
```

## §4 反 forward-progress (沿用 LL-098 X10)

❌ Phase 0 finding 0 产出 → 立即推进 sub-PR 主体 (silent 沿用 prompt cite, 反 anti-pattern 守门)
❌ sub-PR 闭前 0 reality drift verify → silent merge (沿用 prompt cite ≠ fresh verify)
❌ sub-PR 末尾自动 offer schedule agent / paper-mode / cutover / 任 forward-progress 动作 (LL-098 X10 hard block — 等 user 显式触发)

✅ 每 sub-PR Phase 0 finding ≥1 显式 surface (即使 finding = "0 漂移, 全 ✅" 也必显式 cite verify status)
✅ sub-PR 闭后 STATUS_REPORT 必含 finding 数 + 漂移率 cite (沿用 PR #270 体例 — drift 率 25%)
✅ sub-PR 末尾 STATUS_REPORT 0 forward-progress offer (等 user 触发 next sub-PR prompt)

## §5 实证 cite

| 实证 | finding |
|---|---|
| PR #270 `.claude/` audit (5-08) | 8 Claude.ai finding cross-verify, drift 率 25% (2 ❌ + 1 🟡 + 5 ✅), LL-116 主 sediment |
| PR #271 V3 Constitution v0.2 + skeleton (5-08) | 反 v0.1 4 处 audit grounding gap (§L0.3/§L1.1/§L6.1/§L6.2) |
| LL-115 (5-08 chunk C-LL precedent) | sub-PR misframe 修正 active discovery enforcement 沿用 |

## §6 跟 mattpocock grill-me skill 互补

| layer | 机制 |
|---|---|
| mattpocock `grill-me` | user-CC alignment 工具 — sub-PR scope 决议起手时 user 介入 align |
| 本 skill | sub-PR Phase 0 + 闭前 active discovery 强制 — CC 自身 reality drift 主动 surface, 不依赖 user 触发 |

→ **互补不替代** (沿用 Constitution v0.2 §L6.1 mattpocock 选片决议).
