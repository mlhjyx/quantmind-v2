# ADR-066: V3 Tier B TB-1 Closure — RiskBacktestAdapter + 2-Window Replay Real-Test Baseline

**Status**: Accepted  
**Date**: 2026-05-14 (Session 53 + TB-1 closure 3 sub-PR cumulative)  
**Type**: V3 Tier B Sprint Closure ADR  
**Cumulative**: TB-1a (PR #330 `3e1ab6d`) + TB-1b (PR #331 `971c88b`) + TB-1c (本 PR sediment)  
**Plan v0.2 row**: §A TB-1 sprint closure

---

## Context

V3 Tier B Plan v0.2 TB-1 sprint = "`RiskBacktestAdapter` 完整实现 + 历史回放 2 关键窗口" per ADR-064 D3=b 决议 lock (sustained 2026-05-13). 串行 D1=a sequenced after T1.5 Tier A formal closure (ADR-065 7/8 PASS + 1 DEFERRED). Scope:

1. **TB-1a**: 同 RiskBacktestAdapter class 加 evaluate_at(timestamp, ctx, engine) — production parity decision (α) sustained
2. **TB-1b**: ReplayRunner + counterfactual summary + 2 关键窗口 constants (ReplayWindow + EventSummary)
3. **TB-1c**: 真测 2 windows against real DB minute_bars → fire count baseline → reflection sediment to `docs/risk_reflections/replay/`

**Driver**: ADR-063 决议 (Tier A 5d paper-mode skip empty-system anti-pattern) 转 Tier B 真测路径. ADR-063 verbatim: "真测路径转 Tier B RiskBacktestAdapter — 完整实现 = 历史 minute_bars 回放 → 9 RealtimeRiskRule 真触发 → 真 risk_event_log 数据流 → verify 报告 with non-trivial false-positive/latency 数据".

ADR-029 amend cumulative (S9a sustained): 10 RealtimeRiskRule (LimitDownDetection / NearLimitDown / GapDownOpen / TrailingStop / RapidDrop5min / RapidDrop15min / VolumeSpike / LiquidityCollapse / IndustryConcentration / CorrelatedDrop). Plan v0.2 §A TB-1 row originally cited 9 rules — corrected to 10 in this PR (留 TB-5c batch closure for footnote).

---

## Decisions

### D1: (α) Architecture — 同 RiskBacktestAdapter class extension (TB-1a sustained)

**Decision**: TB-1a evaluator (evaluate_at) 加到 RiskBacktestAdapter (S5 sub-PR 5c stub 已留), 走 RealtimeRiskEngine 真实路径 + 0 IO 注入 (broker / notifier / price_reader stubs sustained).

**Rationale**:
- Production parity 最大化: replay 走与 production 完全相同的 RealtimeRiskEngine.on_tick / on_5min_beat / on_15min_beat 路径
- Pure-function contract audit 自然落地: adapter._sell_calls / _alerts 长度不变 before/after replay → 0 broker / 0 alert assertable
- 反 separate-class B (替代方案: 单独 ReplayEvaluator class): 重复 cadence 分发逻辑 + 失去 stub injection 复用

**Sustained user ack 2026-05-13**: option (α) explicit ack at TB-1a kickoff.

### D2: (ii) Plan v0.2 §A TB-1 row 9 rules → 10 rules amend pending TB-5c batch

**Decision**: Plan v0.2 §A TB-1 row 写 "9 rules" 是 ADR-029 S5 base time write 体例; S9a TrailingStop 加为第 10 个 RealtimeRiskRule (ADR-060 sustained). 本 ADR-066 sediment cycle 不 retro-edit Plan v0.2 row (sustained ADR-022 反 retroactive content edit), 留 TB-5c batch closure 时统一 amend 多处:
- Plan v0.2 §A TB-1 row "9 rules" → "10 rules" annotation
- Constitution §L10.2 line 411 item 2 (12 年 counterfactual replay → 2 关键窗口 per D3=b)
- Constitution §L10.2 line 412 item 3 (WF 5-fold → ⏭ N/A factor research scope)
- V3 §11.1 module path drift corrections (留 TB-5c)

**Rationale**: 反 ADR-022 retroactive content edit pattern; batch closure 集中处理多处 drift 减 N×N sync risk.

### D3: Synthetic per-bar Position methodology for fire-count baseline (TB-1c)

**Decision**: TB-1c real-test 用 universe-wide treat-as-held synthetic Position (shares=100, entry_price=prev_close, current_price=close per bar) 而非 empty positions.

**Rationale**:
- 10 realtime rules 全部 iterate `for pos in context.positions:` — empty positions → 0 events fire → useless baseline
- Universe-wide treat-as-held = 测量 "若全 universe 持仓" 的 upper-bound fire count → production fire count 应 ≤ baseline (sim-to-real gap upper bound)
- 替代方案 A (历史真实 position_snapshot 回放): position_snapshot 仅含 paper/live mode, 2024Q1 + 2025-04 时 V3 paper mode 未启用 → 0 historical positions → 与 (α) decision empty positions 等价 fail
- 替代方案 B (单 symbol fixed portfolio): 不可能 cover universe 触发模式, 失去 sim-to-real gap baseline 意义
- 故 universe-wide 是唯一可行 v1 baseline

**Caveat documented in reflection markdown**: v1 baseline 仅覆盖 7/10 rules. 3/10 rules silent skip due to missing data:
- `avg_daily_volume` missing → VolumeSpike / LiquidityCollapse silent skip
- `industry` missing → IndustryConcentration falls back to "unknown" category (fires 100% — 元数据 noise, not real concentration signal)
- `atr_pct` missing → TrailingStop sparse (fires 6+9 only because pnl_pct < 20% activation threshold without ATR-scaled trailing)
- Per-context single-symbol positions → CorrelatedDrop min_count=3 unsatisfied (永不 fire in this baseline mode)

**TB-5c batch closure** 时补 avg_daily_volume + industry + atr_pct 数据 → 重跑 baseline covering 10/10 rules.

---

## Results (TB-1c real-test against DB minute_bars)

### Window 1: 2024Q1 量化踩踏 (2024-01-02 → 2024-02-09)

- Trading days: 28 (2024-02-09 春节前夕假期, 排除)
- Total minute_bars consumed: **3,322,031**
- Unique timestamps: **1,344** (≈ 48 5min bars × 28 days)
- Unique codes: **2,318**
- Wall clock: **29.8s**
- Pure-function contract verified: **True**
- **Total events: 328,680**
  - `gap_down_open`: 254,870 (77.5%)
  - `limit_down_detection`: 39,351 (12.0%)
  - `near_limit_down`: 32,987 (10.0%)
  - `industry_concentration`: 1,344 (0.4%) — "unknown" data noise per D3 caveat
  - `rapid_drop_5min`: 103 (0.03%)
  - `rapid_drop_15min`: 16 (0.005%)
  - `trailing_stop`: 9 (0.003%)

### Window 2: 2025-04-07 关税冲击 (2025-04-01 → 2025-04-11)

- Trading days: 8 (2025-04-04 清明节假期 + 04-05/04-06 weekend, 排除)
- Total minute_bars consumed: **962,544**
- Unique timestamps: **384** (≈ 48 5min bars × 8 days)
- Unique codes: **2,472**
- Wall clock: **9.1s**
- Pure-function contract verified: **True**
- **Total events: 234,952**
  - `gap_down_open`: 148,448 (63.2%)
  - `limit_down_detection`: 57,229 (24.4%)
  - `near_limit_down`: 28,771 (12.2%)
  - `industry_concentration`: 384 (0.16%) — "unknown" data noise per D3 caveat
  - `rapid_drop_5min`: 107 (0.05%)
  - `rapid_drop_15min`: 7 (0.003%)
  - `trailing_stop`: 6 (0.003%)

### Aggregated cross-window TB-1c metrics

- Total minute_bars: **4,284,575** (4.3M)
- Throughput: **~110K bars/s** (combined wall clock 39s, single-process Python)
- Rules fired: **7/10** (3/10 silent skip per D3 caveat — VolumeSpike / LiquidityCollapse / CorrelatedDrop)
- IndustryConcentration "unknown" noise rate: 1728/4.3M ≈ 0.04% — small enough to filter in TB-5c when industry data wired

---

## Sim-to-real gap 起步 baseline (V3 §15.5)

**Quantified**: fire-count baseline 已建. Production 真触发 (risk_event_log 同期数据) 对比 留 TB-5c batch closure.

**Predicted gap direction**: production << baseline 因为:
1. Production 持仓 ≤ 20 stocks per PT_TOP_N (vs universe ~2500 stocks): expected 0.8% (20/2500) baseline × production = ~3000 events for 2024Q1 production-equivalent
2. PT live trading 4-30 起 0 持仓 (sustained ADR-027 SHUTDOWN): expected 0 production fire 2025-04 window
3. 真 production filter: ST + 停牌 + 新股 < 60 days + BJ 排除 → universe 进一步 shrink

**TB-5c batch closure 任务**:
1. Compare baseline events × (production_universe / replay_universe) 与 risk_event_log 同窗口告警数 → gap quantitative metric
2. 补 avg_daily_volume / industry / atr_pct 数据后重跑 baseline, 覆盖 10/10 rules
3. 加 sim_baseline / production_actual / gap_pct 三列入 ADR-066 closure addendum

---

## Pure-function contract sustained (V3 §11.4 line 1294)

**Verified per window via RiskBacktestAdapter.verify_pure_function_contract**:
- before_sell_count == after_sell_count (0 broker.sell calls during evaluate_at)
- before_alert_count == after_alert_count (0 notifier.send calls during evaluate_at)
- 0 INSERT to risk_event_log (audit via implicit — adapter stub never INSERTs)

**TB-1a evaluate_at signature** (sustained 2026-05-13 ack):
- timestamp tz-aware required (铁律 41) — fails loud if naive
- dedup contract per (timestamp_iso, code, rule_id) — V3 §11.4 line 1298
- All cadence dispatch 走 RealtimeRiskEngine.on_tick / on_5min_beat / on_15min_beat (production parity)

---

## Sprint chain closure status (Plan v0.2 §A)

- ✅ **TB-1a** PR #330 `3e1ab6d` — evaluate_at + register_all_realtime_rules + dedup + pure-function audit (17 tests PASS)
- ✅ **TB-1b** PR #331 `971c88b` — ReplayRunner + ReplayWindow + EventSummary + summarize_events + 2 window constants (20 tests PASS)
- ✅ **TB-1c** 本 PR — scripts/v3_tb_1_replay_2_windows.py + real-test against DB minute_bars + 2 reflection markdowns sediment

**TB-1 sprint closure ✅ achieved**. 留 TB-5c batch closure 补 sim-to-real gap 量化 + 10/10 rules coverage.

---

## Tier B sprint chain status post-TB-1

| Sprint | Status | Notes |
|--------|--------|-------|
| T1.5 | ✅ DONE | ADR-065 Gate A 7/8 PASS + 1 DEFERRED |
| **TB-1** | ✅ **DONE** | 本 ADR-066 closure cumulative |
| TB-2 | ⏳ pending | MarketRegimeService Bull/Bear V4-Pro debate + market_regime_log + L3 集成 (~2 weeks) |
| TB-3 | ⏳ pending | RiskMemoryRAG + pgvector + BGE-M3 + 4-tier retention (~1-2 weeks) |
| TB-4 | ⏳ pending | RiskReflectorAgent + 5 维反思 V4-Pro + lesson 闭环 (~2 weeks) |
| TB-5 | ⏳ pending | Tier B closure + replay 验收 + V3 §15.6 ≥7 scenarios + Gate B/C close (~1 week) |

**Tier B baseline remaining**: ~7-8 weeks (TB-2~TB-5 cumulative, replan 1.5x = 11-12 weeks).

---

## Constitution / Plan / REGISTRY amendments (本 sediment cycle)

- `docs/adr/REGISTRY.md`: ADR-066 row appended (本 ADR)
- `docs/V3_TIER_B_SPRINT_PLAN_v0.1.md` §A TB-1 row: closure marker amend (留 TB-5c batch for "9 rules" → "10 rules")
- `LESSONS_LEARNED.md` LL-160 candidate (synthetic per-bar Position methodology pattern)
- `memory/project_sprint_state.md`: Session 53 +13 TB-1 closure handoff prepend

---

## 红线 sustained (1/5 cash + 1/5 positions + 1/5 .env + 1/5 mode + 1/5 LIVE_TRADING_DISABLED)

- cash=¥993,520.66 (sustained 4-30 user 决议清仓)
- 0 持仓 (xtquant 4-30 14:54 实测)
- LIVE_TRADING_DISABLED=true
- EXECUTION_MODE=paper
- QMT_ACCOUNT_ID=81001102

**0 broker call / 0 .env mutation / 0 真账户 touched** in TB-1c real-test. Pure read-only + in-memory replay.

---

## 关联

**ADR (cumulative)**: ADR-022 (反 retroactive edit) / ADR-027 (清仓决议) / ADR-029 (10 RealtimeRiskRule, S9a 加 TrailingStop) / ADR-054-061 (V3 Tier A S5-S9 sprint cumulative) / ADR-062 (S10 setup) / ADR-063 (S10 5d skip empty-system → Tier B 真测路径) / ADR-064 (Plan v0.2 5 决议 lock D3=b) / ADR-065 (Gate A formal closure 7/8 PASS) / ADR-066 (本)

**LL (cumulative)**: LL-098 X10 (反 auto forward-progress offer) / LL-115 family (CC self drift 11+ 实证) / LL-150-159 (S5-T1.5 cumulative session) / LL-160 candidate (synthetic per-bar Position methodology, 本)

**V3 spec**: §3.5 (fail-open) / §7.2-7.4 (S9 trailing + re-entry) / §11.1 (module path) / §11.4 (RiskBacktestAdapter pure function) / §15.4 (S10 acceptance) / §15.5 (sim-to-real gap counterfactual) / §15.6 (≥7 scenarios, TB-5) / §20.1 (战略对话 sediment)

**Constitution**: §L10.1 Gate A (ADR-063 item 2 DEFERRED + ADR-065 7/8 PASS) / §L10.2 Tier B 验收 (TB-5c 批 amend cumulative)

**File delta (本 PR sediment)**:
1. `scripts/v3_tb_1_replay_2_windows.py` NEW (~280 lines)
2. `docs/risk_reflections/replay/2024_replay_2024Q1_quant_crash.md` NEW
3. `docs/risk_reflections/replay/2025_replay_2025_04_07_tariff_shock.md` NEW
4. `docs/adr/ADR-066-v3-tb-1-replay-closure-2-windows.md` NEW (本)
5. `docs/adr/REGISTRY.md` amend (ADR-066 row append)
6. `LESSONS_LEARNED.md` amend (LL-160 append)
7. `memory/project_sprint_state.md` amend (handoff prepend)

7 file delta atomic 1 PR per ADR-064 D5=inline 体例 sustained.

---

**ADR-066 Status: Accepted (V3 Tier B TB-1 closure 真测 baseline + sim-to-real gap 起步 metric).**

新人 ADR, 0 reserved reserve.
