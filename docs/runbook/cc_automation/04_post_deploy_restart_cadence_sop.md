# 04 — Post-Deploy Restart Cadence SOP (Worker / FastAPI / Beat / RSSHub)

> **Why**: Sprint 2 sub-PR 8b chain 5-07 **4-day silent fallback** reverse case sediment — PR #253 Pydantic→os.environ propagate **in-process startup hook** 沿用 stale process 反**自动 reload** 漂移. Worker @ 5-04 18:52 + FastAPI @ 5-07 03:26:53 post-#253/#254/#255/#257 deploy 全 stale, **production verify 0**.
> **触发**: 任 PR merge **修 Pydantic Settings / config / yaml / fetcher / Celery task / FastAPI lifespan **in-process state** → **post-merge ops checklist 必含 service restart**.

## 适用 service matrix

> **Servy CLI quote 体例**: 沿用 codebase `SYSTEM_RUNBOOK.md` / `CLAUDE.md` / `SOP_EMERGENCY.md` / `DUAL_WRITE_RUNBOOK.md` 全 `--name="<service>"` 双引号体例.

| service | restart prerequisite trigger | restart command | graceful shutdown |
|---|---|---|---|
| **QuantMind-FastAPI** | PR 改 `app/main.py` / `app/api/**` / `app/config.py` / Pydantic Settings field / yaml `os.environ/X` mapping / endpoint logic | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-FastAPI"` | ~1.7s 沿用 5-07 23:00:01 实测 |
| **QuantMind-Celery** (Worker) | PR 改 `app/tasks/**` / `app/services/**` (Celery task path) / `qm_platform/**` / fetcher / `celery_app.py` imports list | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-Celery"` | ~10.6s 沿用 5-07 21:38:25 实测 (CLAUDE.md 30s budget) |
| **QuantMind-CeleryBeat** | PR 改 `app/tasks/beat_schedule.py` (Beat entry add/remove/cron) | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-CeleryBeat"` | ~13s 沿用 5-07 21:20:26 实测 |
| **QuantMind-RSSHub** | PR 改 RSSHub config / lib/routes/ source / dist/ build (反 chunk C-SOP-B 待办) | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-RSSHub"` | TBD (Servy 0-op silent failure 待办 chunk C-SOP-B fix) |
| **QuantMind-QMTData** | PR 改 `scripts/qmt_data_service.py` / xtquant path / Redis cache schema | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-QMTData"` | TBD |

## **3-layer evidence chain** post-restart verify (LL-110 + LL-105 + LL-067 体例)

### Layer 1 — process timestamp 真值
```powershell
Get-CimInstance -Query "select ProcessId,CreationDate,CommandLine from Win32_Process where Name='python.exe'" `
  | Where-Object { (Get-Date) - $_.CreationDate -lt [TimeSpan]::FromMinutes(2) } `
  | Format-Table ProcessId, CreationDate -AutoSize
```
**post-restart 30-60s 内 fresh PID 真值** (反 stale).

### Layer 2 — stdout banner 真值
```powershell
# PowerShell native (沿用 Windows 11 primary shell)
Get-Content "D:\quantmind-v2\logs\<service>-stdout.log" -Tail 50 | Select-String -Pattern "Started|listening|Running"
```
**fresh banner timestamp align process timestamp**.

### Layer 3 — transitive code load 真值 (production endpoint trigger)
e.g. POST `/api/news/ingest` → DB query `news_classified.classifier_model` **deepseek-v4-flash** 反 Ollama qwen3 fallback (验 Pydantic propagate 生效 in-process).

## **反 anti-pattern** (5-07 reverse case sediment)

- ❌ **PR merge 后 0 service restart 假设 deploy 完成** — 沿用 PR #253 5-07 12:00 merge → FastAPI @ 03:26:53 stale → 19h+ silent fallback (Sprint 1 教训 4-day 沿用 sub-PR 8b-llm-diag root cause)
- ❌ **Servy CLI status "Running" ack deploy 完成** — Servy CLI **反 ack process creation timestamp**, **真生产真值** = process timestamp + stdout banner + transitive endpoint trigger 3-layer
- ❌ **任 1 service restart ack 全 chain 生效** — Worker / FastAPI / CeleryBeat **独立 process**, **post-merge restart matrix 沿用 PR scope **determinate**

## 真生产真值 evidence (5-07)

- sub-PR 8b-cadence-B post-merge ops verify (5-07 21:38-22:02) — Worker restart 21:38:25 + Option (C) send_task 22:02:27 → 8/8 deepseek-v4-flash ✓
- chunk C-SOP-A FastAPI restart (5-07 23:00:01) — POST endpoint 23:01 → 16/16 deepseek-v4-flash ✓ (3 fresh + 13 cumulative post-23:00 trigger)

## 关联

- ADR-039 retry policy (audit failure path 沿用 fail-loud)
- ADR-043 Beat schedule + cadence + RSSHub 路由层契约
- LL-097 X9 Beat schedule 必显式 restart 体例
- LL-098 X10 forward-progress reverse case
- LL-110 web_fetch verify SOP / LL-105 SOP-6 4 source cross-verify / LL-067 reviewer 第二把尺子
- drift catch #12 sub-PR 8b-cadence-B post-merge ops Worker stale code reverse case
- drift catch #13 FastAPI stale code reverse case (本 SOP **实证 fix path**)
