# Architecture Review — 战略候选 详 (维持 / 修复 / 推翻重做 / 简化)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 4 / architecture/03
**Date**: 2026-05-01
**Type**: 评判性 + Long-term 演进路径战略候选 (sustained framework §3.1 + EXECUTIVE_SUMMARY §4)

**注**: 沿用 D78 + framework §6.3 + LL-098 — **仅候选, 0 决议**.

---

## §1 维持 候选

### 1.1 真金保护双锁

- LIVE_TRADING_DISABLED=True (config.py:44 默认) ✅
- EXECUTION_MODE=paper sustained ✅
- broker_qmt sell only sustained sustained
- (PT 暂停 4-29 后 真金 0 风险 sustained)

### 1.2 6 块基石 sustained 维持 candidate (3/6 ✅)

- ✅ ADR-021 编号锁定
- ✅ X10 + LL-098 + pre-push hook (12 次 stress test 0 失守)
- ✅ §23 双口径

### 1.3 Servy 4 服务 + DataPipeline + Tushare moneyflow 17:30

(sustained sprint period sustained ✅ 部分 enforce ✅)

---

## §2 修复 候选 (sprint period sustained 假设推翻 finding)

### 2.1 5 schtask 持续失败 cluster (F-D78-8 P0 治理)

修复候选: 5 schtask 真 root cause 分析 + fix
- PT_Watchdog / PTDailySummary / DataQualityCheck / RiskFrameworkHealth / ServicesHealthCheck

### 2.2 minute_bars 真断 (F-D78-183 P0 治理 新)

修复候选: Baostock 5min K 线 incremental pipeline 真断 root cause + fix

### 2.3 intraday_risk_check 真根因 (F-D78-115 P0 治理)

修复候选: position_snapshot mode='paper' 0 行 命名空间漂移 fix

### 2.4 alert silent failure cluster (F-D78-116 P0 治理)

修复候选: 3 schtask (DataQualityCheck/RiskFrameworkHealth/PTDailySummary) 持续失败但 0 alert 触发 修

### 2.5 跨源 reconciliation SOP (F-D78-50 P1)

修复候选: broker → DB position_snapshot path 4-29 后 0 触发 修

### 2.6 panic SOP 0 sustained (F-D78-49 + F-D78-146 P1+P2)

修复候选: docs/runbook/cc_automation/panic_sop.md sustained 沉淀

### 2.7 测试基线 sync (F-D78-76 P0 治理)

修复候选: CLAUDE.md / sprint state baseline 数字 sync update (2864 → 4076)

### 2.8 数字漂移 cluster fix (F-D78-1/5/7/9/57/60/81/122/123/147/148/153/171 sustained)

修复候选: ADR-022 ex-ante prevention 加 (handoff 数字必 SQL verify before 写)

---

## §3 推翻重做 候选 (路线图哲学层 + 协作模式)

### 3.1 Wave 1-4 路线图哲学局限 (F-D78-21/25 P0 治理)

推翻重做候选: L0 event-driven enforce 加 (重大架构改变)
- L0 加入 Wave 1-4 路线图 (vs Wave 5+ 候选 sustained sustained)
- 真根因 5 Why 推到底 sustained sustained

### 3.2 4 源协作 N×N 漂移 (F-D78-26 P0 治理)

推翻重做候选: 协作模式简化 (4 源 N×N → 2 源 / 1 源 SSOT)

### 3.3 1 人项目走企业级架构 (F-D78-28 P1)

推翻重做候选: 12 framework + 6 升维 + 4 Wave + 6 块基石 简化
- 1 人项目 vs 企业级理念 disconnect (sustained)

### 3.4 项目目标 vs 真测产出 disconnect (F-D78-33 P0 治理)

推翻重做候选: user/Claude.ai 战略对话决议真目标
- alpha 15-25% vs 治理 maturity 真目标候选

### 3.5 协作 ROI 中性偏负 (F-D78-176 P0 治理)

推翻重做候选: sprint period 治理 sprint period 反思
- 26 PR / ~26h / 0 业务前进 真测验证

---

## §4 简化 候选 (audit 沉淀 over-engineering)

### 4.1 audit 沉淀 N×N 漂移 (F-D78-30 P1)

简化候选: docs review sprint period (合并 / 删 / 简化)

### 4.2 根目录 *.md violation (F-D78-5 P2)

简化候选: 根目录 8 → 7 上限 修

### 4.3 ADR-022 §22 自身复发 (F-D78-15 P2)

简化候选: 治理修

### 4.4 跨文档漂移 broader 84+ (F-D78-46/171 P2)

简化候选: 文档 SSOT 简化 (减 4 源同步 N×N matrix)

### 4.5 CLAUDE.md 30 day 103 commits churn (F-D78-147 P0 治理)

简化候选: CLAUDE.md 进一步简化 / banner 化 / 减 reference 维护成本

---

## §5 战略候选 总结 (本审查 0 决议)

| 候选 | 数 | 关联 finding |
|---|---|---|
| 维持 | 3 类 | 真金保护 / 6 块基石 3 ✅ / Servy + DataPipeline 等 |
| 修复 | 8 类 | 5 schtask / minute_bars / intraday_risk / alert silent / 跨源 / panic / 基线 / 数字漂移 |
| 推翻重做 | 5 类 | Wave 路线图 / 4 源协作 / 企业级架构 / 项目目标 / 协作 ROI |
| 简化 | 5 类 | audit 沉淀 / 根目录 / §22 自身 / 跨文档 / CLAUDE.md churn |

**0 决议** (沿用 D78 + framework §6.3 + LL-098 第 13 次 stress test sustained sustained sustained sustained sustained sustained).

---

## §6 finding 汇总

(本 sub-md 论据沉淀, 0 新 finding 编号. 沿用 sprint period sustained 多 P0 治理 + P1 finding sustained sustained sustained sustained sustained).

---

**文档结束**.
