# STATUS_REPORT — Step 6.2.5a 纯 audit 决议 (2026-04-30 ~22:30)

**PR**: chore/step6-2-5a-audit
**Base**: main @ `43a3b89` (PR #174 Step 6.2 IRONLAWS.md + ADR-021 + CLAUDE.md banner+ref merged)
**Scope**: 1 新 audit 文档. 0 改任何已存在文件.
**真金风险**: 0 (纯 audit, 0 业务代码 / 0 .env / 0 服务重启 / 0 DML / 0 改文件)
**LL-098 stress test**: 第 6 次

---

## §0 环境前置检查 (E1-E13)

| 检查 | 实测 | 状态 |
|---|---|---|
| E1 git | main HEAD = `43a3b89` (PR #174), 工作树干净 | ✅ |
| E2 PG stuck | 沿用 4-30 ~21:30 PR #174 baseline (无 sprint 事件改变) | ✅ (沿用) |
| E3 Servy 4 服务 | 沿用 4-30 ~21:30 PR #174 baseline | ✅ (沿用) |
| E4 venv | Python 3.11.9 (沿用) | ✅ |
| E5 LIVE_TRADING_DISABLED | True | ✅ |
| E6 真账户 | 沿用 4-30 14:54 实测 (read-only) | ✅ (沿用) |
| E7 cb_state.live nav | 沿用 PR #171 reset 后状态 (993520.16) | ✅ (沿用) |
| E8 position_snapshot 4-28 live | 沿用 PR #171 DELETE 后状态 (0 行) | ✅ (沿用) |
| E9 PROJECT_FULL_AUDIT + SNAPSHOT | 实存 (PR #172) | ✅ |
| E10 LL-098 | L3032 实存 (沿用 PR #173 verify, LL 总数 92) | ✅ |
| E11 IRONLAWS.md | 实存 (PR #174 新建, 791 行) | ✅ |
| E12 ADR-021 | 实存 (PR #174 新建, 206 行) | ✅ |
| E13 CLAUDE.md banner + 铁律段 reference | 实存 (PR #174, banner L5 + 铁律段 L332-L455) | ✅ |

---

## §1 主题 A — X10 工程化候选评估

### A.1 实测 hooks infra

- **`config/hooks/pre-push`** 实存 (铁律 10b 守门: pytest -m smoke 全绿). 用 `git config core.hooksPath config/hooks` 启用.
- **`.git/hooks/`** 全是 sample (Git default), 无项目级 hook.
- **Git 原生 hook 类型** (man githooks): pre-commit / pre-push / commit-msg / prepare-commit-msg / post-commit / post-merge / pre-receive / update / 等. **`pre-merge` Git 不支持** — prompt 假设破灭, 沿用 LL "假设必实测" 候选.

### A.2 X10 检测脚本 IRONLAWS.md §18 候选实测

IRONLAWS.md L723-L730 写两个候选:
- "pre-merge hook grep PR description / commit message" — Git 不支持 pre-merge, 应改 **commit-msg hook 或 pre-push hook**
- "Claude system prompt-level guard — 末尾输出阶段 detect forward-progress 关键词, 自动 strip 或要求二次 confirm" — Wave 5+ 远期, 依赖 Anthropic API/SDK 自定义 system prompt, 当前无近期实施可能

### A.3 决议建议

| 候选 | 决议 | 论据 |
|---|---|---|
| pre-merge hook | ❌ 修订 → **commit-msg hook 或 pre-push 扩展** | Git 原生不支持 pre-merge. 改用 commit-msg (commit 时阻) 或 pre-push 扩展 (push 时阻). pre-push 已有 (10b smoke), 扩展更便利. |
| pre-push 扩展关键词扫 | ✅ **Step 6.2.5b 候选** | 扫 commit message + branch name 含 cutover-bias 关键词 (e.g. "/schedule agent" / "auto cutover" / "next step ..." / etc). 误报需绕过 → `--no-verify` + 写 reason. 可行性高. |
| Claude system prompt-level guard | ⏳ **留 Wave 5+** | 远期, 依赖 Anthropic API custom system prompt. 当前无近期实施可能. |
| 软门 (LL-098 规则 1+2 文档化) | ✅ **当前已实施** | IRONLAWS.md §18 X10 完整内容 + LL-098 规则 1+2. 软门通过 stress test (累计 6 次, 本 PR 第 6) 已 demonstrate 有效. |

### A.4 cutover-bias 关键词清单 (sprint period 累积, Step 6.2.5b 候选)

CC 实测 sprint period (LL-098 沉淀 + 多次 stress test) 累积关键词:

- `/schedule agent`, `schedule agent ...`
- `paper-mode 5d`, `paper-mode dry-run`, `paper→live`
- `auto cutover`, `自动 cutover`, `cutover` (单独词需谨慎, 误报高)
- `next step ...`, `下一步建议`, `下一步是 ...`
- `... days remind`, `remind user about`, `提醒 user`
- `Step X.Y 启动`, `进入 Step X.Y`
- `gate 通过 → ...`, `Phase 通过 → ...`

**误报风险评估**:
- "Step 6.2.5b 启动" 在 audit 文档中合法 (描述路径) → 需 contextual 检测, 仅在 PR description / commit message 阻
- "next step" 在工程文档中合法 (描述工作流) → 需绑定 PR description 末尾 5 行 + 检测 forward-progress action 句式
- 推荐: 阻 hard pattern (e.g. `/schedule agent` / `paper-mode 5d` 显式词组), 不阻 generic ("next step", "下一步") — 减误报

---

## §2 主题 B — narrower 起点链 audit

### B.1 实测 narrower 链 (LL-089 ~ LL-098)

| LL | 实战次数 | 起点解释 |
|---|---|---|
| LL-089 (起点) | **22** | "D3-A 自身 14 次 + Step 4 修订 2 次" (D3-A audit 起点 14 项 forensic 假设错 + Step 4 修订 2 项 = 22) |
| LL-090 | 22 (同 batch) | LL-089 + LL-090 同 D3-A revision batch |
| LL-091 | 23 | LL-091 本 LL 加入 |
| LL-092 | 24 | |
| LL-093 | 25 | LL-091/092/093 同源 D3 5 类源覆盖 |
| LL-094 | 26 | LL-091~094 同源 D3 系列 |
| LL-095 | 27 | LL-091~094 + 本 |
| LL-096 | 28 | LL-091~095 + 本, D3 系列 28 次同源 |
| LL-097 | 29 | LL-091~096 + 本 |
| LL-098 | **30** | LL-091~097 + 本 |

### B.2 LL-089 起点 22 解构

LL-089 内文写 "D3-A 自身 14 次 + Step 4 修订 2 次 = 累计 22". 即:
- **D3-A audit period**: 14 次 forensic 假设错 (D3-A spike 期间 sprint internal 累计)
- **Step 4 修订**: 2 次 (PR #163-164 narrative 修订? 或 4-29 spike?)
- **总 22**: 不含早期 LL (LL-001 ~ LL-088), narrower 是 D3-A audit 起点之后的同质链

### B.3 LL-001 ~ LL-088 同质性

CC 实测 (沿用 LL audit + sprint period memory):
- **LL-001 ~ LL-050 (早期)**: 因子研究 / 回测引擎 / 调度 / 等领域教训 (e.g. LL-013/014 因子 raw vs neutralized IC, LL-017 paired bootstrap, LL-027 RANKING 框架). **不属 "假设必实测" 同质**.
- **LL-051 ~ LL-068 (中期)**: governance / schtask / 审计 (LL-051 开源优先, LL-054 PT 状态实测, LL-055 2 ahead 腐烂数字, LL-068 DataQualityCheck hang). **部分属同质** (e.g. LL-054 PT 状态实测 = "凭 Redis 反推 vs 实测 NAV").
- **LL-076 ~ LL-088 (末期)**: Risk Framework v2, qmt fail-loud, 等 (LL-076 LANDSCAPE, LL-081 v2 LL-081, LL-088 connection 计数器). **部分属同质** (LL-081 v2 LL-081 = "假设 silent_ok 实际 silent fail").

### B.4 broader 33 起点解构

- **PROJECT_FULL_AUDIT §3 (PR #172) declared 31** 没说明 31 累积具体. 沿用 sprint period memory:
  - **早期 sprint accumulated** (~5-7 项): LL-051/054/055 governance / LL-068 schtask / LL-076 LANDSCAPE / LL-081 v2 / LL-088 connection — 这些是 broader scope 的 "Claude 默认假设/默认行为被实测/user 反问推翻", 但不属 narrower D3-A audit 同质链
  - **D3 sprint accumulated** (~22 narrower-equivalent at start): D3-A spike 期间 14 + Step 4 2 + LL-089/090 batch 启动后 narrower 链
  - **31 = 早期 + narrower 起点 22 + D3 系列 + 等**, 数字漂移正常
- **+1 (PR #173 implicit)**: LL-098 加入 broader scope (LL-098 自身既算 narrower 30 也算 broader 32)
- **+1 (PR #174 STATUS_REPORT §2 第 4 项)**: PR #172 §5 "X1-X9 inline" 假设错为新实证 (broader 32 → 33)

### B.5 双口径策略决议

✅ **永久并存** (推荐).

**论据**:
- narrower (LL 内文链 LL-089 起点 22 → LL-098 30): D3-A audit period 起点的 sprint internal 链, 严格 LL +1 链式继承
- broader (PROJECT_FULL_AUDIT scope 33): 全 sprint period 累计 "Claude 默认假设/默认行为被实测/user 反问推翻", 含早期非同质 sprint 累积
- 合并候选: ❌ 不可行 (合并 = 选哪个为 canonical, 损失另一个 scope 信息)
- 替代候选: 显式语境标识 (沿用 PR #173/#174 STATUS_REPORT §3 双口径并列声明)

---

## §3 主题 C — 铁律总数口径统一审计

### C.1 实测 IRONLAWS.md §1 Tier 索引

CC 实测 (IRONLAWS.md L35-L88):
- T1 强制: **31 条** (1, 4, 5, 6, 7, 8, 9, 10, 10b, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 25, 29, 30, 31, 32, 33, 34, 35, 36, 41, 42, 43)
- T2 警告: **14 条** (3, 21, 22, 23, 24, 26, 27, 28, 37, 38, 39, 40, 44 X9, X10)
- T3 建议: **0 条**
- DEPRECATED: **1 条** (#2)
- 候选未 promote: **4 条** (X1/X3/X4/X5)
- 跳号: **3 项** (X2/X6/X7)
- 撤销: **1 项** (X8)

### C.2 不同口径并存现状

PR #174 STATUS_REPORT §1 多处使用不同口径:
- §1 Q1: "T1=31 / T2=14 / DEPRECATED=1 = 46 (含 10b 算独立)"
- §1 Q1 加 X10: "T2 → 15"
- §1 Q6: "T1=31 / T2=14 (+1 X10) / T3=0 / DEPRECATED=1"
- §1 Q12: "原 43 + DEPRECATED 1 + 10b 子条 = 45, 加 X10 = 46"

差异源:
- "10b 算独立" vs "10b 子条" — 同一 10b 在 T1 表内独立行 (CC 实测 IRONLAWS.md L47), 但概念上是 10 的子条
- "+1 X10" vs "X10 已含 14" — IRONLAWS.md T2 表 14 行已含 X10, 但 PR #174 Q6 写 "14 (+1 X10)" 暗示 14 不含 X10

### C.3 推荐 canonical 口径

| 口径名 | 数 | 说明 |
|---|---|---|
| **Tier 化 effective** (推荐 canonical) | T1=31 / T2=14 / T3=0 = **45** | 含 10b 子条独立行 + X10 新加, 不含 DEPRECATED #2. 沿用 IRONLAWS.md §1 实测. |
| **编号占用** | 1-44 + X10 = **45** | 含 1 DEPRECATED #2 + 子条 10b (10b 不占独立编号, 在 10 下). |
| **历史决议覆盖** (含候选/跳号/撤销) | 45 + 4 候选 + 3 跳号 + 1 撤销 = **53** | broader audit scope, 含 X1/X3/X4/X5 候选 + X2/X6/X7 跳号 + X8 撤销 |
| **CLAUDE.md banner 简略口径** | "44 + X9 + X10" = 46 | 沿用 banner "完整铁律 (1-44 + X9 + X10)", 此口径未含 candidate / 跳号 / 撤销 |

### C.4 决议建议

✅ **canonical 口径 = Tier 化 effective 45 (T1=31 / T2=14 / T3=0)**.

**修订位置清单** (Step 6.2.5b 候选):
- IRONLAWS.md §0/§1: 已使用 canonical 口径, 无修订 (✅ 已对齐)
- IRONLAWS.md §22 版本变更记录 L788 "X10 加入 (LL-098 沉淀)" 不含具体计数, 无修订
- CLAUDE.md banner L5 "完整铁律 (1-44 + X9 + X10)": 沿用编号占用口径, 与 Tier 化 effective 不同但都正确, 无修订必要 (banner 是用户语境)
- ADR-021 §2.1 §2.2 §3 §4: 0 改 (PR #174 锁)
- PROJECT_FULL_AUDIT_2026_04_30 §5 line 122 "7 新铁律 X1-X9 实施扫描": **错** (实测 X1-X8 candidates / X9 inline / X10 待落地). PR #172 锁不调.
- 后续任何文档引用铁律总数: 沿用 canonical 45 + 备注 (含候选 49 / 含历史决议 53)

---

## §4 主题 D — 孤儿铁律处置决议

### D.1 实测每条铁律的 ref 状态

CC 实测 IRONLAWS.md §1 表内 "LL backref" + 各 §X 内文 "**LL backref:**" / "**ADR backref:**" header:

| 铁律 | LL backref (table) | LL backref (内文 header) | ADR backref | 状态 |
|---|---|---|---|---|
| 1 | LL-001 series | LL-001 series ✅ | — | ✅ |
| 2 | DEPRECATED | DEPRECATED | — | DEPRECATED |
| 3 | sprint period | — | — | inline 教训 (sprint period) |
| 4 | LL-013 / LL-014 | LL-013 / LL-014 ✅ | — | ✅ |
| 5 | LL-017 | LL-017 ✅ | — | ✅ |
| 6 | LL-027 | LL-027 ✅ | — | ✅ |
| 7 | IC偏差 | — | — | inline 教训 |
| 8 | "IS强OOS崩" | — | — | inline 教训 |
| 9 | OOM 2026-04-03 | — | — | inline 事件 |
| 10 | 清明改造 | — | — | inline 事件 |
| 10b | MVP 1.1b shadow | — | — | inline 事件 |
| 11 | mf_divergence | — | — | inline 教训 |
| 12 | AlphaAgent KDD 2025 | — | — | inline 论文 |
| 13 | reversal_20 | — | — | inline 教训 |
| 14 | Step 6-B | — | — | inline 阶段 |
| 15 | regression_test | — | — | inline 工具 |
| 16 | LL-051+ | — | — | inline LL 编号 |
| 17 | LL-066 | LL-066 ✅ | ADR-0009 ✅ | ✅ |
| 18 | sim-to-real | — | — | inline 概念 |
| 19 | IVOL drift | — | — | inline 教训 |
| 20 | Step 6-F | — | — | inline 阶段 |
| 21 | Qlib 90% | — | — | inline 教训 |
| 22 | S1 审计 10+ | — | — | inline 教训 |
| 23 | 11 设计文档 | — | — | inline 教训 |
| 24 | DEV_AI_EVOLUTION 705 行 | — | — | inline 教训 |
| 25 | LL-019 + 本 sprint | — | — | inline LL 编号 |
| 26 | P0 SN | — | — | inline 教训 |
| 27 | sprint | — | — | inline (sprint period) |
| 28 | sprint | — | — | inline (sprint period) |
| 29 | RSQR_20 11.5M 行 | — | — | inline 事件 |
| 30 | Phase 1.2 SW1 | — | — | inline 教训 |
| 31 | F31 / F43 | — | — | inline finding 编号 |
| 32 | F16 | — | — | inline finding 编号 |
| 33 | F76-F81 | — | — | inline finding 编号 |
| 34 | F45 / F62 / F40 | — | — | inline finding 编号 |
| 35 | F32 / F15 / F65 | — | — | inline finding 编号 |
| 36 | 11 设计文档 80% 未实现 | — | — | inline 教训 |
| 37 | sprint | — | — | inline (sprint period) |
| 38 | Blueprint drift | — | ADR-008 ✅ | ✅ ADR ref |
| 39 | sprint period 多次 | — | — | inline (sprint period) |
| 40 | S4 32 fail | — | — | inline 教训 |
| 41 | Phase 2.1 sim-to-real | — | — | inline 教训 |
| 42 | LL-051 / LL-054 / LL-055 | — | — | inline LL 编号 |
| 43 | LL-068 | LL-068 ✅ | — | ✅ |
| 44 (X9) | LL-097 | LL-097 ✅ | — | ✅ |
| X10 | LL-098 | LL-098 ✅ | ADR-021 ✅ | ✅ |

### D.2 真孤儿 (无任何 ref) 实测

✅ **0 条真孤儿**. 所有铁律都有至少 1 个 ref (inline 教训 / 事件 / 论文 / finding 编号 / LL 编号 / ADR 编号).

### D.3 缺正式 "LL backref:" header 的铁律

CC 实测 (IRONLAWS.md 内文 grep "**LL backref:**" header):
- 有 header: 9 条 (1, 4, 5, 6, 17, 17 例外, 43, 44 X9, X10)
- 无 header: 36 条 (其他铁律全部) — inline 教训/事件 ref

### D.4 处置决议

✅ **大部分 (iii) 承认铁律先于 LL / inline 教训已足够**.

**论据**:
- 铁律是 sprint period 累积的"永恒原则", 先于 LL 沉淀合理 (e.g. 铁律 9 资源仲裁 = OOM 2026-04-03 事件, 不必每条铁律都有 LL 编号)
- 真孤儿 0 条 — 所有铁律 inline ref 已足够追溯
- Retroactive 补 LL = LL 编号膨胀 (LL 总数 92 → 130+? 过度沉淀, 价值低)
- 铁律 22 (文档跟随代码) 不要求 LL backref 统一 header, 只要求文档同步

**例外建议** (Step 6.2.5b 候选, 低成本高价值):
- 铁律 16 inline "LL-051+": 改为正式 "**LL backref:** LL-051" header
- 铁律 25 inline "LL-019 + 本 sprint": 改为正式 "**LL backref:** LL-019" header
- 铁律 38 已标 ADR-008 backref: 加 "**ADR backref:** ADR-008" header (现仅 table 标)
- 铁律 42 inline "LL-051 / LL-054 / LL-055": 改为正式 "**LL backref:** LL-051 / LL-054 / LL-055" header

**LL-099+ 候选**: ❌ 不沉淀. 沿用 (iii) 决议, retroactive 补 LL = 编号膨胀.

---

## §5 主题 E — broader 33 实证 retroactive 沉淀 LL-099+

### E.1 broader 33 三项实证定位

CC 实测 (沿用主题 B B.4):

| 实证 | 来源 | 详细 |
|---|---|---|
| 实证 1: PROJECT_FULL_AUDIT base 含 sprint 早期累积 | PR #172 §3 declared 31 含早期 LL-051/054/055/068/076/081/088 部分 | broader 起点 31 隐含 ~5-7 项 sprint period 早期累计, 不属 narrower D3-A 同质 |
| 实证 2: PR #173 LL-098 加入 broader | PR #173 STATUS_REPORT §3 narrower 30 / broader 32 | LL-098 自身既属 narrower 30 也属 broader 32 — 双口径同步 +1 |
| 实证 3: PR #172 §5 "X1-X9 inline" 假设错 | PR #174 STATUS_REPORT §2 第 4 项 / §3 broader 32 → 33 | sprint period 内 PR #172 PROJECT_FULL_AUDIT 数字假设错 (X1-X9 inline 实测仅 X9 inline) |

### E.2 LL-099+ 沉淀价值评估

| 实证 | LL 沉淀价值 | 决议 |
|---|---|---|
| 实证 1 | ❌ 价值低 — 历史 broader 累积已完成 (PR #172 sprint 累积 narrative), 不可单独抽出沉淀 | 不沉淀 |
| 实证 2 | ❌ 价值低 — LL-098 自身已沉淀 (PR #173), broader 累积是 LL-098 的 derivative, 不需单独 LL | 不沉淀 |
| 实证 3 | ⚠️ 价值中 — PR #172 §5 数字假设错是真实证, 沿用 LL "假设必实测" 同质. 但 PR #172 已锁, retroactive 沉淀 LL = 治理后置 | 候选 (Step 6.2.5b 评估) — 但不强烈推荐, 沿用 PR #174 STATUS_REPORT §2 第 4 项 audit doc 引用足够 |

### E.3 决议建议

✅ **不沉淀 LL-099+** (主决议).

**论据**:
- LL 编号膨胀风险 (92 → 130+ 过度沉淀)
- audit doc (PR #173/#174 STATUS_REPORT §3) 引用足够追溯
- broader scope 33 是累积 narrative, 不是单一事件
- 沿用 LL-098 stress test 第 6 次 (本 PR) — broader 不沉淀 = 沿用拆批 + 不前推原则

**子决议** (Step 6.2.5b 候选):
- 如 user 决议要求, 沉淀 1 LL-099 综合 broader 33 三项实证 (单 LL 含三事件 narrative, 不分三 LL)
- 否则 0 LL 沉淀

---

## §6 主题 F — ADR 编号系统 audit

### F.1 实测 docs/adr/ 完整状态

CC 实测 (15 ADR 文件 + 1 README + ADR-021 新加 = 16 ADR 文件):

| 编号 | 文件名 | Status | 备注 |
|---|---|---|---|
| ADR-0009 | datacontract-tablecontract-convergence | (沿用) | **4 位数字, 历史漂移** |
| ADR-001 | platform-package-name | accepted | 3 位 |
| ADR-002 | pead-as-second-strategy | accepted | 3 位 |
| ADR-003 | event-sourcing-streambus | accepted | 3 位 |
| ADR-004 | ci-3-layer-local | accepted | 3 位 |
| ADR-005 | critical-not-db-event | accepted | 3 位 |
| ADR-006 | data-framework-3-fetcher-strategy | accepted | 3 位 |
| ADR-007 | mvp-2-3-backtest-run-alter-strategy | accepted | 3 位 |
| ADR-008 | execution-mode-namespace-contract | accepted | 3 位 |
| ADR-010 (1) | addendum-cb-feasibility | accepted | **重复编号 #1** (与 #2 共 010) |
| ADR-010 (2) | pms-deprecation-risk-framework | accepted | **重复编号 #2** |
| ADR-011 | qmt-api-utilization-roadmap | accepted | |
| ADR-012 | wave-5-operator-ui | accepted | |
| ADR-013 | rd-agent-revisit-plan | accepted | |
| ADR-014 | evaluation-gate-contract | accepted | |
| (gap) | ADR-015 ~ ADR-020 | — | **6 项空缺, lazy assignment** |
| ADR-021 | ironlaws-v3-refactor | accepted | sprint 预占 (PR #174) |

### F.2 ADR-0009 引用 audit

CC 实测 (Grep "ADR-0009" / "ADR-009" 跨 docs/):
- IRONLAWS.md L270 / L271: "**ADR backref**: ADR-0009 datacontract-tablecontract-convergence" + "ADR-0009"
- IRONLAWS.md L776 §21 关联: "ADR-0009 (datacontract 收敛, 铁律 17 关联)"
- ADR-021 §4.4 关联: "ADR-0009 (datacontract-tablecontract-convergence): 铁律 17 关联"
- 其他 audit / research / mvp docs: 多处引用 (CC 实测真实数, 不假设)

**rename 风险**: ADR-0009 → ADR-009 影响:
- IRONLAWS.md (PR #174 锁): 改 ADR backref + §21
- ADR-021 (PR #174 锁): 改 §4.4
- 其他历史 audit docs (PR #172 / #173 锁的部分): 不动
- 其他历史 audit docs (未锁): 可同步更新

### F.3 ADR-010 双 ADR 处置候选

| 候选 | 描述 | 风险 | 决议建议 |
|---|---|---|---|
| (i) ADR-010a + ADR-010b | rename 一个为 010a, 另一个为 010b | 引用更新 (IRONLAWS.md / ADR-021 内文 / sprint memory) | ⚠️ 中 |
| (ii) ADR-009b (沿用 0009) | rename 一个为 010, 另一个为 009b (沿用 ADR-0009 历史漂移) | 引入新历史漂移 + 4 位数字混入 | ❌ 拒绝 |
| (iii) 维持现状 | 双 ADR-010, 文件名区分 (addendum-cb-feasibility / pms-deprecation) | 无 | ✅ 推荐 |

### F.4 ADR-015 ~ ADR-020 gap 处置

CC 实测: 6 项空缺, lazy assignment. 不预占 (sprint period 未来 ADR 时按需占用顺序编号).

**风险评估**: 0 (gap 不影响现有 ADR 引用).

### F.5 整改决议建议

| 项 | 决议 | 论据 |
|---|---|---|
| **ADR-0009 → ADR-009 rename** | ❌ **拒绝** | 历史决议保留 (sprint period 多文档引用 ADR-0009, rename = 引用漂移). 沿用 IRONLAWS.md / ADR-021 已用 ADR-0009 (PR #174 锁). |
| **ADR-010 双 ADR** | ✅ **维持现状** ((iii)) | 文件名区分已足够. 双 ADR 各自有独立 scope (addendum cb feasibility vs pms-deprecation), 重复编号是历史决议保留. |
| **ADR-015 ~ ADR-020 gap** | ✅ **lazy assignment 维持** | gap 不影响 ADR-021 + 后续 ADR 顺序占用. 0 风险. |
| **ADR backref 漂移防护** | ✅ **Step 6.2.5b 候选** | 加 IRONLAWS.md / ADR-021 注释段说明 "ADR-0009 4 位数字 + ADR-010 双 ADR 是历史决议保留, 不 rename". 防未来 sprint 重提 rename. |

---

## §7 主动发现 (Step 6.2.5a 副产品)

1. **Git 不支持 pre-merge hook** — IRONLAWS.md §18 X10 检测脚本候选写 "pre-merge hook" 是 prompt 假设错. Git native hooks: pre-commit / pre-push / commit-msg / 等. **沿用 LL "假设必实测" broader 33 → 34 候选** (本 PR audit 发现, 留 user 决议是否修订 IRONLAWS.md §18).
2. **真孤儿铁律 0 条** — 所有铁律 inline ref 已足够追溯, retroactive 补 LL = 编号膨胀 (反铁律 22 / X5 精神 — 文档跟随代码, 不文档过度).
3. **broader 33 三项实证不强烈推荐 LL 沉淀** — 沿用拆批原则, audit doc 引用足够.
4. **ADR 编号系统现状维持** — rename 风险 > 治理价值 (ADR-0009 / ADR-010 双 / 015-020 gap 均维持现状).
5. **canonical 铁律总数 = 45 (T1=31 / T2=14 / T3=0)** — 沿用 IRONLAWS.md §1 实测, 多个口径并存 (45 / 编号占用 45 / 历史决议 53 / banner 简略 46) 在不同语境合理.
6. **IRONLAWS.md §18 X10 检测脚本候选语义错** (prompt "pre-merge hook" 应为 "commit-msg / pre-push extension") — 沿用 #1 的 broader 实证. PR #174 锁, 不在本 PR 修, 留 Step 6.2.5b.

---

## §8 LL "假设必实测" 累计更新

| 口径 | PR #174 后 | 本 PR (Step 6.2.5a) 后 |
|---|---|---|
| narrower (LL 内文链 LL-091~) | 30 | **30** (本 PR 0 新 LL) |
| broader (PROJECT_FULL_AUDIT scope) | 33 | **34 候选** (本 PR §7 #1 "Git pre-merge 不支持" 实测 — 留 user 决议) |
| LL 总条目 | 92 | **92** (本 PR 0 新 LL) |

**broader 34 候选论据**: IRONLAWS.md §18 X10 检测脚本候选写 "pre-merge hook grep PR description / commit message" 是 prompt / CC 实施假设错 (Git 不支持 pre-merge). 实际应为 "commit-msg hook" 或 "pre-push extension". 这是 sprint period 第 6 个 (PR #172 §5 X1-X9 inline + 本 #1 等) 数字 / 假设错实证.

⚠️ **discrepancy 持续**: narrower 30 vs broader 34 候选, 差 4. 沿用 PR #173/#174 STATUS_REPORT 双口径并列 + audit doc 引用追溯 (主题 B B.5 决议).

---

## §9 Step 6.2.5b 候选 work item 清单 (基于本 audit 决议, 不实施)

⚠️ **本清单仅作 6.2.5b 启动时的候选 reference, 0 推荐启动. 等 user 显式触发 6.2.5b prompt.**

### 高价值候选 (建议优先)

1. **IRONLAWS.md §18 X10 检测脚本候选语义修订**: "pre-merge hook" → "commit-msg hook 或 pre-push extension" + 加关键词清单 (沿用 §1 主题 A A.4)
2. **commit-msg hook 或 pre-push extension 实施**: 扫 commit message + branch name 含 cutover-bias hard pattern (e.g. `/schedule agent` / `paper-mode 5d` / `auto cutover`), block + 写 reason 才能绕过 (沿用 LL-098 规则 1+2 + 铁律 X9/X10 stress test 软门转硬门)
3. **铁律 16 / 25 / 38 / 42 LL/ADR backref header 标准化**: inline LL 编号改为正式 "**LL backref:**" header (沿用 主题 D D.4 例外建议)

### 中价值候选

4. **IRONLAWS.md / ADR-021 加注释段**: 说明 ADR-0009 4 位数字 + ADR-010 双 ADR 是历史决议保留 (沿用 主题 F F.5)
5. **PROJECT_FULL_AUDIT §5 数字漂移注释**: PR #172 §5 "7 新 X1-X9 inline" 错为 "1 inline X9 + 4 候选 X1/X3/X4/X5 + 3 跳号 X2/X6/X7 + 1 撤销 X8" (PR #172 锁, 不改, 加 audit doc 引用即可)

### 低价值候选

6. ~~**Retroactive LL-099+ 沉淀 broader 33 三项实证**~~ — ❌ 主决议不沉淀 (沿用 主题 E E.3)
7. ~~**ADR-0009 → ADR-009 rename + ADR-010 双 ADR rename**~~ — ❌ 主决议拒绝 (沿用 主题 F F.5)

### Wave 5+ 远期候选

8. **Claude system prompt-level guard**: forward-progress 关键词检测 + 自动 strip / 二次 confirm. 依赖 Anthropic API custom system prompt (沿用 主题 A A.3)

---

## §10 不变

- Tier 0 债 11 项不变 (本 PR 不动)
- LESSONS_LEARNED.md 不变 (PR #173 锁, LL 总数 92, 0 新 LL)
- IRONLAWS.md 不变 (PR #174 锁)
- ADR-021 不变 (PR #174 锁)
- CLAUDE.md 不变 (PR #174 锁)
- PROJECT_FULL_AUDIT / SNAPSHOT 不变 (PR #172 锁)
- 其他 ADR 不变 (0 改, ADR-0009 / ADR-010 双 维持现状)
- 其他 docs 不变 (SYSTEM_RUNBOOK / SYSTEM_STATUS / DEV_*.md / MEMORY / 等)
- 0 业务代码 / 0 .env / 0 服务重启 / 0 DML / 0 真金风险 / 0 触 LIVE_TRADING_DISABLED
- 真账户 ground truth 沿用 4-30 14:54 实测 (0 持仓 + ¥993,520.16)
- PT 重启 gate 沿用 PR #171 7/7 PASS

---

## §11 关联

- **本 PR 文件**: docs/audit/STATUS_REPORT_2026_04_30_step6_2_5a.md (本文件, 新建)
- **关联 PR**: #170 (X9) → #171 (PT gate) → #172 (Step 5 SSOT) → #173 (Step 6.1 LL-098) → #174 (Step 6.2 IRONLAWS+ADR-021) → 本 PR (Step 6.2.5a audit)
- **关联 LL**: LL-097 (X9) / LL-098 (X10) / LL-001 series ~ LL-098
- **关联 ADR**: ADR-021 (PR #174) / ADR-0009 (铁律 17) / ADR-008 (铁律 38)
- **关联铁律**: 铁律 22 (文档跟随代码) / X4 (死码月度 audit) / X5 (文档单源化) / X9 (schedule restart) / X10 (cutover-bias detection, 本 PR 第 6 次 stress test)

---

## §12 LL-059 9 步闭环不适用 — 沿用 PR #172/#173/#174 LOW 模式

本 PR 是纯 audit 决议 (0 业务代码 / 0 改任何已存在文件 / 无 smoke 影响), 跳 reviewer + AI self-merge.

LL-098 stress test 第 6 次 verify (沿用 LL-098 规则 1+2):
- PR description / 本 STATUS_REPORT / 任何末尾 0 写前推 offer
- 不 offer "Step 6.2.5b 启动" / "Step 6.3 启动" / "Step 7" / "paper-mode" / "cutover"
- 等 user 显式触发
