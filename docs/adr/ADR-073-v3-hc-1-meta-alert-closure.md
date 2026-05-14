# ADR-073: V3 横切层 HC-1 Closure — 元监控 alert-on-alert production-active

**Status**: Accepted
**Date**: 2026-05-14
**Context**: Session 53+26, V3 横切层 Plan v0.3 §A HC-1 sprint closure (Gate D item 1)
**Related**: ADR-022 (反 retroactive content edit — Plan §A append-only amend) / ADR-062 (Tier A S10 risk_metrics_daily, HC-1 builds alert-on-alert layer on top) / ADR-063 (paper-mode deferral pattern) / ADR-072 (Plan v0.3 3 决议 lock — HC-1 = D1 first sprint) / LL-098 X10 / LL-100 / LL-164 (Gate-verifier-as-charter) / LL-165 (Plan v0.3 plan-then-execute) / LL-166 (本 HC-1 closure 体例)

---

## §1 Context

V3 横切层 Plan v0.3 §A HC-1 = Gate D item 1 — V3 §13.3 元告警 (alert-on-alert) production-active. risk_metrics_daily 表 + daily_aggregator + Beat 已 Tier A S10 production-active (ADR-062); HC-1 wires the alert-on-alert layer on top — 5 元告警 rule (PURE) + Application orchestration + Beat dispatch + channel fallback chain.

HC-1 planned (Plan v0.3 §A) as **chunked 3 sub-PR** (HC-1a/b/c, ~1000-1800 行). Actual: **chunked 5 sub-PR** (HC-1a/b/b2/b3/c) — 2 extra via precondition-surfaced scope splits (§2 D2). 红线 5/5 sustained throughout: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

---

## §2 Decision

### D1 — §13.3-vs-§14 severity reconciliation (HC-1a Phase 0 Finding)

V3 §13.3 groups 5 元告警 场景 under a "P0 元告警" header, but V3 §14 失败模式表 (per-mode 元告警 column) is more granular: mode 6 News 全 timeout = ⚠️ **P1** (fail-open degraded, alert 仍发 仅缺 sentiment context — not system failure). HC-1 follows §14 per-mode 真值: **News rule = P1, 其余 4 = P0**. Also: §13.3's STAGED **>35min** is distinct from §14 mode 8's normal **30min** user-offline auto-execute (设计行为, ❌ 不元告警) — >35min still PENDING_CONFIRM = cancel_deadline mechanism itself failed = P0. `RULE_SEVERITY` SSOT in `meta_alert_interface.py`.

### D2 — HC-1b scope split into HC-1b / HC-1b2 / HC-1b3 (precondition-surfaced)

Plan v0.3 §A assumed HC-1 = "wire alert-on-alert layer on existing infra" (~1000-1800 行 total). Precondition 核 surfaced materially more net-new infrastructure than planned — 2 scope splits, each user-approved via AskUserQuestion (Plan v0.3 §F (iii)):
- **HC-1b split** → HC-1b (core monitoring loop: meta_monitor_service + Beat wire + 2 real collectors LiteLLM/STAGED + 3 no-signal) + HC-1b2 (channel fallback chain + gap-source instrumentation). Reason: email backup channel + DingTalk-push-status persistence don't exist — genuine net-new infra, not "wire on top".
- **HC-1b2 split** → HC-1b2 (channel fallback chain: email backup + log-P0 escalation) + HC-1b3 (3 gap-source instrumentation). Reason: HC-1b2-as-bundled ≈ 4 workstreams ~700-1000 行, exceeds LL-100 chunked SOP.

HC-1 → **5 sub-PR (a/b/b2/b3/c)**.

### D3 — L1-heartbeat instrumentation DEFERRED (HC-1b3 Finding)

`XtQuantTickSubscriber` + `RealtimeRiskEngine` are instantiated **only in tests + the replay runner** — there is NO production runner wiring the realtime subscriber into a live tick flow (S5/Tier A built the components; production wiring deferred, consistent with paper-mode 红线 0 持仓 / LIVE_TRADING_DISABLED=true). Instrumenting an L1-heartbeat source now would never fire. `_collect_l1_heartbeat` stays no-signal — the **correct** state until the realtime engine gets production-wired (Plan v0.4 cutover scope candidate — touches live xtquant). Not "not yet wired", "源在 production 尚不存在". User-acknowledged via AskUserQuestion.

### D4 — channel fallback chain design (V3 §13.3, HC-1b2)

主 DingTalk → 备 email → 极端 log-P0 (`_push_via_channel_chain`):
- 主 DingTalk terminal when delivered OR by-design-skip (`sent` / `dedup_suppressed` / `alerts_disabled`); escalate to email on `no_webhook` (configured-but-undeliverable) OR `httpx.HTTPError` OR any non-DB error.
- 备 email terminal when sent; escalate to log-P0 on not-delivered / raises.
- 极端 log-P0 = `logger.critical` last resort — 元告警 never silently vanishes.
- `psycopg2.Error` from `send_with_dedup`'s alert_dedup write is NOT caught — propagates (borked transaction, different failure class than channel-down; Beat task rolls back + Celery retries).
- 双锁 sustained: `EMAIL_ALERTS_ENABLED` default-off + SMTP config completeness gate.

### D5 — 4/5 collectors real, 1 DEFERRED (post-HC-1b3)

`meta_monitor_service` collector status:
- LiteLLM 失败率 — real query `llm_call_log` ✅ (HC-1b)
- STAGED overdue — real query `execution_plans` ✅ (HC-1b)
- DingTalk push status — real query `alert_dedup.last_push_ok` ✅ (HC-1b3, +2 cols migration)
- News 全源 timeout — real read Redis `qm:news:last_run_stats` ✅ (HC-1b3, DataPipeline run-stats memo + Beat persist)
- L1 心跳 — no-signal, DEFERRED per D3

---

## §3 Consequences

### §3.1 HC-1 5 sub-PR cumulative

| sub-PR | PR | scope |
|---|---|---|
| HC-1a | #350 `ed3f196` | meta-alert Engine PURE interface + 5 元告警 rule 纯函数 + 38 tests |
| HC-1b | #351 | meta_monitor_service Application + meta_monitor_tasks Beat wire (5min cadence) + runbook; 2 real + 3 no-signal collectors |
| HC-1b2 | #352 | channel fallback chain (email_alert.py + _push_via_channel_chain) + 7 SMTP config fields |
| HC-1b3 | #353 | DingTalk-push-status (alert_dedup +2 cols) + News per-source (DataPipeline run-stats → Redis) instrumentation |
| HC-1c | 本 (直 push, 铁律 42 docs-only) | ADR-073 + Plan §A HC-1 row append-only amend + LL-166 + REGISTRY + memory handoff |

Reviewer 2nd-set-of-eyes: 4 实证 (HC-1a/b/b2/b3 each `oh-my-claudecode:code-reviewer` COMMENT verdict — 0 CRITICAL/HIGH cumulative; all MEDIUM/LOW applied).

### §3.2 HC-1 closed — Gate D item 1 code-side complete

元监控 alert-on-alert layer production-ready: 5-rule meta_monitor tick (5min Beat cadence), 4/5 collectors real, channel fallback chain 主 DingTalk → 备 email → 极端 log-P0. **Gate D item 1 formal verify 留 HC-4c** (sustained Plan v0.3 §C — Gate D formal close = HC-4c, NOT per-sprint HC-1c).

### §3.3 Constitution §L0.4 replan-trigger surfaced + handled

HC-1 3→5 sub-PR = Constitution §L0.4 ("任 sprint 实际超 baseline 1.5x → STOP + push user") trigger. Surfaced via 4 consecutive precondition 核 each finding under-estimation; user-acknowledged at each scope fork (Plan v0.3 §F (iii)). Handled by append-only Plan v0.3 §A HC-1 row amendment (本 ADR + Plan §A closure blockquote, sustained ADR-022 反 retroactive content edit). Plan v0.3 §A HC-1 row "chunked 3 sub-PR" → actual 5 标注 append-only (NOT silent rewrite).

### §3.4 post-merge ops (2 runbooks)

- `docs/runbook/cc_automation/v3_hc_1b_meta_monitor_beat_wire.md` — Beat schedule wire (Servy restart QuantMind-CeleryBeat AND QuantMind-Celery)
- `2026_05_14_alert_dedup_push_status.sql` migration apply (alert_dedup +2 cols) — HC-1b3, post-merge ops

### §3.5 横切层 期 ADR cumulative

ADR-072 (Plan v0.3 3 决议 lock) + **ADR-073 (本 — HC-1 closure)** + ADR-074 (HC-2) + ADR-075 (HC-3) + ADR-076 (HC-4 + Gate D formal close) reserved.

---

## §4 Cite

- [Plan v0.3 §A HC-1 row](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (HC-1 sprint plan + closure blockquote)
- [Plan v0.3 §C](../V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) (Gate D criteria — item 1 formal verify 留 HC-4c)
- [ADR-072](ADR-072-v3-crosscutting-plan-v0-3-3-decisions-lock.md) (Plan v0.3 3 决议 lock — HC-1 = D1 first sprint)
- [ADR-062](ADR-062-v3-s10-setup-metrics-verify.md) (Tier A S10 risk_metrics_daily — HC-1 builds alert-on-alert on top)
- [LL-166](../../LESSONS_LEARNED.md) (HC-1 closure 体例 — §13.3-vs-§14 reconciliation + L1-heartbeat-premature Finding + scope-balloon-as-replan-trigger)
- HC-1 PR #350 / #351 / #352 / #353

### Related ADR

- [ADR-022](ADR-022-anti-anti-pattern-集中修订机制.md) (反 retroactive content edit — Plan §A append-only amend)
- [ADR-063](ADR-063-v3-s10-5d-paper-mode-skip-empty-system-anti-pattern.md) (paper-mode deferral pattern)
