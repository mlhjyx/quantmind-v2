# 04 — Post-Deploy Restart Cadence SOP (Worker / FastAPI / Beat / RSSHub)

> **Why**: Sprint 2 sub-PR 8b chain 5-07 真**4-day silent fallback** reverse case sediment — PR #253 Pydantic→os.environ propagate 真**in-process startup hook** sustained 沿用 stale process 反**自动 reload** 漂移. Worker @ 5-04 18:52 + FastAPI @ 5-07 03:26:53 sustained post-#253/#254/#255/#257 deploy 全 stale, 真**production verify 0** sustained.
> **触发**: 任 PR merge 真**修 Pydantic Settings / config / yaml / fetcher / Celery task / FastAPI lifespan 真**in-process state** sustained → 真**post-merge ops checklist 必含 service restart**.

## 真适用 service matrix

> **Servy CLI quote 体例**: 沿用 codebase `SYSTEM_RUNBOOK.md` / `CLAUDE.md` / `SOP_EMERGENCY.md` / `DUAL_WRITE_RUNBOOK.md` 全 `--name="<service>"` 双引号体例 sustained.

| service | restart prerequisite trigger | restart command | graceful shutdown |
|---|---|---|---|
| **QuantMind-FastAPI** | PR 改 `app/main.py` / `app/api/**` / `app/config.py` / Pydantic Settings field / yaml `os.environ/X` mapping / endpoint logic | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-FastAPI"` | ~1.7s 沿用 5-07 23:00:01 实测 |
| **QuantMind-Celery** (Worker) | PR 改 `app/tasks/**` / `app/services/**` (Celery task path) / `qm_platform/**` / fetcher / `celery_app.py` imports list | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-Celery"` | ~10.6s 沿用 5-07 21:38:25 实测 (CLAUDE.md 30s budget) |
| **QuantMind-CeleryBeat** | PR 改 `app/tasks/beat_schedule.py` (Beat entry add/remove/cron) | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-CeleryBeat"` | ~13s 沿用 5-07 21:20:26 实测 |
| **QuantMind-RSSHub** | PR 改 RSSHub config / lib/routes/ source / dist/ build (反 chunk C-SOP-B 真预约) | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-RSSHub"` | TBD (Servy 0-op silent failure 真预约 chunk C-SOP-B fix) |
| **QuantMind-QMTData** | PR 改 `scripts/qmt_data_service.py` / xtquant path / Redis cache schema | `D:\tools\Servy\servy-cli.exe restart --name="QuantMind-QMTData"` | TBD |

## 真**3-layer evidence chain** post-restart verify (LL-110 + LL-105 + LL-067 体例)

### Layer 1 — process timestamp 真值
```powershell
Get-CimInstance -Query "select ProcessId,CreationDate,CommandLine from Win32_Process where Name='python.exe'" `
  | Where-Object { (Get-Date) - $_.CreationDate -lt [TimeSpan]::FromMinutes(2) } `
  | Format-Table ProcessId, CreationDate -AutoSize
```
真**post-restart 30-60s 内 fresh PID 真值** sustained (反 stale).

### Layer 2 — stdout banner 真值
```powershell
# PowerShell native (沿用 Windows 11 primary shell)
Get-Content "D:\quantmind-v2\logs\<service>-stdout.log" -Tail 50 | Select-String -Pattern "Started|listening|Running"
```
真**fresh banner timestamp align process timestamp** sustained.

### Layer 3 — transitive code load 真值 (production endpoint trigger)
e.g. POST `/api/news/ingest` → DB query `news_classified.classifier_model` 真**deepseek-v4-flash** sustained 反 Ollama qwen3 fallback (验 Pydantic propagate 真生效 in-process).

## 真**反 anti-pattern** (5-07 reverse case sediment)

- ❌ **PR merge 后 0 service restart 假设 deploy 完成** — 沿用 PR #253 5-07 12:00 merge → FastAPI @ 03:26:53 stale → 19h+ silent fallback (Sprint 1 教训 4-day 沿用 sub-PR 8b-llm-diag root cause)
- ❌ **Servy CLI status "Running" sustained ack deploy 完成** — Servy CLI 真**反 ack process creation timestamp** sustained, 真**真生产真值** = process timestamp + stdout banner + transitive endpoint trigger 3-layer
- ❌ **任 1 service restart sustained ack 全 chain 真生效** — Worker / FastAPI / CeleryBeat 真**独立 process** sustained, 真**post-merge restart matrix 沿用 PR scope 真**determinate**

## 真生产真值 evidence (5-07)

- sub-PR 8b-cadence-B post-merge ops verify (5-07 21:38-22:02) — Worker restart 21:38:25 + Option (C) send_task 22:02:27 → 8/8 deepseek-v4-flash sustained ✓
- chunk C-SOP-A FastAPI restart (5-07 23:00:01) — POST endpoint 23:01 → 16/16 deepseek-v4-flash sustained ✓ (3 fresh + 13 cumulative post-23:00 trigger)

## 真关联

- ADR-039 retry policy (audit failure path 沿用 fail-loud)
- ADR-043 Beat schedule + cadence + RSSHub 路由层契约
- LL-097 X9 Beat schedule 必显式 restart 体例
- LL-098 X10 forward-progress reverse case
- LL-110 web_fetch verify SOP / LL-105 SOP-6 4 source cross-verify / LL-067 reviewer 第二把尺子
- 真讽刺 #12 sub-PR 8b-cadence-B post-merge ops Worker stale code reverse case
- 真讽刺 #13 FastAPI stale code reverse case (本 SOP 真**实证 fix path** sustained)
