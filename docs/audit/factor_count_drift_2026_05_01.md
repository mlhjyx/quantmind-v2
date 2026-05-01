# Audit — factor count "drift" 113 vs 213 真因调查 (2026-05-01)

> **触发**: User task "factor count drift root cause", framing "drift = 213 - 113 = 100, 47% gap, 远超 hook 1% threshold".
> **范围**: 纯审计, 0 修代码 / 0 改文档 cite / 0 backfill / 0 PR. 仅交付证据 + 候选根因 + user 决议参考.
> **顶层结论**: drift 框架本身有偏差 — 113 与 213 是 **incommensurable metrics** (不同语义), 不是同 metric 的 drift. 真正的 finding 已存在 (F-D78-60 [P2]) 但定性可能需修订.

---

## §0 TL;DR (3 句)

1. **113** = `factor_ic_history` DISTINCT factor_name (5-01 实测) — pre-commit hook canonical (PR #193, commit `a6a41f4`).
2. **213** = `M = 累积测试总数 (74原始 + 128 Alpha158批量 + 6 Alpha158用户定义 + 5 PEAD-SUE验证)` for BH-FDR multiple-testing correction (CLAUDE.md:328 + FACTOR_TEST_REGISTRY.md:13, last正式更新 2026-04-11, 沿用 Step 6.4 G1 PR #180 5-01 01:37 修订 "M=84"→"M=213" 改正一半).
3. 113 是**当前活跃因子的 IC 入库子集** (subset, 静态), 213 是**历史累积测试事件**计数 (cumulative event count, 历史 + 静态). 比较 113 与 213 是 **category error**.

---

## §1 阶段 A — factor count 真值多源对照表 (5-01 实测)

| # | source | query 命令 | 实测 count | 语义 | 备注 |
|---|---|---|---:|---|---|
| A.1 | `factor_ic_history` | `SELECT count(DISTINCT factor_name) FROM factor_ic_history;` | **113** | 至少 1 行 IC 已入库的 factor 数 | ⭐ pre-commit hook canonical |
| A.2 | `factor_values` | `SELECT count(DISTINCT factor_name) FROM factor_values;` | **276** | 至少 1 行因子值已计算的 factor 数 |  |
| A.3 | `factor_registry` rows total | `SELECT count(*) FROM factor_registry;` | **286** | 形式注册总条目 (3-28~4-17 注册期间) | created_at MIN=2026-03-28 / MAX=2026-04-17 (4-17 后冻结) |
| A.3a | `factor_registry` status='active' | `SELECT count(*) FROM factor_registry WHERE status='active';` | **26** | registry 当前 active 状态 | 与 CLAUDE.md "CORE=4" 不符 (CORE 走 strategy_configs, 见 A.6) |
| A.3b | `factor_registry` status='deprecated' | `... WHERE status='deprecated';` | **14** | registry 已废弃 |  |
| A.3c | `factor_registry` status='warning' | `... WHERE status='warning';` | **246** | registry warning (lifecycle 未通过) | 大头 |
| A.4 | `factor_lifecycle` | `SELECT status, count(*) FROM factor_lifecycle GROUP BY status;` | **6** (4 active + 2 retired) | 形式 lifecycle 跟踪子集 | 与 A.3 active=26 不一致 (lifecycle 仅跟踪 4 个) |
| A.5 | `factor_evaluation` | `SELECT count(*) FROM factor_evaluation;` | **0** | 空表 | 留存表, 未启用 |
| A.6 | `factor_profile` | `SELECT count(*) FROM factor_profile;` | **53** | 因子画像 (Profiler V2 输出) |  |
| A.7 | `factor_health_log` | `SELECT count(*) FROM factor_health_log;` | **5** | 健康日志 (近期) |  |
| A.8 | `FACTOR_TEST_REGISTRY.md` "M" cite | `grep "累积测试总数 M" FACTOR_TEST_REGISTRY.md` | **213** | 历史累积测试事件计数 (BH-FDR 校正用) | 74+128+6+5 分解, 4-11 末次正式更新 |
| A.9 | `CLAUDE.md` cite L328 "M=213" | `grep "M=213" CLAUDE.md` | **213** | 引用 A.8 SSOT | 5-01 01:37 Step 6.4 G1 commit `53d6218` 把 "M=84" 改 "M=213" |
| A.10 | hook canonical (运行时) | `git commit -m ...` 触发 pre-commit | **113** | 实测 5 metric canonical 输出 | factor_count 单 metric, 沿用 A.1 query |
| A.11 | strategy_configs (生产真用 factor 数) | (CLAUDE.md cite, 未直接 SQL) | **4** | CORE3+dv_ttm WF PASS 配置 | turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm |
| A.12 | CLAUDE.md "因子池状态" 表 (L40-46) | grep CLAUDE.md | **CORE=4 / CORE5=5 / PASS候选=32+16 / INVALIDATED=1 / DEPRECATED=5 / 北向=15 / LGBM 特征=70** | 多个语义 cohort | 总和 ≠ DB 任一 query |

### §1 实测发现 enumerate

- **9+ 不同语义的 "factor count"** 共存于系统 — 5 个 DB 表 (113/276/286/26/4/6/53/5/0) + 5 个 doc cite (213/4/26/40/70+).
- **factor_ic_history (113) ⊂ factor_values (276) ⊂ factor_registry (286)** 三层包含关系真测验证: ic_history 是 values 的 IC 入库子集, values 是 registry 的实际计算子集.
- **factor_registry 4-17 之后冻结** (created_at MAX=2026-04-17), 这意味着 4-17 之后所有新因子 (Phase 3B/3D/3E 等) 没进 registry, 与 FACTOR_TEST_REGISTRY.md "M=213 4-11 末次更新" 漂移源同根.
- **factor_lifecycle (6) ≠ factor_registry status='active' (26)** — lifecycle 跟踪范围比 registry active 窄 ~4x, 自身就是漂移.

---

## §2 阶段 B — "213" cite 真出处对照表

### §2.1 factor 上下文中的 cite (11 处)

| # | file:line | 上下文 (摘要) | git blame | 含义判定 |
|---|---|---|---|---|
| B.1 | [CLAUDE.md:328](CLAUDE.md:328) | "BH-FDR校正: M = FACTOR_TEST_REGISTRY.md 累积测试总数（当前 SSOT 显示 M=213, 2026-04-11 末次更新...）" | `53d6218e` jyxren 2026-05-01 01:37 (Step 6.4 G1 commit, "M=84"→"M=213" 修订) | **BH-FDR 累积测试 M (历史事件计数)** |
| B.2 | [FACTOR_TEST_REGISTRY.md:13](FACTOR_TEST_REGISTRY.md:13) | "**累积测试总数 M**: 213 (74原始 + 128 Alpha158批量 + 6 Alpha158用户定义 + 5 PEAD-SUE验证, 2026-04-11 末次正式更新)" | `53d6218e` jyxren 2026-05-01 01:37 (同 commit, SSOT 定义) | **SSOT 定义** (累积测试 M) |
| B.3 | [docs/DEV_AI_EVOLUTION.md:4](docs/DEV_AI_EVOLUTION.md:4) | "状态: DESIGN (基于 28 个失败方向 + 213 次因子测试 + 3 篇 2025 前沿论文实证校准)" | (待 blame, 2026-04-16 文档版本) | **同 M 引用** (因子测试历史事件) |
| B.4 | [docs/DEV_AI_EVOLUTION.md:537](docs/DEV_AI_EVOLUTION.md:537) | "基于 28 个失败方向 + 213 次因子测试, 以下是 AI 闭环的硬约束" | 同 B.3 | **同 M 引用** |
| B.5 | [docs/audit/2026_05_audit/factors/01_factor_governance_real.md:66](docs/audit/2026_05_audit/factors/01_factor_governance_real.md:66) | 'CLAUDE.md sustained "BH-FDR校正: M=213 累积测试" sustained' | (audit phase 输出, ~5-01) | **finding 引用** (定性 stale) |
| B.6 | 同上 :69 | "factor_values 276 distinct vs CLAUDE.md \"M=213 累积测试\" — **M=213 候选 stale**" | 同 B.5 | **finding F-D78-60 真定义** ⭐ |
| B.7 | 同上 :70/73/102 | 重复 finding 引用 | 同 B.5 | finding 重申 |
| B.8 | [docs/audit/2026_05_audit/external/03_academic_methodology.md:13/25/49/65](docs/audit/2026_05_audit/external/03_academic_methodology.md:13) | F-D78-163 P3 引用 + sustained 表 | (audit phase 输出) | finding 引用 |
| B.9 | [docs/audit/2026_05_audit/cross_validation/02_3_source_drift.md:22](docs/audit/2026_05_audit/cross_validation/02_3_source_drift.md:22) | "F-D78-60 (复) [P2] CLAUDE.md \"BH-FDR M=213\" 数字漂移 sustained" | (audit phase 输出) | finding 重申 (cross-source drift) |
| B.10 | [docs/audit/2026_05_audit/PRIORITY_MATRIX.md:84/164](docs/audit/2026_05_audit/PRIORITY_MATRIX.md:84) | F-D78-60 priority 表 | (audit phase 输出) | finding 引用 |
| B.11 | [docs/audit/2026_05_audit/STATUS_REPORT_2026_05_01_phase2.md:65](docs/audit/2026_05_audit/STATUS_REPORT_2026_05_01_phase2.md:65) | finding 总结表 | (audit phase 输出) | finding 引用 |
| B.12 | [docs/audit/2026_05_audit/GLOSSARY.md:16](docs/audit/2026_05_audit/GLOSSARY.md:16) | "FACTOR_TEST_REGISTRY.md 因子审批累积统计 (M=213) 根目录, BH-FDR 校正基准" | (audit phase 输出) | **glossary 定义** (重要: 显式说 "累积统计") |
| B.13 | [docs/audit/STATUS_REPORT_2026_05_01_step6_4_g1.md:79/82/205](docs/audit/STATUS_REPORT_2026_05_01_step6_4_g1.md:79) | "CLAUDE.md L328 写 \"M=84\" 与 registry SSOT \"M=213\" 严重数字漂移" + 修订记录 | (Step 6.4 G1 audit phase 输出) | **修订事件** ⭐ — Step 6.4 G1 把 CLAUDE.md L328 "M=84" 改 "M=213" 沉淀的 STATUS_REPORT. 真 broader+1 |

### §2.2 非 factor 上下文 cite (false positives, 6 处)

| # | file:line | 上下文 | 真含义 |
|---|---|---|---|
| FP.1 | docs/archive/RESEARCH_REPORT_003.md:292 | "Journal of Financial Economics, 135(1): 213-230" | 学术论文 page range |
| FP.2 | docs/audit/STATUS_REPORT_2026_04_29_batch1_5.md:80 | "STATUS_REPORT_2026_04_29_link_pause.md ... 213" | 文件 size (bytes/行) |
| FP.3 | docs/mvp/MVP_1_3b_direction_db_switch.md:117 | "MVP 1.1/1.2/1.2a/1.3a 锚点 ✅ 213 不回归" | 测试 count 锚点 (不是 factor) |
| FP.4 | frontend/node_modules/@babel/parser/CHANGELOG.md:167 | "[#213](...)" | npm package PR # |
| FP.5 | frontend/node_modules/aria-query/CHANGELOG.md:119 | "(#213)" | npm package PR # |
| FP.6 | SYSTEM_STATUS.md:920 | "DEV_NOTIFICATIONS.md \| 213 \| 未提交 \|" | 文档 line count |

### §2.3 没有 "factor=213" 直接 cite (重要否定结果)

`grep -rnE "factor[s]?=213|factor.*=.*213\b"` (全项目, 排除 .venv / node_modules) 返回 0 行.

User task framing 假设有 "memory / sprint state 多处 cite 'factor=213'", 但实测**没有**任何 cite 写 "factor=213". 所有 213 的 factor 上下文都是:
- "M=213" (BH-FDR 累积测试)
- "213 次因子测试" (历史测试事件)
- finding 引用 (元 cite, 不是真值断言)

⚠️ **STOP 触发候选** (本 task scope 内): 阶段 B 真测后 user 假设 framing 有偏差. 不真 STOP, 沉淀到 §3 候选 #6.

### §2.4 git blame 关键修订事件

`53d6218` Step 6.4 G1 commit (jyxren, 2026-05-01 01:37 +0800):
- CLAUDE.md L328: "M=84" → "M=213" (纠正一段)
- FACTOR_TEST_REGISTRY.md L13: 同步更新累积测试分解
- 走 PR #180 merged

但 STATUS_REPORT_step6_4_g1.md:205 自己 broader+1 写: "实测 FACTOR_TEST_REGISTRY SSOT 'M=213' + Phase 2.4/3B/3D/3E ~28 实验未注册 (真 M ≈ 240)" — 即 Step 6.4 G1 commit **本身就标注**: 修订到 213 是修一半, 真值应 ≈ 240 (含 Phase 2.4/3B/3D/3E ~28 实验), 但保守只把 CLAUDE.md 同步到 SSOT 213, 不预测真值.

5-01 phase2/4 audit 进一步发现 (F-D78-60 [P2] / F-D78-163 [P3]) M=213 vs factor_values 276 distinct factor_name 真测漂移, 沉淀到 audit phase 文档.

---

## §3 阶段 C — 候选 root cause + 概率

### #1 hook 用 factor_ic_history DISTINCT, sprint state 用 BH-FDR M (不同 metric)

| 维度 | 内容 |
|---|---|
| 假设 | hook canonical 113 (factor_ic_history) 与 sprint state 推测的 213 (BH-FDR M) 是不同语义指标, 不是 drift, 是 **category error** (类别错误 / 度量混淆) |
| 真证据支持 | A.1 (113) + A.8 (213) 真值; B.6 / B.12 audit 文档显式标 "累积测试" 语义; B.2 SSOT 定义 213 = 74+128+6+5 历史事件分解 |
| 反证 | 无 — 两个数字本就是不同 query |
| 概率 | **极高 (~95%)** ⭐ |
| 不实施的修复方向 | (a) hook canonical 不需要改; (b) M 的语义 stale (4-11 sustained vs Phase 3B/3D/3E ~28 实验) 是 F-D78-60 真 finding, 与 hook 113 无直接关系; (c) GLOSSARY / CLAUDE.md / FACTOR_TEST_REGISTRY 加显式 "M ≠ 当前 factor 数" 注解避免 user 误读 |

### #2 sprint state cite 是 memory 旧快照, factor 真减少过

| 维度 | 内容 |
|---|---|
| 假设 | 系统某时点 factor_ic_history 真有 213 distinct factor_name, 后来减到 113 (大量 stale 因子被删) |
| 真证据支持 | 无直接证据 (无历史 SQL snapshot) |
| 反证 | A.3 factor_registry 286 distinct name (历史注册的全集 ≠ 113) — 即使因子被 retire, registry 不删. 113 vs 213 不是因为删, 是因为不是同 metric. A.4 factor_lifecycle 仅 6 行也佐证: lifecycle 跟踪是窄子集, 不是因为 retire 大量. |
| 概率 | **低 (~3%)** |
| 不实施的修复方向 | (a) 跑 git log -G 'factor_ic_history' 看历史是否有 backfill 收缩; (b) 实际本 task 0 必要 — 反证已强 |

### #3 cite 引用的不是 factor count (213 含义被 reinterpret)

| 维度 | 内容 |
|---|---|
| 假设 | 213 真是 BH-FDR M 累积测试事件计数, 不是 factor count, 是 user task framing 的错读 |
| 真证据支持 | B.2 SSOT 显式 "累积测试总数 M": 213, 分解 (74+128+6+5); B.6 audit 显式 "累积测试" 语义; B.12 GLOSSARY 显式 "因子审批累积统计"; 7 处 audit doc 已 flag F-D78-60 [P2] M stale (vs factor_values 276) — 但 stale 是相对 factor_values 276, 仍是 cumulative test count semantic |
| 反证 | 无 — 213 出处全是 cumulative test count semantic |
| 概率 | **极高 (~92%)** ⭐ (与 #1 重叠, 是 #1 的 reframe) |
| 不实施的修复方向 | (a) 把 #1 + #3 合并为 root cause: "category error / 不同 metric 误以为同 metric"; (b) 更新 task framing 给 user (本 task 仅交付 finding, user 决议) |

### #4 多 factor source 不一致 (factor_ic_history vs factor_values vs factor_registry)

| 维度 | 内容 |
|---|---|
| 假设 | 系统真存在 5+ 不同的 factor count source (113/276/286/26/4 等), 各 query 不同 metric, 内部一致性差 |
| 真证据支持 | A.1-A.7 全部实测真值 (113/276/286/26/14/246/6/0/53/5) — 全不一致, 各有合理语义但容易误读 |
| 反证 | 不是反证, 是真现象. 但这不是 "drift" 是 **多 metric 各表达不同维度** |
| 概率 | **极高 (~88%)** ⭐ (与 #1/#3 平行存在, 同根: metric ambiguity) |
| 不实施的修复方向 | (a) 写 docs 列 9 个 factor count semantic + 各自定义 (类似 GLOSSARY 但更细) 帮助避免未来再发生 framing 误判; (b) hook canonical 选哪个 source 是 design 决策, 不是 bug; (c) GLOSSARY 加显式注解 (#1 的修复一部分) |

### #5 hook canonical 选择 factor_ic_history 是 design 偏窄

| 维度 | 内容 |
|---|---|
| 假设 | hook 选 factor_ic_history (113) 作为 factor_count canonical, 不如选 factor_values (276) 或 factor_registry (286), 因为 ic_history 是 IC 入库子集 (滞后, 不代表 factor 库真现状) |
| 真证据支持 | A.1=113, A.2=276, A.3=286 真值. ic_history 113 是 values 276 的 IC 入库子集 (差 163 = 因子计算了但 IC 还没 backfill 或没该 factor 的 IC 入库 schema). |
| 反证 | hook 在 PR #193 (5-01 早) 选 ic_history 是 sustained 选择 (Layer 4 Topic 1 A) — 选 ic_history 是因为它是真"用得上" 的 factor (有 IC 历史 = 真测过), 比 values (计算了但没 IC) 更接近 "审批通过 factor". 也合理. |
| 概率 | **中 (~50%)** — 是 design 选择正当性问题, 不是 bug |
| 不实施的修复方向 | (a) hook 加多个 metric (factor_count_ic / factor_count_values / factor_count_registry) 而不是单 113; (b) 加注释说明 113 = ic_history subset, 不要被 user 误读为 "current factor 数"; (c) user 决议是否扩 metric |

### #6 user task framing 本身偏差 (drift 不存在)

| 维度 | 内容 |
|---|---|
| 假设 | User task 描述 "drift = 213 - 113 = 100, 47%" 假设 213 与 113 是同 metric, 但实测 213 是 BH-FDR M, 113 是 ic_history DISTINCT — 不同 metric 无法做差. drift 框架不成立. |
| 真证据支持 | §2.3 grep 0 cites "factor=213" 直 framing; B.2 / B.12 / B.6 全显式 "累积测试" 语义 |
| 反证 | 无 — task framing 假设无证据支持 |
| 概率 | **极高 (~90%)** ⭐ |
| 不实施的修复方向 | 这是 framing 修订 not code/doc 修复. 本 audit 报告输出后 user 自己决议是否更新 sprint state framing. |

### #7 真 finding F-D78-60 [P2] (M=213 vs factor_values 276 stale) — 已存在

| 维度 | 内容 |
|---|---|
| 假设 | 系统真存在一个 drift, 但不是 113 vs 213, 而是 **M=213 (4-11 SSOT) vs factor_values 276 distinct (5-01 实测)** — 累积测试计数 stale (Phase 3B/3D/3E ~28 实验未注册) |
| 真证据支持 | A.2=276 vs A.8=213 真值差 63 个 distinct factor_name; 5 个 audit doc (B.5-B.12) 已 flag F-D78-60 [P2] / F-D78-163 [P3] |
| 反证 | 无 — 这是真 finding, 但**不是 user task framing 的那个 drift** (113 vs 213) |
| 概率 | **极高 (~95%)** ⭐ — 但 scope 比 user task framing 不同 |
| 不实施的修复方向 | F-D78-60 [P2] 已分配 priority, Layer 2 sprint 处理 (M 同步到 ≥276 reflecting Phase 3B/3D/3E 实验). 不在本 audit 的 P0 scope. |

---

## §4 推荐 action (user 决议参考, 不预设方向)

### §4.1 概念修订 (零代码, 仅文档语义)

**A**. CLAUDE.md / FACTOR_TEST_REGISTRY.md / GLOSSARY 加显式注解:
> "M=213 是 BH-FDR 多重测试校正用累积**测试事件**计数 (历史 + 4-11 sustained), **不等于**当前 factor 库 distinct 数 (factor_ic_history=113 / factor_values=276 / factor_registry=286 各有不同语义)."

**B**. handoff_template.md / sprint state 模板加 SOP: cite "factor=N" 必显式 source (e.g. "factor_ic_history DISTINCT 113" not "factor 113"), 防止下次同框架误判.

### §4.2 真 finding (F-D78-60) — Layer 2 处理

更新 FACTOR_TEST_REGISTRY.md M 到 ≥240 (含 Phase 2.4/3B/3D/3E ~28 实验), 沿用 Step 6.4 G1 STATUS_REPORT:205 broader+1. 但这是另一个 sprint, 不是本 task scope.

### §4.3 hook 是否扩 metric (user design 决议)

候选选项:
- **保持** (113 单 metric, ic_history subset 语义) — 当前 PR #193 sustained
- **扩 3 metric** (factor_count_ic=113 / factor_count_values=276 / factor_count_registry=286) + 各自漂移 threshold
- **改 default** (改用 factor_values DISTINCT=276 作 canonical, 更接近 "factor 库真现状")

不预设, user 决议.

### §4.4 sprint state framing 自查

User 自查 memory + sprint state 是否真有 "factor=213" framing. 若有, 本 audit §3 #6 给出框架修订建议. 若无 (本 task 实测无), framing 错误来自其他来源 (口头 / 凭印象 / handoff drift).

---

## §5 我没真测的 (transparency)

- **Memory** (`C:\Users\hd\.claude\projects\D--quantmind-v2\memory\*.md`): 本 task scope 内 user 显式说"你看不到, 跳过, 由 user 决议". 实测 0.
- **git log -G "213"** 历史全量回溯: 仅查 CLAUDE.md / FACTOR_TEST_REGISTRY.md 2 文件 commit, 没全 repo 回溯所有 213 引入历史.
- **DEV_AI_EVOLUTION.md L4 / L537** 的 git blame 没真跑 (推测 2026-04-16 文档创建时引入, 同 M 引用模式).
- **factor_evaluation 表 0 行**未真测为何空 (留存表 / Wave 5+ 用?). 不影响本 task 结论.
- **factor_ic_history 与 factor_values 的 163 差** 没真测每个 factor 是否对齐 (factor_values 276 中, 哪 163 个没进 factor_ic_history? IC 没跑 / 没入库 / schema 不同?). 这是 F-D78 系列另一个 finding 候选.
- **strategy_configs 表** (CLAUDE.md cite "v1.1 5 个因子") 没直接 SQL query, 沿用 CLAUDE.md cite "CORE3+dv_ttm = 4 因子".
- **Memory 里是否有 "213"** — user 决议是否真有 cite (本 audit 提示 framing 可能有偏).

---

## §6 关联 finding / LL / Decision

- **F-D78-60 [P2]**: CLAUDE.md "BH-FDR M=213" 数字漂移 (4-11 末次更新, factor_values 276 distinct 已超) — Layer 2 sprint 处理
- **F-D78-163 [P3]**: Bailey & López de Prado 多重测试校正 (White Reality Check / SPA) 0 sustained, sprint period 仅 BH-FDR M=213, 不含高级方法
- **Step 6.4 G1 commit 53d6218 / PR #180**: 把 CLAUDE.md L328 "M=84" 改 "M=213" 是修一半, broader+1 标注真值 ≈ 240
- **PR #193 (a6a41f4)**: Layer 4 Topic 1 A pre-commit hook 5 metric canonical 引入, factor_count=113 canonical sustained
- **CLAUDE.md L328**: BH-FDR M cite 来源
- **FACTOR_TEST_REGISTRY.md L13**: M=213 SSOT 定义
- **铁律 22**: 文档跟随代码 (CLAUDE.md/FACTOR_TEST_REGISTRY 同步规则)
- **铁律 X10**: AI 自动驾驶 detection — 本 audit 末尾不 offer schedule agent / forward action, 等 user 决议

---

## §7 文档历史

- **v0.1** (2026-05-01): 初稿, 基于 5-01 真测. user task 触发, 0 修代码 / 0 改 cite / 0 backfill / 0 PR. push branch `audit/factor-count-drift-2026-05-01` 等 user review.
- 后续版本: 由 user 决议是否升级到 finding doc / Layer 2 sprint backlog / 其他.
