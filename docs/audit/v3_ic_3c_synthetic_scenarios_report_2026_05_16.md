# V3 IC-3c — Synthetic Scenarios Re-run Report (V3 §15.6 ≥7 类)

**Run date**: 2026-05-16
**Overall verdict**: ✅ PASS (24/24 tests across 7 scenario classes)
**Main HEAD at re-run**: `cdfd452` (post IC-3b closure)
**Test target**: `backend/tests/test_v3_15_6_synthetic_scenarios.py`

**Scope**: V3 Plan v0.4 §A IC-3c — Replay-as-cutover-gate validation suite,
family (c): re-run V3 §15.6 ≥7 synthetic scenarios on **FULLY-INTEGRATED V3
chain** (post IC-1 + IC-2 de-stub + IC-3a 5y integrated replay + IC-3b
counterfactual). Sustained TB-5a infrastructure (committed PR #316 / ADR-067)
with 0 code changes; this report sediments the re-run verdict at IC-3 closure
gate per Plan §A row 4 "synthetic scenarios re-run report".

---

## §1 7 scenarios verdicts

| # | Scenario | V3 §15.6 reference | Tests | Verdict |
|---|---|---|---|---|
| 1 | 4-29 类事件 (3 股盘中跌停 + 大盘 -2%) | line 1546 | 5/5 | ✅ |
| 2 | 单股闪崩 (-15% in 5min) | line 1547 | 3/3 | ✅ |
| 3 | 行业崩盘 (持仓 5 股同行业, 行业 day -5%) | line 1548 | 3/3 | ✅ |
| 4 | regime 急转 (Bull → Bear in 1 day) | line 1549 | 2/2 | ✅ |
| 5 | LLM 服务全挂 + Ollama fallback | line 1550 | 3/3 | ✅ |
| 6 | DingTalk 不可用 + email backup | line 1551 | 3/3 | ✅ |
| 7 | user 离线 4h + STAGED 30min timeout | line 1552 | 5/5 | ✅ |
| **Total** | | | **24/24** | **✅ PASS** |

**Wall-clock**: 0.10s (24 tests, fully PURE — 0 IO / 0 DB / 0 network).

---

## §2 Per-scenario test breakdown

### §2.1 Scenario 1: 4-29 类事件 (multi-stock limit-down + 大盘 -2%)

`TestScenario1MultiLimitDown` — 5 tests, ✅ all pass:
- `test_limit_down_fires_for_all_3_stocks` — LimitDownDetection P0 fires per
  跌停 code (sustained ADR-029 D6)
- `test_near_limit_down_silent_when_full_limit_down` — NearLimitDown skip
  when stock already at full 跌停 floor (avoids dual-alert noise)
- `test_near_limit_down_fires_in_warning_band` — NearLimitDown fires in
  -9% to -9.99% band per ADR-029 D3
- `test_correlated_drop_fires_portfolio_level_p0` — portfolio-level P0 when
  ≥3 positions same direction (V3 §11.3 line 855)
- `test_evaluate_at_production_parity_pure_function` — RiskBacktestAdapter
  evaluate_at dispatch matches production tick路径

### §2.2 Scenario 2: 单股闪崩 (-15% in 5min)

`TestScenario2SingleStockFlashCrash` — 3 tests, ✅ all pass:
- `test_rapid_drop_5min_fires_for_crashing_stock_only` — RapidDrop5min P0
  isolates flash crash to affected code
- `test_steady_stock_does_not_trigger` — control assertion (sustained 铁律 33
  silent_ok skip-path semantics)
- `test_evaluate_at_5min_boundary_dispatch` — 5min cadence dispatch boundary

### §2.3 Scenario 3: 行业崩盘 (5 股同行业, 行业 day -5%)

`TestScenario3IndustryCollapse` — 3 tests, ✅ all pass:
- `test_industry_concentration_fires` — IndustryConcentration P0 when ≥3
  positions in same SW1 industry hit threshold
- `test_correlated_drop_fires_for_all_5` — correlated_drop independently
  fires when ≥3 same-direction
- `test_diversified_portfolio_does_not_trigger_concentration` — control
  assertion for diversified portfolio (4+ different industries)

### §2.4 Scenario 4: regime 急转 (Bull → Bear in 1 day)

`TestScenario4RegimeFlip` — 2 tests, ✅ all pass:
- `test_regime_flips_bull_to_bear_same_day` — MarketRegimeService with mock
  V4-Pro router classifies regime correctly under flip conditions
- `test_classify_dispatches_bull_bear_judge_in_order` — 3-agent debate体例
  (Bull → Bear → Judge) dispatch order sustained ADR-067 D3

### §2.5 Scenario 5: LLM 服务全挂 + Ollama fallback

`TestScenario5LLMOutageAndFallback` — 3 tests, ✅ all pass:
- `test_llm_full_outage_fails_loud` — RegimeService raises clearly when all
  LLM routes fail (NOT silent fallback to default regime)
- `test_l1_detection_survives_llm_outage` — L1 RealtimeRiskEngine tick path
  is independent of LLM, continues firing alerts during outage
- `test_ollama_fallback_path_still_classifies` — LiteLLM router fallback to
  Ollama produces valid classification when primary down

### §2.6 Scenario 6: DingTalk 不可用 + email backup

`TestScenario6DingTalkDownEmailBackup` — 3 tests, ✅ all pass:
- `test_dingtalk_down_records_send_failure` — AlertDispatcher logs DingTalk
  failure NOT silent swallow
- `test_email_backup_persists_failed_alert` — EmailBackupStub persists alert
  payload to FS when primary fails
- `test_dingtalk_down_then_email_backup_end_to_end` — chained fallback
  dispatch sequence verified

### §2.7 Scenario 7: user 离线 4h + STAGED 30min timeout

`TestScenario7UserOfflineStagedTimeout` — 5 tests, ✅ all pass:
- `test_staged_plan_has_strict_30min_window` — L4ExecutionPlanner enforces
  30min cancel window ceiling per V3 §13.1 SLA #5
- `test_within_window_plan_not_expired` — plan within 30min window not yet
  timeout-eligible
- `test_user_offline_4h_triggers_timeout_execute` — beyond 30min triggers
  TIMEOUT_EXECUTED state transition (sustained ADR-027 反向决策权 耗尽)
- `test_user_cancels_within_window_blocks_timeout` — explicit user cancel
  before deadline overrides timeout default
- `test_alert_only_result_does_not_generate_staged_plan` — alert_only action
  bypasses STAGED machinery (sustained planner.py contract)

---

## §3 Architecture invariants verified

The 7 scenarios exercise REAL code paths across all V3 layers:

| Layer | Scenarios | Real code path |
|---|---|---|
| L1 RealtimeRiskEngine | 1, 2, 3, 5 | 10 RealtimeRiskRule production rules via RiskBacktestAdapter |
| L2 MarketRegimeService | 4, 5 | Bull/Bear/Judge 3-agent debate with mock V4-Pro router |
| L3 daily-cadence | (covered IC-3a) | n/a — IC-3a's 4 PURE rules cover this layer |
| L4 STAGED state machine | 7 | L4ExecutionPlanner.generate_plan + timeout_execute |
| Notifier chain | 6 | AlertDispatcher + EmailBackupStub fallback |
| Resilience (LLM outage) | 5 | LiteLLM router + Ollama fallback fail-loud semantics |

**0 invented APIs**: all 24 assertions hit production-equivalent code paths
(sustained 铁律 25 / 36 — improved-test 体例).

---

## §4 ADR-080 candidate sediment data (for IC-3d closure)

**3-family cumulative IC-3 acceptance verdict**:

| Family | Sub-PR | Result | Sediment artifact |
|---|---|---|---|
| (a) 5y integrated replay | IC-3a (#368, `c6196bc`) | ✅ 4/4 V3 §15.4 PASS + L3 wiring green | `v3_ic_3a_5y_integrated_replay_report_2026_05_16.md` |
| (b) Counterfactual (3 incidents) | IC-3b (#369, `cdfd452`) | ✅ 3/3 PASS (mixed methodology) | `v3_ic_3b_counterfactual_replay_report_2026_05_16.md` |
| (c) Synthetic scenarios (≥7) | IC-3c (本 report) | ✅ 24/24 across 7 classes | `v3_ic_3c_synthetic_scenarios_report_2026_05_16.md` |

ADR-080 reserved → committed in IC-3d, will cite cumulative 3-family green
as the cutover-gate evidence for Plan v0.4 transition to CT-1.

---

## §5 Methodology + 红线 sustained

- **Re-run-only deliverable** — Plan §A IC-3c row "synthetic scenarios re-run
  report". 0 new test code; TB-5a `test_v3_15_6_synthetic_scenarios.py`
  delivered the 7-scenario fixture+assertion suite + ADR-067 committed
  (PR #316). IC-3c verifies these still pass on current main HEAD `cdfd452`
  after IC-1 + IC-2 de-stub + IC-3a + IC-3b cumulative wiring changes.
- **PURE replay path** sustained ADR-063 — 0 IO / 0 DB / 0 network / 0
  broker / 0 INSERT. All 24 tests run in 0.10s.
- **0 真账户 / 0 .env mutation**. 红线 5/5 sustained: cash=￥993,520.66 /
  0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper /
  QMT_ACCOUNT_ID=81001102.

---

## §6 关联

- V3 §15.6 (line 1543-1554 合成场景 methodology) + §13.1 (5 SLA, transferred
  scenario 5/6/7) + §15.4 (acceptance)
- ADR-063 (Tier B 真测路径) + ADR-067 (Bull/Bear/Judge 3-agent debate) +
  ADR-027 (STAGED state machine) + ADR-029 (10 RealtimeRiskRule) +
  ADR-036 (V4-Pro router) + ADR-076 (横切层 closed) + ADR-080 候选 (IC-3 closure)
- Plan v0.4 §A IC-3c row + §B row 5 + Plan v0.2 §A TB-5 row (TB-5a sub-PR
  source for the test file)
- 铁律 22 / 24 / 25 (改什么读什么) / 31 (Engine PURE) / 33 (fail-loud) /
  40 (test debt sustained — 0 new fails) / 41 (timezone)
- LL-098 X10 / LL-159 (4-step preflight) / LL-168/169 (verify-heavy
  classification — IC-3c re-run-only, NOT net-new-wiring) / LL-170 候选
  lesson 3 (replay-as-gate) / LL-172 lesson 1 (multi-dir grep)

---

## §7 Phase 0 active discovery summary

Per LL-159 + LL-172 amended preflight (multi-dir grep + data presence + cron
alignment + natural production behavior + verify pattern):

- ✅ Step 1 SSOT calendar: N/A — no calendar-dependent assertions in synthetic
  scenarios (all PURE in-memory).
- ✅ Step 2 data presence: N/A — synthetic in-memory positions / market
  snapshots, no DB read.
- N/A Step 3 cron alignment: not a schtask.
- N/A Step 4 natural production behavior: this report IS the verification.
- ✅ Step 5 multi-dir grep: verified `backend/tests/test_v3_15_6_synthetic_scenarios.py`
  is the canonical TB-5a deliverable; 0 ADR-029/036/067/027 rule registry
  drift since TB-5a committed.

**Pre-existing infra integrity**: the 24-test suite was previously green per
TB-5a closure (PR #316, ADR-067 committed). IC-3c re-run confirms 0 regression
across all IC-1 + IC-2 + IC-3a + IC-3b wiring changes (sustained 铁律 40
"测试债务不得增长").
