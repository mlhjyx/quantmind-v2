# Data Review — 第三方源真测 + minute_bars 真断

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 4 / data/02
**Date**: 2026-05-01
**Type**: 评判性 + 第三方源真测 + 推翻 sprint period sustained "Baostock sustained" 假设

---

## §1 第三方源真测 (CC 5-01 实测 PG)

实测 SQL 7 day 真 max + 真增量:

| 表 | source | MAX(trade_date) | 7d count |
|---|---|---|---|
| klines_daily | Tushare | 2026-04-28 | 10,955 |
| moneyflow_daily | Tushare | **2026-04-30** | 20,633 |
| daily_basic | Tushare | 2026-04-28 | 10,955 |
| stock_status_daily | Tushare | 2026-04-28 | 10,955 |
| **minute_bars** | **Baostock** | **None** | **0** |

---

## §2 🔴 重大 finding — minute_bars 真断

### 2.1 真测真值

实测 SQL:
```sql
SELECT MAX(trade_date), COUNT(*) FROM minute_bars WHERE trade_date >= NOW() - INTERVAL '7 days';
```

**真值**: **(None, 0)** — 7 day 0 行 incremental, MAX=None

### 2.2 sprint period sustained 假设推翻

CLAUDE.md sustained sustained:
> **minute_bars**: 190,885,634 行 (~36 GB), 5年(2021-2025), Baostock 5分钟K线, 2537只股票

**真测推翻**:
- 历史 190M 行 sustained sustained ✅
- 但 **7 day 0 增量入库** = Baostock 5min K 线 incremental pipeline 真断
- **silent failure** sustained sustained (无 alert_dedup fire 关于 minute_bars)

### 2.3 真根因 candidate

候选 root cause:
- 4-29 PT 暂停后 Baostock incremental schtask Disabled?
- Baostock API 真 issue (sprint period sustained sustained 0 sustained 度量)
- pipeline pause sustained sustained 沉淀 0 sustained
- 历史数据 5年 sustained sustained 但 5月 0 增量 (真历史: 5年范围 2021-2025, 2026 真增量需 verify)

**🔴 finding**:
- **F-D78-183 [P0 治理]** **minute_bars 7 day 0 增量入库** silent failure cluster, sprint period sustained sustained "Baostock 5分钟K线 sustained" sustained sustained vs 真测 incremental pipeline 真断. 真根因 candidate (Baostock API issue / schtask Disabled / pipeline pause / 5年范围耗尽 — 候选未深查), 沿用 F-D78-8/115/116 silent failure cluster 同源

---

## §3 第三方源 vs DB 真值 reconciliation (CC 扩 M8)

实测 sprint period sustained sustained:
- Tushare 复权 historical bug regression sustained sprint period sustained sustained
- Baostock 5min K 线 sustained sustained
- QMT (xtquant) sustained sustained sustained

**真测 verify** (本审查 partial):
- Tushare 4-30 真 last-data ≤ 4-28 (klines_daily / daily_basic / stock_status) — Tushare 5月数据延迟 1-2 day candidate (candidate finding)
- moneyflow 4-30 ✅ (sprint period PR #46 17:30 schtask 真生效)
- Baostock minute_bars 7d 0 增量 (F-D78-183 P0 治理)
- QMT (xtquant) 真账户 ✅ sustained (E6 sustained)

候选 finding:
- F-D78-184 [P2] Tushare 数据 5月 4-28 sustained 真 max vs 真生产 5-01 真 lag = 3 trade days, sprint period sustained sustained sustained 0 sustained 度量, 候选 Tushare 数据 lag 真测 + alert candidate

---

## §4 数据契约 (DataContract) vs 真 schema drift 复述

(沿用 [`data/01_data_quality_6dim.md`](01_data_quality_6dim.md) §4 sustained F-D78-98 sustained)

---

## §5 Parquet cache 失效策略 enforce

(沿用 [`data/01_data_quality_6dim.md`](01_data_quality_6dim.md) §5 sustained F-D78-99 sustained)

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-183** | **P0 治理** | minute_bars 7 day 0 增量入库 silent failure cluster, sprint period sustained "Baostock 5分钟K线 sustained" 真测 incremental pipeline 真断 |
| F-D78-184 | P2 | Tushare 数据 5月 4-28 真 max vs 5-01 lag 3 trade days, sprint period sustained 0 度量, 候选 alert candidate |

---

**文档结束**.
