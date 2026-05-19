# PT Restart Path B — Paper-Mode 5d Observation STATUS_REPORT Template

> **用途**: ADR-085 path B Phase B-1 期间 (5-20 Wed → 5-26 Tue, 5 trading days) CC daily STATUS_REPORT 沉淀 template.
>
> **Output**: 每日 sediment `docs/audit/STATUS_REPORT_2026_05_<day>_pt_paper_dryrun_day<N>.md` (沿用 STATUS_REPORT naming convention).
>
> **触发 trigger 2 后 CC autonomous**: user "你执行" sustained 后 CC 每日 (5-21 morning / 5-22 evening / 5-25 morning / 5-26 evening / 5-27 morning) 沉淀本 template 实例化.

---

## §0 Template usage 体例

每个 daily STATUS_REPORT 复制本 template 全部 sections, 实例化:
- `<DAY_N>` → 1/2/3/4/5
- `<DATE>` → 5-21 / 5-22 / 5-25 / 5-26
- `<DOW>` → Thu / Fri / Mon / Tue
- `<TIME>` → morning / evening
- `<EVIDENCE>` → cite source + timestamp (沿用 handoff_template.md §3 cite SOP)

---

## STATUS_REPORT 2026-05-<DATE> <TIME> — PT Paper Dry-Run Day <DAY_N>

> **ADR**: [ADR-085](../adr/ADR-085-pt-restart-staged-paper-dryrun-5d-then-live.md) Phase B-1 Day <DAY_N>/5
> **Date**: 2026-05-<DATE> <DOW> <TIME> SH
> **Brief**: [PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19](PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19.md)
> **5d window**: 5-20 Wed → 5-26 Tue (5 trading days)

---

## §1 10/10 Observation Checklist Day <DAY_N>

| # | Check | Expected | Actual <DATE> | Status | Evidence |
|---|---|---|---|---|---|
| 1 | signals 表 daily write | ≥1 row/day | <SQL count> | ✓/⚠/✗ | DB query: `SELECT COUNT(*) FROM signals WHERE created_at >= '<DATE> 00:00 SH'` |
| 2 | execution_plans 表 daily write | ≥1 row/day | <SQL count> | ✓/⚠/✗ | DB query: `SELECT COUNT(*) FROM execution_plans WHERE created_at >= '<DATE>'` |
| 3 | trade_log 0 new rows | 0 (paper sustained) | <SQL count> | ✓/⚠/✗ | DB query: `SELECT COUNT(*) FROM trade_log WHERE filled_at >= '<DATE>'` |
| 4 | risk_event_log 0 P0 incident | 0 P0 severity | <SQL count> | ✓/⚠/✗ | DB query: `SELECT COUNT(*) FROM risk_event_log WHERE severity='P0' AND triggered_at >= '<DATE>'` |
| 5 | meta_monitor_tick 0 alert | 0 fire | <DingTalk + log> | ✓/⚠/✗ | DingTalk log + Beat log grep "meta_monitor_tick" |
| 6 | DingTalk 0 fire | 0 (paper 0 actionable) | <count> | ✓/⚠/✗ | DingTalk audit log + alert_dedup |
| 7 | PT_Watchdog 0 alert | 0 | <count> | ✓/⚠/✗ | logs/pt_watchdog*.log |
| 8 | LLM cost 累计 ≤ $50/月 | < $50 cumulative MTD | <$X.XX> | ✓/⚠/✗ | llm_cost_daily / llm_call_log |
| 9 | Beat 22 entries 100% trigger | 22/22 fire | <22/22?> | ✓/⚠/✗ | Beat log grep + scheduler tick count |
| 10 | PG/Redis/xtquant heartbeat 0 outage | 100% uptime | <%> | ✓/⚠/✗ | Servy status / health log |

### §1.1 Pass/Fail Summary Day <DAY_N>

- **Total**: <N>/10 PASS
- **Warnings**: <list of ⚠>
- **Failures**: <list of ✗>
- **GO/NO-GO gate**: <decision>

---

## §2 .env 红线 5/5 verify Day <DAY_N>

```
$ grep -E "^(EXECUTION_MODE|LIVE_TRADING_DISABLED|QMT_ACCOUNT_ID|DINGTALK_ALERTS_ENABLED|L4_AUTO_MODE_ENABLED)=" backend/.env
EXECUTION_MODE=paper            ← Phase B-1 expected
LIVE_TRADING_DISABLED=true      ← Phase B-1 expected
QMT_ACCOUNT_ID=81001102         ← sustained (0 改)
DINGTALK_ALERTS_ENABLED=true    ← sustained (0 改)
# L4_AUTO_MODE_ENABLED unset    ← sustained (0 改)
```

| # | Field | Expected (Phase B-1) | Actual <DATE> | Status |
|---|---|---|---|---|
| 1 | EXECUTION_MODE | paper | <grep result> | ✓/✗ |
| 2 | LIVE_TRADING_DISABLED | true | <grep result> | ✓/✗ |
| 3 | QMT_ACCOUNT_ID | 81001102 | <grep result> | ✓/✗ |
| 4 | DINGTALK_ALERTS_ENABLED | true | <grep result> | ✓/✗ |
| 5 | L4_AUTO_MODE_ENABLED | unset | <grep result> | ✓/✗ |

---

## §3 Schtask state verify Day <DAY_N>

```powershell
Get-ScheduledTask -TaskName QuantMind_DailyExecute, QuantMind_CancelStaleOrders | Select-Object TaskName, State
```

| Schtask | Expected | Actual <DATE> | Status |
|---|---|---|---|
| QuantMind_DailyExecute | Ready | <state> | ✓/✗ |
| QuantMind_CancelStaleOrders | Ready | <state> | ✓/✗ |
| QuantMind_DailySignal | Ready (sustained) | <state> | ✓/✗ |
| QM-HealthCheck | Ready (sustained) | <state> | ✓/✗ |

---

## §4 LL-188 sediment-drift check Day <DAY_N>

pre-commit hook LL-188 step 0 verify:
- handoff claim "EXECUTION_MODE=paper" vs .env actual ✓ (Phase B-1 真值 ALIGNED)
- handoff claim "LIVE_TRADING_DISABLED=true" vs .env actual ✓ (Phase B-1 真值 ALIGNED)
- handoff claim "0 broker call sustained" vs trade_log <SQL count> ✓/⚠

---

## §5 Daily anomaly log (if any)

- 5-<DATE> <HH:MM> SH: <anomaly description> + <evidence cite> + <action taken>

(If 0 anomaly: "Day <DAY_N> nominal — 0 anomaly observed")

---

## §6 Phase B-2 readiness gate update

**Cumulative 5d PASS count**: <N>/<DAY_N×10>

**Phase B-2 GO/NO-GO gate criteria** (5-26 Tue evening Day 5 evaluation):
- [ ] 5/5 daily 10/10 checklist PASS
- [ ] 0 P0 incident across 5d
- [ ] LL-188 sediment drift 0 false positive
- [ ] .env 5/5 红线 sustained Phase B-1 expected state
- [ ] LLM cost trajectory < $50/月 projection

**Current readiness status (Day <DAY_N>)**: <ON-TRACK / CONCERNED / OFF-TRACK>

---

## §7 Next 24h forecast

- Next signal generation: 5-<DATE+1> 16:30 SH
- Next execute fire: 5-<DATE+1> 09:31 SH
- Next Beat 22 entries fire window: continuous (sustained)
- Next milestone: <Day N+1 STATUS_REPORT / Phase B-2 readiness gate>

---

## §8 实施 source

- ADR-085 §3.4 STATUS_REPORT cadence
- handoff_template.md §3 cite SOP (沿用)
- LL-188 step 0 enforce (commit `9dea1cc`)
- 22 Beat entries sustained verify (commit `8dfd0be`)
- 27 schtask state PowerShell cold verify (5-19 Session 58+1)

---

**End of Day <DAY_N> STATUS_REPORT template instance.**

---

## Appendix A: Quick reference cmds for daily verify

```powershell
# 1. .env 5/5 红线 verify
grep -E "^(EXECUTION_MODE|LIVE_TRADING_DISABLED|QMT_ACCOUNT_ID|DINGTALK_ALERTS_ENABLED)=" backend/.env

# 2. Schtask state
Get-ScheduledTask | Where-Object { $_.TaskName -like "QuantMind_*" } | Select-Object TaskName, State | Format-Table

# 3. Servy 4 services state
powershell -File scripts/service_manager.ps1 status
& "D:\tools\Servy\servy-cli.exe" status --name="QuantMind-QMTData"

# 4. FastAPI health
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"

# 5. DB queries (走 .env DATABASE_URL):
# (i) signals daily writes
# (ii) execution_plans daily writes
# (iii) trade_log 0 new rows
# (iv) risk_event_log 0 P0
# (v) LLM cost MTD
```

## Appendix B: Rollback path (任意时刻 Phase B-1 期间)

```powershell
# Step 1: Restore .env from backup
Copy-Item logs/.env-backup-pre-paper-dryrun-2026-05-20.bak backend/.env

# Step 2: Restart Servy
powershell -File scripts/service_manager.ps1 restart all
& "D:\tools\Servy\servy-cli.exe" restart --name="QuantMind-QMTData"

# Step 3: (Optional) Disable schtask back to Disabled
Disable-ScheduledTask -TaskName QuantMind_DailyExecute
Disable-ScheduledTask -TaskName QuantMind_CancelStaleOrders

# Step 4: Verify
grep EXECUTION_MODE backend/.env  # 期望: live
Get-ScheduledTask -TaskName QuantMind_DailyExecute | Select State  # 期望: Disabled
```

## Appendix C: ADR-085 cumulative artifacts inventory

- `docs/adr/ADR-085-pt-restart-staged-paper-dryrun-5d-then-live.md` — strategic decision sediment
- `scripts/pt_restart_path_b_step1.ps1` — Phase B-1 launch
- `scripts/pt_restart_path_b_step2.ps1` — Phase B-2 launch (5-27 Wed)
- `docs/runbook/pt_restart_path_b_observation_template.md` — this file (daily STATUS_REPORT template)
- `docs/audit/STATUS_REPORT_2026_05_2<X>_pt_paper_dryrun_day<N>.md` — daily sediment (CC autonomous post trigger 2)
- `logs/.env-backup-pre-paper-dryrun-2026-05-20.bak` — Phase B-1 backup
- `logs/.env-backup-pre-live-restart-2026-05-27.bak` — Phase B-2 backup
