# Path B 5-Day Paper-Dryrun PASS Gate Criteria + Early Rollback Decision Tree

> **Plan v8 action queue A6 closure** (sediment-then-implement, 反 LL-190)
> **Source**: ADR-085 Path B Phase B-1 staged paper-mode 5d dry-run
> **Created**: 2026-05-19 Session 58+1 evening
> **Status**: Sediment pre-validation, 5-20 → 5-26 active period

---

## §1 Scope

Path B Phase B-1 (Tue 5-20 → Mon 5-26): 5 trading days paper-mode dry-run before 5-27 Wed live flip (Phase B-2).

**Mandatory PASS criteria** (all must hold for B-2 trigger). **Early rollback triggers** (any one fires → user touchpoint).

---

## §2 5d Path B-1 PASS Gate Criteria

### §2.1 红线 sustained (5 conditions, **0 violation allowed**)

| # | Criterion | Source of truth | Verify cadence |
|---|---|---|---|
| 1 | `EXECUTION_MODE=paper` | `backend/.env` | Daily preflight @09:30 SH |
| 2 | `LIVE_TRADING_DISABLED=true` | `backend/.env` | Daily preflight @09:30 SH |
| 3 | `QMT_ACCOUNT_ID=81001102` | `backend/.env` | Daily preflight @09:30 SH |
| 4 | `DINGTALK_ALERTS_ENABLED=true` | `backend/.env` | Daily preflight @09:30 SH |
| 5 | `L4_AUTO_MODE_ENABLED=false` | `backend/.env` | Daily preflight @09:30 SH |

**0 broker call sustained**: trade_log table 5-19 last row 4-29 (清仓 day) — 5-20→5-26 期间 0 new rows allowed (paper-mode 不发真单).

**0 持仓 sustained**: position_snapshot.holdings == {} sustained 5-20→5-26.

**Cash sustained**: ¥993,520.66 ± ¥1 (任何 mutation 即异常).

### §2.2 Functional health (5 checks, **0 P0 alert**)

| # | Check | Tool | Daily SLA |
|---|---|---|---|
| 1 | Servy 4 services healthy | `service_manager.ps1 status` | All 4 = Running |
| 2 | Beat alive | `audit_beat_heartbeat.py` (P0-5) | mtime < 300s |
| 3 | Schtask 27 tasks healthy | `audit_schtask_freshness.py` (P0-6) | FAIL+STALE = 0 for critical (DailySignal/HealthCheck/DataQuality/PT_Watchdog) |
| 4 | pg_backup integrity | `pg_backup.py` Step 5 post-verify (P0-3) | exit=0 daily 02:00 SH |
| 5 | Market open watcher | `audit_market_open_watcher.py` (P0-15) | exit=0 at 09:31 SH on trading days |

### §2.3 Strategy alignment (3 checks)

| # | Check | Tool | Daily Required |
|---|---|---|---|
| 1 | DailySignal Top-5 generated | `signal_engine.py` log + signals table | Top 5 stocks daily, 0 violation 涨跌停 / ST / 停牌 |
| 2 | Paper-mode dry-run: 0 broker call | `execution_service.py` audit trail | 0 broker.place_order calls (LIVE_TRADING_DISABLED=true gate) |
| 3 | LLM cost sustained < $50/月 | `llm_cost_monthly_audit.py` (P0-16) | Daily check, cumulative < budget |

### §2.4 Data freshness (3 checks)

| # | Check | Source | SLA |
|---|---|---|---|
| 1 | klines_daily latest = T-1 trading day | `klines_daily` MAX(trade_date) | Within 24h of trading day close |
| 2 | factor_values latest = T-1 trading day | `factor_values` MAX(trade_date) | Within 24h of factor compute |
| 3 | factor_ic_history fresh | `factor_ic_history` MAX(trade_date) | Within 24h via DailyIC schtask |

---

## §3 PASS verdict logic

**Day-by-day**:
- ✅ **PASS day**: all §2.1 + §2.2 + §2.3 + §2.4 pass + 0 P0 alert raised
- ⚠️ **WARN day**: §2.2/2.3/2.4 1 fail but recoverable in next fire (no manual intervention)
- ❌ **FAIL day**: §2.1 violation OR sustained §2.2-2.4 fail across 2+ consecutive fires

**5d cumulative verdict**:
- ✅ **PROCEED to Phase B-2 (5-27 Wed live flip)**: 5/5 PASS days OR 4/5 PASS + 1 WARN
- ⚠️ **USER TOUCHPOINT**: 3/5 PASS + 1 WARN + 1 FAIL → user decides (extend B-1 vs proceed B-2)
- ❌ **ROLLBACK + DEFER**: 2+ FAIL days → defer Phase B-2 until root cause closed

---

## §4 Early Rollback Decision Tree

### §4.1 Immediate rollback triggers (during B-1, any 1 fires)

```
TRIGGER A: 红线 sustained violation
  - .env EXECUTION_MODE != paper
  - .env LIVE_TRADING_DISABLED != true
  - position_snapshot has any holdings
  - trade_log has new rows in 5-20→5-26 window
  ↓
  IMMEDIATE ROLLBACK:
  1. Run scripts/pt_restart_path_b_step1.ps1 inverse (.env restore from backup)
  2. Servy restart 4 services
  3. DingTalk P0 alert to user
  4. Halt 5-27 Phase B-2 plan
  5. Sediment incident in docs/audit/STATUS_REPORT_2026_05_NN_path_b_rollback.md

TRIGGER B: PT_Watchdog detects 持仓 ≠ 0
  - schtask QuantMind_PT_Watchdog 检测 broker live state contamination
  - Possible cause: xtquant cache stale OR concurrent live process
  ↓
  IMMEDIATE ROLLBACK + INCIDENT:
  1. emergency_close_all.py (if 持仓 真存在 → user 决议)
  2. .env audit + servy restart
  3. ADR-085 update with incident root cause

TRIGGER C: Sustained Beat death (LL-181 pattern)
  - audit_beat_heartbeat.py BEAT-DEAD across 3 fires (15min sustained)
  - Beat schedule paused = paper signal not generated = silent failure
  ↓
  ESCALATION:
  1. Servy restart QuantMind-CeleryBeat
  2. Beat heartbeat probe 5min later — if still DEAD, halt B-2
  3. ADR-086 Tier 2 schtask CeleryNightlyRestart 紧急 register
```

### §4.2 Soft warning triggers (B-1 continues, user notified)

```
TRIGGER D: 1 schtask FAIL day (e.g. DailySignal LastResult=1)
  - Cold run `run_paper_trading.py signal --dry-run` → exit=0 OK
  - schtask context-specific issue (memory / Python path)
  ↓
  REMEDIATION:
  1. Diagnose script log
  2. Re-fire schtask manually if stale evidence
  3. Sediment NATURAL_CLOSURES doc if next-day fire PASS
  4. B-1 continues

TRIGGER E: Tushare/Baostock data 1-day stale
  - klines_daily MAX(trade_date) = T-2 instead of T-1
  - Possible: Tushare 17:00 ready delay (rare)
  ↓
  REMEDIATION:
  1. Manual pull via `pull_tushare_daily.py` (no broker)
  2. Verify next DailyIC schtask consumes fresh data
  3. B-1 continues
```

### §4.3 Hard halt triggers (B-1 paused, user touchpoint)

```
TRIGGER F: Servy service crash 2+ times in 24h
  - QuantMind-FastAPI / QuantMind-Celery / QuantMind-CeleryBeat 任一 restart loop
  ↓
  HALT B-1:
  1. Servy log analysis
  2. ADR-086 implementation accelerated (Tier 1 + Tier 2)
  3. user 决议 B-1 extension vs B-2 delay vs ROLLBACK

TRIGGER G: LLM cost $50/月 budget breach
  - llm_cost_monthly_audit.py 检测 month-to-date > budget
  ↓
  REMEDIATION:
  1. V4 routing audit (V4-Pro vs V4-Flash ratio drift)
  2. Pause LLM features if breach > 20%
  3. ADR-036 sediment review
  4. B-1 continues with degraded LLM mode

TRIGGER H: SqlAlchemy session pool exhaustion
  - PG connection count > 80% capacity (LL-009 cross-domain recurrence)
  ↓
  IMMEDIATE:
  1. Servy restart of FastAPI (clears connections)
  2. PG `pg_stat_activity` audit
  3. service-layer commit() audit (P0-9 priority bump)
```

---

## §5 Daily preflight script SOP

**5-20 → 5-26 daily @09:30 SH** (sustained until Phase B-2 trigger):

```bash
# 1. 红线 sustained verify
grep -E "EXECUTION_MODE=|LIVE_TRADING_DISABLED=|QMT_ACCOUNT_ID=|DINGTALK_ALERTS_ENABLED=|L4_AUTO_MODE_ENABLED=" backend/.env

# 2. cash + 持仓 sustained
python -c "import xtquant.xttrader as x; ..."  # query_asset + query_stock_positions

# 3. Functional health
python scripts/audit_beat_heartbeat.py --no-alert
python scripts/audit_schtask_freshness.py --no-alert
python scripts/audit_market_open_watcher.py --no-alert

# 4. Data freshness
psql -c "SELECT MAX(trade_date) FROM klines_daily; SELECT MAX(trade_date) FROM factor_values; SELECT MAX(trade_date) FROM factor_ic_history;"

# 5. STATUS_REPORT sediment
echo "Day N PASS/WARN/FAIL" >> docs/audit/STATUS_REPORT_2026_05_NN_pt_paper_dryrun_dayN.md
```

---

## §6 Sediment

- **Maintenance**: 5-20 → 5-26 daily preflight evidence sediment per day
- **5-26 Mon evening sediment**: Cumulative verdict (PASS / USER_TP / ROLLBACK)
- **5-27 Wed Phase B-2 trigger**: Requires user "你执行" 第 3 trigger per ADR-027 §7
- **Cron 83e3c350** automated 10:07 SH daily Day-N STATUS_REPORT generation

---

**Maintained by**: CC autonomous (Session 58+1 evening, action queue A6 closure)
**Cross-ref**:
- ADR-085 Path B
- ADR-086 Celery周期 restart (T1 Day 1 deployment)
- ADR-027 §7 双 trigger 体例 (Phase B-2 5-27 Wed user 决议 prerequisite)
- LL-181 / LL-183 / LL-188 / LL-189 / LL-190 / LL-191 sustained context
- `docs/audit/PHASE_B_2_PREFLIGHT_CHECKLIST_2026_05_27.md` (5-27 Wed live flip prep, A5 already sedimented)
- `docs/runbook/pt_restart_path_b_observation_template.md` (per-day STATUS_REPORT template)
