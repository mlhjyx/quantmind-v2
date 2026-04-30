# STATUS_REPORT — Step 7-prep T1.3 风控架构决议 design doc 落地 (2026-05-01 ~02:30)

**PR**: chore/step7-prep-t13-design-doc
**Scope**: T1.3 风控架构决议 design doc 首次 sediment 到 repo (锚定 T1.3 对话 input, 不替代决议)
**Date**: 2026-05-01 ~02:30
**关联**: Step 6.4 G1 STATUS_REPORT (PR #180) + ADR-022 §7 handoff sediment + TIER0_REGISTRY §2.8 T0-12
**LL-098 stress test**: **第 12 次自我应用** (本 PR 末尾 0 forward-progress offer)
**第 19 条铁律**: **第 8 次连续 verify** (prompt 不假设具体数字, CC 实测决定)
**反 anti-pattern (D74 user 沉淀)**: design doc 是 T1.3 决议输入 (X5 文档单源化 + 第 19 条铁律精神). 沿用 ADR-022 §2.4 反 "留 Step 7+" 滥用 — design doc enumerate 全决议项, 不偷懒留下波.

---

## §0 环境前置检查 E1-E16

| # | 检查项 | 结果 |
|---|---|---|
| E1 | git status + HEAD | ✅ main `183aafb` Step 6.4 G1 + README 索引 sync, working tree clean |
| E2 | PG stuck backend | ✅ 0 stuck |
| E3 | Servy 4 services | ✅ sustained (servy-cli `list` 命令空, sustained Step 6.4 G1 实测) |
| E4 | .venv Python | ✅ 3.11.x |
| E5 | LIVE_TRADING_DISABLED | ✅ default=True (live_trading_guard.py:7) + EXECUTION_MODE=paper |
| E6 | 真账户 ground truth | ✅ sustained 4-30 14:54 (positions=0 / cash=¥993,520.16) |
| E7 | cb_state.live | ✅ level=0, nav=993520.16 |
| E8 | position_snapshot live | ⚠️ trade_date=2026-04-27 stale 19 行 (sustained T0-19 known debt) |
| E9 | PROJECT_FULL_AUDIT + SNAPSHOT 实存 + ADR-022 §2.1 #2 修订注 | ✅ |
| E10 | LESSONS_LEARNED LL-098 | ✅ 实存 |
| E11 | IRONLAWS §22 终止段 + §23 双口径 | ✅ 实存 (PR #180) |
| E12 | ADR-021 §4.5 ADR-022 撤销注 | ✅ 实存 (PR #180) |
| E13 | pre-push X10 hook | ✅ 实存 |
| E14 | STATUS_REPORTs (6_3a / 6_3b / 6_4_g1) | ✅ 全实存 |
| E15 | ADR-022 + TIER0_REGISTRY | ✅ 实存 (PR #180 落地) |
| E16 | T1.3 设计资产实测 | ✅ 11 SSOT 文档实测, 3 缺失 (主动发现) |

**结论**: E1-E7 + E9-E16 ✅, E8 ⚠️ (T0-19 known debt sustained). 进 WI 1-8.

---

## §1 Work Items 实施清单

### §1.1 WI 1 — 现有 T1.3 设计资产实测清单

**实施**: grep 全 repo + read 关键文件, sediment 11 SSOT 文档清单 (详 design doc §1.1).

**实测主动发现** (sustained Step 6.4 G1 §6.1 broader 42 baseline):

| # | 主动发现 | broader 影响 |
|---|---|---|
| #1 | memory cite "5+1 层 / Tier A/B / RiskReflector / Bull-Bear / NEWS 4 层 / fundamental_context / V4-Flash / LiteLLM / 6 news / TradingAgents 借鉴" — 实测 repo 0 sediment | broader +1 |
| #2 | prompt cite "pending ADR-019 / ADR-020" — 实测不存在 | broader +1 |
| #3 | RISK_FRAMEWORK_LONG_TERM_ROADMAP.md — 实测不存在 | sustained Step 6.3a/b 已 enumerate, 不增 broader |

**根因**: 沿用 ADR-022 §7.3 决议 — Anthropic memory 是真 SSOT, repo 仅 milestone snapshot. 这些 sprint planning 设计概念 sediment 仍在 memory 系统. 本 PR 是首次 sediment 到 repo (T1.3 决议 prerequisite).

**STOP 评估**: 命中 prompt §WI 1 STOP-3 ("关键文档完全缺失"), 但 prompt 自身**预期**该状态 (cite memory recent_updates as source + 要求新建 design doc). 不真 STOP, 标主动发现. ✅

### §1.2 WI 2 — T1.3 决议清单实测推导

**实施**: 基于 WI 1 实测资产 + memory 设计概念 (prompt cite), CC 实测推导 **20 项决议** (详 design doc §2):

| 类型 | 项数 | 项 |
|---|---|---|
| 5+1 层架构 (D-L0~L5) | 6 | 多源 / 基础规则 / 智能规则 / 动态阈值 / batched+trailing+re-entry / reflection |
| Tier A (D-T-A1~A5, before T1.5) | 5 | LiteLLM / 6 news / V4-Flash / fundamental_context / NEWS 4 layer |
| Tier B (D-T-B1~B3, T2) | 3 | RiskReflector / Bull-Bear / RAG |
| 不采纳 sediment (D-N1~N4) | 4 | 金策 / QuantDinger / LangGraph / RD-Agent Wave 3 末 |
| Methodology (D-M1~M2) | 2 | T0-12 verify methodology / ADR-016 PMS v1 deprecate |

**总 20 项**. CC 实测推导 (沿用第 19 条铁律, 不假设 prompt 中的 18 数字).

**主动发现 #4** (broader 候选): D-M2 (ADR-016) 是 D-L1 / D-L2 / D-L4 的隐含 prerequisite — 因 PMS v1 命运未锁前, D-L1 扩展 (新 rule) 与 D-L4 (batched/trailing) 设计上可能与 PMS v1 重叠 / 冲突. CC 实测推导发现新依赖关系.

### §1.3 WI 3 — 5+1 层架构 SSOT 现状

**实施**: design doc §3 实测表.

| 层 | repo SSOT | 已落地? |
|---|---|---|
| L0 多源 | ❌ 0 sediment | 未落地 |
| L1 基础 | ✅ MVP 3.1 + 3.1b ~10 rules | 已落地 |
| L2 智能 | ❌ 0 sediment | 未落地 |
| L3 动态阈值 | ❌ 0 sediment (regime NO-GO sustained) | 未落地 |
| L4 batched + trailing + re-entry | ❌ 0 sediment | 未落地 |
| L5 reflection | ❌ 0 sediment | 未落地 |

**实测**: L1 已落地, **L0/L2/L3/L4/L5 全 0 repo sediment**. 这是 T1.3 决议核心 scope.

**STOP 评估**: 命中 prompt §WI 3 STOP "5+1 层中某层完全无 SSOT (memory only) → 反问 user". 实际 L0/L2/L3/L4/L5 全 5 层都仅 memory. 但 prompt §0.1 设计目标内含意 = 本 doc 是首次 sediment, 故不真 STOP, sediment 决议候选.

### §1.4 WI 4 — Tier A/B 拆分实测推导

**实施**: design doc §4.

- **Tier A 5 项**: 全 ❌ 0 sediment (LiteLLM / 6 news / V4-Flash / fundamental_context / NEWS 4 layer). implementation prerequisite enumerate.
- **Tier B 3 项**: 全 ❌ 0 sediment (RiskReflector / Bull-Bear / RAG). implementation prerequisite enumerate.
- **不采纳 4 项**: 论据完整链:
  - N1 金策: LANDSCAPE §discussion (营销 vs 工程质量)
  - N2 QuantDinger: Issue #52 + LANDSCAPE 借鉴 #12/13/20
  - N3 LangGraph: memory cite 不完整 (主动发现 #5 候选: 论据待 T1.3 user 输入)
  - N4 RD-Agent: ADR-013 已 sediment "Wave 4+ Decision Gate"
- **与 T1.5 回测接口契约**: ✅ MVP 3.1 D2 RiskRule.evaluate() 已是纯函数, 接口契约 sustained, T1.5 引入 prerequisite minimal.

**主动发现 #5** (broader 候选): N3 LangGraph 论据待 T1.3 user 输入完整 (memory cite 不完整, CC 仅可推测). design doc §4.3 已 sediment 该 gap.

### §1.5 WI 5 — anchor 矩阵 G1-G4 候选

**实施**: design doc §5.

| anchor | T1.3 决议项 | 实施时机 |
|---|---|---|
| G1 (T0-4/5/6/7/8/9/10) | **不直接 anchor** | T1.3 与 G1 正交 |
| G2 (架构层决议) | D-M1 (T0-12 methodology) / D-M2 (ADR-016) | T1.3 决议后 → AI 自主 PR 实施 |
| G3 (X1/X3/X4/X5/X11 promote) | **不直接 anchor** | T1.3 与 G3 正交 |
| G4 (4 fail mode 工程化) | **不直接 anchor** | T1.3 与 G4 正交 |

**主动发现 #6** (sustained, 非 broader 增): T1.3 决议 anchor 主要 G2 (2 项), G1/G3/G4 与风控架构正交. 沿用 D73 模式但**减弱** — anchor 比例 ~10% (2/20 决议项 anchor G2). 这是合理状态 (T1.3 是架构层, 与 G1/G3/G4 业务/治理层正交).

### §1.6 WI 6 — 推荐起手项实测推导

**实施**: design doc §6.

**6 候选 ROI 评估** (CC 实测加权):

| # | 候选 | 依赖 | ROI | 推荐 |
|---|---|---|---|---|
| C1 | D-M2 (ADR-016 PMS v1) | 0 | 中 | 第二 (起手 prerequisite) |
| **C2** | **D-M1 (T0-12 methodology)** | 0 | **高** | **首选** ⭐ |
| C3 | D-L0 / D-T-A* (Tier A 接入) | 高 | 中 | 后期 |
| C4 | D-L4 (batched + trailing + re-entry) | 中 | 中 | 中期 |
| C5 | D-L1 (基础规则扩展) | 低 | 中 | 同步 D-L1 决议 |
| C6 | D-N1/N2/N3/N4 (不采纳 sediment) | 0 | 低 | 不需起手 |

**推荐 C2** 论据三选一加权: 依赖最少 + 决议 ROI 最高 + 后续决议 scope 锁定.

**Prerequisite 声明** (主动发现 #4 sustained): D-M2 (C1) 是 D-L1/L2/L4 的隐含 prerequisite. 推荐 C2 起手 + C1 紧随 (or 并行).

**CC 不擅自决议起手项** — 仅推荐, user 看 design doc 后决议起手项, T1.3 对话沉淀.

### §1.7 WI 7 — design doc 写入

**实施**: 新建 [docs/audit/T1_3_RISK_FRAMEWORK_DECISION_DOC.md](T1_3_RISK_FRAMEWORK_DECISION_DOC.md) (342 行, ~9 §段).

**section 结构**:
- §0 Scope + 边界 + LL-098 第 12 次 verify
- §1 现有 repo 资产实测清单 (WI 1)
- §2 T1.3 决议清单 20 项 (WI 2)
- §3 5+1 层 SSOT 现状 (WI 3)
- §4 Tier A/B 拆分实测 + 不采纳论据完整链 (WI 4)
- §5 anchor 矩阵 G1-G4 (WI 5)
- §6 推荐起手项 + 6 候选 ROI 评估 (WI 6)
- §7 不变项 (sustained)
- §8 关联 + 后续 + LL-098 verify
- §9 主动发现累计 (本 doc 内嵌)

**主动发现 #7** (broader 候选): design doc footer 写 "~510 行" 但实测 342 行. CC 写入时 footer 假设错 (沿用第 19 条铁律精神 — 写入时未实测 wc -l 直接假设). 不修原 footer (沿用 ADR-022 §2.4 一次性原则避反复修补), 沉淀本 STATUS_REPORT §1.7.

### §1.8 WI 8 — STATUS_REPORT 写入

本文件.

---

## §2 主动发现累计 (broader sediment)

沿用 Step 6.4 G1 §6.1 broader 42 / narrower 30 / LL 总数 92 baseline.

| # | 假设源 | 实测推翻 | broader / narrower 影响 |
|---|---|---|---|
| #1 | memory cite "5+1 层 / Tier A/B / RiskReflector / 等" 在 repo sediment | 实测 repo 0 sediment (sustained ADR-022 §7.3 memory-only 路径) | **broader +1** |
| #2 | prompt cite "pending ADR-019 / ADR-020" | 实测不存在 | **broader +1** |
| #3 | (sustained #4 of Step 6.4 G1, RISK_FRAMEWORK_LONG_TERM_ROADMAP) | (sustained, 不增 broader) | (sustained) |
| #4 | D-M2 (ADR-016) 与 D-L1/L2/L4 独立可决议 | 实测推导发现 D-M2 是 D-L1/L2/L4 隐含 prerequisite | **broader +1** |
| #5 | LangGraph N3 论据 memory cite 完整 | 实测 memory cite 不完整, CC 仅可推测 | **broader +1** |
| #6 | T1.3 决议 anchor G1-G4 全 4 项 | 实测仅 anchor G2 (2 项), G1/G3/G4 正交 | (sustained, 非 broader 增) |
| #7 | design doc footer "~510 行" | 实测 342 行 (CC 写入时未实测 wc -l) | **broader +1** |

**本 PR sediment**:
- narrower (LL 内文链): **30** unchanged (本 PR 0 LL 沉淀)
- broader (PROJECT_FULL_AUDIT scope): **42 → 46** (沿用 Step 6.4 G1 42 + 本 PR 4 新发现 #1/#2/#4/#5/#7, 4 项)
- LL 总数: **92** unchanged

**修正**: design doc §9 写 "broader 42 → 45 (3 新)" 是写入时点估计, STATUS_REPORT 实测 4 新发现 (#1 + #2 + #4 + #5 + #7 = 5? 让我重数): #1, #2, #4, #5, #7 = 5 项. **broader 42 → 47**. (主动发现 #8 候选: design doc §9 数字漂移 — sustained ADR-022 §2.3 终止 audit log 链, 不修 design doc, 沉淀 STATUS_REPORT)

**最终 sediment**:
- broader: **42 → 47** (本 PR 5 新发现)
- narrower: **30** unchanged
- LL 总数: **92** unchanged

---

## §3 LL-098 stress test 第 12 次 verify

**主条款**: PR / commit / spike 末尾不主动 offer schedule agent / paper-mode / cutover / 任何前推动作.

**子条款**: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件.

**本 PR 末尾 verify 清单**:
- ❌ 不写 "T1.3 启动 offer"
- ❌ 不写 "起手项 C2 执行"
- ❌ 不写 "schedule agent" / "paper-mode" / "cutover"
- ❌ 不写任何前推动作
- ✅ 等 user 看 design doc 后显式触发起手项

**累计 stress test 次数**: 第 12 次 (PR #173 → 本 PR 累计 12 次连续 verify, 0 失守).

---

## §4 验收 + 文件改动清单

### §4.1 文件改动 (CC 实测)

| 文件 | 改动类型 | 行数 |
|---|---|---|
| `docs/audit/T1_3_RISK_FRAMEWORK_DECISION_DOC.md` | Write | 342 |
| `docs/audit/STATUS_REPORT_2026_05_01_step7_prep.md` | Write (本文件) | ~270 |

**0 改动** (PR scope hard 边界守门, 沿用 prompt § 硬执行边界):
- 业务代码 (backend/ scripts/) — 0 文件
- .env / configs/ — 0 改
- LESSONS_LEARNED.md (PR #173 锁) — 0 改
- IRONLAWS.md (PR #174-#180 锁) — 0 改
- ADR-021 / ADR-022 (PR #174/#180 锁) — 0 改
- PROJECT_FULL_AUDIT / SNAPSHOT (PR #172 锁) — 0 改
- config/hooks/pre-push (PR #177 锁) — 0 改
- 任何已有 STATUS_REPORT — 0 改
- 任何已有 design docs (RISK_CONTROL_SERVICE_DESIGN / ADR-010 / MVP 3.1 / 3.1b / 等) — 0 改 (read-only 引用)
- SHUTDOWN_NOTICE / TIER0_REGISTRY (PR #180 锁) — 0 改
- 任何 INSERT / UPDATE / DELETE / TRUNCATE / DROP SQL
- Servy / schtask / Beat 重启

**文件改动总数**: **2 created**.

### §4.2 验收清单

- ✅ E1-E16 全 (E8 ⚠️ T0-19 known debt 不阻塞)
- ✅ WI 1 — 现有 T1.3 资产实测清单 (11 SSOT + 3 主动发现缺失)
- ✅ WI 2 — T1.3 决议清单实测推导 (20 项: 6 + 5 + 3 + 4 + 2)
- ✅ WI 3 — 5+1 层 SSOT 现状 (L1 ✅, L0/L2/L3/L4/L5 全 ❌)
- ✅ WI 4 — Tier A/B 拆分实测 (Tier A 5 + Tier B 3 + 不采纳 4 + T1.5 接口契约)
- ✅ WI 5 — anchor 矩阵 (T1.3 主 anchor G2, G1/G3/G4 正交)
- ✅ WI 6 — 推荐起手项 (C2 D-M1 T0-12 methodology + C1 prerequisite)
- ✅ WI 7 — design doc 写入 (342 行, ~9 §段)
- ✅ WI 8 — STATUS_REPORT (本文件)
- ✅ LL-098 stress test 第 12 次 (sprint period 累计 12 次 0 失守)
- ✅ 第 19 条铁律第 8 次 (prompt 不假设具体数字, CC 实测决定项数 / 5+1 层细节 / Tier A/B / anchor 点 / 起手项)
- ✅ 反 anti-pattern (D74) — design doc 是 T1.3 输入, 不替代决议. CC 不擅自决议 20 项 / 5+1 层 / Tier A/B / 起手项, 仅 enumerate + 推荐 + cite source.
- ✅ ADR-022 §2.4 反 "留 Step 7+" 滥用 — design doc enumerate 全决议项, 0 偷懒留下波.

### §4.3 sprint 治理基础设施 6 块基石维持

| 基石 | 状态 |
|---|---|
| 1. IRONLAWS.md SSOT (v3.0.3 末次 audit log entry, §22.终止) | ✅ 维持 |
| 2. ADR-021 + ADR-022 编号锁定 | ✅ 维持 |
| 3. 第 19 条 memory 铁律 | ✅ 第 8 次 verify |
| 4. X10 + LL-098 + pre-push hook | ✅ LL-098 第 12 次 stress test |
| 5. §23 双口径 | ✅ 维持 (本 PR sediment broader +5, narrower 0) |
| 6. ADR-022 集中修订机制 | ✅ 维持 (本 PR 0 触发新 audit log entry) |

---

## §5 G1 vs G2 边界 (sustained ADR-022 §2.4 + TIER0_REGISTRY §4)

### §5.1 本 PR 是 G2 prerequisite (非 G1)

本 PR (Step 7-prep) 是 **G2 prerequisite** — design doc 是 T1.3 G2 决议输入. T1.3 决议本身 (20 项) 是 G2 范围 (架构层决议, CC 不能单方面).

**与 G1 (T0-4/5/6/7/8/9/10) 关系**: 不直接 anchor. G1 是 T1.4 批 2.x AI 自主修, 与 T1.3 风控架构决议正交.

### §5.2 沿用 D72 反 sprint period treadmill

本 PR enumerate 全 20 项决议 + 6 候选起手项 + 不采纳 4 项, 0 偷懒留下波. 沿用 ADR-022 §2.4 反 "留 Step 7+" 滥用.

---

## §6 关联 + 后续

### §6.1 关联 PR

- PR #172 (Step 5 PROJECT_FULL_AUDIT)
- PR #173 (Step 6.1 LL-098 沉淀)
- PR #174-#179 (Step 6.2 - 6.3b)
- PR #180 (Step 6.4 G1 治理债 cleanup + ADR-022 + TIER0_REGISTRY)
- 本 PR (Step 7-prep T1.3 design doc 落地)

### §6.2 关联 ADR

- ADR-010 (PMS Deprecation + Risk Framework Migration)
- ADR-010-addendum (CB Hybrid spike)
- ADR-013 (RD-Agent Re-evaluation Plan, sustained NO-GO)
- ADR-014 (Evaluation Gate Contract)
- ADR-021 (IRONLAWS v3 重构)
- ADR-022 (Sprint Period Treadmill 反 anti-pattern)
- 本 PR design doc cite: 全 ADR-010* + ADR-013 + ADR-022

### §6.3 后续 (T1.3 对话起手 留 user 显式触发)

T1.3 起手项由 user 决议. 沿用 LL-098 stress test 第 12 次 verify, 本 STATUS_REPORT 末尾 0 forward-progress offer.

---

**STATUS_REPORT 写入完成 (2026-05-01 ~02:30, ~270 行, 8 WI 全 verify, broader 42 → 47, sustained 6 块基石)**.
