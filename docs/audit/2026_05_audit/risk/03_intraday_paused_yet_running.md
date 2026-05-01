# Risk Review — intraday_risk_check 真测推翻 "4-29 暂停" 假设

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 3 WI 4 / risk/03
**Date**: 2026-05-01
**Type**: 评判性 + 真测 推翻 sprint period sustained 假设

---

## §1 真测真值 (CC 5-01 实测 scheduler_task_log)

实测 SQL:
```sql
SELECT task_name, status, COUNT(*)
FROM scheduler_task_log
WHERE start_time >= NOW() - INTERVAL '7 days'
GROUP BY task_name, status;
```

**真值** (intraday_risk_check 7 day):
- `error`: **73** 次
- `success`: 9 次
- `disabled`: 1 次

**最新 5 entries** 全 status=error (4-30 14:40 / 14:45 / 14:50 / 14:55 sustained 5min 周期).

---

## §2 🔴 真根因找到 (推翻 sprint period sustained "4-29 暂停" 假设)

### 2.1 真 error_message

实测 result_json:
```json
{
  "error": "RuntimeError: [IntradayRisk] All 1 strategies failed: PositionSourceError: position_snapshot no rows for strategy=28fc37e5-2d32-4ada-92e0-41c11a5103d0 mode=paper",
  "status": "error"
}
```

### 2.2 真根因解析

**链条**:
1. sprint state Session 44 沉淀 4-29 PT 暂停决议
2. schtask `QuantMind_IntradayMonitor` Disabled (snapshot/03 §3.2 ✅) — but **Celery Beat `intraday-risk-check` PAUSED 仅 source code 注释** (snapshot/03 §2.2)
3. 真测验证: **Celery Beat 仍 5min trigger intraday_risk_check task** (是否真 PAUSED 待 verify, 真测显示 5min 周期 sustained 触发)
4. trigger 时 strategy=PAPER_STRATEGY_ID (28fc37e5...) mode='paper' 查 position_snapshot
5. **position_snapshot mode='paper' 真值 = 0 行** (sustained snapshot/07 §3 真测 only mode='live' 19 行 4-day stale)
6. PositionSourceError raise → IntradayRisk fail → status=error 73 次/7 day

### 2.3 命名空间漂移真因 (沿用 sprint state Session 44 sustained)

实测推断:
- position_snapshot 仅 mode='live' 数据 (19 行 4-27 stale, F-D78-4)
- mode='paper' 0 行
- intraday_risk_check 跑 mode='paper' (沿用 EXECUTION_MODE=paper sustained .env)
- **真生产 mode/strategy 命名空间漂移 sustained sustained**

---

## §3 sprint period sustained "PAUSED" 假设 真推翻

| 沿用 sprint period sustained | 真测 5-01 |
|---|---|
| Beat schedule entry `intraday-risk-check` PAUSED 4-29 (snapshot/03 §2.2) | ⚠️ 可能仅 source code 注释, 真生产 5min 周期仍触发 |
| schtask `QuantMind_IntradayMonitor` Disabled ✅ | ✅ 真 Disabled (snapshot/03 §3.2) |
| risk_event_log 0 真生产触发 (sprint state Session 44) | ✅ 真 2 entries 全 audit log (risk/02 §1) |

**🔴 finding**:
- **F-D78-115 [P0 治理]** intraday_risk_check 5min 周期真测 sustained 触发 73 次 error in 7 day, 真根因 = position_snapshot mode='paper' 0 行 (PAPER_STRATEGY_ID 命名空间漂移). sprint period sustained "Beat intraday-risk-check PAUSED 4-29" 假设候选推翻 (Beat 是否真 stop 待 verify, 真测每 5min trigger error)
- **F-D78-118 [P1]** position_snapshot mode/strategy 命名空间漂移 sustained — 仅 mode='live' 19 行 4-day stale (F-D78-4) + mode='paper' 0 行, 跨 mode/strategy 一致性候选 0 sustained sustained 治理

---

## §4 Silent failure 性质评估

实测真测:
- 73 error in 7 day = ~10 error/day
- error_message 字段 = None (写 result_json 不写 error_message)
- 真生产**用户 0 通知** (DingTalk 是否 fired? 沿用 alert_dedup 真测 — 真测 services_healthcheck fire 27/2 day, 但 intraday_risk_check **不在 alert_dedup**)

**finding**:
- **F-D78-119 [P0 治理]** intraday_risk_check error 73 次 silent failure, 用户 0 通知 (alert_dedup 不含 intraday_risk_check fire), sprint period sustained sustained 沉淀 33 (silent_failure 反 anti-pattern) enforcement 失败

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-115** | **P0 治理** | intraday_risk_check 真测 73 error/7 day, 真根因 position_snapshot mode='paper' 0 行 (命名空间漂移). sprint period sustained "Beat PAUSED 4-29" 假设候选推翻 |
| F-D78-118 | P1 | position_snapshot mode/strategy 命名空间漂移 sustained (mode='live' 19 行 4-day stale + mode='paper' 0 行) |
| **F-D78-119** | **P0 治理** | intraday_risk_check 73 次 silent failure, 用户 0 通知, 铁律 33 (silent_failure 反 anti-pattern) enforcement 失败 |

---

**文档结束**.
