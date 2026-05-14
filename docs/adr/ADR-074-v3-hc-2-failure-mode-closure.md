# ADR-074: V3 横切层 HC-2 Closure — 失败模式 15 项 enforce + 灾备演练 synthetic ≥1 round

**Status**: Accepted
**Date**: 2026-05-14
**Context**: Session 53+29, V3 横切层 Plan v0.3 §A HC-2 sprint closure (Gate D item 2)
**Related**: ADR-022 (反 retroactive content edit — Plan §A append-only amend) / ADR-072 (Plan v0.3 3 决议 lock — HC-2 = D1 second sprint) / ADR-073 (HC-1 closure — HC-2 builds 失败模式 enforce on top of the alert-on-alert layer) / LL-098 X10 / LL-100 (chunked SOP) / LL-166 (HC-1 closure 体例 — scope-balloon-as-replan-trigger sustained) / LL-167 (本 HC-2 closure 体例)

---

## §1 Context

V3 横切层 Plan v0.3 §A HC-2 = Gate D item 2 — V3 §14 失败模式表 enforce + 灾备演练 ≥1 round. HC-2a audited all 15 modes into an enforcement matrix + 12-item gap list; HC-2b/b2/b3 wired the missing detection/degrade paths; HC-2c ran the disaster drill (synthetic injection ≥1 round, mode 1-12) + sediment.

HC-2 planned (Plan v0.3 §A) as **chunked 3 sub-PR** (HC-2a/b/c). Actual: **chunked 5 sub-PR** (HC-2a/b/b2/b3/c) — 2 extra via the 12-item gap list being materially larger than the plan's "wire any missing detection/degrade path" assumption (§2 D2). 红线 5/5 sustained throughout: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

---

## §2 Decision

### D1 — V3 §14 失败模式 = 15 模式 superset enforce (12 vs 15 真值差异, HC-2a Finding)

Constitution §L10.4 / §0.1 footer cite "失败模式 12 项" is a stale cite — V3 §14 表真值 = **15 模式** (mode 13 BGE-M3 OOM / mode 14 RiskReflector V4-Pro 失败 / mode 15 LIVE_TRADING_DISABLED 双锁失效 是表演进新增, sustained Plan v0.3 §H Finding #1 + ADR-072 D-Finding #1). HC-2a enforcement matrix doc enumerates all 15; HC-2b/b2/b3 wired the mode-relevant gaps. Constitution §L10.4 item 2 + §0.1 footer "12 项 → 15 模式" amend 留 HC-4c batch closure 标注 (sustained ADR-022 反 retroactive content edit).

### D2 — HC-2b scope balloon → HC-2b / HC-2b2 / HC-2b3 (gap-list-driven)

Plan v0.3 §A assumed HC-2b = "wire any missing detection/degrade path" (~1 sub-PR). HC-2a's 12-item gap list surfaced materially more net-new wiring than planned — 2 scope splits, each user-approved via AskUserQuestion (Plan v0.3 §F (iii)):
- **HC-2b** (PR #354) = G5 (V3 §14 mode 14 — RiskReflector 失败 retry-once-skip + `RISK_REFLECTOR_FAILED` event-emitted 元告警) + G6 (V3 §14 mode 15 — `assert_live_trading_lock_integrity` LIVE_TRADING_DISABLED 双锁 startup gate).
- **HC-2b2** (PR #355) = G7 (V3 §14 mode 12 — `sweep_stuck_broker_plans` + `BROKER_PLAN_STUCK` event-emitted 元告警 P0 + Beat */5) + G8 (V3 §14 mode 4 — `RedisThresholdCache` cooldown auto-reconnect, Redis 恢复无需进程重启).
- **HC-2b3** (PR #356 + #357 followup) = G3 (V3 §14 mode 3 — `evaluate_pg_health` polled meta-alert rule, `pg_stat_activity` idle-in-tx) + G4 (V3 §14 mode 9 — `evaluate_market_crisis` polled meta-alert rule + `market_indicators_query` shared feed de-stub).

HC-2 → **5 sub-PR (a/b/b2/b3/c)**.

### D3 — 灾备演练 = synthetic injection ≥1 round, NOT 月度 wall-clock drill (Plan v0.3 §G push-back #3)

V3 §14.1 line 1465 cites "每月 1 次, 模拟 failure mode 1-12" — a wall-clock cadence. HC-2c 决议: 灾备演练 = **synthetic injection** pytest fixture/script (instant, 0 wall-clock wait — sustained TB-5a synthetic scenario fixture 体例 + memory feedback_no_observation_periods 反日历式观察期). V3 §14.1 "每月 1 次" cite NOT amended (设计层保留 production cadence 建议); Gate D closure 验收走 synthetic injection ≥1 round. Round 1 = `backend/tests/test_v3_hc_2c_disaster_drill.py` (29 tests, 12 modes) + sediment `docs/risk_reflections/disaster_drill/2026-05-14.md`.

### D4 — carried gaps explicitly routed (HC-2a matrix §3 + HC-2c drill §2)

HC-2 closes with the enforcement surface wired + carried gaps explicitly routed (sustained ADR-071 D4 honest-scope 体例 — DEFERRED with reasoning on record, NOT faked PASS, NOT blocking closure):
- **mode 2 / mode 11** (G1/G2): xtquant 断连 + RealtimeRiskEngine crash — `evaluate_l1_heartbeat` PURE rule works, but collector no-signal / no production realtime runner. → **Plan v0.4 cutover** (shared root cause, sustained ADR-073 D3).
- **mode 3** (G3): PG `risk_event_log → memory-cache` full degrade path — ~30-file writer surface + new memory-cache subsystem, sprint-sized. detection + 元告警 wired (HC-2b3 G3). full-degrade → **HC-4 / Plan v0.4**.
- **mode 9** (G4): §14.2 Crisis Mode behaviors (alert dedup 同行业合并 / portfolio-level 1 push / News 减频) — substantial subsystem. detection + 元告警 + batched_planner degrade wired (HC-2b3 G4). §14.2 behaviors → carried.
- **mode 7 / mode 10** (G10/G12, spec ⚠️ P2): Tushare rate-limit 元告警 + 误触发 quantitative 误报率 threshold → future sprint (P2 低优先).

### D5 — spec-internal divergence record (§6.1 Crisis vs §14 mode 9 Crisis)

V3 design itself carries two "Crisis" threshold definitions: `QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md:754` §6.1 Crisis = 大盘 -5% OR 跌停 > 200 (L3 阈值收紧触发, `dynamic_threshold/engine.py MarketState.CRISIS`); `:1455` §14 mode 9 = 大盘 -7% / 跌停 > 500 (千股跌停极端 regime, Crisis Mode 触发). HC-2b3 G4's `evaluate_market_crisis` uses the §14 mode 9 thresholds (-7%/>500). The two same-named tiers = spec-internal divergence, recorded for HC-4c batch closure 标注 (sustained HC-2a §4 divergence 体例 + ADR-022 反 retroactive edit, 仅 append 标注).

---

## §3 Consequences

### §3.1 HC-2 5 sub-PR cumulative

| sub-PR | PR | scope |
|---|---|---|
| HC-2a | (bundled into #354) | V3 §14 15-mode enforcement matrix audit doc + 12-item gap list — `docs/audit/v3_hc_2a_failure_mode_enforcement_matrix_2026_05_14.md` |
| HC-2b | #354 | G5 RiskReflector 失败 retry-once-skip + 元告警 / G6 LIVE_TRADING_DISABLED 双锁 startup gate |
| HC-2b2 | #355 | G7 broker plan stuck sweep + `BROKER_PLAN_STUCK` 元告警 / G8 Redis cooldown auto-reconnect |
| HC-2b3 | #356 + #357 | G3 `evaluate_pg_health` PG OOM meta-alert / G4 `evaluate_market_crisis` Crisis regime meta-alert + `market_indicators_query` feed de-stub (#357 = post-merge python+database reviewer findings) |
| HC-2c | 本 | 灾备演练 synthetic injection ≥1 round (29 tests, 12 modes) + sediment doc + ADR-074 + LL-167 + REGISTRY + Plan §A amend |

Reviewer 2nd-set-of-eyes: HC-2b/b2/b3 each independent reviewer agent (HC-2b/b2 `oh-my-claudecode:code-reviewer` APPROVE 0 CRITICAL/HIGH; HC-2b3 `code-reviewer` APPROVE + post-merge `python-reviewer` + `database-reviewer` → #357 followup — sustained feedback_code_pr_workflow parallel-multi-reviewer 体例). HC-2c (test + docs) → `code-reviewer` + `python-reviewer`.

### §3.2 HC-2 closed — Gate D item 2 code-side complete

V3 §14 失败模式 enforcement surface wired across 15 modes (HC-2a matrix + HC-2b/b2/b3 gap wire); 灾备演练 ≥1 round synthetic injection complete (HC-2c, 8/12 ✅ full chain + 4/12 🟡 carried-gap rounds). **Gate D item 2 formal verify 留 HC-4c** (sustained Plan v0.3 §C — Gate D formal close = HC-4c, NOT per-sprint HC-2c).

### §3.3 Constitution §L0.4 replan-trigger surfaced + handled (2nd consecutive 横切层 sprint)

HC-2 3→5 sub-PR = Constitution §L0.4 ("任 sprint 实际超 baseline 1.5x → STOP + push user") trigger — the **2nd consecutive 横切层 sprint** to balloon (HC-1 also 3→5, ADR-073 §3.3). Surfaced via HC-2a's 12-item gap list being larger than the plan's "wire any missing path" assumption; each scope fork user-acknowledged via AskUserQuestion (Plan v0.3 §F (iii)). Handled by append-only Plan v0.3 §A HC-2 row amendment (本 ADR + Plan §A closure blockquote, sustained ADR-022). The cumulative HC-1+HC-2 pattern (both 3→5) is itself meta-evidence the 横切层 plan's per-sprint chunk estimate runs low — surfaced to user as a sustained finding (LL-167 lesson 1).

### §3.4 post-merge ops

- HC-2b2 G7: `risk-l4-broker-stuck-sweep` Beat schedule (Servy restart QuantMind-CeleryBeat AND QuantMind-Celery — sustained LL-141 4-step).
- HC-2c: 0 post-merge ops (test + docs only, no Beat/migration/.env).

### §3.5 横切层 期 ADR cumulative

ADR-072 (Plan v0.3 3 决议 lock) + ADR-073 (HC-1 closure) + **ADR-074 (本 — HC-2 closure)** + ADR-075 (HC-3) + ADR-076 (HC-4 + Gate D formal close) reserved.

---

## §4 Cite

- [Plan v0.3 §A HC-2 row](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (HC-2 sprint plan + closure blockquote)
- [Plan v0.3 §C](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (Gate D criteria — item 2 formal verify 留 HC-4c)
- [Plan v0.3 §D](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (横切层 真测期 SOP — HC-2 灾备演练 synthetic injection)
- [HC-2a enforcement matrix](audit/../../audit/v3_hc_2a_failure_mode_enforcement_matrix_2026_05_14.md) (15-mode matrix + 12-item gap list SSOT)
- [disaster drill round 1](../risk_reflections/disaster_drill/2026-05-14.md) (HC-2c synthetic injection sediment)
- [ADR-073](ADR-073-v3-hc-1-meta-alert-closure.md) (HC-1 closure — HC-2 builds 失败模式 enforce on the alert-on-alert layer)
- [ADR-072](ADR-072-v3-crosscutting-plan-v0-3-3-decisions-lock.md) (Plan v0.3 3 决议 lock — HC-2 = D1 second sprint)
- [LL-167](../../LESSONS_LEARNED.md) (HC-2 closure 体例 — scope-balloon 2nd consecutive + synthetic-injection-drill 体例 + carried-gap honest closure)
- HC-2 PR #354 / #355 / #356 / #357

### Related ADR

- [ADR-022](ADR-022-anti-anti-pattern-集中修订机制.md) (反 retroactive content edit — Plan §A append-only amend + §6.1-vs-§14 divergence 留 HC-4c 标注)
- [ADR-063](ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (paper-mode deferral pattern — carried gaps 沿用)
