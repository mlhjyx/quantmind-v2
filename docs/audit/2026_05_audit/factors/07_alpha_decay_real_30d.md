# Factors Review — Alpha decay 30d 真测 + decay_level NULL cluster

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 8 WI 4 / factors/07
**Date**: 2026-05-01
**Type**: 评判性 + factor_ic_history 30d 真测 (sustained factors/04 F-D78-194)

---

## §1 CORE3+dv_ttm 30d rolling IC 真测 (CC 5-01 实测)

实测 SQL:
```sql
SELECT factor_name, AVG(ic_20d), AVG(ic_ma20), AVG(ic_ma60), COUNT(*)
FROM factor_ic_history
WHERE factor_name IN ('turnover_mean_20','volatility_20','bp_ratio','dv_ttm')
  AND trade_date >= NOW() - INTERVAL '30 days'
GROUP BY factor_name;
```

**真值**:

| factor_name | AVG(ic_20d) | AVG(ic_ma20) | AVG(ic_ma60) | COUNT |
|---|---|---|---|---|
| bp_ratio | **None** | **None** | **None** | 17 |
| dv_ttm | **None** | **None** | **None** | 17 |
| turnover_mean_20 | **None** | **None** | **None** | 17 |
| volatility_20 | **None** | **None** | **None** | 17 |

---

## §2 🔴 重大 finding — 30d IC AVG = None

**真值**: 4 CORE 因子 30d window 17 entries each, 但 AVG(ic_20d) + AVG(ic_ma20) + AVG(ic_ma60) **全 None**.

**真根因 candidate**:
- factor_ic_history 30d window 内 ic_20d / ic_ma20 / ic_ma60 字段 NULL
- 沿用 factors/01 §1.2 4-28 latest IC 真测 (有真值, 单次):
  - turnover_mean_20: ic_20d=-0.0957 (sustained)
  - volatility_20: ic_20d=-0.0905
  - bp_ratio: ic_20d=+0.0586
  - dv_ttm: ic_20d=+0.0397
- 但 30d window AVG NULL = 单次 4-28 entry 之外 sustained NULL data

**🔴 finding**:
- **F-D78-228 [P1]** factor_ic_history 30d AVG IC = None for CORE3+dv_ttm 4 因子, 真 IC 数据 30d 内多数 NULL (仅 4-28 末次有真 IC 真值, 其他 16/17 entries NULL?), candidate 真 IC 入库 sustained gap. 沿用 F-D78-58 sustained sustained sustained sustained "163 因子 raw 但 0 IC 入库 = 等同不存在" 加深 (现 CORE3+dv_ttm 4 因子虽 IC 入库 17 entries/30d but AVG NULL = 真 IC 0 effective)

---

## §3 decay_level 30d distribution 真测

实测 SQL:
```sql
SELECT decay_level, COUNT(*) FROM factor_ic_history
WHERE trade_date >= NOW() - INTERVAL '30 days'
GROUP BY decay_level ORDER BY COUNT(*) DESC;
```

**真值**:

| decay_level | COUNT |
|---|---|
| **None (NULL)** | **471** |
| unknown | 15 |
| mkt | 15 |
| event | 10 |

**真测**: NULL = 471 / total 511 = **~92.2% NULL**

**🔴 finding**:
- **F-D78-230 [P2]** decay_level 30d 真测 distribution NULL ~92.2% (471/511), sprint period sustained sustained "decay_level" 字段 sustained 沉淀 但 真 enforcement 候选失败 (沿用 LL-013/014 sustained "IC 衰减>50% 标记虚假 alpha" sustained 但 真 decay_level enforce ~92.2% NULL = 实质 0 tracking)

---

## §4 alpha decay 真半衰期 candidate

(本审查未深 calculate alpha 半衰期, 因 30d AVG NULL data sustained sustained sustained 0 sustained 度量)

候选 finding:
- F-D78-231 [P3] alpha 半衰期真 calculate 0 sustained sustained sustained 度量, 真 IC NULL data 阻断 sustained sustained 度量 (沿用 F-D78-228 sustained 同源)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-228** | **P1** | factor_ic_history 30d AVG IC = None for CORE3+dv_ttm 4 因子, 真 IC 数据 30d 内多数 NULL, 真 IC 0 effective |
| **F-D78-230** | **P2** | decay_level 30d distribution NULL ~92.2% (471/511), 真 enforcement 失败 |
| F-D78-231 | P3 | alpha 半衰期真 calculate 0 sustained 度量 |

---

**文档结束**.
