# V3 TB-5b — Replay Acceptance Report (2 关键窗口)

**Run date**: 2026-05-14  
**Overall verdict**: ✅ PASS  
**Scope**: V3 §15.4 4 项 acceptance + V3 §13.1 SLA (replay-exercisable subset) on the 2 关键窗口 (ADR-064 D3=b), via the pure `qm_platform.risk.replay.acceptance` evaluator. ADR-063 转 Tier B 真测路径.

---

## Replay Acceptance — `2024Q1_quant_crash`

**Overall verdict**: ✅ PASS

- Total events: **328,680** · minute_bars: **3,322,031** · timestamps: **1,344**

### V3 §15.4 — 4 项 acceptance (replay-path transferable)

| # | Criterion | Threshold | Actual | Result |
|---|---|---|---|---|
| 1 | P0 alert 误报率 | `< 30%` | `6.72% (1244/18499)` | ✅ |
| 2 | L1 detection latency P99 | `< 5000ms` | `0.010ms` | ✅ |
| 3 | L4 STAGED 流程闭环 0 失败 | `= 0` | `0` | ✅ |
| 4 | 元监控 0 P0 元告警 | `= 0` | `0` | ✅ |

### V3 §13.1 — SLA verify (replay-exercisable subset)

| SLA | Threshold | Actual | Result |
|---|---|---|---|
| L1 detection latency P99 < 5s | `< 5000ms` | `0.010ms` | ✅ |
| L4 STAGED 30min cancel 窗口 | `<= 30min` | `all within window` | ✅ |

> 3/5 §13.1 SLA (L0 News 30s / LiteLLM 3s / DingTalk 10s) have no LLM/News/DingTalk path in a pure-function replay — covered by the TB-5a synthetic scenarios (scenario 5 + 6) per Plan v0.2 §C line 203-207.

#### P0 alert 误报率

Counterfactual FP methodology (ADR-070 locked): P0 events deduped to first-per-(code, rule_id, day) [removes the gap_down_open per-bar artifact], then a deduped alert is a false positive if the stock's day-end close recovered to >= prev_close (flagged downside fully reversed), true positive if it ended the day below prev_close (held position underwater = real loss). Raw P0 events (pre-dedup): 327,208. Deduped daily alerts: 18,499. Classified: 18,499 (FP=1,244, TP=17,255). Unclassifiable (no prev_close / no day-end close, incl. correlated_drop): 0. Per-rule: gap_down_open: FP=1011/TP=11896/uncls=0; limit_down_detection: FP=79/TP=2126/uncls=0; near_limit_down: FP=154/TP=3233/uncls=0.

#### L1 detection latency P99

Replay-path proxy: wall-clock of each RiskBacktestAdapter.evaluate_at call (one synthetic tick over the pure RealtimeRiskEngine). This is a LOWER-BOUND proxy for production tick→risk_event_log INSERT latency — it excludes I/O (DB INSERT, Redis read, network). ADR-063 §1.5: replay path 等价 transferable. Samples: 3,322,031.

#### L4 STAGED 流程闭环 0 失败

Each actionable RuleResult (shares > 0) driven through the real L4ExecutionPlanner STAGED state machine. Actionable events: 9. Plans generated: 9. Closed OK (→ TIMEOUT_EXECUTED): 9. Failed: 0.

#### 元监控 0 P0 元告警

Replay-run integrity form: a pure-function replay cannot exercise the live §13.3 P0 元告警 conditions (L1 心跳 / LiteLLM 失败率 / DingTalk push fail / News 全 timeout — all production-runtime). The replay-exercisable subset is: pure-function contract held (0 broker / 0 alert / 0 INSERT) = True; and STAGED cancel-window integrity (no plan > 30min, §13.3 inverse) = True.


---

## Replay Acceptance — `2025_04_07_tariff_shock`

**Overall verdict**: ✅ PASS

- Total events: **234,952** · minute_bars: **962,544** · timestamps: **384**

### V3 §15.4 — 4 项 acceptance (replay-path transferable)

| # | Criterion | Threshold | Actual | Result |
|---|---|---|---|---|
| 1 | P0 alert 误报率 | `< 30%` | `14.74% (1438/9757)` | ✅ |
| 2 | L1 detection latency P99 | `< 5000ms` | `0.011ms` | ✅ |
| 3 | L4 STAGED 流程闭环 0 失败 | `= 0` | `0` | ✅ |
| 4 | 元监控 0 P0 元告警 | `= 0` | `0` | ✅ |

### V3 §13.1 — SLA verify (replay-exercisable subset)

| SLA | Threshold | Actual | Result |
|---|---|---|---|
| L1 detection latency P99 < 5s | `< 5000ms` | `0.011ms` | ✅ |
| L4 STAGED 30min cancel 窗口 | `<= 30min` | `all within window` | ✅ |

> 3/5 §13.1 SLA (L0 News 30s / LiteLLM 3s / DingTalk 10s) have no LLM/News/DingTalk path in a pure-function replay — covered by the TB-5a synthetic scenarios (scenario 5 + 6) per Plan v0.2 §C line 203-207.

#### P0 alert 误报率

Counterfactual FP methodology (ADR-070 locked): P0 events deduped to first-per-(code, rule_id, day) [removes the gap_down_open per-bar artifact], then a deduped alert is a false positive if the stock's day-end close recovered to >= prev_close (flagged downside fully reversed), true positive if it ended the day below prev_close (held position underwater = real loss). Raw P0 events (pre-dedup): 234,448. Deduped daily alerts: 9,757. Classified: 9,757 (FP=1,438, TP=8,319). Unclassifiable (no prev_close / no day-end close, incl. correlated_drop): 0. Per-rule: gap_down_open: FP=1323/TP=3816/uncls=0; limit_down_detection: FP=37/TP=2179/uncls=0; near_limit_down: FP=78/TP=2324/uncls=0.

#### L1 detection latency P99

Replay-path proxy: wall-clock of each RiskBacktestAdapter.evaluate_at call (one synthetic tick over the pure RealtimeRiskEngine). This is a LOWER-BOUND proxy for production tick→risk_event_log INSERT latency — it excludes I/O (DB INSERT, Redis read, network). ADR-063 §1.5: replay path 等价 transferable. Samples: 962,544.

#### L4 STAGED 流程闭环 0 失败

Each actionable RuleResult (shares > 0) driven through the real L4ExecutionPlanner STAGED state machine. Actionable events: 6. Plans generated: 6. Closed OK (→ TIMEOUT_EXECUTED): 6. Failed: 0.

#### 元监控 0 P0 元告警

Replay-run integrity form: a pure-function replay cannot exercise the live §13.3 P0 元告警 conditions (L1 心跳 / LiteLLM 失败率 / DingTalk push fail / News 全 timeout — all production-runtime). The replay-exercisable subset is: pure-function contract held (0 broker / 0 alert / 0 INSERT) = True; and STAGED cancel-window integrity (no plan > 30min, §13.3 inverse) = True.


---

关联: V3 §15.4 / §13.1 / §15.5 · ADR-063 / ADR-064 / ADR-066 / ADR-070 ·
Plan v0.2 §A TB-5 row + §C + §D · 铁律 31/33/41 · LL-098 X10 / LL-159
