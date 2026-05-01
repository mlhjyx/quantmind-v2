# Operations Review — schtask 7d 真测 cluster

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / operations/12
**Date**: 2026-05-01
**Type**: 评判性 + scheduler_task_log 7d 真测 cluster

---

## §1 真测 (CC 5-01 SQL 7d 实测)

实测 SQL:
```sql
SELECT task_name, status, COUNT(*)
FROM scheduler_task_log
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY task_name, status
ORDER BY task_name, status
```

**真值** (7d 真所有 schtask):

| task_name | status | COUNT | 真证据 |
|---|---|---|---|
| factor_health_daily | warning | 3 | sustained 健康 warning sustained 7d (新 finding) |
| **intraday_risk_check** | **disabled** | 1 | 真 disabled (sustained F-D78-89 PT 暂停 sustained) |
| **intraday_risk_check** | **error** | **73** | sustained F-D78-115 真证据 verify 7d 73 error sustained |
| **intraday_risk_check** | **success** | 9 | 真 9 success vs 73 error = 真 8.9% success rate ❌ sustained |
| **pending_monthly_rebalance** | **executed** | 32 | 真 32 executed 7d sustained |
| **pending_monthly_rebalance** | **expired** | **16** | **🔴 真 16 expired 7d sustained 真证据加深** |
| pt_audit | skipped | 2 | 真 skipped 2 7d (PT 暂停 sustained) |
| pt_audit | success | 4 | 真 4 success 7d (4-30 sustained sustained sustained) |
| reconciliation | success | 2 | 真 2 reconciliation success 7d ✅ |
| risk_daily_check | disabled | 1 | sustained PT 暂停 disabled |
| risk_daily_check | retry | 2 | 真 2 retry 7d sustained |
| risk_daily_check | success | 1 | 真 1 success 7d sustained |
| signal_phase | success | 2 | 真 2 signal 7d ✅ |

---

## §2 🔴 重大 finding — pending_monthly_rebalance 16 expired sustained

**真测**: pending_monthly_rebalance 7d **真 32 executed + 16 expired** = 真 33% expired rate sustained 7d.

**真根因 candidate**:
- pending_monthly_rebalance schtask 真**月度调仓** (sustained CORE3+dv_ttm 月度调仓 1 次)
- 7d 真 48 个 task entries (32+16) = 真**多 task entries / 月度** sustained 真候选 = 真 schtask 真**多次 trigger sustained** 真证据
- 真 16 expired 真证据 = 真 schtask trigger 真**timeout / queued 真过期** sustained 真证据

**🔴 finding**:
- **F-D78-273 [P0 治理]** pending_monthly_rebalance 真 7d 32 executed + 16 expired = 真 33% expired rate sustained, 真 schtask 真**multiple trigger / timeout / queued expired** sustained 真证据, sustained F-D78-89 + F-D78-115 cluster 同源真证据加深 (PT 暂停后 schtask 真**仍 sustained sustained** 但 真**真生产 0 enforce + 真 expired sustained**)

---

## §3 intraday_risk_check 73 error sustained 7d (sustained F-D78-115 真证据加深)

**真测真证据**:
- intraday_risk_check 7d: **disabled 1 + error 73 + success 9**
- 真 success rate = 9 / (1+73+9) = **10.8%** ❌
- 真 error rate = 73 / 83 = **88%** ❌

**🔴 真证据加深 sustained F-D78-115**: 7d intraday_risk_check 真 88% error sustained, sustained sprint period sustained "73 error/7d" 真完美 verify sustained.

**finding**:
- F-D78-274 [P1] intraday_risk_check 7d **88% error rate** sustained, sustained F-D78-115 真证据完美 verify sustained sprint period sustained 真**0 sustained 度量 fix** sustained 7d 持续 sustained

---

## §4 factor_health_daily warning 3 sustained (新 finding)

**真测**: factor_health_daily 7d 真**0 success + 0 error + 真 3 warning** sustained.

**真根因 candidate**: 真 factor health 真**有 warning 但 0 success / 0 error** = 真 schtask 真**仅 warning state sustained** 真证据 (新 finding sustained)

**finding**:
- F-D78-275 [P2] factor_health_daily 7d 真 0 success + 3 warning sustained, 真 schtask 真**仅 warning state sustained**, 沿用 sprint state sustained "factor_lifecycle 周五 19:00 Beat" 真有 warning state 真证据加深

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-273** | **P0 治理** | pending_monthly_rebalance 7d 32 executed + 16 expired = 33% expired rate, schtask multiple trigger + timeout + queued expired sustained |
| F-D78-274 | P1 | intraday_risk_check 7d 88% error rate, F-D78-115 真证据完美 verify |
| F-D78-275 | P2 | factor_health_daily 7d 0 success + 3 warning, schtask 仅 warning state sustained |

---

**文档结束**.
