# V3 IC-3a — 5y Integrated V3 Chain Replay Acceptance Report

**Run date**: 2026-05-16  
**Overall verdict**: ✅ PASS  
**Scope**: V3 Plan v0.4 §A IC-3a — 5y full minute_bars replay on FULLY-INTEGRATED V3 chain (L1 RealtimeRiskEngine + L4 STAGED state machine + L3 daily-cadence PURE rules). Sustained HC-4a chunked per-quarter体例 (20 quarters, 5y range 2021-2025, sustained CLAUDE.md §因子存储 minute_bars 190M+ rows). LLM reflector + L0 News EXCLUDED per IC-3 Q2 (out-of-band, sustained acceptance.py §1 + IC-3 user decision 2026-05-16). Synthetic-universe体例 sustained ADR-070.

---

## §1 L1 + L4 STAGED — V3 §15.4 4 项 acceptance (sustained HC-4a)

| # | Criterion | Threshold | Actual | Result |
|---|---|---|---|---|
| 1 | P0 alert 误报率 | `< 30%` | `4.12% (8,193/199,074)` | ✅ |
| 2 | L1 detection latency P99 | `< 5000ms` | `0.010ms (max-quarter)` | ✅ |
| 3 | L4 STAGED 流程闭环 0 失败 | `= 0` | `0` | ✅ |
| 4 | 元监控 0 P0 元告警 (replay-integrity form) | `= 0` | `0` | ✅ |

- Total minute_bars: **139,303,467** · events: **3,757,195** · raw P0: **3,694,523** · deduped daily P0: **199,074** · classified: **199,074** · STAGED actionable: **1,363** · closed-ok: **1,363** · failed: **0**

---

## §2 L3 daily-cadence PURE rule wiring (NEW for IC-3a)

| Metric | Value | Verdict |
|---|---|---|
| Trading days evaluated (5y) | `1,212` | — |
| Synthetic positions (Σ code×day) | `2,901,547` | — |
| Rule.evaluate() calls | `4,848` (= trading_days × 4 rules) | — |
| Crashes | `0` | ✅ |
| L3 wiring (eval_calls > 0 AND crashes == 0) | — | ✅ |

**Per-rule trigger counts** (informational — synthetic-universe ≠ real-portfolio precision):

| rule_id | triggers |
|---|---|
| `new_position_volatility` | 78,565 |
| `pms_l1` | 10 |
| `pms_l2` | 15 |
| `pms_l3` | 38 |
| `single_stock_stoploss_l1` | 4,797 |
| `single_stock_stoploss_l2` | 520 |
| `single_stock_stoploss_l3` | 25 |
| `single_stock_stoploss_l4` | 5 |

---

## §3 Per-quarter breakdown

| quarter | bars | events | FP | TP | P99 ms | staged failed | L3 td | L3 calls | L3 crashes |
|---|---|---|---|---|---|---|---|---|---|
| 2021Q1 | 5,985,648 | 183,473 | 323 | 10,510 | 0.009 | 0 | 58 | 232 | 0 |
| 2021Q2 | 6,301,632 | 136,243 | 216 | 6,404 | 0.009 | 0 | 60 | 240 | 0 |
| 2021Q3 | 6,833,568 | 224,657 | 373 | 12,089 | 0.009 | 0 | 64 | 256 | 0 |
| 2021Q4 | 6,616,272 | 139,792 | 284 | 7,145 | 0.009 | 0 | 61 | 244 | 0 |
| 2022Q1 | 6,383,280 | 200,651 | 437 | 12,562 | 0.009 | 0 | 58 | 232 | 0 |
| 2022Q2 | 6,555,216 | 269,044 | 603 | 14,652 | 0.009 | 0 | 59 | 236 | 0 |
| 2022Q3 | 7,315,776 | 207,801 | 304 | 10,793 | 0.009 | 0 | 65 | 260 | 0 |
| 2022Q4 | 6,850,560 | 126,883 | 242 | 6,886 | 0.009 | 0 | 60 | 240 | 0 |
| 2023Q1 | 6,803,040 | 55,356 | 88 | 3,016 | 0.009 | 0 | 59 | 236 | 0 |
| 2023Q2 | 6,873,648 | 147,119 | 169 | 6,746 | 0.009 | 0 | 59 | 236 | 0 |
| 2023Q3 | 7,530,864 | 86,031 | 116 | 4,116 | 0.009 | 0 | 64 | 256 | 0 |
| 2023Q4 | 7,089,184 | 82,948 | 144 | 4,040 | 0.009 | 0 | 60 | 240 | 0 |
| 2024Q1 | 6,887,700 | 382,670 | 1,383 | 21,607 | 0.009 | 0 | 58 | 232 | 0 |
| 2024Q2 | 7,025,207 | 289,680 | 292 | 12,972 | 0.009 | 0 | 59 | 236 | 0 |
| 2024Q3 | 7,634,928 | 107,893 | 168 | 5,206 | 0.009 | 0 | 64 | 256 | 0 |
| 2024Q4 | 7,289,664 | 353,133 | 641 | 17,583 | 0.009 | 0 | 61 | 244 | 0 |
| 2025Q1 | 6,840,576 | 170,167 | 301 | 9,022 | 0.009 | 0 | 57 | 228 | 0 |
| 2025Q2 | 7,227,888 | 335,831 | 1,602 | 12,641 | 0.010 | 0 | 60 | 240 | 0 |
| 2025Q3 | 7,984,848 | 112,419 | 196 | 5,910 | 0.009 | 0 | 66 | 264 | 0 |
| 2025Q4 | 7,273,968 | 145,404 | 311 | 6,981 | 0.009 | 0 | 60 | 240 | 0 |

---

## §4 Methodology + caveats

- **Integrated V3 chain** scope: L1 RealtimeRiskEngine (10 rules at tick cadence) + L4 STAGED state machine (via `evaluate_staged_closure`) + L3 daily-cadence PURE rules (PMSRule + PositionHoldingTimeRule + NewPositionVolatilityRule + SingleStockStopLossRule, evaluated at 15:00 Asia/Shanghai EOD per trading day). L2 regime + LLM reflector + L0 News classifier are out-of-band per IC-3 Q2 (LLM lesson-learning loop is post-event, NOT signal critical path).
- **L3 synthetic positions**: 1 share per code per trading day, entry_price = first bar's open, peak_price = max(high), current_price = last bar's close, entry_date = trade_date. Single-day positions deliberately rarely satisfy real rule thresholds (PMSRule needs ≥10% gain + ≥10% drawdown; PositionHoldingTime needs ≥30 days; etc) — the wiring-assertion test is **0 rule.evaluate() crashes**, NOT trigger-count significance.
- **L1 + L4 STAGED methodology** sustained ADR-070 (daily-dedup + prev_close baseline counterfactual FP classification + max-quarter P99 conservative aggregate + STAGED state-machine 30min cancel window ceiling). Pure-function replay path per ADR-063.
- **0 真账户 / 0 broker / 0 .env / 0 INSERT** — pure read-only DB SELECT + in-memory replay (sustained HC-4a + TB-5b). 红线 5/5 sustained: cash=￥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

关联: V3 §15.4 / §13.1 / §15.5 · ADR-063 / ADR-066 / ADR-070 / ADR-076 / ADR-080 候选 · Plan v0.4 §A IC-3a row · 铁律 31/33/41 · LL-098 X10 / LL-159 / LL-170 候选 lesson 3 / LL-172 lesson 1
