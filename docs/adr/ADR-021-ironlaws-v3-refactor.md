# ADR-021: 铁律 v3.0 重构 + IRONLAWS.md 拆分 + X10 加入

**Status**: Accepted
**Date**: 2026-04-30
**Deciders**: user (4-30 ~21:00 决议 D-1=A / D-2=A / D-3=A) + CC (Step 6.2 实施)
**PR**: chore/step6-2-ironlaws-adr021 (Step 6.2)
**Supersedes**: 无 (历史 inline 铁律 v1/v2/v3/v4 banner 演进自然继承)
**Related**: ADR-0009 (datacontract-tablecontract-convergence) / ADR-008 (execution-mode-namespace-contract)

---

## §1 Context (背景)

### 1.1 铁律治理现状 (v4 2026-04-30 PR #170 后)

- **inline source**: 全部 44 编号铁律 (1-44, 含 1 DEPRECATED #2) 散落在 `CLAUDE.md` L330-L508 (179 行)
- **X 系列** (sprint period 软铁律候选):
  - **X9** (条目 44): inline at L501, 编号 44 标 `(X9)` tag, 由 LL-097 沉淀 PR #170 c2 落地
  - **X1 / X3 / X4 / X5**: 候选未 inline (sprint audit 软铁律, 散落在 audit docs / scripts/audit/README.md)
  - **X2 / X6 / X7**: 跳号未定义 (历史决议保留)
  - **X8**: 撤销 (T0-17 撤销同源, SHUTDOWN_NOTICE §195 v3 "PR #150 是补丁不是替代")
- **LL backref / ADR backref**: 散落 inline 在各条铁律内文 + 各 LL 内文, 无统一索引

### 1.2 触发事件: LL-098 沉淀 (PR #173 Step 6.1)

LL-098 = AI 自动驾驶 cutover-bias (sprint 偏移). 沉淀候选铁律 X10 (在 LL-098 L3068-3075 显式声明 "Step 6.2 ADR-021 时机沉淀, 本 PR 不加入 CLAUDE.md").

### 1.3 累积治理债

- **PROJECT_FULL_AUDIT_2026_04_30 §5** 写 "7 新铁律 X1-X9 实施扫描 (CLAUDE.md 铁律段 inline)" — 实测仅 X9 inline, 其他候选未 inline. 这是 sprint period 第 5 个数字假设错 (LL "假设必实测" broader 32→33 候选, Step 6.2 §0 STOP-B 实测发现).
- **CLAUDE.md 铁律段 179 行 inline**, 任何文档需要引用某条铁律时只能 grep + copy 数字, 漂移高发 (e.g. PR #172 §5 "7 新 / X1-X9" 双错).
- **D15-D21 决议** (历史 sprint period 决议) 提议 tier 化 (T1/T2/T3), 但未落地.
- **铁律 22 文档跟随代码** 要求文档与代码 / 数字一致, 但 inline 治理腐烂高发, 自相矛盾.

### 1.4 ADR-021 编号占位

Sprint 内文档 3+ 处预占 `ADR-021` 编号:
- `STATUS_REPORT_2026_04_30_D3_C.md` L154
- `STATUS_REPORT_2026_04_30_D3_B.md` L194
- `SHUTDOWN_NOTICE_2026_04_30 §195`

实测 `docs/adr/` 现有最大编号 = ADR-014, 015-020 共 6 项 gap (sprint period lazy assignment). ADR-021 是预占编号, 不是 next available. **D-3=A** 决议: 沿用预占编号, 不改用 ADR-015 (改编号 = 3 处文档引用漂移).

---

## §2 Decision (决议)

### 2.1 IRONLAWS.md 拆分 (D-1=A 硬 scope)

新建 `IRONLAWS.md` (项目根目录, 与 `CLAUDE.md` / `LESSONS_LEARNED.md` 平级) 作为铁律 SSOT:

- **结构** (Q4=a 单文件):
  - §0 Tier 分类标准
  - §1 Tier 索引 (T1/T2/T3 + DEPRECATED + 候选 + 跳号 / 撤销)
  - §2-§18 编号 1-44 + X9 完整内容 (复制 + 标准化, Q5=iii)
  - §18 X 系列治理类 (44 X9 + X10 新)
  - §19 候选未 promote (X1/X3/X4/X5 显式声明留 Step 6.2.5)
  - §20 跳号 / 撤销 (X2/X6/X7 + X8)
  - §21 关联
  - §22 版本变更记录

- **复制 + 标准化** (Q5=iii):
  - 0 信息丢失 (复制保 100% 内容)
  - 加价值: tier 标识 (T1/T2/T3) / LL backref / ADR backref / 关联 PR

### 2.2 X10 加入 (D-2=A 仅 X10 inline)

X10 = "AI 自动驾驶 detection — 末尾不写 forward-progress offer" (T2 tier).

**X10 主条款 + 子条款** 沿用 LL-098 L3068-3075 raw text (PR #173 verify 通过):
- **主条款**: PR / commit / spike 末尾不主动 offer schedule agent / paper-mode / cutover / 任何前推动作. 等 user 显式触发. 反例 → STOP.
- **子条款**: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件. 必须显式核 D 决议链全部前置, 才能进入下一步.

X10 加入位置:
- **IRONLAWS.md §18**: 紧接 44 (X9) 之后, 含完整内容 + 复用规则 5 条 + 检测脚本候选 + Stress test 实绩
- **CLAUDE.md 铁律段 reference**: 仅简述 X10 + link IRONLAWS.md §18

### 2.3 X1 / X3 / X4 / X5 候选 promote 留 Step 6.2.5 (D-2=A 拆批)

- 不在本 PR promote (sprint 拆批原则)
- 在 IRONLAWS.md §19 显式列出 (来源 + 含义 + 状态)
- 留 Step 6.2.5 评估后批量 promote

### 2.4 X2 / X6 / X7 / X8 历史决议保留

- X2 / X6 / X7: 跳号未定义, 不 reuse (保留历史决议)
- X8: 撤销 (T0-17 撤销同源)

### 2.5 CLAUDE.md 改动 scope (D-1=A 硬 scope)

**仅改**:
- 顶部加 v3.0 banner (含 IRONLAWS.md pointer + ADR-021 link + 4-30 user 决议 D-1/D-2/D-3=A)
- 铁律段 (L330-L508) reference 化, 留:
  - 简述 (1-2 行 / 条) + tier 标识
  - link IRONLAWS.md 完整内容
  - 历史 X 系列状态简述

**不改**:
- 项目身份段
- coding 规范段
- 任何 audit / spike 引用
- 8 D2 已 add 文档引用 (PR #173)
- 因子系统 / 技术栈 / 目录结构 / 编码规则 / 因子审批硬标准 / 因子画像评估协议 / 性能规范 / 已知失败方向 / 策略配置 / 文档查阅索引 / 当前进度 / CC 自动化操作 / 文件归属规则 / 执行标准流程 等其他段

**v3.0 全文件 ~150 行 重构留 Step 6.3** (D-1=A 拆批原则). 本 PR 不做 CLAUDE.md 全文件重构, 只做铁律段 reference 化.

### 2.6 ADR-021 编号锁定 (D-3=A)

沿用 sprint period 预占 ADR-021 编号. 不改用 ADR-015 (改编号 = STATUS_REPORT_D3_B/D3_C/SHUTDOWN_NOTICE 3 处引用漂移).

ADR-015 ~ ADR-020 共 6 项 gap 留待后续 ADR 写作时按需 lazy assignment.

---

## §3 Consequences (后果)

### 3.1 长期治理资产 (positive)

- **铁律 SSOT 落地**: 所有铁律 / X 系列 / 候选 / 跳号 / 撤销 历史决议在 IRONLAWS.md 集中. 任何文档引用某条铁律 link IRONLAWS.md, 不再 grep + copy.
- **tier 化** (T1/T2/T3) 落地, 后续可基于 tier 设 PR / commit / hook 自动化阻断规则 (Step 6.2.5+ 候选检测脚本).
- **LL backref + ADR backref 标准化**, 治理债追溯链完整 (沿用铁律 22 文档跟随代码精神).
- **铁律 X5 文档单源化** 落地 (X5 候选自身的实例).
- **Step 6.2.5 解锁**: 候选 X1/X3/X4/X5 promote 评估 + tier calibration + narrower 起点链 audit 等后续治理工作.

### 3.2 短期改动 (本 PR scope)

| 文件 | 改动 | 行数估 |
|---|---|---|
| `IRONLAWS.md` | 新建 | ~700 行 (CC 实测决定) |
| `docs/adr/ADR-021-ironlaws-v3-refactor.md` | 新建 (本文件) | ~150 行 |
| `CLAUDE.md` | 顶部 banner + 铁律段 reference 化 | -179 → ~50 行 (铁律段净减少 ~130 行 + banner +5 行 = 净减 ~125 行) |
| `docs/audit/STATUS_REPORT_<date>_step6_2.md` | 新建 (verify 证据) | ~250 行 |

**不改**:
- 任何业务代码 / .env / configs / .py / migrations
- LESSONS_LEARNED.md (LL-098 已锁 PR #173)
- PROJECT_FULL_AUDIT / SNAPSHOT (PR #172 已锁)
- 其他 ADR (ADR-NNN ≠ 021)
- CLAUDE.md 非铁律段 (D-1=A 硬 scope)

### 3.3 引用关系传导 (后续 PR 需注意)

任何后续文档 / commit / PR 引用某条铁律时:
- **新引用**: 直接 link `IRONLAWS.md §X.YY` (e.g. `IRONLAWS.md §18 X10`)
- **历史引用** (CLAUDE.md inline 时代写的 "铁律 33") 不必批量改, 沿用编号 (历史编号保持不变, 防文档引用漂移). CLAUDE.md 铁律段 reference 仍含编号简述, 老引用仍可走 CLAUDE.md 找到 link.

### 3.4 风险

- **零风险**: 0 业务代码改动 / 0 .env / 0 服务重启 / 0 DML / 0 真金风险.
- **回滚成本低**: `git revert <merge-commit>` 即可还原 3 文件 + STATUS_REPORT.

### 3.5 铁律 22 / X5 自相一致

本 PR 是 "文档跟随代码" 治理债的反向产物 — 不是代码先变, 而是铁律治理本身腐烂. 沿用铁律 X5 (文档单源化) 修治理. 自洽.

### 3.6 ADR 编号系统历史决议保留 (Step 6.2.5b-1 沉淀, 沿用 PR #175 §6 主题 F F.5)

ADR 编号系统当前状态 (历史决议保留, **不 rename**):

| ADR 编号 | 历史漂移 | 决议 | 论据 |
|---|---|---|---|
| **ADR-0009** | 4 位数字 (其他全 3 位) | 维持现状 | sprint period 多文档已用 ADR-0009 (本 ADR §4.4 + IRONLAWS.md / 多 audit / research / mvp docs). rename = 引用漂移. 治理价值 < rename 风险. |
| **ADR-010 双 ADR** | 重复编号 010 | 维持现状 | 文件名后缀区分 scope (addendum-cb-feasibility + pms-deprecation-risk-framework). 双 ADR 独立决议. |
| **ADR-015 ~ ADR-020** | 6 项 gap | 维持现状 (lazy assignment) | gap 不影响 ADR-021 + 后续 ADR 顺序占用. 0 风险. |
| **ADR-021** | sprint period 预占 | 已落地 (PR #174) | 本 ADR. |

**修订时点候选** (Wave 5+ 远期, 0 PR commitment): 治理价值显著上升时重评 rename 风险.

**防未来 sprint 重提 rename**: 本 §3.6 + IRONLAWS.md §21.1 是 SSOT 历史决议保留声明, 任何后续 PR / sprint 提议 rename 必须先撤销本子段 + 更新所有引用文档.

---

## §4 关联

### 4.1 D 决议 (4-30 user 决议)

- **D-1=A**: 沿用硬 scope (仅改铁律段 + banner). 全文件 ~150 行 重构留 Step 6.3.
- **D-2=A**: 仅 X10 inline. X1/X3/X4/X5 候选 promote 留 Step 6.2.5.
- **D-3=A**: ADR-021 编号锁定 (sprint period 预占).

### 4.2 关联 LL

- **LL-098** (X10 沉淀): PR #173 L3032-3105
- **LL-097** (X9 沉淀, 编号 44 inline): PR #170 c2
- **LL-066** (铁律 17 例外条款): PR #43 / #45
- **LL-068** (铁律 43 触发): Session 26 DataQualityCheck hang
- **LL-051 / LL-054 / LL-055** (铁律 42 PR 分级审查触发)
- **LL-001 series** (铁律 1 不靠猜测)

### 4.3 关联 PR

- **PR #170** (批 2 P0 修): 铁律 44 (X9) inline 落地
- **PR #171** (PT 重启 gate): 沿用 LL-097 闭合 T0-18
- **PR #172** (Step 5 PROJECT_FULL_AUDIT): 沿用 X5 (文档单源化), §5 "X1-X9 inline" 假设错为 sprint period 第 5 个数字假设错
- **PR #173** (Step 6.1): LL-098 + 8 D2 untracked 闭合 + X10 候选声明
- **本 PR (Step 6.2)**: ADR-021 + IRONLAWS.md + X10 落地 + CLAUDE.md banner + reference

### 4.4 关联 ADR

- **ADR-0009** (datacontract-tablecontract-convergence): 铁律 17 关联
- **ADR-008** (execution-mode-namespace-contract): 铁律 38 (Blueprint 长期记忆) 关联

### 4.5 后续步骤 (留 Step 6.2.5+, 本 PR 不预设)

> **Step 6.4 G1 撤销** (2026-05-01, [ADR-022](ADR-022-sprint-treadmill-revocation.md) §2.1 #1): 本节 §4.5 "Step 6.3 全文件 ~150 行 重构" target 实测推翻 (Step 6.3b STOP-1+STOP-2 双触发 — SSOT 现实约束下不可达). 实际 Path C ~509 行落地 (PR #179). **本节仅作 Step 6.2 时点历史快照保留**, 后续步骤实际走 Step 6.2.5a/b-1/b-2 (PR #175-#177) + Step 6.3a (PR #178) + Step 6.3b (PR #179) + Step 6.4 G1 (本 PR).

- Step 6.2.5: X10 工程化候选评估 (检测脚本 / pre-merge hook / Claude system prompt-level guard)
- Step 6.2.5: narrower 起点链 audit + (可选) X1/X3/X4/X5 promote
- Step 6.3: 6+1 文档 SSOT 整合 + 11 项 Tier 0 enumerate + CLAUDE.md 全文件 ~150 行 重构 <!-- ADR-022 §2.1 #1 撤销, 实际 Path C ~509 行 -->

**注**: 沿用 LL-098 stress test 第 5 次, ADR-021 § 4.5 不 offer 启动 Step 6.2.5/6.3/Step 7. 等 user 显式触发.

---

## §5 验收

- IRONLAWS.md 实存 + tier 标识完整 + LL/ADR backref 标准化 + X10 含 LL-098 完整内容
- ADR-021 实存 (本文件) + §1-§4 完整 + D 决议 / LL / PR / ADR 关联清晰
- CLAUDE.md 顶部 banner + 铁律段 reference 化 + 其他段 0 改 (D-1=A 硬 scope 守门)
- LL-098 backref 在 X10 sections (IRONLAWS.md §18 + CLAUDE.md reference) 全部存在
- STATUS_REPORT 含完整 verify 证据 (diff + raw text + Q1-Q12 答案)
- pre-push smoke green (沿用 PR #173 baseline)
- AI self-merge (沿用 PR #172/#173 LOW 模式, 跳 reviewer)
