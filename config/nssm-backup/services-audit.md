# NSSM Services Backup - 2026-04-04
# Pre-Servy migration audit snapshot

## QuantMind-FastAPI
- Application: D:\quantmind-v2\.venv\Scripts\python.exe
- AppDirectory: D:\quantmind-v2\backend
- AppParameters: -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
- DependOnService: Redis
- AppStdout: D:\quantmind-v2\logs\fastapi-stdout.log
- AppStderr: D:\quantmind-v2\logs\fastapi-stderr.log
- AppRotateFiles: 1
- AppRotateOnline: 1
- AppRotateBytes: 104857600 (100MB)
- AppRestartDelay: 3000
- AppThrottle: 1500
- AppStopMethodSkip: 0
- AppStopMethodConsole: 1500 (Ctrl+C wait 1.5s)
- AppStopMethodWindow: 1500
- AppStopMethodThreads: 1500
- Start: SERVICE_AUTO_START
- ObjectName: LocalSystem

## QuantMind-Celery
- Application: D:\quantmind-v2\.venv\Scripts\python.exe
- AppDirectory: D:\quantmind-v2\backend
- AppParameters: -m celery -A app.tasks.celery_app worker --pool=solo --concurrency=1 -Q default,factor_calc,data_fetch -n worker-main@%COMPUTERNAME%
- DependOnService: Redis
- AppStdout: D:\quantmind-v2\logs\celery-stdout.log
- AppStderr: D:\quantmind-v2\logs\celery-stderr.log
- AppRotateFiles: 1
- AppRotateOnline: 1
- AppRotateBytes: 104857600 (100MB)
- AppRestartDelay: 5000
- AppThrottle: 1500
- AppStopMethodSkip: 0
- AppStopMethodConsole: 1500 (Ctrl+C wait 1.5s)
- AppStopMethodWindow: 1500
- AppStopMethodThreads: 1500
- Start: SERVICE_AUTO_START
- ObjectName: LocalSystem

## Native Services (NOT migrated)
- PostgreSQL16: "D:\pgsql\bin\pg_ctl.exe" runservice -N "PostgreSQL16" -D "D:\pgdata16" -w
- Redis: "C:\Program Files\Redis\redis-server.exe" --service-run "C:\Program Files\Redis\redis.windows-service.conf"

## Missing Service (to be added)
- Celery Beat: python -m celery -A app.tasks.celery_app beat --loglevel=info
  (currently no Windows service, needs to be added during migration)

## Registry Backups
- QuantMind-FastAPI.reg
- QuantMind-Celery.reg

## Rollback
If Servy fails, re-import registry:
  reg import QuantMind-FastAPI.reg
  reg import QuantMind-Celery.reg
  net start QuantMind-FastAPI
  net start QuantMind-Celery
