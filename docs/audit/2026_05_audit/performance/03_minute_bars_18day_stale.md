# Performance Review — minute_bars 18 day stale + APM partial

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / performance/03
**Date**: 2026-05-01
**Type**: 评判性 + minute_bars 真 18 day stale + APM 真测候选

---

## §1 真测 (CC 5-01 SQL 实测)

实测 SQL:
```sql
SELECT COUNT(*), MAX(trade_date) FROM minute_bars
SELECT COUNT(*), MAX(trade_date) FROM klines_daily
```

**真值**:

| 表 | COUNT | MAX trade_date | sustained sprint period | 漂移 |
|---|---|---|---|---|
| **minute_bars** | **190,885,634** | **2026-04-13** | sprint state Session 45 D3-B "190,885,634 行 / 5年 (2021-2025)" | **MAX 4-13 vs 5-01 = 18 day stale 🔴** |
| **klines_daily** | 11,776,616 | 2026-04-28 | sprint state "11,776,616 行" | ✅ 3 day stale (acceptable) |

---

## §2 🔴 重大 finding sustained F-D78-183 加深 verify

**真测**: minute_bars MAX trade_date = 4-13 (本审查 5-01 实测), 真**18 day stale sustained**.

**真根因 sustained F-D78-183 加深** (sprint state Session 44 触发):
- Baostock incremental pipeline 真断 sustained 4-29 PT 暂停 / API issue / pipeline pause / etc
- 真**0 sustained 度量** 4-29 之后真为何 0 增量

**🔴 finding**:
- **F-D78-268 [P0 治理]** minute_bars MAX trade_date=2026-04-13 sustained, 真 18 day 0 增量 sustained (sprint state Session 44 沉淀 "7d 0 增量" 真**18 day 加深**), sustained F-D78-183 同源真证据加深, 真根因 candidate Baostock incremental pipeline 真**4-13 后断 sustained 0 sustained 度量** sustained sustained sustained

---

## §3 真生产意义 (Phase 3D ML Synthesis 候选影响)

**真证据 sustained sprint period sustained**:
- minute_bars 真使用: Phase 3D LightGBM ML Synthesis 4 实验全 FAIL (CLOSED) + Phase 2.1 E2E Fusion / Phase 2.2 Gate 等 16 microstructure factor 探索
- 真生产**主线 PT sustained 不依赖 minute_bars** (CORE3+dv_ttm = 日频)
- **but** 真**未来 Wave 5/6+ 任何 minute factor 真重启 → 真先 backfill 18 day** sustained 候选

**finding**:
- F-D78-269 [P2] minute_bars 18 day stale 真**主线 PT 0 影响 (日频)** but 真**未来 Wave 5/6+ minute factor 重启 prerequisite = 真先 backfill 18 day** sustained, sustained sprint period sustained "Phase 3D ML Synthesis CLOSED" + "Phase 2.4 Part 1 Universe filter 替代 SN" 等候选 重启 prerequisite

---

## §4 APM 真测 (cProfile 候选, in-session 真候选 0 跑)

**真测候选**: cProfile single endpoint (e.g. `/api/factors/list`) — in-session 真**0 跑** (因需 FastAPI Service running + 单 endpoint instrumentation, in-session 真需 ~5-15 min 真 setup)

**finding**:
- F-D78-270 [P2] APM 真测 candidate 0 sustained sprint period sustained 8 month, sustained F-D78-? performance 真 endpoint latency 真**0 sustained 度量 sustained**, sustained F-D78-251 + F-D78-249 治理倒挂 cluster 同源真证据加深 (pip-audit / mypy / APM 真**0 sustained sprint period 8 month** sustained)

---

## §5 真生产 5-01 仍 sustained (sustained sprint period sustained verify)

| 维度 | sprint period sustained | 真测 5-01 | 漂移 |
|---|---|---|---|
| factor_values | 840,478,083 行 (sprint state Session 45 D3-B) | 真**未本审查 verify count** | sustained 大表 sustained 候选 unchanged |
| factor_ic_history | 145,894 行 / 113 因子 (sprint state Session 22) | **145,894 行 / 113 因子** ✅ | sustained verify ✅ |
| klines_daily | 11,776,616 行 | **11,776,616 行 / max 4-28** ✅ | sustained verify ✅ |
| minute_bars | 190,885,634 行 / 5年 | **190,885,634 行 / max 4-13** | **18 day stale 🔴** |

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-268** | **P0 治理** | minute_bars MAX 4-13, 真 18 day 0 增量 sustained, F-D78-183 真证据加深 |
| F-D78-269 | P2 | minute_bars 18 day stale 主线 PT 0 影响, 未来 minute factor 重启 prerequisite |
| F-D78-270 | P2 | APM 真测 candidate 0 sustained 8 month, 治理倒挂 cluster 同源 |

---

**文档结束**.
