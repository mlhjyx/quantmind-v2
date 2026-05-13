# Replay Sediment — 2024Q1_quant_crash

**Window**: 2024-01-02 → 2024-02-09  
**Description**: 雪球结构化产品集中敲入 + 量化中性策略踩踏 (2024-01~02), 微盘股下跌 + 千股跌停  
**Run date**: 2026-05-13  

## Run metadata

- Total minute_bars consumed: **3,322,031**
- Total unique timestamps: **1,344**
- Wall clock: **29.8s**
- Pure-function contract verified (0 broker / 0 INSERT / 0 alert): **True**

---

# Replay Window Event Summary

- Window: 2024-01-02 00:00:00+00:00 → 2024-02-10 00:00:00+00:00
- Total events: 328680
- Unique codes: 2318
- Unique rule_ids: 7

## Events by rule_id

- `gap_down_open`: 254870
- `limit_down_detection`: 39351
- `near_limit_down`: 32987
- `industry_concentration`: 1344
- `rapid_drop_5min`: 103
- `rapid_drop_15min`: 16
- `trailing_stop`: 9

## Top events by code (top 20)

- ``: 1344
- `000908.SZ`: 686
- `000020.SZ`: 644
- `002217.SZ`: 625
- `002767.SZ`: 624
- `002141.SZ`: 624
- `002620.SZ`: 614
- `002211.SZ`: 602
- `000638.SZ`: 584
- `003015.SZ`: 569
- `001217.SZ`: 563
- `000668.SZ`: 562
- `002952.SZ`: 553
- `002888.SZ`: 549
- `002789.SZ`: 549
- `600689.SH`: 539
- `002856.SZ`: 531
- `002682.SZ`: 523
- `002395.SZ`: 519
- `000691.SZ`: 514


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
