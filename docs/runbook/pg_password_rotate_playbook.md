# PG Password Rotate Playbook (P0-2 closure prep)

> **Plan v8 P0-2 closure prep** — script ready, user-trigger only.
> **Trigger conditions**: post Phase B-2 (5-27 Wed live flip), OR pre next quarterly audit, OR ad-hoc incident.
> **Risk**: Touches PG credentials — all PG-connected services need restart.
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, defer execution to Phase B-2+).

---

## §1 Background

**Audit finding (Plan v8 S4 §17 Security)**:
- backend/.env contains `PG_PASSWORD=quantmind` (plaintext)
- 6 `.bak` files in logs/ may contain same password (env backup history)
- ~15 research/archive scripts hardcode `password="quantmind"` (security review MEDIUM)
- DB binds localhost only — blast radius LOW (single-user system)

**Why rotate now**:
1. Single-user-but-still-secret-hygiene (defense-in-depth)
2. Pre Phase B-2 live flip = clean credential boundary
3. Quarterly rotation cadence per audit cadence calendar (§VIII #29)

---

## §2 Procedure

### §2.1 Pre-flight checks (PowerShell — Windows-only system per code review LOW fix 5-20)

```powershell
# 1. Verify cash + 持仓 baseline sustained
psql -U xin -d quantmind_v2 -c "SELECT trade_date, nav FROM performance_series ORDER BY trade_date DESC LIMIT 1;"
# Expected: NAV ~¥993,520.66

# 2. Servy services healthy
powershell -File scripts/service_manager.ps1 status

# 3. .env backup (Windows PowerShell, not bash)
$DateStamp = Get-Date -Format "yyyyMMdd"
Copy-Item backend/.env "logs/.env-backup-pre-pg-rotate-$DateStamp.bak"

# 4. Verify no active long-running transactions
psql -U xin -d quantmind_v2 -c "SELECT pid, query_start, state, query FROM pg_stat_activity WHERE state != 'idle';"
```

### §2.2 Rotation steps

```powershell
# Step 1: Generate new password (32 chars, alphanumeric)
$NEW_PASSWORD = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})

# Step 2: Update PG role password (via psql, needs old password)
$env:PGPASSWORD = "quantmind"  # old
psql -U xin -d postgres -c "ALTER ROLE xin WITH PASSWORD '$NEW_PASSWORD';"
# Expected: ALTER ROLE

# Step 3: Stop all PG-connected Servy services
powershell -File scripts/service_manager.ps1 stop fastapi
powershell -File scripts/service_manager.ps1 stop celery
powershell -File scripts/service_manager.ps1 stop celerybeat
powershell -File scripts/service_manager.ps1 stop qmtdata

# Step 4: Update backend/.env with new PG_PASSWORD
# Manual edit OR script:
(Get-Content backend/.env) -replace 'PG_PASSWORD=.*', "PG_PASSWORD=$NEW_PASSWORD" | Set-Content backend/.env

# Also update DATABASE_URL if it embeds password
# DATABASE_URL=postgresql://xin:OLD_PWD@localhost:5432/quantmind_v2
# →
# DATABASE_URL=postgresql://xin:NEW_PWD@localhost:5432/quantmind_v2
(Get-Content backend/.env) -replace 'postgresql://xin:[^@]+@', "postgresql://xin:$NEW_PASSWORD@" | Set-Content backend/.env

# Step 5: Restart Servy services
powershell -File scripts/service_manager.ps1 start fastapi
powershell -File scripts/service_manager.ps1 start celery
powershell -File scripts/service_manager.ps1 start celerybeat
powershell -File scripts/service_manager.ps1 start qmtdata

# Step 6: Verify all services connect successfully
sleep 10
powershell -File scripts/service_manager.ps1 status
```

### §2.3 Post-flight verification

```bash
# 1. PG connection test from FastAPI
curl http://127.0.0.1:8000/api/system/health

# 2. Celery worker connected
celery -A app.tasks.celery_app inspect ping

# 3. Verify 红线 sustained post-rotation
grep -E "EXECUTION_MODE|LIVE_TRADING_DISABLED|DINGTALK_ALERTS_ENABLED" backend/.env

# 4. Cash + 持仓 unchanged
psql -U xin -d quantmind_v2 -c "SELECT trade_date, nav FROM performance_series ORDER BY trade_date DESC LIMIT 1;"
# Expected: NAV ~¥993,520.66 (UNCHANGED)
```

---

## §3 Rollback Procedure

If services fail to connect post-rotation:

```powershell
# Plan v8 code review MEDIUM fix (5-20): rollback extracts OLD password from backup
# file (NOT hardcoded — after rotation the previous value is unknown to this script).

# 1. Extract OLD password from .env backup file
$BackupFile = (Get-ChildItem logs/.env-backup-pre-pg-rotate-*.bak | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
$OldPasswordLine = Select-String -Path $BackupFile -Pattern 'PG_PASSWORD=' | Select-Object -First 1
if (-not $OldPasswordLine) {
    # Fallback: extract from DATABASE_URL line in backup
    $OldUrlLine = Select-String -Path $BackupFile -Pattern 'DATABASE_URL=' | Select-Object -First 1
    $OldPassword = ($OldUrlLine.Line -replace '.*postgresql://[^:]+:([^@]+)@.*', '$1')
} else {
    $OldPassword = $OldPasswordLine.Line.Split('=', 2)[1]
}
Write-Host "Extracted OLD password from $BackupFile"

# 2. Restore .env from backup
Copy-Item $BackupFile backend/.env -Force

# 3. Revert PG role password (need CURRENT new password to authenticate, then reset to OLD)
$env:PGPASSWORD = "$NEW_PASSWORD"  # current set in §2.2 step 1
psql -U xin -d postgres -c "ALTER ROLE xin WITH PASSWORD '$OldPassword';"

# 4. Restart all Servy services
powershell -File scripts/service_manager.ps1 restart all

# 5. Verify
powershell -File scripts/service_manager.ps1 status
```

---

## §4 Cleanup (post successful rotation)

```bash
# 1. Update 15+ research/archive scripts to use env var (security review MEDIUM)
# Pattern:
#   OLD: conn = psycopg2.connect(host=h, port=port, dbname=db, user=u, password='quantmind')
#   NEW: conn = psycopg2.connect(host=h, port=port, dbname=db, user=u, password=os.environ['PG_PASSWORD'])

grep -rln "password=\"quantmind\"" scripts/ | head -20
# Then edit each (defer to dedicated PR)

# 2. Delete .env backup files older than 30 days
find logs -name ".env-backup-*.bak" -mtime +30 -delete

# 3. Add to LL log
echo "## LL-XXX: 2026-MM-DD PG password rotated post Phase B-2" >> LESSONS_LEARNED.md
```

---

## §5 Schedule

**Recommended trigger**:
- Phase B-2 evening (5-27 Wed) post live flip 验证 — atomic credential boundary
- Quarterly cadence: 7-1 / 10-1 / next year

**Pre-requisites**:
- Phase B-1 5d dry-run complete OR aborted
- 0 active trading session (use evening windows after 15:30 SH)
- Cash + 持仓 baseline locked

**NOT during**:
- Trading hours (09:30-15:00 SH)
- Active backtest run
- L4 STAGED pending plans (cancel_deadline < 30min)

---

**Maintained by**: CC autonomous (Plan v8 P0-2 closure prep, 2026-05-20 Day 1)
**User trigger**: required (high-risk credential mutation)
**Cross-ref**:
- ADR-085 Path B (B-2 5-27 Wed live flip context)
- §VIII #29 Audit Cadence Calendar (quarterly cadence)
- backend/.env (PG_PASSWORD field)
- scripts/service_manager.ps1 (Servy control)
