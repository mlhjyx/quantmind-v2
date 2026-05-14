# ADR-070: V3 Tier B TB-5b — Replay Acceptance (V3 §15.4 4 项 + §13.1 SLA verify on 2 关键窗口)

**Status**: Accepted
**Date**: 2026-05-14 (Session 53 + TB-5b sub-PR)
**Type**: V3 Tier B Sprint Sub-PR ADR (replay 真测结果 sediment per ADR-063 referenced "ADR-XXX 记录真测结果")
**Plan v0.2 row**: §A TB-5 row 第 2 sub-PR (TB-5b)

---

## Context

V3 Tier B Plan v0.2 §A TB-5 = "Tier B closure + RiskBacktestAdapter replay 验收 + V3 §15.6 合成场景 ≥7 类 + Gate B/C 形式 close", chunked 3 sub-PR: TB-5a (≥7 synthetic scenarios — PR #347 ✅) → **TB-5b (replay 验收 4 项 + 5 SLA verify on 2 关键窗口 + ADR-070 sediment + report doc)** → TB-5c (Gate B/C subagent verify + ADR-071 + Constitution amend + Tier B closure).

**Driver**: ADR-063 转 Tier B 真测路径. V3 §15.4 4 项 acceptance + V3 §13.1 SLA were originally designed for the Tier A S10 paper-mode 5d dry-run; ADR-063 deferred that (empty-system anti-pattern) and made them "transferable to the RiskBacktestAdapter 历史 minute_bars replay path". TB-1 (ADR-066) built the replay infrastructure + a fire-count baseline. TB-5b builds the **acceptance layer** on top of it: instrument the replay, compute the 4 §15.4 items + the replay-exercisable §13.1 SLA, decide + lock the numerical baselines.

**TB-1 prior work reused** (ADR-066): `ReplayRunner` + `RiskBacktestAdapter.evaluate_at` + the 2 关键窗口 constants (`WINDOW_2024Q1_QUANT_CRASH` 2024-01-02→02-09, `WINDOW_2025_04_07_TARIFF_SHOCK` 2025-04-01→04-11) + the synthetic per-bar universe-wide Position methodology (ADR-066 D3).

---

## Decisions

### D1: PURE acceptance evaluator module + `_TimingAdapter` side-channel — 0 changes to closed TB-1 code

**Decision**: TB-5b adds a new PURE module `backend/qm_platform/risk/replay/acceptance.py` (FP classification + latency percentile + STAGED closure + report assembly) and a thin DB-wired script `scripts/v3_tb_5b_replay_acceptance.py`. The replay is instrumented via a `_TimingAdapter` subclass of `RiskBacktestAdapter` (local to the script) that captures, as a side-channel, (a) per-`evaluate_at` wall-clock latency samples and (b) `(timestamp, RuleResult)` pairs — because `RuleResult` carries no timestamp and the FP counterfactual needs the alert time.

**Rationale**:
- `RuleResult` has no timestamp field; `ReplayRunner.run_window` returns a flat `list[RuleResult]`. The `_TimingAdapter` recovers both latency + timestamps **without modifying `runner.py` or `backtest_adapter.py`** (both closed in TB-1b/TB-1a) — sustained ADR-022 反 retroactive edit of closed code.
- The pure `acceptance.py` module is unit-testable in isolation (36 tests, 0 DB) — sustained 3-layer pattern (Engine PURE + thin script wrapper).
- 反 alternative: modifying `ReplayRunner` to collect latency/timestamps — would expand the blast radius into TB-1's closed code + require re-verifying TB-1's existing tests.

The synthetic-universe runner (`Tb1cRunner` equivalent — per-bar synthetic Position + 5min/15min lookback ring + day-boundary reset) is re-implemented locally in the TB-5b script rather than imported, because TB-1c's runner lives inside a script-local closure. Consolidating both into a shared module is **deferred** (out of TB-5b scope, 反 closed-code blast radius) — ~80 lines of bounded script-glue duplication accepted.

### D2: False-positive classification methodology — daily-dedup + `prev_close` baseline counterfactual (the key methodology lock)

**Decision**: A P0 alert's "误报" status is computed in two steps:
1. **DAILY DEDUP**: P0 events are deduped to the FIRST occurrence per `(code, rule_id, trading-day)`. The synthetic-universe replay registers `gap_down_open` at `tick` cadence, so it re-fires on every 5min bar of a gapped-down day (the rule is semantically `pre_market` once-daily — a v1-baseline artifact, ADR-066 D3 caveat family). Dedup mirrors a real alert dispatcher (no re-spamming the same stuck stock) and collapses the per-bar artifact.
2. **`prev_close` COUNTERFACTUAL**: a deduped P0 alert is a **FALSE POSITIVE** if the stock's **end-of-day close recovered to ≥ `prev_close`** (the day's flagged downside fully reversed — a synthetic position entered at `prev_close` ended NOT underwater). It is a **TRUE POSITIVE** if the stock ended the day **below `prev_close`** (the held position was actually underwater = real loss). No `prev_close` in metrics (correlated_drop — portfolio-level) OR no day-end close → UNCLASSIFIABLE, excluded from the rate denominator.

**Rationale — why NOT "did it fall further"**: the TB-5b smoke run exposed that a "P0 alert is a false positive if the stock didn't fall further within N bars" definition is **fundamentally broken for floor-hitting rules**. `limit_down_detection` flags a stock already AT the -10% 跌停 price floor — it physically cannot fall further, so the "fell further" test mis-labelled ~89% of 跌停 alerts as false positives (nonsense). The `prev_close`-baseline test asks the **operationally-correct** question — *did the held position end the day underwater* — uniformly across all directional P0 rules, and aligns with `verify_report.py`'s existing "alert but no actual loss" semantics + V3 §15.4 "following 1 day" intent (here: "by alert-day close").

**Two real bugs caught by the smoke run** (主动 verify-before-claim value):
- `gap_down_open` carries `open_price` + `prev_close` in metrics — **NO `current_price`**. The first FP implementation keyed on `current_price` and silently dropped ~66% of P0 events (all gap_down_open) as "unclassifiable". The `prev_close` baseline (present in all directional P0 rules) fixes this structurally.
- The "fell further" methodology flaw above.

### D3: Replay-path §13.1 SLA scope — 2/5 exercisable, 3/5 cross-referenced to TB-5a

**Decision**: Of the 5 SLA in Plan v0.2 §C, only **2 are exercisable on a pure-function replay path** and are measured by TB-5b:
- **L1 detection latency P99 < 5s** — per-`evaluate_at` wall-clock (see D6).
- **L4 STAGED 30min cancel 窗口** — pure-function `L4ExecutionPlanner` state-machine check.

The other **3 have no LLM / News / DingTalk path in a pure-function replay** and are covered by the TB-5a synthetic scenarios (PR #347), per Plan v0.2 §C line 203-207:
- L0 News 6 源 30s timeout → TB-5a scenario 5 (LLM 服务全挂)
- LiteLLM API < 3s, fail → Ollama → TB-5a scenario 5
- DingTalk push < 10s P99 → TB-5a scenario 6 (DingTalk 不可用)

**Rationale**: faithful reading of Plan §C — not a scope cut. The replay is a pure-function L1-rule evaluation; News/LiteLLM/DingTalk are L0/L2/notification-layer concerns with no replay surface. TB-5a's synthetic scenarios already exercise them.

### D4: V3 §15.4 #4 元监控 — replay-run integrity form

**Decision**: "元监控 0 P0 元告警 on replay run" is measured as the **replay-run integrity check**: `pure_function_contract_verified == True` (0 broker / 0 alert / 0 INSERT side effects) AND STAGED cancel-window integrity (no plan exceeds the 30min ceiling — the §13.3 ">35min PENDING_CONFIRM" 元告警 condition inverse).

**Rationale**: a pure-function replay cannot exercise the live §13.3 P0 元告警 conditions (L1 心跳超 5min / LiteLLM 失败率 >50% / DingTalk push fail / News 6 源全 timeout) — those are all production-runtime states. The replay-exercisable subset of §13.3 is the STAGED cancel-window integrity + the pure-function contract. ADR-070 documents the production-only conditions as N/A-on-replay.

### D5: Numerical baselines locked (replay run 2026-05-14, 2 关键窗口)

| Acceptance / SLA | Threshold | Window 1 (2024Q1) | Window 2 (2025-04-07) |
|---|---|---|---|
| P0 alert 误报率 | < 30% | **6.72%** (1244/18499) ✅ | **14.74%** (1438/9757) ✅ |
| L1 detection latency P99 | < 5000ms | **0.010ms** ✅ | **0.011ms** ✅ |
| L4 STAGED 流程闭环 0 失败 | = 0 | **0** (9 plans, 9 closed) ✅ | **0** (6 plans, 6 closed) ✅ |
| 元监控 0 P0 元告警 | = 0 | **0** ✅ | **0** ✅ |
| SLA L1 latency P99 | < 5s | 0.010ms ✅ | 0.011ms ✅ |
| SLA L4 STAGED 30min | ≤ 30min | all within window ✅ | all within window ✅ |

**Both windows PASS all 4 §15.4 items + 2 replay-exercisable SLA.** The 误报率 ordering is sensible: the 2024Q1 量化踩踏 crash window has a lower 误报率 (6.72%) than the 2025-04-07 tariff shock (14.74%) — in the sustained crash window, stocks that hit 跌停 / gapped down mostly stayed down (real losses → true positives); the tariff-shock window had more sharp-then-recover intraday volatility.

Per-rule FP breakdown (transparency, ADR-070 locked):
- Window 1: gap_down_open FP=1011/TP=11896 (7.8%) · limit_down_detection FP=79/TP=2126 (3.6%) · near_limit_down FP=154/TP=3233 (4.5%)
- Window 2: gap_down_open FP=1323/TP=3816 (25.7%) · limit_down_detection FP=37/TP=2179 (1.7%) · near_limit_down FP=78/TP=2324 (3.3%)

### D6: L1 detection latency is a documented LOWER-BOUND proxy

**Decision**: the replay-path "L1 detection latency P99" = the wall-clock of each `RiskBacktestAdapter.evaluate_at` call (one synthetic tick over the pure `RealtimeRiskEngine`). This is **explicitly a lower-bound proxy** for production tick→`risk_event_log` INSERT latency — it excludes I/O (DB INSERT, Redis read, network). The measured ~0.01ms trivially passes < 5s; ADR-070 records it as a proxy, not as production-equivalent latency. ADR-063 §1.5: replay path 等价 transferable (WHAT 不变, WHEN+HOW 换).

---

## Results

- **2 windows replayed against real DB minute_bars**: 2024Q1 (3,322,031 bars / 1,344 timestamps / 34.4s wall clock) + 2025-04-07 (962,544 bars / 384 timestamps / 10.2s) — counts match ADR-066 TB-1c baseline (328,680 + 234,952 events).
- **Pure-function contract verified True** both windows (0 broker / 0 alert / 0 INSERT during replay).
- **Acceptance report sedimented**: `docs/audit/v3_tb_5b_replay_acceptance_report_2026_05_14.md` — overall verdict ✅ PASS.
- **36 unit tests** for the pure `acceptance.py` module (`backend/tests/test_replay_acceptance.py`), `ruff check` + `ruff format` clean.

### Methodology limitations carried forward (ADR-066 D3 caveat family sustained)

- The synthetic universe-wide Position methodology (treat every stock as held, shares=100) means the 误报率 is a **universe-wide upper-bound proxy**, NOT a production-portfolio (≤20 stocks) precision metric. ADR-066 D3 + the TB-5c batch (compare baseline × shrink_ratio vs `risk_event_log`) sustain.
- 3/10 rules still silent-skip on the v1 baseline (VolumeSpike / LiquidityCollapse / IndustryConcentration meaningfully) due to missing `avg_daily_volume` / `industry` / `atr_pct` — ADR-066 D3 TB-5c data-enrichment task sustains. The P0 误报率 is computed over the 3 directional P0 rules that DO carry `prev_close` (limit_down_detection / near_limit_down / gap_down_open); correlated_drop is unclassifiable (portfolio-level, 0 in this single-symbol-context baseline).

---

## Tier B sprint chain status post-TB-5b

| Sprint | Status | Notes |
|--------|--------|-------|
| T1.5 | ✅ DONE | ADR-065 Gate A 7/8 PASS + 1 DEFERRED |
| TB-1 | ✅ DONE | ADR-066 replay baseline |
| TB-2 | ✅ DONE | ADR-067 MarketRegimeService V4-Pro × 3 |
| TB-3 | ✅ DONE | ADR-068 RiskMemoryRAG + pgvector + BGE-M3 |
| TB-4 | ✅ DONE | ADR-069 RiskReflectorAgent + lesson 闭环 |
| **TB-5** | 🟡 **in progress** | TB-5a ✅ PR #347 (≥7 synthetic scenarios) + **TB-5b ✅ 本 PR (replay acceptance + ADR-070)** + TB-5c ⏳ (Gate B/C verify + ADR-071 + Constitution amend + Tier B closure) |

**TB-5c remaining**: Gate B 5 项 + Gate C 6 项 subagent verify + ADR-071 cumulative sediment + Constitution §L10.1/§L10.2 amend + Constitution §0.1 line 35 ROADMAP closure 标注 + Tier B LL append-only review (**LL-164 candidate** — TB-5 closure 体例 + the TB-5b FP-methodology-flaw discovery is a candidate lesson: "verification methodology must be validated against the rule semantics it measures — a 'fell further' counterfactual is structurally wrong for floor-hitting rules") + memory handoff append + Plan v0.3 横切层 起手 prereq sediment.

---

## 红线 sustained (5/5)

- cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102
- TB-5b: 0 broker call / 0 .env mutation / 0 真账户 touched / 0 production code change. Pure read-only DB SELECT (minute_bars + klines_daily) + in-memory replay + new test/script/module files only.

---

## 关联

**ADR (cumulative)**: ADR-022 (反 retroactive edit of closed code) / ADR-027 (STAGED) / ADR-029 (10 RealtimeRiskRule) / ADR-036 (V4-Pro) / ADR-063 (Tier B 真测路径 transferable) / ADR-064 D3=b (2 关键窗口) / ADR-065 (Gate A closure) / ADR-066 (TB-1 replay baseline + D3 synthetic methodology + caveat family) / ADR-067 (TB-2) / ADR-068 (TB-3) / ADR-069 (TB-4) / ADR-070 (本) / ADR-071 候选 (TB-5c Tier B closure)

**LL (cumulative)**: LL-067 (reviewer 2nd-set-of-eyes 体例, 24 实证 cumulative pre-TB-5b) / LL-098 X10 (反 auto forward-progress) / LL-100 (chunked sub-PR SOP) / LL-115 family (CC self drift) / LL-159 (4-step preflight SOP) / LL-160-163 (TB-1~TB-4 closure cumulative) / **LL-164 候选** (TB-5 closure 体例 + verification-methodology-must-match-rule-semantics — 留 TB-5c promote)

**V3 spec**: §13.1 (SLA 定义) / §13.2-13.3 (元监控 / 元告警) / §15.4 (S10 4 项 acceptance) / §15.5 (历史回放 sim-to-real gap counterfactual) / §15.6 (≥7 scenarios, TB-5a) / §11.4 (RiskBacktestAdapter pure function)

**Constitution**: §L10.2 Gate B (TB-5c subagent verify) / §L10.3 Gate C (TB-5c)

**Plan**: V3_TIER_B_SPRINT_PLAN_v0.1.md §A TB-5 row line 131-145 + §C (Gate B/C + §15.4 4 项 + §13.1 5 SLA mapping) + §D (replay 真测期 SOP)

**File delta (本 PR)**:
1. `backend/qm_platform/risk/replay/acceptance.py` NEW (~370 lines — PURE FP classification + latency percentile + STAGED closure + report assembly)
2. `scripts/v3_tb_5b_replay_acceptance.py` NEW (~390 lines — DB-wired runner + `_TimingAdapter` + day-end price index + report sediment)
3. `backend/tests/test_replay_acceptance.py` NEW (~360 lines, 36 tests)
4. `docs/audit/v3_tb_5b_replay_acceptance_report_2026_05_14.md` NEW (acceptance run evidence — overall ✅ PASS)
5. `docs/adr/ADR-070-v3-tb-5b-replay-acceptance.md` NEW (本)
6. `docs/adr/REGISTRY.md` amend (ADR-070 row append + count footer)

6 file delta atomic 1 PR per ADR-064 D5=inline 体例 sustained.

---

**ADR-070 Status: Accepted (V3 Tier B TB-5b replay acceptance — 4 项 + 2 SLA verify on 2 关键窗口, both windows PASS, FP methodology + 阈值 baselines locked).**

新人 ADR, 0 reserved reserve.
