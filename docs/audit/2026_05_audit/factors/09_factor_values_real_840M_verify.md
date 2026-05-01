# Factors Review — factor_values 840M 真 verify + 真 hypertable n_live_tup gotcha

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 10 / factors/09
**Date**: 2026-05-01
**Type**: 评判性 + factor_values 840M 真 reverify (sustained F-D78-? 加深)

---

## §1 真测 (CC 5-01 SQL 真重 5-01 ground truth)

实测 SQL:
```sql
SELECT COUNT(*) FROM factor_values
SELECT MAX(trade_date), MIN(trade_date), COUNT(DISTINCT factor_name) FROM factor_values
SELECT hypertable_name, num_chunks FROM timescaledb_information.hypertables
```

**真值 5-01**:

| 维度 | 真测 5-01 | sustained sprint period | verify status |
|---|---|---|---|
| **factor_values COUNT(*)** | **840,478,083** | sprint state Session 45 D3-B "840,478,083 行 / ~172 GB" | ✅ **完美 verify** |
| factor_values MAX trade_date | 2026-04-28 | sustained "MAX 4-28" 同 klines_daily | ✅ verify |
| factor_values MIN trade_date | 2014-01-02 | sustained "12 yr full history" | ✅ verify |
| factor_values DISTINCT factor_name | **276** | sustained "70 LGBM + CORE + 北向 + Alpha158 etc" | ✅ verify |
| factor_values num_chunks | **152** | sustained "TimescaleDB hypertable 152 chunks" | ✅ verify |
| **klines_daily** | 11,776,616 / 53 chunks | sustained verify | ✅ |
| **minute_bars** | 190,885,634 | sustained verify (但 max=4-13 18d stale 真证据 sustained F-D78-268) | ✅ |
| **daily_basic** | 11,681,799 | sustained "11,681,799 行 / ~3.7 GB" | ✅ verify |
| factor_ic_history | 145,894 / 113 因子 | sustained verify | ✅ |

---

## §2 🔴 重大 finding — TimescaleDB hypertable n_live_tup 真**误导 0**

**真测真证据**: 真 batch 1 (Phase 10) 第一次 query 真:
```sql
SELECT relname, n_live_tup FROM pg_stat_user_tables
WHERE relname IN ('factor_values', ...) ORDER BY n_live_tup DESC
```

**真值返回**:
```
factor_ic_history  145,894 ✅ (regular table)
daily_basic         54,848 ❗ (sustained 真 pg_stat 真 stale, 直 COUNT=11,681,799)
factor_values            0 ❗ (hypertable parent, 真 chunks 全 840M row in 152 chunks)
klines_daily             0 ❗ (hypertable parent)
minute_bars              0 ❗ (hypertable parent)
```

**真根因**: TimescaleDB hypertable parent 表 真 0 row sustained, 真 row 全在 152 chunks. `pg_stat_user_tables.n_live_tup` 真**仅 reflect parent**, 真 chunks 真 row 不计 sustained.

**真 size 真证据**:
- factor_values parent: 40 kB (metadata only)
- klines_daily parent: 16 kB
- minute_bars parent: **36 GB** (含 chunks size sustained — 真 minute_bars 真 chunk size 沉淀 36 GB sustained)
- daily_basic: 3805 MB (regular table sustained)
- factor_ic_history: 36 MB (regular)

**🔴 finding**:
- **F-D78-283 [P1]** TimescaleDB hypertable `n_live_tup` 真**仅反映 parent**, 真 chunks 真 row 真**完全不计**, sustained sprint period sustained 真**0 sustained 度量** sustained — 真生产 hypertable 真**多次依靠 n_live_tup 真生产 silent error candidate** sustained, sustained 第 19 条铁律 ("memory 数字 SQL verify before 写") 真**真 hypertable case 真陷阱** sustained 真证据 sustained sprint period sustained 0 documented warning. **真证据真重要**: 真 phase 10 batch 1 真**自身**就被 n_live_tup=0 真 mislead, 真**自检 batch 2 直 COUNT(*) 才真 reverify 840M sustained**

---

## §3 真 verify sprint state Session 45 D3-B 数字真完美 ✅

**sprint state 沉淀**:
> factor_values: 840,478,083 行 (~172 GB, TimescaleDB hypertable 152 chunks)
> factor_ic_history: 145,894 行 (~36 MB)
> minute_bars: 190,885,634 行 (~36 GB), 5年(2021-2025), Baostock 5分钟K线, 2537只股票
> klines_daily: 11,776,616 行 (~4 GB, TimescaleDB hypertable 53 chunks)
> daily_basic: 11,681,799 行 (~3.7 GB)

**真测 5-01 reverify**:
- factor_values: 840,478,083 ✅ + 152 chunks ✅
- factor_ic_history: 145,894 ✅
- minute_bars: 190,885,634 ✅
- klines_daily: 11,776,616 ✅ + 53 chunks ✅
- daily_basic: 11,681,799 ✅

**真证据**: sprint state Session 45 D3-B 真**数字 5-01 真完美 verify** ✅ — 真**第 19 条铁律 真 sprint state 真 reliable 真证据加深** sustained, sustained F-D78-17 P2 sustained "handoff 写入层 0 enforce" 真证据 part-corrected (真 Session 45 D3-B 数字真严谨, 但 Phase 9 sustained 沉淀 "测试基线 2864 / smoke 28" 真 12 day stale = 真**handoff 数字真 reliability 真不一致** sustained 真证据).

---

## §4 真 276 因子 factor_values 真新发现

**真测**: factor_values 真 **276 distinct factor_name** sustained.

**真根因**: sustained sprint state CLAUDE.md 沉淀:
- CORE 4 (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm)
- CORE5 前任 (5 因子)
- PASS 候选 32+16
- INVALIDATED 1
- DEPRECATED 5
- 北向 RANKING 15
- LGBM 70 (含 48 核心 + 15 北向 + 7 新 Phase 2.1)

**真**累计**: 4+5+48+1+5+15+70 = ~148 factor sustained sprint period sustained 沉淀

**真测 276 factor_values distinct = 真**比 sprint state CLAUDE.md 沉淀 多 +128** sustained = 真**真生产 factor_values 真**多 ~128 factor**未沉淀 CLAUDE.md sustained, 真**真生产 factor 真盘点 真不全** sustained.

**finding**:
- F-D78-284 [P2] factor_values 真**276 distinct factor_name** sustained 5-01 真测, vs CLAUDE.md 沉淀 ~148 = 真**真生产 真**~128 factor (Alpha158 大头 + 其他 sustained)** 未沉淀 CLAUDE.md sustained, sustained F-D78-? "Alpha158 11 orphan" Session 24 真证据加深 (真 factor_values vs FACTOR_TEST_REGISTRY vs CLAUDE.md 三套 factor 真账 sustained 真 disconnect)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-283** | **P1** | TimescaleDB hypertable n_live_tup=0 真陷阱, 真 chunks 真 row 完全不计, hypertable case 真 silent error candidate |
| F-D78-284 | P2 | factor_values 真 276 factor vs CLAUDE.md ~148 = +128 factor 未沉淀, factor 三套账 disconnect |

---

**文档结束**.
