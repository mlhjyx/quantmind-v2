# End-to-End — 路径 5-8 (CC 扩 4 路径)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 3 WI 5 / end_to_end/02
**Type**: 跨领域 + 端到端真路径 (CC 扩 4 路径, sustained framework_self_audit §1.1)

---

## §1 路径 5: 因子发现 → IC 入库 → 画像 → Gate → 回测

**设计声明** (CLAUDE.md sustained §因子评估流程):
1. 经济机制假设 (铁律 13/14)
2. IC 计算+入库 (铁律 11)
3. 画像 (factor_profiler, 5 维)
4. 模板匹配 (T1-T15)
5. Gate G1-G8+BH-FDR
6. 回测验证 (paired bootstrap p<0.05)

**真测 (本审查 partial)**:
- IC 入库: factor_ic_history 113 distinct factor_name (factors/01 §1.1) — 真 enforce ✅
- 263 factor 真测 raw 但 0 IC 入库 (factor_values 276 - 113 = 163, F-D78-58 P2) — 路径 step 2 enforce 失败
- 画像 / Gate / 回测 验证 真 last-run 0 sustained sustained 度量

**finding**:
- F-D78-125 [P2] 路径 5 (因子 onboarding) step 2 (IC 入库) enforce 失败 163 因子真测漏 (factor_values raw 入库但 IC 入库未走), sprint period sustained 铁律 11 sustained sustained 但 enforcement 候选 partial

---

## §2 路径 6: Wave 4 alert → DingTalk → user reply → 决策 (告警闭环)

**设计声明** (sprint period sustained Wave 4 MVP 4.1):
1. AlertRulesEngine fire alert
2. PostgresAlertRouter (alert_dedup 防 spam)
3. DingTalk push to user
4. user reply via DingTalk webhook → broker_qmt sell

**真测**:
- alert_dedup 真 38 fire (operations/03 §1) — step 1+2 真 enforce ✅
- DingTalk push 真触发频率 0 sustained sustained (F-D78-121 候选 reconciliation)
- user reply → broker_qmt sell 真 active 路径 0 sustained (4-29 ad-hoc emergency_close, panic SOP 0 sustained F-D78-49)

**🔴 finding**:
- **F-D78-126 [P1]** 路径 6 (告警闭环) step 3-4 真生产 enforce candidate disconnect (alert dedup ✅ but DingTalk push 真 + user reply 真 0 sustained 实测), 沿用 F-D78-90 同源

---

## §3 路径 7: schtask → Celery Beat → DB → cache → 第二日生效 (调度链路)

**设计声明**:
- Windows schtask (PT 类) + Celery Beat (GP 类) 分工 (CLAUDE.md sustained)
- 触发时间→执行→DB 写入→cache invalidate→第二日生效

**真测**:
- schtask 13 active + 5 持续失败 cluster (snapshot/03 §3.1 F-D78-8 P0 治理)
- Celery Beat 4 active + 2 PAUSED (snapshot/03 §2.2 F-D78-7)
- intraday_risk_check 73 error real 5min 周期 (risk/03 §1 F-D78-115 P0 治理 真测推翻 PAUSED 假设)
- pending_monthly_rebalance 16 expired 历史信号残留 (Phase 3 实测)
- DB 写入: position_snapshot mode='paper' 0 行 + mode='live' 4-day stale (F-D78-4)
- cache invalidate: Parquet cache 0 sustained verify (F-D78-99)
- 第二日生效: 真 enforce 候选 0 sustained sustained

**🔴 finding**:
- **F-D78-127 [P1]** 路径 7 (调度链路) 真 5 schtask + Beat PAUSED 仍触发 + 1241 scheduler_task_log entries 含 73 intraday_risk_check error + 16 pending_monthly_rebalance expired = sprint period sustained Wave 4 batch 2 "调度自愈" sustained 沉淀 vs 真生产持续 silent failure cluster, sustained F-D78-8/115/116/119/120 同源 cluster

### 3.1 pending_monthly_rebalance 16 expired (历史 signal 残留)

实测 result_json:
```json
{"target": {"000858.SZ": 0.05, "600519.SH": 0.05}, "signal_date": "2025-07-31"}
```
error_message: `L1触发延迟月度调仓 signal_date=2025-07-31`

**finding**:
- **F-D78-128 [P2]** pending_monthly_rebalance 16 expired 历史信号残留 (2025-07-31 L1 调仓信号 sustained 跨 sprint period 未清理 sustained), 候选 sub-md 详查

---

## §4 路径 8: PR plan → CC implement → reviewer → AI self-merge (协作闭环)

**设计声明** (sprint period sustained sustained 22 PR 治理 sprint period):
1. user 触发 prompt
2. CC plan (TodoWrite)
3. CC implement
4. reviewer agents (LOW 模式跳 reviewer 候选)
5. AI self-merge

**真测** (sprint period 22 PR sustained 实证):
- LOW 模式 跳 reviewer + AI self-merge sustained sustained
- sprint period 22 PR 0 真 reviewer challenge (sustained F-D78-59 Model Risk Independent validation 同源 — reviewer 是 CC self-review 非真独立)
- sprint period 治理 sprint period 0 业务前进 (F-D78-19 P0 治理)
- D72-D78 4 次反问 印证 user 已不耐烦协作 sprint period sustained

**finding**:
- **F-D78-129 [P1]** 路径 8 (PR 协作闭环) sprint period 22 PR LOW 模式 跳 reviewer + 0 真 reviewer challenge, sprint period 治理 sprint period (F-D78-19 复) sustained sustained

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-125 | P2 | 路径 5 (因子 onboarding) step 2 IC 入库 enforce 失败 163 因子真漏, 铁律 11 enforcement partial |
| **F-D78-126** | **P1** | 路径 6 (告警闭环) step 3-4 真生产 enforce disconnect (alert dedup ✅ but DingTalk push + user reply 真 0 sustained) |
| **F-D78-127** | **P1** | 路径 7 (调度链路) 1241 scheduler_task_log + 73 intraday_risk_check error + 16 expired = sprint period sustained Wave 4 "调度自愈" vs 真生产持续 silent failure cluster |
| F-D78-128 | P2 | pending_monthly_rebalance 16 expired 历史信号残留 (2025-07-31 L1 调仓 sustained 跨 sprint period 未清理) |
| **F-D78-129** | **P1** | 路径 8 (PR 协作闭环) sprint period 22 PR LOW 模式 + 0 真 reviewer challenge, 治理 sprint period sustained sustained |

---

**文档结束**.
