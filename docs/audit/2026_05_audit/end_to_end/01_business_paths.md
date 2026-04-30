# End-to-End Review — 4 业务路径真测

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 5 / end_to_end/01
**Type**: 跨领域 + 端到端真路径 (sustained framework §4.1, 4 路径)

---

## §1 路径 1: 数据 → 因子 → 信号 → 回测

**设计声明**: Tushare/AKShare/QMT/Baostock → DataPipeline → factor_values → SignalComposer → run_backtest → 真 baseline

**真测 verify** (本审查未深 trace, 候选 finding):
- DataPipeline 唯一入口 (铁律 17, sprint period sustained sustained)
- factor_values 276 distinct factor_name 真测 (factors/01 §1)
- SignalComposer sprint period sustained sustained (PR #116 PlatformSignalPipeline)
- run_backtest 真 last-run 未本审查 verify (sustained F-D78-84 同源)

**finding**:
- F-D78-87 [P2] 路径 1 端到端真 last-trace + 真 dropoff 0 sustained, candidate sub-md 详 trace

---

## §2 路径 2: 数据 → 因子 → 信号 → PT (真账户)

**设计声明**: 同路径 1, 换 PT 真账户.

**真测**:
- PT 暂停 sustained (4-29 sustained sustained), 路径 2 真生产 0 active
- 真账户 0 持仓 / cash ¥993,520.66 (E6 实测 sustained)

**finding**:
- F-D78-88 [P1] 路径 2 自 4-29 后 0 active, sprint period sustained "PT 重启 prerequisite" gate 候选 (沿用 F-D78-29 5d dry-run vs 充分条件推翻)

---

## §3 路径 3: PT → 风控 → broker_qmt → 真账户

**设计声明**: PMSRule (L1 14:30 Beat) + SingleStockStopLoss + ConcentrationGuard + 等 ~10 rules → broker_qmt sell only → 真账户

**真测**:
- 风控 14:30 Beat PAUSED sustained (sprint period sustained 4-29 暂停, snapshot/03 §2.2)
- risk_event_log 仅 2 entries 全 audit log (risk/02 §1)
- broker_qmt sell only sustained sustained, design 含 buy 候选 (security/01 §4 F-D78-75)
- **路径 3 真生产 enforce 0 active** (4-29 后)

**🔴 finding**:
- **F-D78-89 [P0 治理]** 路径 3 自 4-29 后 真生产风控 enforce 0 active, sprint period sustained "Wave 3 MVP 3.1 Risk Framework 完结" 推翻再印证 (沿用 F-D78-7 P2 + risk/02 §1 真测验证)

---

## §4 路径 4: 告警 → user → 决策 → 执行

**设计声明**: DingTalk push → user reply → broker_qmt sell

**真测**:
- DingTalk webhook 配置 (E5) + secret=空 (F-D78-3 1 锁)
- DingTalk push 真 last-trigger 未本审查 verify (sustained F-D78-63 alert_dedup 真值未深查)
- user reply → broker_qmt sell: ad-hoc (4-29 emergency_close 路径 sustained sprint state Session 44, 0 sustained panic SOP F-D78-49)

**finding**:
- F-D78-90 [P1] 路径 4 真 last-trigger 0 sustained, panic SOP 0 sustained (sustained F-D78-49)

---

## §5 8 路径扩 (CC 扩, framework_self_audit §1.1 4 端到端 → 8)

5 路径: **因子发现 → IC 入库 → 画像 → Gate → 回测** (factor onboarding 路径)
- 真测: factor_values 276 → factor_ic_history 113, 163 因子有 raw 但 0 IC 入库 (factors/01 §1.1 F-D78-58)
- 候选 sub-md detail

6 路径: **Wave 4 MVP 4.1 alert → DingTalk → user reply → 决策** (告警闭环)
- 真测: alert 真触发统计 0 sustained (F-D78-63), 5 schtask 持续失败 cluster (F-D78-8) 含 RiskFrameworkHealth 自愈失败 silent failure
- 候选 sub-md detail

7 路径: **schtask → Celery Beat → DB → cache → 第二日生效** (调度链路)
- 真测: schtask 13 active + 5 持续失败 (snapshot/03 §3.1)
- 候选 sub-md detail

8 路径: **PR plan → CC implement → reviewer → AI self-merge** (协作闭环)
- 真测: sprint period 22 PR 链 sustained, sprint period 治理 sprint period (F-D78-19 P0 治理), reviewer 候选独立性问题 (F-D78-59 Model Risk Independent validation)
- 候选 sub-md detail

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-87 | P2 | 路径 1 端到端真 last-trace + 真 dropoff 0 sustained |
| F-D78-88 | P1 | 路径 2 自 4-29 后 0 active, prerequisite 候选推翻 (F-D78-29) |
| **F-D78-89** | **P0 治理** | 路径 3 自 4-29 后 真生产风控 enforce 0 active, "Wave 3 MVP 3.1 Risk Framework 完结" 推翻再印证 |
| F-D78-90 | P1 | 路径 4 真 last-trigger 0 sustained, panic SOP 0 sustained |
| (路径 5-8) | (待详 sub-md) | CC 扩 4 路径 |

---

**文档结束**.
