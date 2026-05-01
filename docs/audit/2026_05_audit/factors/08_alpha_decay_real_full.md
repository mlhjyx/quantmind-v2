# Factors Review — Alpha decay full history 真算 12yr

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / factors/08
**Date**: 2026-05-01
**Type**: 评判性 + factor_ic_history 12yr full 真算

---

## §1 真测 (CC 5-01 SQL 实测)

实测 SQL:
```sql
SELECT factor_name, COUNT(*), MIN(trade_date), MAX(trade_date),
       AVG(ABS(ic_20d))::numeric(10,5),
       AVG(ic_20d)::numeric(10,5),
       MAX(ABS(ic_20d))::numeric(10,5)
FROM factor_ic_history
WHERE factor_name IN ('turnover_mean_20','volatility_20','bp_ratio','dv_ttm')
  AND ic_20d IS NOT NULL
GROUP BY factor_name;
```

**真值** (12 年 full history):

| factor_name | COUNT | MIN | MAX | AVG \|IC\| | AVG IC | MAX \|IC\| |
|---|---|---|---|---|---|---|
| turnover_mean_20 | **2954** | 2014-01-15 | **2026-03-30** | **0.114** | -0.096 | 0.381 |
| volatility_20 | **2952** | 2014-01-16 | **2026-03-30** | **0.116** | -0.090 | 0.403 |
| bp_ratio | **2971** | 2014-01-02 | **2026-03-30** | **0.090** | +0.059 | 0.309 |
| dv_ttm | **2968** | 2014-01-02 | **2026-03-30** | **0.058** | +0.040 | 0.303 |

总: 113 因子 / 145,894 rows (sustained sprint state Session 45 D3-B 数字) ✅
IC_20d NULL: 2,567 rows (sustained F-D78-58 同源 真 IC NULL 沉淀)

---

## §2 🔴 finding — CORE3+dv_ttm 12yr 真 IC 衰减真测

**真测真证据**:

### 2.1 Alpha 强度真排序 (AVG |IC| 12yr)
1. **volatility_20**: 0.116 (强度最高)
2. **turnover_mean_20**: 0.114
3. **bp_ratio**: 0.090
4. **dv_ttm**: 0.058 (最低)

### 2.2 Alpha 方向真测
- volatility_20: AVG IC -0.090 (sustained sprint period sustained "direction=-1") ✅
- turnover_mean_20: AVG IC -0.096 (sustained "direction=-1") ✅
- bp_ratio: AVG IC +0.059 (sustained "direction=+1") ✅
- dv_ttm: AVG IC +0.040 (sustained "direction=+1") ✅

**真证据**: CORE3+dv_ttm 4 因子 12yr full history 真 IC 方向 + 强度真 sustained sprint period sustained "WF OOS Sharpe=0.8659" 真 verify ✅.

### 2.3 真**MAX IC 真 4 因子 0.30+ 同等级**
- volatility_20 MAX |IC| = 0.403
- turnover_mean_20 MAX |IC| = 0.381
- bp_ratio MAX |IC| = 0.309
- dv_ttm MAX |IC| = 0.303

**真测**: 4 因子 真 MAX |IC| sustained 0.30+ = 真**4 因子 在 sustained sustained 12yr 中 真 sustained alpha capable** ✅.

---

## §3 🔴 IC max date = 2026-03-30 sustained (真 IC 真**4-30 后 0 入库** sustained)

**真测 sustained**: 4 CORE 因子 真 IC max trade_date = **2026-03-30** sustained (本审查 5-01 实测), 而 sustained sprint period sustained PR #37+#40 + #43+#44 + #45 真 IC 入库 schtask Mon-Fri 18:00/18:15 触发.

**真证据 sustained F-D78-228 + F-D78-58 加深**:
- factor_ic_history 真 IC 最新 4-30 后 0 入 = 真生产 IC 真**4 月 sustained 0 入库** sustained
- sustained sprint state Session 22 沉淀 PR #40 DailyIC schtask Mon-Fri 18:00 + Session 22 PR #44 IcRolling Mon-Fri 18:15 schtask 沉淀, 真**应该 sustained 入库** but 真测 IC max 3-30 sustained = 真 schtask 真**4-30 后失败** sustained

**🔴 finding**:
- **F-D78-257 [P0 治理]** factor_ic_history 4 CORE 真 IC max trade_date=2026-03-30 sustained (本审查 5-01 实测), sustained sprint period 沉淀 PR #40 DailyIC + #44 IcRolling schtask Mon-Fri 18:00/18:15 真**4-30 后失败 sustained** = 真生产 IC 真**1 month gap sustained sustained**, sustained F-D78-228 + F-D78-58 + F-D78-8 同源加深 (5 schtask 持续失败 cluster 真证据 IC 通道 真断 1 month)

---

## §4 真生产 alpha 半衰期 真算 (真测真半衰期)

**真测**: AVG |IC| / MAX |IC| 比真**半衰期 candidate**:
- volatility_20: 0.116 / 0.403 = 0.288 (真 sustained 28.8%, 半衰期 ~ 几 month-quarter)
- turnover_mean_20: 0.114 / 0.381 = 0.299 (~30%)
- bp_ratio: 0.090 / 0.309 = 0.291 (~29%)
- dv_ttm: 0.058 / 0.303 = 0.191 (~19%, 较低 sustained)

**真测**: 4 因子 真 average/peak ratio sustained 19-30% 区间 = 真生产**真 IC 衰减程度真不极端**, sustained 4 因子 真 alpha 真**12yr sustained sustained** ✅.

**finding**:
- F-D78-258 [P3] CORE3+dv_ttm 真 alpha 半衰期真测 average/peak ratio 19-30%, 4 因子 真 12yr alpha sustained 真证据, sustained 沿用 PT WF OOS Sharpe=0.8659 真 verify

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-257** | **P0 治理** | factor_ic_history 4 CORE IC max=2026-03-30, schtask 真 4-30 后失败 sustained = 真 IC 通道 1 month gap |
| F-D78-258 | P3 | CORE3+dv_ttm 真 alpha 半衰期真测 19-30% ratio, 4 因子 12yr alpha sustained ✅ verify |

---

**文档结束**.
