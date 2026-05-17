# Monday 2026-05-18 Live-Fire Operational Checklist

**Purpose**: Step-by-step operator runbook for first V3-path live trade execution at 09:31 SH.

**Background**: V3 Plan v0.4 Gate E formal CLOSED 2026-05-17. `QuantMind_DailyExecute` schtask State=Ready / NextRun=Mon 2026-05-18 09:31:00 SH. All Phase 0 operational defects remediated tonight (see `docs/audit/v3_ct_2c_pre_operational_remediation_report_2026_05_17.md`).

---

## ⏰ Timeline + Gates

### 09:00 SH — Pre-open infrastructure verify

| # | Check | Command | Pass criteria | If fail |
|---|---|---|---|---|
| 1 | 4 Servy services Running | `powershell -File scripts\service_manager.ps1 status` | QuantMind-FastAPI / Celery / CeleryBeat / QMTData all "Running" | Restart failed service via `D:\tools\Servy\servy-cli.exe start --name=<svc>` |
| 2 | services_healthcheck full pass | `python scripts\services_healthcheck.py` | `Status: ok` + `Beat heartbeat: <10min` | Investigate which check failed (see post-fix script output format) |
| 3 | /health endpoint | `Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"` | `{"status":"ok","execution_mode":"live"}` | Restart QuantMind-FastAPI |
| 4 | xtquant truth via Redis | `redis-cli HGETALL portfolio:current` (or read portfolio:nav) | cash=¥993,520.66 / 0 持仓 / position_count=0 | Investigate QMT Data Service |
| 5 | qm:qmt:status stream fresh | Check XLEN + last entry timestamp | last_published within last 5min | Restart QuantMind-QMTData |
| 6 | DB freshness | `SELECT MAX(trade_date) FROM klines_daily` | latest = 2026-05-15 (sustained from Sat backfill) | (Not blocking — Mon signal uses Fri data) |
| 7 | QuantMind_DailyExecute schtask state | `Get-ScheduledTask -TaskName QuantMind_DailyExecute \| Format-List State, NextRun` | State=Ready / NextRun=2026-05-18 09:31:00 | Re-enable: `Enable-ScheduledTask -TaskName QuantMind_DailyExecute` |

### 09:25 SH — Last-minute pre-open

| # | Check | Pass criteria |
|---|---|---|
| 8 | Beat heartbeat fresh | services_healthcheck Beat heartbeat ≤10min |
| 9 | xtquant cash + 持仓 sustained | unchanged from 09:00 |
| 10 | No P0 alerts overnight | `/api/dashboard/alerts` clean (or known-stale per Finding #11) |

### 09:30 SH — Market open

| # | Watch | Expected |
|---|---|---|
| 11 | xtquant ticks publishing | `qm:qmt:status` XLEN growing rapidly |
| 12 | FastAPI logs | No errors in `logs/fastapi-stdout.log` tail |
| 13 | Celery worker logs | No exceptions in `logs/celery-stdout.log` tail |

### 09:31 SH — 🎯 **QuantMind_DailyExecute fires (LIVE-FIRE)**

| # | Watch (within 60s) | Expected |
|---|---|---|
| 14 | scheduler_task_log new entry | `task_name='execute_phase'` status='success' |
| 15 | trade_log new rows | `execution_mode='live'`, ~20 BUY orders (per Fri 5-15 signal) |
| 16 | xtquant cash decreases | from ¥993,520.66 → ~50-70% deployed |
| 17 | xtquant positions populate | ~20 stocks per signal target |
| 18 | /api/dashboard/summary | nav reflects live state, position_count=20 |
| 19 | /api/execution/asset | total_asset ≈ 993,520 (cash + market_value) |

### 🚨 Emergency P0 surfaces during 09:31-10:00 SH

**Immediate response**:
```powershell
# Step 1 — STOP further execution (within 30s)
Disable-ScheduledTask -TaskName QuantMind_DailyExecute

# Step 2 — Assess scope:
#   (a) If orders placed but unfilled: cancel in QMT GUI
#   (b) If orders filled partially: monitor, decide hold vs. exit
#   (c) If V3 chain malfunction (signal/portfolio/risk): rollback below
```

**Severe P0 — full rollback to paper**:
```powershell
cd D:\quantmind-v2
python scripts\v3_ct_2b_env_flip_apply.py --rollback   # .env back to paper
powershell -File scripts\service_manager.ps1 restart all
# Verify post-rollback: Invoke-RestMethod http://127.0.0.1:8000/health
# Expected: execution_mode = "paper"
```

**Position cleanup if needed**:
```powershell
# (a) Emergency liquidate via existing tool:
#     POST /api/execution/emergency-liquidate (read endpoint exists)
# (b) Manual sell via QMT GUI for problematic positions
# (c) Restore pre-cutover position state (last resort):
python scripts\v3_ct_2c_pre_position_snapshot_cleanup.py --rollback
```

### 10:00-15:00 SH — Live trading day

| Time | Watch |
|---|---|
| 09:35-12:00 | Intraday monitor (`QuantMind_IntradayMonitor` fires every 5min during 9-14) |
| Continuous | `/api/dashboard/summary` nav drift; `/api/dashboard/alerts` for P0 |
| 12:00 | Mid-day P&L check (paper-mode equivalent baseline NAV: ¥993,520.66) |

### 15:00 SH — Market close

| Time | Action |
|---|---|
| 15:00 | Market close. Final positions + cash snapshot. |
| 15:40 | `QuantMind_DailyReconciliation` fires — reconcile DB vs xtquant truth |
| 16:30 | `QuantMind_DailySignal` fires — generates Tue 5-19 target signal using today's close |
| 16:30+ | **Verify daily_signal_task SUCCESS** (not 健康预检失败); 5-19 signal in signals table |
| 17:30 | `QuantMind_DailyMoneyflow` fires (Tushare moneyflow ingest) |
| 17:30+ | **CRITICAL**: 5-18 klines + daily_basic ingest needed for Tue 5-19 16:30 signal. **Built `QuantMind_DailyDataIngest` tonight per Tier 2a — verify it fires successfully**. Without this, Tue signal_phase will hit data_fresh gate failure. |

### Evening — End-of-day sediment

| Action |
|---|
| Capture live trade evidence to `docs/audit/v3_first_live_trade_evidence_2026_05_18.md` |
| Sediment lessons learned → LL-176 candidate (post-cutover ongoing monitoring lessons) |
| Update SYSTEM_STATUS.md §0 with PT live status (NOT plan-期 sediment — BAU mode per Plan §A line 232) |

---

## Health probe quick reference

```powershell
# 4 services + Beat
python scripts\services_healthcheck.py

# /health
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"

# xtquant truth (Redis)
redis-cli GET portfolio:nav
redis-cli HGETALL portfolio:current

# Recent trades + positions (DB)
psql -U xin -d quantmind_v2 -c "SELECT * FROM trade_log WHERE execution_mode='live' ORDER BY executed_at DESC LIMIT 10;"
psql -U xin -d quantmind_v2 -c "SELECT code, quantity, market_value FROM position_snapshot WHERE execution_mode='live' AND trade_date=CURRENT_DATE ORDER BY market_value DESC;"

# scheduler_task_log recent
psql -U xin -d quantmind_v2 -c "SELECT task_name, status, start_time FROM scheduler_task_log WHERE start_time > NOW() - INTERVAL '24 hours' ORDER BY start_time DESC LIMIT 20;"
```

---

## 红线 5/5 pre-Mon-open state (sustained)

| # | 红线 | Pre-fire state |
|---|---|---|
| 1 | cash | ¥993,520.66 (xtquant ground truth) |
| 2 | 持仓 | 0 |
| 3 | LIVE_TRADING_DISABLED | false (post CT-2b apply `fc809c0`) |
| 4 | EXECUTION_MODE | live (post CT-2b apply `fc809c0`) |
| 5 | QMT_ACCOUNT_ID | 81001102 |

Upon Mon 09:31 first live trade execute → 红线 5/5 **TRANSITIONED** (cash/持仓 update with first fills).

---

## 关联

- `docs/audit/v3_ct_2c_pre_operational_remediation_report_2026_05_17.md` — comprehensive remediation report
- LL-175 — CT-2c-pre cycle 5 lessons
- ADR-077 — Plan v0.4 closure + Gate E formal close
- ADR-082 — Post-cutover ongoing monitoring体例
- Constitution v0.13 §L10.5 Gate E ✅ CLOSED
- Emergency rollback paths: `scripts/v3_ct_2b_env_flip_apply.py --rollback` + `scripts/v3_ct_2c_pre_position_snapshot_cleanup.py --rollback` + `scripts/v3_ct_1a_apply_cleanup.py --rollback`
- Tier 2a (built tonight): `scripts/daily_data_ingest.py` + `QuantMind_DailyDataIngest` schtask (08:50 SH pre-open + 17:30 SH post-close M-F)
