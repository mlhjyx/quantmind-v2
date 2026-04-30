# Adversarial — 推翻 Claude 假设清单

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 6 / blind_spots/01
**Date**: 2026-05-01
**Type**: adversarial review (sustained framework §5.1)

---

## §0 元说明

User D77 显式开放: "整个项目系统审查, 不固定 Wave 1-4". 沿用 framework §5.1 — Claude 沉淀但 CC 必质疑的:
- Wave 1-4 + 12 framework + 6 升维 完成度声明
- 5+1 层风控架构 (4-29 决议)
- 6 块基石治理胜利
- TIER0_REGISTRY 18 项分类
- ADR-021 / ADR-022 reactive 沉淀 enforcement
- 9+ NO-GO 沉淀完整性
- CORE3+dv_ttm WF PASS sustained
- SignalComposer / DataPipeline / RiskEngine 真覆盖度
- Servy 4 服务 ALL Running 真状态
- regression_test max_diff=0 sustained

CC 主动质疑全部. 本 md 沉淀**真推翻** + 推翻论据.

---

## §1 推翻 Claude 假设 — 真推翻清单

### 1.1 🔴 推翻 "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅"

**Claude 沉淀**: sprint state Session 43-46 sustained "Wave 4 MVP 4.1 Observability batch 1 (PostgresAlertRouter / MetricExporter / AlertRulesEngine) + batch 2.1 (PR #145+146 RiskFrameworkHealth dead-man's-switch) + batch 2.2 ✅".

**CC 实测推翻**: 5 schtask 持续 LastResult=1/2 失败 cluster:
- QM-PTDailySummary (1)
- DataQualityCheck (2)
- PT_Watchdog (1)
- **RiskFrameworkHealth (1) — 自愈机制本身失败 silent failure!**
- ServicesHealthCheck (1) — 5-01 4:30 持续失败 (15min 周期)

**推翻论据**:
- snapshot/03_services_schedule §4 真测 (PowerShell `Get-ScheduledTask` 5-01 04:32 实测)
- "完工" 仅停留在 PR merge, 真生产 enforce 持续失败
- LL-098 X10 同源 anti-pattern (forward-progress offer 反 anti-pattern 印证)

**关联 finding**: F-D78-8 [P0 治理]

---

### 1.2 🔴 推翻 "sprint period 6 块基石治理胜利"

**Claude 沉淀**: sprint state Session 46 末沉淀 sprint period 6 块基石建立 (IRONLAWS / ADR-021 / ADR-022 / 第 19 条 / X10+LL-098 / §23) sustained.

**CC 实测推翻**: 部分推翻 (3/6 ✅ + 2/6 ⚠️ + 1/6 🔴).

**推翻论据**:
- governance/01_six_pillars_roi §2 总评:
  - ADR-022 (基石 3): **🔴 真治理 alpha 低** (reactive + enforcement 失败 + 数字漂移 F-D78-1/7/9/11 仍 active)
  - IRONLAWS SSOT (基石 1): ⚠️ §22 自身复发
  - 第 19 条 (基石 4): ⚠️ handoff 写入层 0 enforcement, sprint state 自身漂移仍 active

**关联 finding**: F-D78-15/16/17/19 [P2 + P0 治理]

---

### 1.3 ⚠️ 推翻 "sprint period 22 PR 链是 sprint period 治理胜利"

**Claude 沉淀**: sprint state sustained "sprint period 治理基础设施 5→6 块基石完整链" (PR #172-#181 跨日).

**CC 实测推翻**: 22 PR 全是治理 / docs / IRONLAWS 重构, **0 业务前进** — sprint period 是 治理 sprint period (governance sprint period), 真治理 vs over-engineering 之比中性偏负.

**推翻论据**:
- governance/01_six_pillars_roi §3 sprint period 22 PR ROI 评估
- D72-D78 4 次反问印证 user 已不耐烦
- ADR-022 反 sprint period treadmill 自身是 sprint period 6.4 G1 PR #180 沉淀 (反 anti-pattern 自身复发)

**关联 finding**: F-D78-19 [P0 治理]

---

### 1.4 ⚠️ 推翻 "TIER0_REGISTRY 18 项分类" 完整性

**Claude 沉淀**: sprint state Session 46 末 "TIER0_REGISTRY 18 unique IDs (T0-1~T0-19 含 T0-13 gap), 9 ✅ closed (T0-1/2/3/11/15/16/17 撤销/18/19) + 9 🟡 待修".

**CC 实测推翻**: 部分推翻.
- T0-19 sustained "已 closed (PR #168+#170)" 但本审查实测 DB live position 4-day stale 仍 active (snapshot/07_business_state §4 + F-D78-4)
- "已 closed" ≠ "真 enforce closed", T0-19 只是代码层 closed, 运维层 stale 仍 active

**推翻论据**:
- snapshot/07_business_state §4 跨源 drift (xtquant vs DB live position 4 trade days stale)
- T0-19 closed 含义模糊 (代码 vs 运维)

**关联 finding**: F-D78-4 [P2]

---

### 1.5 ⚠️ 推翻 "Wave 3 MVP 3.1 Risk Framework 完结" 真生产 enforce

**Claude 沉淀**: sprint state Session 30 "MVP 3.1 Risk Framework 6 PR / 65 新 tests / Celery Beat 5 schedule entries 生产激活 ✅".

**CC 实测推翻**: 
- "5 entries 生产激活" 数字漂移 — 实测 Beat active = 4 entries + 2 PAUSED (4-29 暂停 risk-daily-check + intraday-risk-check 后未及时更新 handoff)
- risk-daily-check + intraday-risk-check 4-29 暂停后 **真生产风控 enforce vacuum**, sprint period sustained "完结" 假设 = 代码层 ✅ 但 真生产层 ⚠️

**推翻论据**:
- snapshot/03_services_schedule §2.2 PAUSED entries 实测
- 4-29 风控 vacuum (sprint state Session 44 沉淀) 印证 PAUSED 后真生产 enforce 失效

**关联 finding**: F-D78-7 [P2]

---

### 1.6 ⚠️ 推翻 "5+1 层风控架构 D-L0~L5 (T1.3 design doc) 落地"

**Claude 沉淀**: sprint state Session 46 末 "T1.3 V3 design doc 342 行沉淀, L1 ✅ 已落地 (MVP 3.1+3.1b ~10 rules), L0/L2/L3/L4/L5 全 ❌ 0 repo sediment, memory only".

**CC 实测**: ✅ Claude 沉淀真实 (沿用 ADR-022 §7.3 缓解原则), **本审查 0 推翻**.

**判定**: ✅ Claude 沉淀真实, **不在推翻清单**.

但 CC 实测加深: **L0 0 实施根因 5 Why 推到底 = Wave 1-4 路线图设计哲学局限** (沿用 risk/01_april_29_5why §2-3, F-D78-21).

---

### 1.7 ⚠️ 推翻 "CORE3+dv_ttm WF OOS Sharpe=0.8659 sustained"

**Claude 沉淀**: sprint state CLAUDE.md sustained "PT 配置 = CORE3+dv_ttm WF OOS Sharpe=0.8659 (2026-04-12 PASS)".

**CC 实测**: ✅ 数字 sustained sprint period 沉淀 (2026-04-12 WF PASS), **本审查未深查**.

**待 verify** (留 sub-md factors / backtest 详查):
- WF OOS Sharpe=0.8659 真复现率 (铁律 15 sustained 但 enforcement 度未实测)
- 4-12 后 PT 真期间 NAV 演进是否 align 0.8659 Sharpe 预期? (snapshot/17_pt_restart_history 留 verify)
- 3 个 active factor (turnover_mean_20 / volatility_20 / bp_ratio) + 1 warning (dv_ttm Session 5 lifecycle ratio=0.517 < 0.8) — sprint state Session 5 警告 (4-18) 未升级为决议

**判定**: ⚠️ 暂不推翻 (本审查未深查), 留 verify candidate.

**finding**:
- F-D78-23 [P2] dv_ttm warning Session 5 (4-18) 未升级决议, sprint period sustained PT 配置仍含 dv_ttm sustained 但 lifecycle ratio < 0.8

---

### 1.8 ✅ 推翻 "Servy 4 服务 ALL Running" — 0 推翻

**CC 实测**: ✅ Servy 4 服务全 Running 5-01 04:16 实测. **本审查 0 推翻**.

但 sprint period sustained "ALL Running" ≠ "ALL 真生产 enforce 健康", 沿用 1.1 推翻 — 5 schtask 持续失败但 Servy 4 服务 Running, **Servy 健康 ≠ schtask + Beat 健康**.

---

### 1.9 ⚠️ 推翻 "regression_test max_diff=0 sustained"

**Claude 沉淀**: 铁律 15 sustained "回测可复现 (regression max_diff=0 硬门)".

**CC 实测**: 本审查未深查最近一次 regression test 真 last-run + 真 max_diff. 留 sub-md backtest 详查.

**待 verify**:
- 最近一次 regression test 真 last-run timestamp
- max_diff 真值 (是 ≤ 1e-9 还是 sprint period sustained 沿用历史值)

**判定**: ⚠️ 暂不推翻, 留 verify candidate.

**finding**:
- F-D78-24 [P3] regression_test max_diff=0 sustained 假设, 真 last-run + 真 max_diff 未 verify, 留 backtest sub-md 深查

---

### 1.10 ⚠️ 推翻 "sprint state 沿用 4-day stale T0-19 known debt audit-only"

**Claude 沉淀**: sprint state Session 45 "DB 4-28 stale 19 行 (T0-19 known debt audit-only)".

**CC 实测推翻**:
- 实测 max(trade_date)=4-27 (sprint state 写"4-28"漂移 1 天, F-D78-1)
- "audit-only" 含义模糊 — 真生产是否真 0 影响? sprint state 沉淀但未深查
- T0-19 sustained "4-29 PT 暂停后已 closed (PR #168+#170)" 但 stale 仍 active (F-D78-4)

**推翻论据**:
- snapshot/07_business_state §4 跨源 drift 真测
- E1-E9 实测 5-01 仍 4-day stale

**关联 finding**: F-D78-1 + F-D78-4

---

## §2 真推翻 vs 部分推翻 vs 0 推翻 总结

| Claude 沉淀 | 推翻判定 | 关联 finding |
|---|---|---|
| Wave 4 MVP 4.1 Observability 完工 | 🔴 真推翻 | F-D78-8 [P0 治理] |
| sprint period 6 块基石治理胜利 | ⚠️ 部分推翻 (3/6 ✅) | F-D78-15/16/17/19 |
| sprint period 22 PR 链 sprint period 治理胜利 | 🔴 真推翻 (sprint period 治理 sprint period 0 业务前进) | F-D78-19 [P0 治理] |
| TIER0_REGISTRY 18 项 closed/待修 | ⚠️ 部分推翻 (T0-19 closed 含义模糊) | F-D78-4 [P2] |
| Wave 3 MVP 3.1 Risk Framework 完结 | ⚠️ 部分推翻 (4-29 PAUSED 后真生产 enforce vacuum) | F-D78-7 [P2] |
| 5+1 层 D-L0~L5 落地 | ✅ 0 推翻 (Claude 沉淀真实) | (深挖根因 F-D78-21) |
| CORE3+dv_ttm WF Sharpe=0.8659 | ⚠️ 暂不推翻 待 verify | F-D78-23 候选 |
| Servy 4 服务 ALL Running | ✅ 0 推翻 | (Servy 健康 ≠ schtask + Beat 健康) |
| regression_test max_diff=0 sustained | ⚠️ 暂不推翻 待 verify | F-D78-24 候选 |
| 4-day stale T0-19 audit-only | ⚠️ 部分推翻 (audit-only 含义模糊) | F-D78-1 + F-D78-4 |

---

## §3 finding 汇总

(本 md 主要是推翻论据沉淀, 0 新 finding 编号. 已链 F-D78-1/4/7/8/15/16/17/19/21/23/24.)

新 finding:
| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-23 | P2 | dv_ttm warning Session 5 (4-18) 未升级决议, sprint period PT 配置仍含 sustained 但 lifecycle ratio=0.517 < 0.8 |
| F-D78-24 | P3 | regression_test max_diff=0 sustained 假设, 真 last-run + 真 max_diff 未 verify (留 backtest sub-md 深查) |

---

## §4 元 verify

### 4.1 反 §7.9 被动 follow 自查
CC 主动质疑 10 项 Claude 沉淀 ✅, 0 follow Claude framework 偷懒.

### 4.2 LL-098 第 13 次 stress test verify
本 md 末尾 0 forward-progress offer ✅.

---

**文档结束**.
