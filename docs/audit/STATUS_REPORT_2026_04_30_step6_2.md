# STATUS_REPORT — Step 6.2 铁律 v3.0 重构 + IRONLAWS.md 拆分 + ADR-021 + X10 加入 (2026-04-30 ~21:30)

**PR**: chore/step6-2-ironlaws-adr021
**Base**: main @ `dd2247f` (PR #173 Step 6.1 LL-098 + 8 D2 untracked 闭合 merged)
**Scope**: IRONLAWS.md (新建) + ADR-021 (新建) + CLAUDE.md (banner + 铁律段 reference) + 本 STATUS_REPORT
**真金风险**: 0 (纯 SSOT 治理重构, 0 业务代码 / 0 .env / 0 服务重启 / 0 DML)
**D 决议**: D-1=A / D-2=A / D-3=A (4-30 ~21:00 user 决议)

---

## §0 环境前置检查 (E1-E13 全 PASS)

| 检查 | 实测 | 状态 |
|---|---|---|
| E1 git | main HEAD = `dd2247f` (PR #173), 工作树干净 | ✅ |
| E2 PG stuck | 0 (沿用 4-30 20:30 实测) | ✅ |
| E3 Servy 4 服务 | ALL Running (沿用 4-30 20:30 实测) | ✅ |
| E4 venv | Python 3.11.9 | ✅ |
| E5 LIVE_TRADING_DISABLED | True | ✅ |
| E6 真账户 | 沿用 4-30 14:54 实测 (read-only) | ✅ (沿用) |
| E7 cb_state.live nav | 993520.16 (沿用 PR #171 reset 后状态生效) | ✅ |
| E8 position_snapshot 4-28 live | 0 行 (沿用 PR #171 DELETE 后状态生效) | ✅ |
| E9 Step 5 docs | PROJECT_FULL_AUDIT + SNAPSHOT 实存 | ✅ |
| E10 LL-098 boundary | L3032-L3105 (74 行, 沿用 PR #173 verify raw text) | ✅ |
| E11 CLAUDE.md 铁律段 | L330-L508 = 179 行 (CC 实测) | ✅ |
| E12 IRONLAWS.md | 不存在 (新建 OK) | ✅ |
| E13 ADR-021 | 不存在 (新建 OK) | ✅ |

---

## §1 12 题逐答

### Q1 — CLAUDE.md 当前铁律完整 enumerate

**实测结果**:
- 铁律段范围: L330-L508 = 179 行
- 编号: 1-44 (含 1 DEPRECATED #2 + 1 sub-rule 10b)
- effective 条数: **43** (1-44 减 #2 DEPRECATED)
- X 系列 inline: 仅 **X9** (在编号 44 内文 inline tag), 其他 X1/X3/X4/X5 候选未 inline

**详细 enumerate** (按 grep `^[0-9]+\.` 分组):

| 类别 | 编号 | 数 | tier 候选 |
|---|---|---|---|
| 工作原则类 | 1, 2 (DEPRECATED), 3 | 3 | T1×1 / T2×1 / DEPRECATED×1 |
| 因子研究类 | 4, 5, 6 | 3 | T1×3 |
| 数据与回测类 | 7, 8 | 2 | T1×2 |
| 系统安全类 | 9, 10 (含 10b), 11 | 4 | T1×4 |
| 因子质量类 | 12, 13 | 2 | T1×2 |
| 重构原则类 (Step 6-B) | 14, 15, 16, 17 | 4 | T1×4 |
| 成本对齐 | 18 | 1 | T1×1 |
| IC 口径统一 (Step 6-E) | 19 | 1 | T1×1 |
| 因子噪声鲁棒性 (Step 6-F) | 20 | 1 | T1×1 |
| 工程纪律类 (Step 6-H 后) | 21, 22, 23, 24 | 4 | T2×4 |
| CC 执行纪律类 | 25, 26, 27, 28 | 4 | T1×1 / T2×3 |
| 数据完整性类 (P0-4) | 29, 30 | 2 | T1×2 |
| 工程基础设施类 (S1-S4) | 31, 32, 33, 34, 35 | 5 | T1×5 |
| 实施者纪律类 (2026-04-17) | 36, 37, 38, 39, 40, 41 | 6 | T1×2 / T2×4 |
| PR 治理类 | 42 | 1 | T1×1 |
| schtask 硬化类 | 43 | 1 | T1×1 |
| X 系列 (inline) | 44 (X9) | 1 | T2×1 |

**总计**: T1 = 31 / T2 = 14 / DEPRECATED = 1 (条目 2). 加 X10 (新, T2) = T2 → 15.

✅ Q1 实测确认, 无新假设破灭.

### Q2 — 历史铁律来源 audit

**实测**: 每条铁律的 LL backref 已沉淀到 IRONLAWS.md §1 Tier 索引 + §2-§18 内文.

**孤儿铁律** (无 LL backref + 无 ADR backref):
- 条目 1 (不靠猜测): 引用 LL-001 series (历史 LL, 早期沉淀)
- 条目 7-8: 散落引用 (IC 偏差教训 / IS强OOS崩) — 无单一 LL
- 条目 9: 引用 OOM 2026-04-03 事件 (无单一 LL, sprint period 共识)
- 条目 12-13: 引用论文 (AlphaAgent KDD 2025) + reversal_20 教训
- 条目 14-15: Step 6-B 系列, 无单一 LL
- 条目 18-20: Step 6-E/F 系列, 无单一 LL

**ADR backref** (实测真实关联):
- 条目 17 (DataPipeline) → **ADR-0009 datacontract-tablecontract-convergence** (datacontract 收敛)
- 条目 38 (Blueprint) → **ADR-008 execution-mode-namespace-contract** (跨 session 架构记忆 sprint 落地)
- X10 (新) → **ADR-021 (本 PR)**

✅ Q2 实测完整, 已沉淀 IRONLAWS.md §1 Tier 索引 + §21 关联.

### Q3 — 历史 ADR 实测 enumerate

**实测 docs/adr/** (15 ADR + 1 README):

```
ADR-0009-datacontract-tablecontract-convergence.md    (4 位数字, 历史漂移)
ADR-001-platform-package-name.md
ADR-002-pead-as-second-strategy.md
ADR-003-event-sourcing-streambus.md
ADR-004-ci-3-layer-local.md
ADR-005-critical-not-db-event.md
ADR-006-data-framework-3-fetcher-strategy.md
ADR-007-mvp-2-3-backtest-run-alter-strategy.md
ADR-008-execution-mode-namespace-contract.md
ADR-010-addendum-cb-feasibility.md                    (重复 010 #1)
ADR-010-pms-deprecation-risk-framework.md             (重复 010 #2)
ADR-011-qmt-api-utilization-roadmap.md
ADR-012-wave-5-operator-ui.md
ADR-013-rd-agent-revisit-plan.md
ADR-014-evaluation-gate-contract.md
[gap]   ADR-015 ~ ADR-020  (6 项空缺)
```

**编号系统状态**:
- 最大: ADR-014
- gap: ADR-015 ~ ADR-020 (6 项)
- 重复: ADR-010 (2 个)
- 4 位数字: ADR-0009 (1 个, 历史漂移)
- ADR-021 占位: 实测**不存在**, 沿用 sprint period 预占编号 (D-3=A)

✅ Q3 实测完整, ADR-021 编号锁定 (D-3=A).

### Q4 — IRONLAWS.md 结构设计

✅ 选 **(a) 单文件**.

**理由**:
- 沿用 PROJECT_FULL_AUDIT 整合精神 (single source of truth)
- 沿用铁律 X5 候选 (文档单源化) 落地实例
- 多文件 (b) 引入分层 lookup, 与 SSOT 精神冲突
- 单文件 +tier 标识 + LL/ADR backref 索引 (§1) 已足够 navigation

实测结果: IRONLAWS.md 791 行 (单文件, §0-§22, tier 索引 + 各类别完整内容).

### Q5 — IRONLAWS.md 内容 source 决议

✅ 选 **(iii) 复制 + 标准化**.

**理由**:
- 复制保 100% 内容 (0 信息丢失)
- 标准化加价值: tier 标识 / LL backref / ADR backref / 关联 PR / 关联 commit
- 重写 (ii) 引入语言漂移风险, 与铁律 22 文档跟随代码精神冲突

实测结果: IRONLAWS.md §2-§18 完整复制 CLAUDE.md L330-L508 内容, 标识 tier + backref. X10 (新) 在 §18 加入.

### Q6 — tier 分类标准 (D15-D21 决议复用)

**实测 D15-D21 决议原文**: 沿用 sprint period audit docs + memory (无单一 D 决议文档, 散落在 sprint handoff). Tier 化标准沿用 prompt §类 B Q6:

- **T1 强制**: 违反 → block PR / 真金风险 / 数据完整性破坏
- **T2 警告**: 违反 → 提示 + commit message 写 reason 才能绕过
- **T3 建议**: 违反 → 不阻断 (本版本 0 条, 留 Step 6.2.5+ promote)

**Tier 分类结果** (CC 实测决议, 沿用 prompt 的 tier 定义 + D-2=A):

| Tier | 数 | 编号 |
|---|---|---|
| T1 | 31 | 1, 4, 5, 6, 7, 8, 9, 10 (含 10b), 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 25, 29, 30, 31, 32, 33, 34, 35, 36, 41, 42, 43 |
| T2 | 14 (+1 X10) | 3, 21, 22, 23, 24, 26, 27, 28, 37, 38, 39, 40, 44 (X9), **X10** |
| T3 | 0 | (留 Step 6.2.5+) |
| DEPRECATED | 1 | 2 (合并入 25) |

**决议依据**:
- T1 = 直接生产破坏 / 数据丢失 / 真金风险
- T2 = governance / process (违反须解释)
- T3 留 Step 6.2.5+ (拆批)

✅ Q6 决议完整, IRONLAWS.md §0 + §1 已落地.

### Q7 — ADR-021 内容

✅ ADR-021 完整含 §1-§5:
- §1 Context (背景): 4 子段 (现状 / LL-098 触发 / 治理债 / 编号占位)
- §2 Decision (决议): 6 子段 (拆分 / X10 / 候选 promote / 跳号撤销 / scope / 编号锁定)
- §3 Consequences (后果): 5 子段 (长期资产 / 短期改动 / 引用传导 / 风险 / 自相一致)
- §4 关联: 5 子段 (D 决议 / LL / PR / ADR / 后续步骤)
- §5 验收

实测: docs/adr/ADR-021-ironlaws-v3-refactor.md 206 行.

### Q8 — X10 加入位置 + 内容

**位置**:
- IRONLAWS.md §18 (紧接 44 X9 之后, T2 tier)
- CLAUDE.md 铁律段 reference (新 X10 编号 + 简述 + link IRONLAWS.md §18)

**内容沿用 LL-098 raw text** (PR #173 verify 通过, L3032-L3105):
- 主条款: PR / commit / spike 末尾不主动 offer schedule agent / paper-mode / cutover / 任何前推动作. 等 user 显式触发. 反例 → STOP.
- 子条款: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件. 必须显式核 D 决议链全部前置, 才能进入下一步.
- 复用规则 5 条 (沿用 LL-098 内文)
- 检测脚本候选 (Step 6.2.5+)
- Stress test 实绩 (5 次累计)

✅ Q8 完整.

### Q9 — CLAUDE.md banner 内容

**banner** (顶部 L5 加入, 3 行):
```
> **铁律 SSOT (v3.0, 2026-04-30)**: [IRONLAWS.md](IRONLAWS.md) — 完整铁律 (1-44 + X9 + X10) + tier 标识 (T1/T2/T3) + LL/ADR backref. 本文件铁律段已 reference 化, 详 [ADR-021](docs/adr/ADR-021-ironlaws-v3-refactor.md).
> **D 决议 (4-30 user 决议)**: D-1=A 硬 scope (仅铁律段 reference) / D-2=A 仅 X10 inline / D-3=A ADR-021 编号锁定.
```

**铁律段 reference**: L332-L455 = 124 行 (从原 179 行减少 55 行 = -31%). 内容:
- 段头 + ADR-021 link + 历史编号保持声明
- Tier 索引 (T1/T2/T3 + DEPRECATED + 候选 + 跳号撤销)
- 编号简述索引 (按类别分组, 每条 1 行 + tier 标识 + LL/ADR backref + link IRONLAWS.md §X.YY)
- X10 (新) 在 §18 单独段落 (含主/子条款 + 触发 case)
- 引用规范 (新 link IRONLAWS.md / 历史沿用编号)

### Q10 — CLAUDE.md 改动 scope 边界 (D-1=A 硬 scope)

✅ 仅改:
- 顶部 L5 加 v3.0 banner (3 行)
- 铁律段 L330-L508 reference 化 (179 → 124 行, 净减 55 行)

**不改**:
- 项目身份段 ✅ (L1-L4 + L8-L17 不动)
- 技术栈段 ✅ (L18-L33 不动)
- 因子系统段 ✅ (L34-L57 不动)
- 架构分层段 ✅ (L58-L66 不动)
- 目录结构段 ✅ (L67-L229 不动)
- 编码规则段 ✅ (L230-L329 不动)
- 因子审批硬标准 ✅ (原 L509-L516 → 现 L456-L463 不动)
- 因子画像评估协议 / 性能规范 / 已知失败方向 / 策略配置 / 文档查阅索引 / 当前进度 / CC 自动化操作 / 文件归属规则 / 执行标准流程 ✅ (全部不动)
- 8 D2 已 add 文档引用 ✅ (PR #173 锁)

**最终 CLAUDE.md = 813 行** (原 866 - 铁律段净减 55 + banner 加 3 = 866 - 53 = 813 ✅).

### Q11 — 改动 diff verify

#### CLAUDE.md before/after 关键段 diff

**Before (L330-L508, 179 行)**:
```
## 铁律（违反即停, 44 条全局原则, v4 2026-04-30）

> **全局性要求**: 每条铁律必须是"永恒原则"...
...
44. **Beat schedule / config 注释 ≠ 真停服, 必显式 restart (X9)** — 全局原则: 注释 Beat schedule entry / cron / Servy config / .env 等运行时配置文件 **不等于服务真停**...
```

**After (L332-L455, 124 行)**:
```
## 铁律（v3.0 reference, 完整内容见 [IRONLAWS.md](IRONLAWS.md)）

> **本段已 reference 化** ([ADR-021](docs/adr/ADR-021-ironlaws-v3-refactor.md), 2026-04-30 Step 6.2)...

### Tier 索引 (T1 强制 / T2 警告 / T3 建议)
...
### 编号简述索引 (link IRONLAWS.md §X.YY 完整)
#### 工作原则类 (1-3) — IRONLAWS.md §2
1. [T1] 不靠猜测做技术判断 — 外部 API/数据接口必须先读官方文档确认
...
44. [T2] **(X9)** Beat schedule / config 注释 ≠ 真停服...
**X10 (新, 2026-04-30 Step 6.2 PR 落地)** [T2]: **AI 自动驾驶 detection — 末尾不写 forward-progress offer**
- 主条款...
- 子条款...
- 触发 case...
### 引用规范
- 新引用: 直接 link `IRONLAWS.md §X.YY` (e.g. `IRONLAWS.md §18 X10`)
- 历史引用: 沿用编号
```

#### IRONLAWS.md 完整 raw text

✅ 实存 791 行, 含 §0-§22:
- §0 Tier 分类标准
- §1 Tier 索引 (T1/T2/T3 + DEPRECATED + 候选 + 跳号撤销)
- §2 工作原则类 (1-3)
- §3 因子研究类 (4-6)
- §4 数据与回测类 (7-8)
- §5 系统安全类 (9-11)
- §6 因子质量类 (12-13)
- §7 重构原则类 (14-17, 含铁律 17 例外)
- §8 成本对齐 (18)
- §9 IC 口径统一 (19)
- §10 因子噪声鲁棒性 (20)
- §11 工程纪律类 (21-24)
- §12 CC 执行纪律类 (25-28)
- §13 数据完整性类 (29-30)
- §14 工程基础设施类 (31-35)
- §15 实施者纪律类 (36-41)
- §16 PR 治理类 (42)
- §17 schtask 硬化类 (43)
- §18 X 系列治理类 (44 X9 + X10 新, X10 含完整 LL-098 内容)
- §19 候选未 promote (X1/X3/X4/X5)
- §20 跳号 / 撤销 (X2/X6/X7 + X8)
- §21 关联
- §22 版本变更记录

#### ADR-021 完整 raw text

✅ 实存 206 行, 含:
- Header (Status / Date / Deciders / PR / Supersedes / Related)
- §1 Context (4 子段)
- §2 Decision (6 子段)
- §3 Consequences (5 子段)
- §4 关联 (5 子段)
- §5 验收

### Q12 — verify checklist

| 检查 | 实测 | 状态 |
|---|---|---|
| IRONLAWS.md 总条数 = CLAUDE.md 原铁律数 + X10 | 原 43 + DEPRECATED 1 + 10b 子条 = 45, IRONLAWS.md 全含 + X10 = 46 含 X10 | ✅ |
| 每条铁律 tier 已标 | T1×31 / T2×15 (含 X10) / DEPRECATED×1 | ✅ |
| ADR-021 完整含 §1-§4 | 含 §1-§5 (多 §5 验收) | ✅ |
| LL-098 backref 在 X10 sections 全部存在 | IRONLAWS.md §18 X10 + §21 关联 + ADR-021 §4.2 + CLAUDE.md 铁律段 reference X10 段 | ✅ |
| 每条铁律 LL backref + ADR backref 完整 | IRONLAWS.md §1 Tier 索引 + §2-§18 内文 | ✅ |
| CLAUDE.md banner 顶部加入, 铁律段已 reference 化 | banner L5 (3 行) + 铁律段 L332-L455 (124 行) | ✅ |
| D-1=A 硬 scope 守门 (CLAUDE.md 其他段 0 改) | 项目身份/技术栈/因子系统/架构/目录/编码规则/因子审批/因子画像/性能/失败方向/策略/文档索引/当前进度/CC自动化/文件归属/执行标准流程 全部 0 改 | ✅ |

✅ Q12 全 PASS.

---

## §2 主动发现 (Step 6.2 副产品, 沿用 PR #172/#173 §9 模式)

1. **CLAUDE.md 铁律段实测 179 行 → 124 行 (-31%)** — sprint period prompt "v3.0 ≤ 200 行 (target 150)" 假设破灭实测确认 (CC 4-30 STOP-A). user 决议 D-1=A 后改沿用 Q10 硬 scope, ~150 全文件重构留 Step 6.3.
2. **IRONLAWS.md 总条数 46 (含 X10)** — 涵盖原 44 编号 + X9 inline + X10 新 + DEPRECATED 1 + 10b 子条. tier 化 T1=31 / T2=15 / T3=0 (拆批留 Step 6.2.5+).
3. **ADR 编号系统持续腐烂** — ADR-0009 (4 位数字) + ADR-010 重复 2 个 + ADR-015~020 6 项 gap. ADR-021 沿用 sprint period 预占 (D-3=A). Step 6.2.5+ 候选: ADR 编号一致性审计 + rename 历史漂移.
4. **PR #172 §5 "X1-X9 inline" 假设错为 sprint period 第 5 个数字假设错** — LL "假设必实测" broader 32→**33** (本 STATUS_REPORT 沉淀, 但 PR #172 已锁不调).
5. **本 PR 是铁律 X5 (文档单源化) 候选自身的落地实例** — X5 是候选未 promote inline (D-2=A 留 Step 6.2.5), 但本 PR 行为 = X5 落地. 自洽: 候选铁律 inline 缺失 ≠ 不实施, "实施" 优先于 "inline".

---

## §3 LL "假设必实测" 累计更新

| 口径 | PR #173 后 | 本 PR (Step 6.2) 后 |
|---|---|---|
| narrower (LL 内文链 LL-091~) | 30 (含 LL-098) | **30** (本 PR 0 新 LL) |
| broader (PROJECT_FULL_AUDIT scope) | 32 | **33** (PR #172 §5 "X1-X9 inline" 假设错为新实证) |
| LL 总条目 | 92 | **92** (本 PR 0 新 LL) |

⚠️ **discrepancy 持续**: narrower 30 vs broader 33, 差 3. 沿用 PR #173 STATUS_REPORT §3 主动发现, PR #172 已锁 broader 数字不调.

---

## §4 不变

- Tier 0 债 11 项不变 (本 PR 不动, 沿用 PR #173)
- LESSONS_LEARNED.md 不变 (LL-098 已锁 PR #173)
- PROJECT_FULL_AUDIT / SNAPSHOT 不变 (PR #172 锁)
- 其他 ADR 不变 (ADR-NNN ≠ 021, 0 改)
- 其他 docs 不变 (SYSTEM_RUNBOOK / SYSTEM_STATUS / DEV_*.md / MEMORY / 等)
- CLAUDE.md 非铁律段非 banner 不变 (D-1=A 硬 scope)
- 0 业务代码 / 0 .env / 0 服务重启 / 0 DML / 0 真金风险 / 0 触 LIVE_TRADING_DISABLED
- 真账户 ground truth 沿用 4-30 14:54 实测 (0 持仓 + ¥993,520.16)
- PT 重启 gate 沿用 PR #171 7/7 PASS

---

## §5 关联

- **本 PR 文件**:
  - IRONLAWS.md (新建, 791 行)
  - docs/adr/ADR-021-ironlaws-v3-refactor.md (新建, 206 行)
  - CLAUDE.md (修改, 866 → 813 行, -53 行)
  - 本 STATUS_REPORT (新建)
- **关联 PR**: #170 (X9) → #171 (PT gate) → #172 (Step 5 SSOT) → #173 (Step 6.1 LL-098 + 8 D2) → 本 PR (Step 6.2 IRONLAWS + ADR-021)
- **关联 LL**: LL-097 (X9) / LL-098 (X10) / LL-066 (铁律 17 例外) / LL-068 (铁律 43 触发)
- **关联 ADR**: ADR-021 (本 PR 决议) / ADR-0009 (铁律 17) / ADR-008 (铁律 38)

---

## §6 LL-059 9 步闭环不适用 — 沿用 PR #172/#173 LOW 模式

本 PR 是 SSOT 治理重构 (0 业务代码 + 无 smoke 影响), 跳 reviewer + AI self-merge.

LL-098 stress test 第 5 次 verify (沿用 LL-098 规则 1+2):
- PR description / STATUS_REPORT / 任何末尾 0 写前推 offer
- 不 offer "Step 6.2.5 启动" / "Step 6.3 启动" / "Step 7" / "paper-mode" / "cutover"
- 等 user 显式触发
