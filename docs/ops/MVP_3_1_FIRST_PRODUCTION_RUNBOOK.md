# MVP 3.1 Risk Framework 首次真生产触发 Runbook (2026-04-27 Monday)

> **Session 33 交付 (2026-04-24)**: Monday 4-27 首次真生产触发 5 checkpoint 观察清单 + 钉钉/DB/Log 三源验证脚本.
> **背景**: Session 28-30 merged 批 1+2+3 (PR #55-#61), Session 31 merged PR #64 Sunset monitor + PR #63 P0 CB column drift 修复, Session 32 merged PR #65-#68 (schtask wire + shadow prevention).

---

## 目的

MVP 3.1 生产激活后首个交易日 (Monday 2026-04-27) 系统性观察 5 触发点是否按预期工作, 早期发现与 dry-run 行为差异. **非故障排查 runbook** — 是主动 observation 清单.

**关键假设** (Session 31 dry-run 已验证):
- intraday Beat delta -0.0045% << 3% → triggered=0 alerted=0 (prev_close_nav=¥1,012,224)
- daily Beat positions=0 fail-safe post-close (Friday 晚间 run 实测 status=ok checked=0)
- CB adapter column drift 已修 (PR #63), escalate/recover 事件可正确 emit
- PTDailySummary shadow bug 已修 (PR #67), Monday 首次真日报应成功发送

---

## Checkpoint 时间表 (2026-04-27 CST)

| 时间 | Trigger | 观察类型 | 预期 |
|---|---|---|---|
| **Sunday 04:00** | `QuantMind_MVP31SunsetMonitor` 首次 schtask | schtask LastResult + 钉钉 | LastResult=0, 无钉钉 (A+B+C 未满足是 normal, script 自带去重不发) |
| **Sunday 22:00** | Celery Beat `gp-weekly-mining` | Celery log | GP mining 正常跑 (历史已稳定, 仅作背景验证) |
| **Monday 09:00** | 🆕 MVP 3.1 intraday Beat 首次 | Celery log + risk_event_log | intraday_risk_check 返 status=ok, 无 event (盘初) |
| **Monday 09:00-14:55** | intraday 5min × 72 trigger | 累计 | 无 intraday event (除非真 -3%/-5%/-8% drop, 不应有) |
| **Monday 14:30** | 🆕 MVP 3.1 daily Beat 首次 | Celery log + risk_event_log + DB cb_state | daily_risk_check 返 status=ok, positions 非 0 时 checked>0 |
| **Monday 15:40** | DailyReconciliation schtask | DB mismatches | QMT vs DB mismatches=0 (历史稳定) |
| **Monday 16:30** | DailySignal schtask | DB signals + position_snapshot | 20 股新 signal, position_snapshot 写入 |
| **Monday 17:35** | 🆕 PTDailySummary 修复后首次真日报 | **钉钉** | NAV/PnL/持仓 日报钉钉送达 (PR #67 修复生效证据) |
| **Monday 17:35** | PTAudit 同时段 | schtask LastResult + 钉钉 | 5-check PASS → silent (无钉钉), FAIL → 聚合告警 |
| **Monday 18:00** | DailyIC schtask | DB factor_ic_history | 4 CORE factors × horizons upserted |
| **Monday 18:15** | IcRolling schtask | DB ic_ma20/ic_ma60 | 83+ factors ma rolling 刷新 |
| **Monday 18:30** | DataQualityCheck | schtask exit + 钉钉 | exit 0 或 1 (告警滞后天数) |

---

## Checkpoint 1: Sunday 04:00 MVP31SunsetMonitor 首次 schtask

### 观察 (Sunday 04:00-04:05)

```powershell
# 查 schtask 最近结果
Get-ScheduledTaskInfo -TaskName "QuantMind_MVP31SunsetMonitor" | Select-Object LastRunTime, LastTaskResult, NextRunTime
# 预期: LastRunTime ~2026/4/26 4:00, LastTaskResult=0, NextRunTime=2026/5/3 4:00

# 查 log
Get-Content -Tail 30 D:\quantmind-v2\logs\monitor_mvp_3_1_sunset.log
# 预期: "条件 A: 2 日 (< 30 日) / 条件 B: 0 真事件 / 条件 C: flag=False"
```

### 钉钉预期
- **无钉钉** (A+B+C 都未满足, `should_send_dingtalk` 返 False)

### 异常处理
- LastResult 非 0 → 查 log stderr → 根据 error 分诊
- 钉钉发了 → check `notifications` 表 category='mvp_3_1_sunset_gate' 是否误 emit (Session 31 P2 dedup bug)

---

## Checkpoint 2: Monday 09:00 intraday Beat 首触发

### 观察 (Monday 09:00-09:15)

```bash
# Celery worker log
tail -100 D:\quantmind-v2\logs\celery-stdout.log | grep "intraday_risk_check\|risk-intraday"
# 预期: task received + succeeded, status=ok, alerted=0
```

```sql
-- DB 真实事件 (应为空)
SELECT COUNT(*) FROM risk_event_log
WHERE rule_id LIKE 'intraday_%'
  AND triggered_at >= '2026-04-27 00:00:00+08';
-- 预期: 0 (盘初 NAV 基本不动, 无 -3% drop)
```

### 钉钉预期
- **无钉钉** (triggered=0 alerted=0)

### 异常处理
- Celery task 报错 → 查 traceback → `intraday_rule_adapter.py` / `risk_wiring.py` 相关
- 真触发 event (rule_id=intraday_drop_3/5/8) → **这是真告警, 不是系统异常**, 通知 user 查 portfolio

---

## Checkpoint 3: Monday 14:30 daily Beat 首触发

### 观察 (Monday 14:30-14:40)

```bash
tail -100 D:\quantmind-v2\logs\celery-stdout.log | grep "daily_risk_check\|risk-daily"
# 预期: task succeeded, status=ok, checked>0 (positions 非 0 时)
```

```sql
-- CB state 更新 (daily 检查会 upsert cb_state)
SELECT strategy_id, execution_mode, current_level, entered_date, updated_at
FROM circuit_breaker_state
WHERE execution_mode='live' ORDER BY updated_at DESC LIMIT 5;
-- 预期: 看到 live row updated_at ≈ 14:30:xx, current_level=0 (假设未熔断)

-- PMS event
SELECT COUNT(*) FROM risk_event_log
WHERE rule_id LIKE 'pms_%' OR rule_id LIKE 'cb_%'
  AND triggered_at >= '2026-04-27 14:00:00+08';
-- 预期: 0 (post-close, 正常状态)
```

### 异常处理
- `cb_state live` updated_at 未更新 → CB adapter 未跑 → 查 Celery log
- `rule_id LIKE 'cb_%'` 有 event → 真 level 变化, 查 approve_l4.py 若 L4

---

## Checkpoint 4: Monday 17:35 PTDailySummary 首次真日报 (修复证据)

### 观察 (Monday 17:35-17:40)

```powershell
# schtask 结果
Get-ScheduledTaskInfo -TaskName "QM-PTDailySummary" | Select-Object LastRunTime, LastTaskResult
# 预期: LastTaskResult=0 (pre-PR #67: 循环 =1)

# log
Get-Content -Tail 30 D:\quantmind-v2\logs\pt_daily_summary.log
# 预期: "[PT Daily Summary] 2026-04-27", "报告内容: ### 📈/📉 PT 日报", "[DingTalk] 日报已发送"
```

### 钉钉预期
- **✅ 关键证据: 钉钉应收到 `PT日报 2026-04-27 +X.XX%` 标题日报**
- 内容: NAV / 日收益 / 累计收益 / 回撤 / 持仓 / 信号 / 成交

### 异常处理
- LastTaskResult 仍 =1 → 回归 bug, 紧急查 stderr (PR #67 修复未生效?)
- DingTalk 未送达 → 查 httpx POST 返 code, 网络 / token 问题

---

## Checkpoint 5: Monday 18:00-18:30 数据链路

### DailyIC 18:00

```sql
SELECT factor_name, trade_date, horizon, spearman_ic
FROM factor_ic_history
WHERE trade_date = '2026-04-27'
  AND factor_name IN ('turnover_mean_20','volatility_20','bp_ratio','dv_ttm')
ORDER BY factor_name, horizon;
-- 预期: 12 rows (4 CORE × 3 horizons 5/10/20)
```

### IcRolling 18:15

```sql
SELECT factor_name, trade_date, ic_ma20, ic_ma60
FROM factor_ic_history
WHERE trade_date = '2026-04-27'
  AND factor_name IN ('turnover_mean_20','volatility_20','bp_ratio','dv_ttm')
  AND horizon = 20;
-- 预期: ma20/ma60 刷新 (Session 22 Part 8 部署)
```

### DataQualityCheck 18:30

```powershell
Get-ScheduledTaskInfo -TaskName "QuantMind_DataQualityCheck" | Select-Object LastTaskResult
# 预期 exit=0 (全 PASS) 或 exit=1 (轻警: 数据滞后 1 天等)
```

---

## 全局 summary 检查 (Monday 21:00)

```sql
-- 全量 risk_event_log 今日
SELECT rule_id, severity, COUNT(*) FROM risk_event_log
WHERE triggered_at::date = '2026-04-27'
GROUP BY rule_id, severity ORDER BY COUNT(*) DESC;
-- 预期: 0 event (normal day) 或 INFO/P2 level

-- Celery task 成功率
grep -c "Task .* succeeded" D:\quantmind-v2\logs\celery-stdout.log
-- 对比 expected: ~72 intraday + 1 daily + 1 gp + factor-lifecycle (Friday) = ~74+/日
```

### 健康指标
- ✅ 所有 schtask LastResult ∈ {0, 1} (1 = 有滞后告警, not broken)
- ✅ risk_event_log 无 P0 event
- ✅ PTDailySummary 钉钉送达
- ✅ cb_state live row updated_at ≈ 14:30:xx + 16:30:xx (2 次 refresh)

### 异常升级路径
- P0 event (CB level ≥ 3) → 立即 check approve_l4.py + portfolio 实际状态
- schtask 连续 2 日 LastResult 非 0 → 脚本硬化回归 bug 嫌疑, 查 log
- PTDailySummary 钉钉未送 → PR #67 修复回退嫌疑, 查 git log + 重 dry-run

---

## 附录: 关联 PR 与 session

| 组件 | 交付 PR | Session |
|---|---|---|
| MVP 3.1 批 1 (Framework + PMSRule) | #55/#57/#58 | 28 |
| MVP 3.1 批 2 (Intraday + Redis dedup) | #59/#60 | 29-30 |
| MVP 3.1 批 3 (CB Hybrid adapter) | #61 | 30 |
| CB column drift P0 fix | #63 | 31 |
| Sunset monitor script | #64 | 31 |
| Sunset schtask wire | #65 | 32 |
| GPPipeline ps1 cleanup | #66 | 32 |
| PTDailySummary shadow fix | #67 | 32 |
| 6 scripts shadow prevention | #68 | 32 |

## 下一步 (基于 Monday 观察结果)

| Monday 结果 | 后续行动 |
|---|---|
| 全 5 checkpoint PASS | 🟢 Session 33+ 被动维持, Wave 3 下一 MVP plan 模式启动 |
| intraday/daily triggered event | 🟡 正常触发, 核实 portfolio 真实状态, 不改代码 |
| PTDailySummary 钉钉失败 | 🔴 PR #67 回归, hotfix |
| schtask 异常 | 🔴 具体诊断, 小 PR 修 |
| Sunset monitor 误钉钉 | 🟡 Session 31 P2 dedup bug 回归, 小 PR 修 |

---

**维护者须知**: 本 runbook 仅覆盖**首个交易日**. 稳定运行 1 周后可归档到 `docs/ops/archive/`, 日常 observability 交给 Wave 4 (Observability MVP) 统一 dashboard.
