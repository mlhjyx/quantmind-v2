---
name: quantmind-v3-cite-source-lock
description: V3 实施期任 cite (数字/编号/路径/audit/Constitution/V3/IRONLAWS/LL/ADR) 必含 4 元素 (path + line# + section + fresh verify timestamp). 反 hallucination + N×N 同步漂移 (LL-101/103/104/116 sediment).
trigger: cite|引用|line#|section|timestamp|链接|reference|锚点|cross-cite|数字|编号|路径
---

# QuantMind V3 Cite Source Lock SOP

## §1 触发条件

任 cite 时必 invoke (反 silent cite drift):

- 任 数字 cite (factor count / LL # / ADR # / sprint #)
- 任 编号 cite (PR # / commit hash / row #)
- 任 路径 cite (file path / directory path)
- 任 audit / Constitution / V3 / IRONLAWS / SESSION_PROTOCOL / LL / ADR / 铁律 cite
- 任 cross-system claim (user "跟 Claude 说过 X" / "Claude.ai 决议 Y" / "memory cite Z")

## §2 4 元素 cite SOP (沿用 SESSION_PROTOCOL §3.1)

每 cite 必含全 4 元素 (任一缺即 v1 凭空 anti-pattern):

| 元素 | 体例 |
|---|---|
| (a) path | 完整相对 path, e.g. `IRONLAWS.md` / `docs/adr/REGISTRY.md` |
| (b) line# | line number (单行 / 范围), e.g. `:35` / `:35-42` |
| (c) section | section heading, e.g. `§T1 强制` / `§L6.2` |
| (d) fresh verify timestamp | sub-PR 起手 fresh verify 时间, e.g. "起手 fresh verify 2026-05-08 ✅" |

完整体例:
```
[IRONLAWS.md:35](IRONLAWS.md#L35) §T1 强制 (共 31 条) — 起手 fresh verify 2026-05-08 ✅
```

## §3 漂移 cite 体例 (反 silent drift)

任 cite 真值 vs prompt cite 不一致时, 必显式 cite 漂移 + 真值修正:

```
prompt cite "X" / fresh verify 真值 "Y" / 真值修正 scope: "起点 A / patch = B / 编号 next = C"
```

实证 PR #270 audit (drift 率 25%, 8 finding 中 2 ❌ + 1 🟡 — 沿用 LL-116 sediment):
- "9 hook 5 类型 wire" / fresh verify "9 .py + 7 wired in 4 types" / 修正 scope "SessionEnd 类型缺失 + 2 unwired"
- "design-an-interface 推荐" / fresh verify "in deprecated/, plugin.json 0 register" / 修正 scope "v0.2 移除"

## §4 5 类漂移 detect (沿用 SESSION_PROTOCOL §3.3)

每 sub-PR 起手 + sediment 前必 detect: 数字 / 编号 / 存在 / mtime / cross-reference (详见 `docs/V3_IMPLEMENTATION_CONSTITUTION.md` §L5.2 SSOT).

## §5 跨 system claim source 锁定 (沿用 LL-103 SOP-4 + LL-104)

user "跟 Claude 说过 X" / "Claude.ai 决议 Y" / "memory cite Z" 等跨 system claim:

- CC 必明示 source 锁定 (memory cite / DB row / git log / xtquant API / file grep / cross-source cross-verify ≥2)
- 不信 user 单 cite, 不信 prompt 单 cite, 不信 memory 单 cite
- Claude.ai vs CC 分离 architecture (LL-103 sediment) — conversation 不 cross-sync, 必 fresh verify

## §6 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/verify_completion.py` (Stop matcher) — V3 期合并 cite-source-poststop 扩展 (沿用 Constitution v0.2 §L6.2 line 278 决议) | sub-PR 闭后 auto reject silent 漂移 cite |
| 本 skill (CC 主动 invoke 知识层) | 任 cite 出前 CC 主动 cite SOP + 4 元素 verify (反仅依赖 hook auto reject 的事后 enforce) |

→ skill 是知识层, hook 是机制层. **互补不替代**.

## §7 反 anti-pattern v1-v5 (沿用 Constitution §L1.3)

| anti-pattern | 守门 |
|---|---|
| v1 凭空数字 | 必 cite source 4 元素 |
| v2 凭空 path/file | 必 ls / glob / Read verify |
| v3 信 user GUI cite | 必 CC SQL / script / log cross-check |
| v4 静态 grep ≠ 真测 verify | 必 run command + output cite |
| v5 Claude 给具体 → CC 实测决议 | prompt 仅写方向 / 目标 / 验收, CC 实测 path / SQL / command |
