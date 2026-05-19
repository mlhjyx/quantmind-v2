# Phase B-2 Pre-Flight Checklist — Live Flip 2026-05-27 Wed (sediment ahead, gate prerequisite)

> **目的**: ADR-085 Phase B-2 (5-27 Wed paper→live flip) **gate evaluation single source**. 5d Phase B-1 observation 5-26 Tue evening 后 user gate decision evidence 这里 cite.
>
> **Sediment timing**: 5-19 evening SH (ahead of 5-27 Wed) — 反 LL-190 sediment-then-forget pattern, 提前 sediment 防 5-26 evening ambiguous decision.
>
> **Date**: 2026-05-19 evening / Target: 2026-05-27 Wed 早 SH
> **Authors**: CC Session 58+1 (ADR-086 Tier sequence 同期 sediment)
>
> **Trigger 3 ("你执行" for Phase B-2)** 沿用 ADR-027 §7 双 trigger 体例: trigger 1 "同意" (5-19 received) + trigger 2 "执行" (5-19 received for Phase B-1) + **trigger 3 "你执行 Phase B-2 live flip"** (5-26 Tue evening OR 5-27 Wed morning, 待 user).

---

## §0 Phase B-2 Gate Evaluation Criteria (10 dim PASS/FAIL)

5-26 Tue evening Day 5 final STATUS_REPORT evaluate against this:

| # | Criterion | PASS threshold | FAIL action |
|---|---|---|---|
| 1 | trade_log new rows | 0 (paper sustained 5d) | If > 0 → forensic investigate, may delay live flip |
| 2 | execution_plans daily writes | ≥ 1/day each 5 trading days | If gap day → diagnose schtask + signal pipeline |
| 3 | signals 表 daily writes | ≥ 1/day each 5 trading days | If gap → DailySignal schtask + parquet cache verify |
| 4 | risk_event_log P0 incident | 0 P0 across 5d | If P0 → halt live flip, ADR/LL sediment 后再评估 |
| 5 | meta_monitor_tick alert-on-alert | 0 alert across 5d | If alert → debug 7 polled rules + memory monitor |
| 6 | DingTalk fire count | 0 (paper sustained 0 actionable broker event) | If fire → diagnose source, distinguish info vs alert |
| 7 | LLM cost MTD | < $50/month (V3 §20.1 #6 budget) | If > $50 → audit V4-Pro routing, possibly Ollama fallback |
| 8 | Beat 22 entries fire rate | ≥ 95% (1 outage/day tolerable) | If < 95% → Beat heartbeat investigation (P0-5/P0-6) |
| 9 | PG/Redis/xtquant heartbeat | 100% uptime | If outage → diagnose, post-mortem 沉淀 |
| 10 | Worker memory baseline | < 2GB private at Day 5 evening | If > 2GB → ADR-086 Tier 1 immediate trigger, possibly delay live flip |

### §0.1 Gate Decision Tree

```
ALL 10 PASS → GO Phase B-2 live flip 5-27 Wed morning
9/10 PASS + 1 WARN → GO with documented WARN + user explicit ack
8/10 PASS + 2 WARN → NEEDS_USER decision (extend 5d to 7d OR proceed)
≤ 7/10 PASS → NO-GO Phase B-2, extend paper-mode OR rollback to live armed state
```

---

## §1 Pre-Flight Verify Sequence (5-27 Wed early SH ~08:00 SH)

### §1.1 Cold .env verify

```powershell
# Expected post Phase B-1 state (5d sustained)
$envContent = Get-Content backend/.env -Raw
$envContent -match "(?m)^EXECUTION_MODE=paper" -or (throw "FAIL: env not paper")
$envContent -match "(?m)^LIVE_TRADING_DISABLED=true" -or (throw "FAIL: env not true")
$envContent -match "(?m)^QMT_ACCOUNT_ID=81001102" -or (throw "FAIL: account mismatch")
$envContent -match "(?m)^DINGTALK_ALERTS_ENABLED=true" -or (throw "FAIL: dingtalk not enabled")
Write-Host "[OK] .env 5/5 red-line state pre-flip verified"
```

### §1.2 Cold schtask verify

```powershell
# Sustained Phase B-1 state expectation
$execTask = Get-ScheduledTask QuantMind_DailyExecute
$execTask.State -eq "Ready" -or (throw "FAIL: DailyExecute not Ready")
$cancelTask = Get-ScheduledTask QuantMind_CancelStaleOrders
$cancelTask.State -eq "Ready" -or (throw "FAIL: CancelStaleOrders not Ready")
Write-Host "[OK] schtask 2 entries Ready (sustained Phase B-1)"
```

### §1.3 Redline guardian fresh spawn

**Mandatory** (沿用 Guardian §5 verdict "Phase B-2 requires fresh re-gate"):

```
Agent({
  subagent_type: "quantmind-redline-guardian",
  description: "Fresh re-gate Phase B-2 live flip mutation verify",
  prompt: "Planned mutation Phase B-2 step 2: .env EXECUTION_MODE paper→live + LIVE_TRADING_DISABLED true→false + 4 Servy restart. schtask 沿用 Phase B-1 Ready. Pre-flight checklist evidence: docs/audit/PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27.md §0 10-dim gate result + Day 1-5 STATUS_REPORT cite. Brief: ADR-085 §2.1 Phase B-2. Verdict expected: ALLOW (10/10 PASS) OR NEEDS_USER (gate ambiguous) OR BLOCK (gate FAIL)."
})
```

### §1.4 Backup chain pre-mutation

- Phase B-1 backup sustained: `logs/.env-backup-pre-paper-dryrun-2026-05-20.bak` ✓
- Phase B-2 NEW backup: `logs/.env-backup-pre-live-restart-2026-05-27.bak` (atomic Copy-Item before edit)

### §1.5 5d Cumulative STATUS_REPORT chain verify

```bash
# Verify 5d STATUS_REPORT chain complete
ls docs/audit/STATUS_REPORT_2026_05_2[0-6]_pt_paper_dryrun_day[1-5].md | wc -l  # expect 5
```

---

## §2 Phase B-2 Step Sequence (5-27 Wed early SH)

### §2.1 Run step2 script (sustained step1 体例)

```powershell
.\scripts\pt_restart_path_b_step2.ps1
```

Script sequence (verified DryRun fail-fast):
1. Pre-cond verify (.env paper + schtask Ready)
2. Atomic backup .env → `logs/.env-backup-pre-live-restart-2026-05-27.bak`
3. Edit .env (paper → live + true → false)
4. Restart 4 Servy services
5. Verify /health execution_mode=live

### §2.2 第一笔 live execute monitor (5-27 Wed 09:31 SH)

- CC ScheduleWakeup (OR manual user trigger) at 5-27 Wed 09:35 SH
- Verify trade_log first new row since 4-30 (19+5 = 24 days)
- DingTalk fire expected (broker confirm)
- 5-27 Wed evening Day 1 LIVE STATUS_REPORT sediment

### §2.3 Post-flip 5d live observation cadence

5-27 Wed → 6-02 Mon, sustained ADR-027 §2.1 #1 "STAGED 真实运行 ≥ 1 个月 0 真生产事件" prerequisite:
- Day 1-5 live execute monitor
- LL-182 long-run verify natural starts
- ADR-028 AUTO 5 prerequisite #1 sustained tracking starts

---

## §3 NO-GO Scenarios + Rollback Path

### §3.1 Common NO-GO triggers

| Trigger | Action |
|---|---|
| Day 1 paper trade_log unexpectedly written | Halt + forensic, paper adapter routing audit |
| Day 3 (5-22 Fri 19:00) factor-lifecycle 触发 worker leak | ADR-086 Tier 1 immediate trigger, may extend 5d to 7d |
| Day 4 (5-24 Sun 22:00) gp-weekly fire 撑爆 worker | Hold 5-26 gate, restart worker first |
| Day 5 Beat fire rate < 95% | Beat heartbeat root cause investigation (P0-5) |
| 5-26 evening LLM cost projection > $50/month | Audit V4-Pro routing, may switch Ollama fallback test |

### §3.2 Rollback Path (任意时刻 in Phase B-1 OR pre-step2)

```powershell
# Step 1: Restore .env from Phase B-1 backup
Copy-Item logs\.env-backup-pre-paper-dryrun-2026-05-20.bak backend\.env

# Step 2: Restart Servy
powershell -File scripts/service_manager.ps1 restart all
& "D:\tools\Servy\servy-cli.exe" restart --name="QuantMind-QMTData"

# Step 3: Disable schtask back to Disabled (return to pre-Path-B state)
Disable-ScheduledTask -TaskName QuantMind_DailyExecute
Disable-ScheduledTask -TaskName QuantMind_CancelStaleOrders

# Step 4: Verify
$envContent = Get-Content backend\.env -Raw
$envContent -match "(?m)^EXECUTION_MODE=live"  # expect post-rollback live (operator-armed state pre-Path-B)
$envContent -match "(?m)^LIVE_TRADING_DISABLED=false"  # expect pre-Path-B state
Get-ScheduledTask QuantMind_DailyExecute | Select-Object State  # expect Disabled
```

**沿用 Path B brief §6 X10 enforce**: rollback 决议 由 user 显式 trigger, CC 不自动 rollback.

---

## §4 Decision Authority Chain

| Decision | Authority |
|---|---|
| 5d gate PASS/FAIL evaluation | CC autonomous (5-26 Tue evening STATUS_REPORT analysis) |
| Phase B-2 GO/NO-GO | **User trigger 3 ("你执行")** based on CC gate evidence |
| Rollback during Phase B-1 | User explicit trigger |
| Phase B-2 step2 script execution | CC autonomous after user trigger 3 |
| Post-flip live monitor cadence | CC autonomous (沿用 Phase B-1 cadence体例) |

---

## §5 关联

- [ADR-085](../adr/ADR-085-pt-restart-staged-paper-dryrun-5d-then-live.md) §2.1 Phase B-2
- [ADR-086](../adr/ADR-086-celery-worker-periodic-restart-and-memory-monitor.md) Tier 1 schtask register
- [ADR-027 §7](../adr/ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md) 双 trigger 体例
- [LL-188](../../LESSONS_LEARNED.md#ll-188) (sediment drift forensic)
- [LL-189](../../LESSONS_LEARNED.md#ll-189) (worker leak hardening trigger)
- [LL-190](../../LESSONS_LEARNED.md#ll-190) (plan v8 sediment-then-forget pattern parent — 本 doc 提前 sediment 反 pattern)
- [PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19](PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19.md)
- [PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19](PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md)
- `scripts/pt_restart_path_b_step2.ps1` (DryRun fail-fast verified)
- `docs/runbook/pt_restart_path_b_observation_template.md`

---

**End Phase B-2 Pre-Flight Checklist. Awaiting 5-26 Tue evening 5d gate evaluation evidence + user trigger 3 "你执行" for Phase B-2 live flip.**
