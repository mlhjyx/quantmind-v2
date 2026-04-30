# PRIORITY_MATRIX — SYSTEM_AUDIT_2026_05

**目的**: 全 finding 严重度矩阵 (P0真金/P0治理/P1/P2/P3 5 级), 渐进式填充 (CC 每完成 sub-md 即追加).

**Status**: 🟡 渐进式填充中 (snapshot 5 + reviews 4 + adversarial 4 + cross_validation 1 = 14 sub-md done)

---

## 严重度定义 (沿用 GLOSSARY F)

| 级别 | 定义 | SOP |
|---|---|---|
| **P0 真金** | 真金 ¥993K 直接风险 | STOP 反问 user 立即 |
| **P0 治理** | 项目治理崩溃 / sprint period 重大假设推翻 | 沉淀 + (audit 末尾决议是否 STOP 反问 user 扩 scope) |
| **P1** | 重要, 影响下次 sprint period 决策 | 沉淀, audit 末尾汇总 |
| **P2** | 一般, 供战略对话参考 | 沉淀 |
| **P3** | 微小, sprint period anti-pattern 候选 | 沉淀 |

---

## P0 真金

(0 触发 — E5/E6 实测 sustained: LIVE_TRADING_DISABLED=True / EXECUTION_MODE=paper / xtquant 0 持仓 / cash=¥993,520.66.)

---

## P0 治理 ⚠️ (7 项, 重大推翻 sprint period sustained 假设)

| ID | 描述 | 来源 sub-md |
|---|---|---|
| **F-D78-8** | 5 schtask 持续 LastResult=1/2 失败 cluster (PT_Watchdog/PTDailySummary/DataQualityCheck/RiskFrameworkHealth/ServicesHealthCheck), sprint period sustained "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅" 重大假设推翻 | snapshot/03_services_schedule §4 |
| **F-D78-19** | sprint period 22 PR 链是治理 sprint period (0 业务前进), 治理价值 vs over-engineering 之比中性偏负, sprint period sustained "6 块基石治理胜利" 假设 部分推翻 | governance/01_six_pillars_roi §3 |
| **F-D78-21** | 4-29 PT 暂停事件真根因 (5 Why 推到底): Wave 1-4 路线图设计哲学局限 = batch + monitor, L0 event-driven enforce 是哲学外维度. user 假设"实施层未到位"深 1-2 层 | risk/01_april_29_5why §2-3 |
| **F-D78-25** | 共同假设 "Wave 路线图最佳" 推翻. 路线图设计哲学局限, 4-29 真金 ~¥6,479 损失印证 | blind_spots/03_shared_assumptions §1.1 |
| **F-D78-26** | 共同假设 "4 源协作有效" 推翻. 4 源 N×N 同步矩阵 sustained 漂移 (5 漂移 finding 印证), sprint period 治理 sprint period 大头是 4 源同步 overhead | blind_spots/03_shared_assumptions §1.2 |
| **F-D78-33** | User 项目目标 (alpha 15-25%) vs 真测投入产出 (治理 + Observability) disconnect, 真目标候选 = 治理 maturity 而非 alpha | blind_spots/02_user_assumptions §1.5 |
| **F-D78-48** | 项目 bus factor 极低. User 退出 N 月后接手者 onboarding 极困难 (4 源协作漂移 + 70-110 audit md 无 SOP + 真生产 self-recover 0). 沿用 F-D78-13 + F-D78-41 | business/01_workflow_economics §3 |

---

## P1 (8 项)

| ID | 描述 | 来源 sub-md |
|---|---|---|
| F-D78-27 | 共同假设 "三领域 V3 同步升级" 推翻, 候选风控 V3 独立优先 | blind_spots/03_shared_assumptions §1.4 |
| F-D78-28 | 共同假设 "1 人量化走企业级架构" 候选推翻 (CC 扩), 候选简化 candidate | blind_spots/03_shared_assumptions §1.5 |
| F-D78-29 | 共同假设 "PT 重启 5d dry-run = 充分条件" 推翻 (CC 扩), 候选 prerequisite 重审 | blind_spots/03_shared_assumptions §1.6 |
| F-D78-30 | 共同假设 "audit 沉淀越多越好" 候选推翻 (CC 扩), 候选文档审 sprint period 启动 | blind_spots/03_shared_assumptions §1.7 |
| F-D78-31 | User 时间投入 vs 项目产出经济性候选推翻, NAV ~-0.65% + 0 业务前进 + 全职 N 月 | blind_spots/02_user_assumptions §1.3 |
| F-D78-32 | 协作模式 (Claude.ai + CC + memory + repo 4 源) 候选推翻有效性 | blind_spots/02_user_assumptions §1.4 |
| F-D78-41 | Unknown unknown — User 健康 + 持续性 + 项目 bus factor 风险未深查 | blind_spots/04_unknown_unknowns §1.7 |
| F-D78-49 | panic SOP 沉淀 0 (4-29 ad-hoc), 候选 docs/runbook/cc_automation/panic_sop.md sustained 沉淀 | business/01_workflow_economics §4 |

---

## P2 (15 项)

| ID | 描述 | 来源 sub-md |
|---|---|---|
| F-D78-1 | sprint state handoff 数字漂移 (写 "DB 4-28 stale" 真值 4-27, 错 1 天) | snapshot/07_business_state §4 |
| F-D78-4 | DB live position vs xtquant 真账户 4 trade days stale (T0-19 sustained, 仍 active) | snapshot/07_business_state §4 |
| F-D78-5 | 根目录 8 *.md (多 3 未授权), CLAUDE.md §文件归属规则 reactive 治理失败 | snapshot/01_repo_inventory §2 |
| F-D78-7 | sprint state Session 30 "5 schedule entries 生产激活" 数字漂移 (实测 active=4 + 2 PAUSED) | snapshot/03_services_schedule §2.4 |
| F-D78-10 | 死表 candidate margin_detail (902 MB / 0 rows) + northbound_holdings (648 MB / 0 rows), 未 deprecated 标记 | snapshot/02_db_schema §3 |
| F-D78-13 | 项目 git 全 history 仅 90 day (741 commits 全集中近 90 day), bus factor 高风险 | snapshot/01_repo_inventory §3 |
| F-D78-15 | ADR-022 反 §22 entry 但 §22 entry sustained 累计 (反 anti-pattern 自身复发) | governance/01_six_pillars_roi §1.1 |
| F-D78-16 | ADR-022 ex-post 沉淀但 ex-ante prevention 缺, 数字漂移仍 active (F-D78-1/7/9/11 印证) | governance/01_six_pillars_roi §1.3 |
| F-D78-17 | 第 19 条 memory 铁律 prompt 层 enforce 但 handoff 写入层 0 enforce, sprint state 漂移仍 active | governance/01_six_pillars_roi §1.4 |
| F-D78-22 | T1.3 V3 design doc 342 行沉淀但真接入点路径未 demonstrate | risk/01_april_29_5why §5 |
| F-D78-20 | 4-29 后 STAGED 决策权路径 0 推进, 真生产仍 user 100% 手工 | risk/01_april_29_5why §6 |
| F-D78-23 | dv_ttm warning Session 5 (4-18) 未升级决议, sprint period PT 配置仍含 sustained 但 lifecycle ratio < 0.8 | blind_spots/01_claude_assumptions §1.7 |
| F-D78-34 | D78 决议本身候选不完美 (context limit 风险 + 反 treadmill 可能新 sprint period 起点) | blind_spots/02_user_assumptions §1.6 |
| F-D78-35 | Unknown unknown — broker 视角看项目状态未深查 (broker 端风控 / 月报 / 资金分类) | blind_spots/04_unknown_unknowns §1.1 |
| F-D78-36 | Unknown unknown — 项目硬件成本累计真值未深查 | blind_spots/04_unknown_unknowns §1.2 |
| F-D78-38 | Unknown unknown — 第三方源真 ToS + 真稳定性 + 单点失败风险未深查 | blind_spots/04_unknown_unknowns §1.4 |
| F-D78-39 | Unknown unknown — 个人量化交易合规法规边界未深查 | blind_spots/04_unknown_unknowns §1.5 |
| F-D78-40 | LLM cost 累计真值未深查 | blind_spots/04_unknown_unknowns §1.6 |
| F-D78-42 | Unknown unknown — 项目数据未来 N 年演进风险未深查 | blind_spots/04_unknown_unknowns §1.8 |
| F-D78-43 | 候选: 3 源 N×N 漂移矩阵 sustained, 同 fact 跨 3 源描述真一致性未深查 | cross_validation/01_doc_drift_broader §1.4 |
| F-D78-45 | 表层 (CLAUDE.md) / 中层 (sprint state) / 真生产层 3 维 drift, 表层 vs 真生产层差距大 | cross_validation/01_doc_drift_broader §1.6 |
| F-D78-46 | 跨文档漂移 broader 累计 70+ (sprint period 47 + 本审查 22+), ADR-022 反"数字漂移" enforcement 失败实证扩 | cross_validation/01_doc_drift_broader §2 |
| F-D78-47 | Beat + schtask 跨调度 fact 候选 redundancy (DataQualityCheck 同名候选 双重调度) | cross_validation/01_doc_drift_broader §3 |

---

## P3 (10 项)

| ID | 描述 | 来源 sub-md |
|---|---|---|
| F-D78-2 | sprint state handoff 用 `cb_state` 别名 + `source` 字段, 真表 `circuit_breaker_state` + `execution_mode` 字段 | snapshot/07_business_state §2 + GLOSSARY C |
| F-D78-3 | DINGTALK_SECRET=空 (signature 验签 disabled, 仅 keyword=xin 1 锁) | E5 实测 / 待 security 领域沉淀 |
| F-D78-9 | CLAUDE.md "factor_values hypertable 152 chunks" 数字漂移, 实测 chunk ID 已超 152 | snapshot/02_db_schema §1.3 |
| F-D78-11 | schtask trigger time 漂移 (DataQualityCheck sprint state 17:45 → 真 18:30) | snapshot/03_services_schedule §5 |
| F-D78-12 | xtquant cash 4-30 14:54 ¥993,520.16 → 5-01 04:16 ¥993,520.66, 差 ¥0.50 (微小利息或费用, 非 anomaly) | snapshot/07_business_state §4 |
| F-D78-14 | docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md untracked draft, 与 PR #181 沉淀的 T1_3_RISK_FRAMEWORK_DECISION_DOC.md 关系 sprint state 未明确 | snapshot/01_repo_inventory §6 |
| F-D78-18 | X10 候选 12 次 stress test 0 失守, 候选 framework v3.0 promote 到 T1/T2 | governance/01_six_pillars_roi §1.5 |
| F-D78-24 | regression_test max_diff=0 sustained 假设, 真 last-run + 真 max_diff 未 verify (留 backtest sub-md 深查) | blind_spots/01_claude_assumptions §1.9 |
| F-D78-37 | 项目 846 *.py 死码 + 真生产 path 比例未深查, 候选 ruff / mypy 全 repo 静态扫描 | blind_spots/04_unknown_unknowns §1.3 |
| F-D78-44 | sprint state Session 内 fact drift 高发, 后续 Session 修订印证 sprint state handoff 写入层 0 verify enforcement | cross_validation/01_doc_drift_broader §1.5 |

---

## 统计

| 严重度 | 当前数 |
|---|---|
| P0 真金 | 0 |
| **P0 治理** | **7** ⚠️ |
| P1 | 8 |
| P2 | 22 |
| P3 | 10 |
| **小计** | **47** |

---

## sprint period sustained 假设推翻清单 (汇总)

| 假设 | 真值 | 来源 |
|---|---|---|
| **sprint state sustained "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅"** | 5 schtask 持续 LastResult=1/2 失败, 含 RiskFrameworkHealth 自愈机制本身失败 | F-D78-8 |
| sprint period sustained "6 块基石治理胜利" | 部分推翻 (3/6 ✅ + 2/6 ⚠️ + 1/6 🔴 ADR-022 reactive + enforcement 失败) | F-D78-19 |
| sprint state Session 30 "5 schedule entries 生产激活" | active=4 + 2 PAUSED | F-D78-7 |
| sprint state Session 45 "DB 4-28 stale 19 行" | max(trade_date)=2026-04-27, 错 1 天 | F-D78-1 |
| sprint state Session 45 "T0-19 known debt audit-only" | 仍 active (本审查 4-30 + 5-01 实测仍未自愈) | F-D78-4 |
| CLAUDE.md "factor_values hypertable 152 chunks" | 实测 chunk ID 已超 152 | F-D78-9 |
| CLAUDE.md §文件归属规则 (根目录 7 上限) | 实测 8 (多 3 未授权) | F-D78-5 |
| 共同假设 "Wave 路线图最佳" | 推翻, 路线图设计哲学局限 | F-D78-25 |
| 共同假设 "4 源协作有效" | 推翻, N×N 漂移矩阵 | F-D78-26 |
| User 项目目标 "alpha 15-25%" | 真测投入产出 disconnect, 真目标 = 治理 maturity 候选 | F-D78-33 |
| User 假设 "4-29 真根因 = 盘中 + 风控未设计" | 真根因深 3 层 = 路线图设计哲学局限 | F-D78-21 |
| User 隐含 "项目全职投入合理" | 经济性候选推翻 (NAV ~-0.65% + 0 业务前进) | F-D78-31 |

---

**文档结束 (渐进填充中)**.
