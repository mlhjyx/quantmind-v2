---
name: quantmind-v3-banned-words
description: V3 实施期 reply + prompt 出前 banned-words check. 仅白名单 真账户/真发单/真生产/真测/真值; 任 真+任意词 (反 5 白名单) HARD BLOCK + sustained 中文滥用 reject. 沿用 memory #25 + Ctrl-F SOP.
trigger: banned|出前|reply|response|prompt 出|表达风格|memory #25|Ctrl-F|真+词|sustained 中文滥用
---

# QuantMind V3 Banned Words SOP

## §1 触发条件

任一发生 → 必走 banned-words check:

- CC reply 出前 (任 user-facing text output)
- CC 写 prompt 给 user / 自身 / 其他 agent 出前
- sub-PR commit message / PR description / handoff sediment 出前
- ADR / LL / STATUS_REPORT 沉淀文件出前

## §2 5 白名单 (HARD BLOCK 反 5 白名单 之外)

仅允许的 5 真+ 复合词:

| 白名单 | 用途 |
|---|---|
| `真账户` | xtquant 真账户上下文 (LIVE_TRADING_DISABLED / EXECUTION_MODE 等红线相关) |
| `真发单` | broker order_stock 真发单上下文 (paper vs live execution) |
| `真生产` | production environment vs dry-run / mock / 模拟 上下文 |
| `真测` | fresh verify cite (SQL / git / ls / Read 真测 vs 静态推断) |
| `真值` | fresh verify 出的 ground truth value vs cite drift |

任 5 白名单 之外的 真+任意词 → HARD BLOCK + 必改:

| ❌ banned | ✅ 替换 |
|---|---|
| 真有 | 确实有 / 实际有 |
| 真存在 | 确实存在 / 实测存在 |
| 真生效 | 确实生效 / 实际生效 |
| 真闭环 | 完整闭环 / cumulative closure |
| 真完成 | 确实完成 / 已 closure |
| 真起手 | 实际起手 / 起手 verify |

## §3 sustained 中文滥用 reject

`sustained` 仅允许 4 类英文 technical term 上下文 (反任意作为中文 "保持 / 持续" 替代词):

| ✅ 允许 | ❌ 反例 |
|---|---|
| "5/5 红线 sustained" (技术 status verify) | ~~"sustained 沿用"~~ → "持续沿用" |
| "test baseline sustained" (technical baseline) | ~~"sustained verify"~~ → "持续 verify" |
| "ADR-022 sustained" (specific ADR enforce status) | ~~"sustained 体例"~~ → "沿用体例" |
| "0 P0 sustained" (technical metric) | ~~"sustained 推进"~~ → "持续推进" |

## §4 META description 例外

引用 banned words rule 自身 (META description) 是允许的, 反误删本 SKILL.md / Constitution §L6.2 / verify_completion.py 扩展 cite. 例:

- ✅ "0 '真+词' 禁词 (memory #25 HARD BLOCK)" — META cite, allowed
- ✅ "扩 真+词 / sustained 中文滥用 reject + auto-rewrite" — META description of skill, allowed
- ✅ "本 skill scope: 反 真+任意词 (反 5 白名单)" — META scope cite, allowed

## §5 grep 真测 SOP

reply / prompt / 沉淀 file 出前必走 grep 真测 (沿用 Ctrl-F + memory #25):

```bash
# 真+任意词 (反 5 白名单) detect
grep -nE '真[^账测值生发]' <file>

# sustained 中文滥用 detect (粗筛, 需上下文 verify)
grep -n 'sustained' <file>
```

任一 hit → 必读上下文 verify 是否 META description (例外) 或 banned 滥用. 滥用 → 必改替换.

## §6 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/verify_completion.py` (Stop matcher) — V3 期合并 banned-words-poststop 扩展 (沿用 Constitution v0.2 §L6.2 line 279 决议) | sub-PR 闭后 auto reject + auto-rewrite candidate suggest |
| 本 skill (CC 主动 invoke 知识层) | reply / prompt 出前 CC 主动 grep verify (反仅依赖 hook 事后 reject) |

→ skill 是知识层, hook 是机制层. **互补不替代**.

## §7 实证 cite

PR #270 reviewer P2-1 surface 3 处 真+verb (line 49 真有 / line 52 真生效 / line 53+180 真存在) — 沿用本 skill SOP 修 (实证 5-08 audit grounding sub-PR 体例). 沿用本 skill 反 5-07 sub-PR 8a-followup-pre 真生产 first verify 体例 lessons.
