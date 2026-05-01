# 现状快照 — alert_dedup history (类 16)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 6 WI 3 / snapshot/16
**Date**: 2026-05-01
**Type**: 描述性 + 实测 (sustained operations/03 + Phase 5 §3)

---

## §1 alert_dedup 真测 (CC 5-01 实测)

实测真值 (sustained operations/03 §1):
- 3 entries / 38 fires (4-30 + 5-01)
- services_healthcheck:degraded:5-01 = 27 fire (sustained 14:45 末次)
- services_healthcheck:degraded:4-30 = 10 fire
- pt_watchdog:summary:4-30 = 1 fire

---

## §2 历史趋势

实测 5-01 14:45 累计 27 fire (snapshot 14:45 vs 0:00 累计 ~14h45m → ~1.83 fire/h sustained):
- 沿用 ServicesHealthCheck schtask 4:30 + 15min 周期 = 96 真 trigger/day
- 实际 fire 27 (5-01 partial day) sustained sustained 候选 dedup 真 enforce ✅

候选 finding:
- F-D78-211 [P3] alert_dedup 真历史 (历史多日累计) 0 sustained sustained sustained 度量 (alert_dedup 真表 sustained 仅含 today + yesterday entries, 历史 sustained sustained sustained 0 sustained 度量)

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-211 | P3 | alert_dedup 真历史 (多日累计) 0 sustained 度量 |

---

**文档结束**.
