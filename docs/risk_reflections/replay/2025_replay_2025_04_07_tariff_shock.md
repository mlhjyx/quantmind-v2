# Replay Sediment — 2025_04_07_tariff_shock

**Window**: 2025-04-01 → 2025-04-11  
**Description**: 关税冲击 4-07 大盘单日 -13.15% + 千股跌停 (TB-1 真测窗口 #2)  
**Run date**: 2026-05-13  

## Run metadata

- Total minute_bars consumed: **962,544**
- Total unique timestamps: **384**
- Wall clock: **9.1s**
- Pure-function contract verified (0 broker / 0 INSERT / 0 alert): **True**

---

# Replay Window Event Summary

- Window: 2025-04-01 00:00:00+00:00 → 2025-04-12 00:00:00+00:00
- Total events: 234952
- Unique codes: 2472
- Unique rule_ids: 7

## Events by rule_id

- `gap_down_open`: 148448
- `limit_down_detection`: 57229
- `near_limit_down`: 28771
- `industry_concentration`: 384
- `rapid_drop_5min`: 107
- `rapid_drop_15min`: 7
- `trailing_stop`: 6

## Top events by code (top 20)

- ``: 384
- `603579.SH`: 353
- `002384.SZ`: 335
- `002529.SZ`: 316
- `001333.SZ`: 316
- `002444.SZ`: 313
- `000953.SZ`: 301
- `002947.SZ`: 298
- `002329.SZ`: 293
- `003019.SZ`: 291
- `002347.SZ`: 290
- `002132.SZ`: 286
- `002923.SZ`: 286
- `002241.SZ`: 282
- `002801.SZ`: 278
- `002938.SZ`: 276
- `603677.SH`: 274
- `002475.SZ`: 271
- `002655.SZ`: 270
- `603129.SH`: 268


## Sim-to-real gap audit (V3 §15.5)

**Methodology**: synthetic per-bar Position (universe-wide treat-as-held, shares=100, entry_price=prev_close). 此为 fire-count baseline — 测量 "若全 universe 持仓" 的规则触发上限. 真生产持仓 < universe, 故 production fire count 应 ≤ baseline.

**Data dependency caveats (v1 baseline)**:
- `prev_close` 来自 klines_daily.close LAG(1, partition by code), 若某 code 在 window start 前无 klines_daily 行 → entry_price=close → TrailingStop silent skip (pnl=0).
- `avg_daily_volume` / `industry` / `atr_pct` 留 TB-5c batch 补 → **VolumeSpike / LiquidityCollapse / IndustryConcentration / TrailingStop 在 v1 baseline 中 silent skip** (expected sparsity).
- `price_5min_ago` / `price_15min_ago` per-code rolling state, overnight gap 清零 (avoid cross-day false lookback).

**Next steps (TB-5c batch closure)**:
1. Compare 本 baseline events 与 risk_event_log 同窗口告警数 → gap = sim_baseline - production_actual.
2. 入 ADR-066 closure 终态 + V3 §15.5 sim-to-real gap 量化指标.
3. 补 avg_daily_volume / industry / atr_pct 数据后重跑 baseline, 覆盖 10/10 rules 完整 fire count.

---

关联:
- V3 §11.4 RiskBacktestAdapter pure function
- V3 §15.5 历史回放 sim-to-real gap counterfactual
- ADR-029 (10 RealtimeRiskRule)
- ADR-064 D3=b (2 关键窗口 sustained)
- ADR-066 候选 (TB-1 closure)
- LL-098 X10 / LL-159 (4-step preflight SOP)
