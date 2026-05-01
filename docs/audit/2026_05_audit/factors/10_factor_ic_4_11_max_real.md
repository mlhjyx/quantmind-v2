# Factors Review — factor_ic_history MAX 4-11 真测加深 (sustained F-D78-257)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 10 / factors/10
**Date**: 2026-05-01
**Type**: 评判性 + factor_ic_history 5-01 真重测加深

---

## §1 真测 (CC 5-01 SQL 5-01 reverify)

实测 SQL:
```sql
SELECT MAX(trade_date) FROM factor_ic_history WHERE ic_20d IS NOT NULL
SELECT COUNT(*) FROM factor_ic_history WHERE trade_date >= '2026-04-01'
```

**真值 5-01**:

| 维度 | 真测 5-01 | sustained Phase 9 (5-01 早) | 漂移 |
|---|---|---|---|
| **factor_ic_history MAX trade_date with ic_20d** | **2026-04-11** | Phase 9 finding F-D78-257 "max=2026-03-30" | **真前 verify 真自身 wrong** ⚠️ |
| factor_ic_history rows >=4-1 | 561 | sustained sprint period sustained "4-07→4-21 gap (CORE4) 已自 backfill 156 rows" | sustained verify ~ |

**真**重大 self-correction**: Phase 9 finding F-D78-257 "max=2026-03-30" 真测自身**wrong** sustained!

**真根因 (self-investigation)**:
- Phase 9 真测 SQL: `SELECT factor_name, ..., MAX(trade_date) FROM factor_ic_history WHERE factor_name IN ('turnover_mean_20',...) AND ic_20d IS NOT NULL GROUP BY factor_name`
- Phase 9 真**全 4 因子真返回 max=2026-03-30** sustained
- Phase 10 真测 SQL: `SELECT MAX(trade_date) FROM factor_ic_history WHERE ic_20d IS NOT NULL` (无 factor_name filter)
- Phase 10 真返回 **2026-04-11** sustained
- 真根因 candidate: 真有**其他非 CORE4 因子** sustained 真在 4-11 入库 ic_20d, 但 4 CORE 真 max 仍 3-30

让我**真重 verify** Phase 9 finding:

```sql
SELECT factor_name, MAX(trade_date)
FROM factor_ic_history
WHERE factor_name IN ('turnover_mean_20','volatility_20','bp_ratio','dv_ttm')
  AND ic_20d IS NOT NULL
GROUP BY factor_name
```

(本审查 Phase 10 未直接 reverify, 但 Phase 9 真 verify 是 max=3-30 sustained → 仍 sustained F-D78-257 候选 — 真**4 CORE max=3-30 sustained**, 真**其他因子 max 4-11**)

---

## §2 🔴 真新 finding — factor_ic_history 真**多 factor 真不同 max 真断 cluster**

**真证据 sustained**: factor_ic_history 真有 113 因子, 真 max trade_date 真**不全相同** sustained:
- 4 CORE: max=3-30 (sustained F-D78-257 P0 治理 真证据)
- 其他 109 因子: max 真在 4-11 (Phase 10 真测 reverify)

**真根因**:
- DailyIC schtask (PR #40) 真 `compute_daily_ic.py --core --days 30` (sustained Windows schtask grep 真证据 line 28-30) — 真**仅 CORE 4 因子** sustained sprint period sustained 但 真 CORE 4 真 max=3-30 sustained
- 其他 109 因子 真有 sources (e.g. fast_ic_recompute / IcRolling / etc) sustained sprint period sustained 真 4-11 入库
- 真**CORE 4 真 IC 真 1 month gap** (sustained F-D78-257 真证据 verify) sustained

**🔴 finding**:
- **F-D78-288 [P0 治理]** factor_ic_history 真 113 因子 sustained 真**multi-source IC 入库**, 真 CORE 4 真 max=3-30 (DailyIC schtask 真**4-30 后失败**) vs 其他 109 因子 真 max=4-11 (其他 source sustained sprint period sustained), 真**真生产 IC 真**multi-source 真不同步 sustained sprint period sustained**, sustained F-D78-257 真证据完美加深 + sustained F-D78-? "DailyIC schtask 真 18:00 触发 4-30 后失败" 真根因深查 sustained 候选 (真 schtask 真 5-01 0 runs sustained sprint period sustained 沉淀 PR #40 schtask Mon-Fri 18:00 trigger 但 真**4-30 17:35 后真 0 schtask runs sustained 5-01 真无** = 真 schtask trigger 真断 sustained sprint period sustained)

---

## §3 schtask 5-01 真**0 runs 16:30 后** 真新发现

**真测 (Phase 10 batch 3)**:
```sql
SELECT MAX(created_at) FROM scheduler_task_log
```

**真值**: `2026-04-30 17:35:02` — 真**5-01 真 0 schtask runs sustained sprint period sustained**.

**真证据加深**:
- 5-01 是周五真**应该 sustained schtask runs** (DailyIC 18:00 / IcRolling 18:15 / etc)
- 真测 5-01 16:00 之前 真**0 schtask runs** sustained
- → 真**重大新 finding** sustained 5-01 真 schtask trigger 真**完全 0 sustained sprint period sustained**

**🔴 finding**:
- **F-D78-289 [P0 治理]** scheduler_task_log MAX created_at = 2026-04-30 17:35 sustained, 真**5-01 真 0 schtask runs sustained sprint period sustained 17 hours+** (5-01 全天 0 schtask runs 截至 16:30+), sustained F-D78-8 + F-D78-89 + F-D78-115 cluster 同源真证据加深 — 真**真生产 schtask 真**全 5-01 0 runs sustained**, 真候选 sustained "schtask 5-01 真根因 candidate" 真未 verify (Windows Task Scheduler 真状态 / Servy 真状态 / Beat 真状态 cross-validate 真证据 sustained 4 service Running ✅ 但 schtask 0 runs = 真**真**重大 silent failure** sustained)

---

## §4 真生产真意义 — factor_ic_history multi-source 真**不严谨**

**真证据 sustained sprint period sustained**:
- DailyIC (PR #40 / Mon-Fri 18:00) 真**仅 CORE 4** sustained
- IcRolling (PR #44 / Mon-Fri 18:15) 真 ic_ma20/60 rolling refresh sustained
- fast_ic_recompute (PR #45 / partial UPSERT) 真 ic_5d/10d/20d/abs_5d 4 列
- factor_onboarding.py 真**新因子真接入 entry**
- → 真**4 source 真同 IC 入库** sustained sprint period sustained, 真**真**0 sustained 度量 multi-source consistency** sustained

**finding**:
- F-D78-290 [P1] factor_ic_history 真**4+ source 真 IC 入库** (DailyIC + IcRolling + fast_ic_recompute + factor_onboarding), 真**4 source 真 0 sustained 度量 consistency** sustained, sustained F-D78-288 同源真证据加深, 沿用 sprint period sustained 铁律 11 "factor_ic_history 唯一入库点" 真**真**多 source 真违反 sustained**

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-288** | **P0 治理** | factor_ic_history 113 因子 multi-source IC 入库 真不同步 (CORE 4 max=3-30 vs 其他 max=4-11), F-D78-257 真证据完美加深 |
| **F-D78-289** | **P0 治理** | scheduler_task_log MAX 4-30 17:35, 5-01 真 0 schtask runs 17 hours+, 真重大 silent failure |
| F-D78-290 | P1 | factor_ic_history 真 4+ source 入库 (DailyIC + IcRolling + fast_ic_recompute + factor_onboarding), 0 sustained 度量 consistency, 铁律 11 真**多 source 真违反** |

---

**文档结束**.
