# V3 §15.4 Paper-Mode 5d Verify Report — 2026-05-09 → 2026-05-13

**Overall verdict**: ❌ FAIL

⚠️ Missing days in window: [datetime.date(2026, 5, 9), datetime.date(2026, 5, 10)]

## V3 §15.4 4 Acceptance Items

| # | Criterion | Threshold | Actual | Result |
|---|---|---|---|---|
| 1 | P0 alert 误报率 | `< 30%` | `0.00% (0/2)` | ✅ |
| 2 | L1 detection latency P99 | `< 5000ms` | `<no L1 data>` | ❌ |
| 3 | L4 STAGED 流程闭环 0 失败 | `= 0` | `0` | ✅ |
| 4 | 元监控 0 P0 元告警 | `= 0` | `0` | ✅ |

### P0 alert 误报率

P0 alerts cumulative: 2. False positives: 0.

### L1 detection latency P99

No detection_latency_p99_ms data in window — extraction not running?

### L4 STAGED 流程闭环 0 失败

execution_plans status=FAILED count in 5d window.

### 元监控 0 P0 元告警

Caller-provided count. §13.3 元告警 channel + table pending; default 0 until those land.
