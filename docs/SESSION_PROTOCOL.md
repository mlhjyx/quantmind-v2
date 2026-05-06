# SESSION_PROTOCOL.md — QuantMind V2 Session 起手前必走 SOP

> **真意义**: sub-PR / sub-step / step / cross-session resume 起手前必走 fresh read SOP, 真生产 enforcement 体例 sustained.
> **触发原因 (P0 finding, 2026-05-06)**: user 指出 "CLAUDE.md / IRONLAWS.md / LESSONS_LEARNED.md / SYSTEM_STATUS.md 4 doc 整 session 反 fresh read sustained, CC 显然没有触发这些, 这是为什么?"
> **真根因**: SOP gap — sub-PR 1-6 累计沉淀 仅 外 source fresh verify (智谱/Tavily/Anspire/GDELT/Marketaux/RSSHub docs, 沿用 LL-104 cross-verify), 反 sediment 内 source (4 root doc) fresh read SOP, 致 5-02→5-06 累计 ~3-4x 真值漂移 (e.g. prompt cite "32 rules T1=8 + T2=18 + T3=6" 真值 = 45 rules T1=31 + T2=14 + T3=0).
> **关联文档**: [CLAUDE.md](../CLAUDE.md) (项目入口) / [IRONLAWS.md](../IRONLAWS.md) (铁律 SSOT v3.0) / [LESSONS_LEARNED.md](../LESSONS_LEARNED.md) (LL backlog) / [SYSTEM_STATUS.md](../SYSTEM_STATUS.md) (系统现状) / docs/adr/ADR-037 (候选, PR-B sediment).
> **本文件版本**: v0.1 (PR-A sediment, 2026-05-06)

---

## §1 4 doc fresh read SOP

### §1.1 4 doc 真值 cite source (5-06 fresh verify ✅)

| Doc | path | size | 真意义 | last update mtime (5-06 ls -la 真测) |
|---|---|---|---|---|
| CLAUDE.md | [CLAUDE.md](../CLAUDE.md) | ~35 KB / ~530 行 | 项目入口 + 铁律 reference + 当前进度 + 文档查阅索引 | 2026-05-01 (Step 6.3b 重构) |
| IRONLAWS.md | [IRONLAWS.md](../IRONLAWS.md) | ~47 KB | 铁律 SSOT v3.0 (45 rules: T1=31 + T2=14 + T3=0, 1-44 + X9 + X10 编号) | 2026-05-01 (Step 6.2 ADR-021 sediment) |
| LESSONS_LEARNED.md | [LESSONS_LEARNED.md](../LESSONS_LEARNED.md) | ~222 KB | LL backlog (last LL-105 sustained 5-02 sprint close, 跳号 LL-006/007/008/071/072/073/075/099/102 = 9 gaps, ll_unique_ids canonical=97 含 LL-074 Amendment 双 heading) | 2026-05-03 (LL-105 ADR # registry SOP-6) |
| SYSTEM_STATUS.md | [SYSTEM_STATUS.md](../SYSTEM_STATUS.md) | ~65 KB | 系统现状 (Servy services / DB / schtask / 当前 Sprint) | 2026-05-03 (Sprint 1 真生产 sediment) |

> **mtime 漂移 finding (本 P0 真因 cite source)**: 0/4 5-06 fresh sustained — 这就是 user 5-06 P0 finding 真因 (整 session 反 fresh read sustained).

### §1.2 fresh read 触发条件 (任一 true → 必走 §1.3 体例)

1. **新 sub-PR / sub-step / step 起手前** (含 prerequisite Step / sub-PR 间 transition / Sprint 间 transition)
2. **跨 session resume** (含 /compact + SessionStart hook trigger / new session 冷启动)
3. **prompt cite 4 doc 任一具体数字 / 编号 / cite source** (反信任 prompt cite + memory cite, 沿用 LL-101 真测 verify + LL-104 cross-verify)
4. **sediment cite 4 doc 任一 ground truth claim** (反 silent overwrite, 沿用 LL-103 真分离 architecture finding)

### §1.3 fresh read 真生产体例 (4 步必走)

| 步骤 | tool | 真意义 |
|---|---|---|
| (1) ls -la 4 doc verify mtime | `Bash ls -la` | 真值 mtime 验证, 反"已读"假设 (5-06 P0 真因) |
| (2) full file fresh read 4 doc 关键 section | `Read` (sequential, full section) | 反 head/tail truncate (LL-057), full ground truth |
| (3) grep cross-reference cite source 锁定 | `Grep` (parallel, 多 pattern 一次 batch) | 沿用 LL-104 cross-verify, 反信任 prompt 单 row cite |
| (4) sediment cite 真值 in PR description / STATUS_REPORT | — | 真值 cite source ≠ 凭印象 cite, 沿用 LL-101 |

### §1.4 fresh read scope (本 SOP 当前 scope = 4 root doc)

- **本 SOP scope**: CLAUDE.md / IRONLAWS.md / LESSONS_LEARNED.md / SYSTEM_STATUS.md (4 root doc)
- **拓展候选 (audit Week 2 batch sediment 候选讨论时)**: V3 §3.1+§5.5+§18.1+§20.1 / sprint_state v7 / ADR-031~036 / docs/adr/REGISTRY.md (沿用 LL-104 cross-verify 体例 + LL-105 SOP-6 4 source 延伸)

---

## §2 sub-PR / sub-step / step 起手前必走清单

### §2.1 强制思考 (任一答错 → STOP + 问)

1. **本 PR scope** (单 PR sediment ≤ LL-100 chunked SOP 阈值 vs 拆 ≥2 chunked PR sediment)
2. **4 doc fresh verify 真值** (沿用 §1.2 触发条件, 任一 true 必走 §1.3)
3. **precondition verify** (依赖 / 锚点 / 测试数据三项核, 沿用铁律 36)
4. **红线 sustained 5/5 verify** (cash / 持仓 / LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID)
5. **main HEAD verify** (`git log -1 --oneline main` 沿用 prompt cite hash 真值 verify)
6. **test re-run 全绿 verify** (沿用 sub-PR 1-N 累计 mock + smoke + ruff clean baseline)

### §2.2 主动发现 (任一异常 → STOP + 问)

CC 必须报告"跟我假设不同":
- prompt cite 数字 / 编号 / cite source 漂移 (沿用 LL-101 + LL-104, 反信任 prompt cite + memory cite)
- 4 doc cross-reference cite source 漂移 (沿用 LL-101 + LL-105 SOP-6 体例)
- 真生产 enforcement 体例 vs prompt cite 体例 (e.g. SESSION_PROTOCOL.md "已存在拆分 sediment" vs 真值 0 存在)
- 真 PR 体量 vs prompt cite scope (e.g. "微 PR ~150-300 行 单 PR" vs 真值 ~360-550 行 拆 ≥2 chunked)

### §2.3 挑战假设 (push back 有理 → STOP + 问)

CC 允许 push back 沿用 LL-098 X10 反 forward-progress default:
- 真 scope 真值 vs prompt cite scope 漂移 ~3-4x sediment cite source 锁定 (e.g. T1=8 vs 真起点 T1=31)
- 真 PR 体量 > LL-100 chunked SOP 阈值 (沿用拆 ≥2 chunked PR sediment 体例)
- 真生产 enforcement 体例 vs prompt cite 体例 (e.g. "CLAUDE.md 拆分 sediment 沿用" 真完全 fictitious, 真 sediment scope = standalone create)

任一 push back 有理 → STOP, 等 user 决议沿用真值修正 scope sediment 还是反 prompt cite 沿用 (沿用 LL-098 X10 反 forward-progress default).

---

## §3 cite source 锁定真值 SOP (沿用 LL-101 + LL-104 + LL-105)

### §3.1 真值 cite source 必含 4 元素

| 元素 | 真意义 | 体例 |
|---|---|---|
| (a) **doc + line# + section** | 真值定位 | `[IRONLAWS.md:35](../IRONLAWS.md#L35) "T1 强制 (共 31 条)"` |
| (b) **fresh verify timestamp** | 真值时效 | "5-06 fresh verify ✅" / "5-06 16:00 git log -1 真测" |
| (c) **真值 vs prompt cite 漂移 cite** | 漂移定量 | "prompt cite '97 → 98' / fresh verify 真值 LL-105 last sustained 5-02" |
| (d) **真值修正 scope** | actionable patch | "真起点 T1=31 / 真 patch = T1=32 / 1-44 编号 next = 45" |

### §3.2 反信任 prompt cite + memory cite 真生产体例

任一 doc cite 真值 → fresh verify 沿用 §1.3 + cite source 锁定 (含 line# + section). 反:
- ❌ 凭印象 sediment "ll_unique_ids 97 sustained" 反 fresh tail verify (沿用 LL-101)
- ❌ 沿用 sub-PR 1-N sediment cite 反 fresh verify 4 doc 哪条 sediment cite source (沿用 LL-104)
- ❌ 信任 memory cite 5-02 沉淀真值 sustained 反 5-06 真值漂移 sediment cite source (沿用 LL-103 真分离)

### §3.3 真值漂移类型 cite source (PR description / STATUS_REPORT 必含)

5 类漂移类型 cite (沿用 LL-101 真测 verify + LL-104 cross-verify):
1. **数字漂移** (e.g. T1=8 vs 真起点 T1=31 / 32 rules vs 真起点 45 rules)
2. **编号漂移** (e.g. LL-120 vs 真起点 LL-105 next free = LL-106 / ADR-037 # 占用 verify ✅ free)
3. **存在漂移** (e.g. SESSION_PROTOCOL.md "已存在拆分" vs 真值 0 存在)
4. **mtime 漂移** (e.g. "4 doc 5-06 mtime sustained" vs 真值 0/4 5-06)
5. **cross-reference 漂移** (e.g. CLAUDE.md cite SESSION_PROTOCOL "拆分 sediment" vs 真值 0 cite)

---

## §4 关联铁律 + LL backref

### §4.1 IRONLAWS 关联 (5-06 fresh verify 真值, [IRONLAWS.md:35-90](../IRONLAWS.md))

| 铁律 # | Tier | 真意义 | SESSION_PROTOCOL 体例 |
|---|---|---|---|
| 25 | T1 | 代码变更前必读当前代码验证 — 改什么读什么 | §1.2 触发条件 (1) + (4) |
| 36 | T1 | 代码变更前必核 precondition — 依赖/锚点/数据 | §2.1 (3) precondition verify |
| 37 | T2 | Session 关闭前必写 handoff (memory/project_sprint_state.md) | §2.3 STATUS_REPORT 体例 |
| 38 | T2 | Platform Blueprint 是唯一长期架构记忆 — 跨 session 实施漂移禁止 | §1.2 (2) cross-session resume 触发 |
| 44 (X9) | T2 | Beat schedule / config 注释 ≠ 真停服, 必显式 restart | §3.2 ❌ silent overwrite 体例延伸 |
| **45 (候选, PR-B sediment)** | T1 (候选) | **4 doc fresh read SOP enforcement (LL-106 候选 + ADR-037 候选)** | 全 §1+§2+§3 sediment 体例 |

### §4.2 LL backref (5-06 fresh tail verify 真值, last LL-105 [LESSONS_LEARNED.md:3471](../LESSONS_LEARNED.md))

| LL # | 真意义 | SESSION_PROTOCOL 沿用 |
|---|---|---|
| LL-098 (X10) | AI 自动驾驶 cutover-bias — sprint 路径完整性失守 | §2.3 push back 有理 → STOP 体例 |
| LL-100 | reviewer agent mid-flight kill — chunked re-launch 真闭环 SOP | §2.1 (1) PR scope 阈值 |
| LL-101 | audit cite 数字必 SQL/git/log 真测 verify before 复用 | §3.1 cite source 锁定 |
| LL-103 | Claude.ai vs CC 真分离 architecture + audit row backfill | §1.2 (4) sediment cite 反 silent overwrite |
| LL-104 | Claude.ai 写 prompt 时表格 cite 仅看 1 row 真不够, 必 grep 全表 cross-verify | §1.3 (3) grep cross-reference parallel |
| LL-105 | ADR # reservation 真预约 4 source cross-verify 必 grep registry SSOT | §3.1 + §3.2 体例延伸 |
| **LL-106 (候选, PR-B sediment)** | **4 doc fresh read SOP enforcement (5-06 P0 finding) — 内 source fresh verify SOP, 沿用外 source LL-104 + LL-101 cross-verify 体例延伸** | 全文 sediment 真意义 sustained |

### §4.3 ADR 关联 (5-06 fresh verify 真值, [REGISTRY.md](adr/REGISTRY.md))

| ADR # | 真意义 | 关联 |
|---|---|---|
| ADR-021 | 铁律 v3.0 重构 + IRONLAWS.md 拆分 + X10 加入 (committed Step 6.2) | §4.1 IRONLAWS 真值起源 |
| ADR-022 | Sprint Period Treadmill 反 anti-pattern + 集中修订机制 (committed Step 6.4) | §2.3 push back 体例延伸 |
| **ADR-037 (候选, PR-B sediment)** | **Internal source fresh read SOP (governance)** | 全文 sediment 治理决议 sustained |

---

## §5 maintenance

### §5.1 修订机制

- **新 SOP section sediment** → 1 PR sediment + 同 PR sediment LESSONS_LEARNED.md +LL row + IRONLAWS.md cross-ref update + ADR sediment (e.g. ADR-037 governance decision)
- **真值 mtime drift** (e.g. CLAUDE.md / IRONLAWS.md mtime 漂移 > 7 天 sustained) → §1.1 表格 last update 列同步 update
- **新 4 doc 加入 SOP scope** (e.g. V3 / sprint_state v7 / ADR 沿用 LL-104 cross-verify 体例 + LL-105 SOP-6 4 source 延伸 sediment) → audit Week 2 batch sediment 候选讨论时 sediment

### §5.2 版本 history

- **v0.1 (PR-A sediment, 2026-05-06)**: 4 doc fresh read SOP + sub-PR / sub-step / step 起手前必走清单 + cite source 锁定真值 SOP (沿用 5-06 user (1) 修正 scope ack)
- **v0.2 候选 (PR-B sediment 待 user 触发)**: IRONLAWS.md +铁律 45 (本 SOP enforcement) + LESSONS_LEARNED.md +LL-106 (5-06 P0 finding sediment) + ADR-037 真新建 (governance decision) + REGISTRY +1 row + README +1 cite

### §5.3 footer

- **维护频率**: 4 doc fresh read SOP scope 拓展时 / SESSION_PROTOCOL section 真新增时 (1 PR sediment 沿用 LL-100 chunked SOP)
- **真 SSOT**: 本 [SESSION_PROTOCOL.md](SESSION_PROTOCOL.md) 是 sub-PR / sub-step / step 起手前必走 SOP 唯一权威源
- **现 last update**: 2026-05-06 (PR-A sediment, Step 4-7 v2 fresh verify 真值修正 scope sustained)
- **关联 PR**: PR #237 候选 (本 PR-A sediment) + PR #238 候选 (PR-B sediment, ADR-037 + IRONLAWS 铁律 45 + LL-106 + REGISTRY + README)
