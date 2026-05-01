# Operations Review — Alert Storm 真测 (38 fires in 2 day)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 3 WI 4 / operations/03
**Date**: 2026-05-01
**Type**: 评判性 + 真测 alert_dedup + 推翻 sprint period sustained "alert 真触发 0 sustained" 假设

---

## §1 alert_dedup 真测 (CC 5-01 实测)

实测 SQL:
```sql
SELECT dedup_key, severity, source, last_fired_at, fire_count FROM alert_dedup ORDER BY last_fired_at DESC;
```

**真值 — 3 entries / 38 累计 fire**:

| dedup_key | severity | source | last_fired | fire_count |
|---|---|---|---|---|
| services_healthcheck:degraded:**2026-05-01** | p0 | services_healthcheck | 5-01 14:45:04 | **27** |
| services_healthcheck:degraded:2026-04-30 | p0 | services_healthcheck | 4-30 23:45:04 | 10 |
| pt_watchdog:summary:2026-04-30 | p0 | pt_watchdog | 4-30 20:00:02 | 1 |

**总 fire**: **38 次 in 2 day** (主要 services_healthcheck cluster)

---

## §2 🔴 sprint period sustained "alert 真触发 0 sustained" 假设 部分推翻

| 沿用 sprint period sustained | 真测 |
|---|---|
| F-D78-63 候选 P1 "alert_dedup 真值未深查 (Wave 4 MVP 4.1 alert 真触发统计 0 真测)" | 真测 3 entries / 38 fires (2 day) — sprint period sustained "0 sustained" candidate 部分推翻 |
| Wave 4 MVP 4.1 batch 1 PostgresAlertRouter ✅ | ✅ alert_dedup 表存 + 真触发 (alert routing 真 enforce) |
| Wave 4 MVP 4.1 batch 2.1 RiskFrameworkHealth dead-man's-switch ✅ | ⚠️ 真测 RiskFrameworkHealth schtask LastResult=1 (snapshot/03 §3.1 F-D78-8) — 但**未在 alert_dedup 中**, 候选 silent failure |

---

## §3 真 fire 类别分析

### 3.1 services_healthcheck:degraded (37 fires, 97%)

- 5-01 已累计 27 fires (0:00-14:45, ~1.8 fire/h, sustained 持续告警)
- 4-30 累计 10 fires (推测 startup→23:45 累计)
- **真根因**: services_healthcheck schtask 4:30 + 15min 周期, 沿用 F-D78-8 cluster — `LastResult=1` 持续失败 = degraded alert 持续 fire
- alert_dedup 真 dedup 但 fire_count 累计

### 3.2 pt_watchdog:summary (1 fire)

- 4-30 20:00 触发 1 次, 沿用 F-D78-8 cluster

### 3.3 缺失 candidate 漏触发

实测 sprint period sustained sustained 5 schtask 持续失败 cluster (F-D78-8):
- **PT_Watchdog ✅ 1 fire** (上述)
- **ServicesHealthCheck ✅ 37 fires** (上述)
- **DataQualityCheck ❌ 0 fire in alert_dedup** — schtask LastResult=2 失败但 0 alert
- **RiskFrameworkHealth ❌ 0 fire in alert_dedup** — schtask LastResult=1 失败但 0 alert (sustained dead-man's-switch self-health 真 silent failure!)
- **PTDailySummary ❌ 0 fire in alert_dedup** — schtask LastResult=1 失败但 0 alert

**🔴 finding**:
- **F-D78-116 [P0 治理]** alert_dedup 真测 38 fire/2 day cluster (主要 services_healthcheck:degraded sustained 触发), sprint period sustained Wave 4 MVP 4.1 "完工" alert 路由真有 enforce ✅ but **DataQualityCheck/RiskFrameworkHealth/PTDailySummary 3 schtask 持续失败但 0 alert 触发** = silent failure 漏告警 cluster
- **F-D78-120 [P1]** RiskFrameworkHealth dead-man's-switch self-health 真测 silent failure (schtask 失败 + 0 alert), sprint period sustained PR #145+146 设计意图 = 自愈失败 自动告警, 真生产 0 自愈 0 告警 = 设计 vs 真生产 disconnect

---

## §4 alert storm 真治理评估

实测真值:
- alert dedup 防 spam ✅ (services_healthcheck 27 fires 同 dedup_key, 不会 27 次 push DingTalk)
- 但 **真生产 user 通知频率** 候选未深查 (DingTalk push 真 fire 次数 vs alert_dedup fire_count)
- 候选 finding: alert dedup logic 真 enforce vs DingTalk push 真触发 reconciliation

**finding**:
- F-D78-121 [P2] DingTalk push 真触发频率 vs alert_dedup fire_count reconciliation 0 sustained 实测 (alert dedup 防 spam 设计 sustained 但真 user 通知频率候选)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-116** | **P0 治理** | alert_dedup 真测 38 fire/2 day, services_healthcheck cluster 持续 sustained, **3 schtask (DataQualityCheck/RiskFrameworkHealth/PTDailySummary) 持续失败但 0 alert 触发** silent failure 漏告警 cluster |
| F-D78-120 | P1 | RiskFrameworkHealth dead-man's-switch self-health 真测 silent failure, 设计意图自愈→告警, 真生产 0 自愈 0 告警 disconnect |
| F-D78-121 | P2 | DingTalk push 真触发频率 vs alert_dedup fire_count reconciliation 0 sustained |

---

**文档结束**.
