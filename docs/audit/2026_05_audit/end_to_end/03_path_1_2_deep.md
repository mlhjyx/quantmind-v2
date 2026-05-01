# End-to-End — 路径 1+2 真生产 trace 深 (sustained end_to_end/01)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 5 / end_to_end/03
**Date**: 2026-05-01
**Type**: 跨领域 + 路径 1+2 真生产 trace 深 (sustained end_to_end/01 §1+2)

---

## §1 路径 1 真生产 trace 深 (数据 → 因子 → 信号 → 回测)

### 1.1 真测 step-by-step

| Step | 真测 | 真生产 status |
|---|---|---|
| 1 数据源 | Tushare (klines/moneyflow/daily_basic 4-28~4-30 ✅) + Baostock (minute_bars 7d 0 增量 🔴 F-D78-183) | ⚠️ Baostock 真断 |
| 2 DataPipeline 入库 | factor_values 276 distinct (factors/01 §1.1) | ⚠️ partial enforce |
| 3 IC 入库 | factor_ic_history 113 distinct (163 漏 F-D78-58) | 🔴 partial 铁律 11 enforce 失败 |
| 4 SignalComposer | sprint period MVP 3.3 PR #116 PlatformSignalPipeline | ⚠️ 真生产 0 active 4-29 后 (F-D78-89) |
| 5 BacktestEngine | regression 5yr+12yr baseline | ⚠️ 真 last-run 0 sustained verify (F-D78-84) |
| 6 PT 信号生成 | run_paper_trading.py | ⚠️ PT 暂停 4-29 后 (sustained F-D78-88) |

**finding**:
- F-D78-195 [P0 治理] 路径 1 真生产 step 1 (Baostock minute_bars 真断 F-D78-183) + step 3 (IC 入库 163 漏 F-D78-58) + step 4 (SignalComposer 0 active F-D78-89) + step 6 (PT 暂停 F-D78-88) — 全 step silent failure cluster sustained

---

## §2 路径 2 真生产 trace 深 (数据 → 因子 → 信号 → PT 真账户)

### 2.1 真测 step-by-step

| Step | 真测 | 真生产 status |
|---|---|---|
| 1-5 | (沿用路径 1) | (sustained §1.1) |
| 6 PT 信号 | run_paper_trading.py | ⚠️ PT 暂停 4-29 后 |
| 7 broker_qmt | xtquant 真账户 (QMT 81001102) | ✅ 真账户 0 持仓 / cash ¥993,520.66 (E6 sustained) |
| 8 cb_state | circuit_breaker_state.live nav=¥993,520.16 (4-30 19:48 update) | ✅ |
| 9 position_snapshot live | max trade_date=4-27 (4-day stale 19 持仓 F-D78-4) | 🔴 stale |

**finding** (sustained):
- F-D78-89 (复) [P0 治理] 路径 2 (PT) 自 4-29 后 真生产 enforce 0 active

---

## §3 路径 5-8 真测 复述

(沿用 [`end_to_end/02_paths_5_to_8_combined.md`](02_paths_5_to_8_combined.md) sustained F-D78-125-129 sustained)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-195** | **P0 治理** | 路径 1 真生产全 step silent failure cluster (Baostock 真断 + IC 入库 163 漏 + SignalComposer 0 active + PT 暂停) sustained sustained |
| F-D78-89 (复) | P0 治理 | 路径 2 真生产 enforce 0 active 4-29 后 |
| F-D78-4 (复) | P2 | position_snapshot live 4-day stale |

---

**文档结束**.
