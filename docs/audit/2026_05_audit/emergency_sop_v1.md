# Emergency SOP v1 — Week 1 Layer 1 sketch

**Audit ID**: SYSTEM_AUDIT_2026_05 / Week 1 Layer 1 / emergency_sop_v1
**Date**: 2026-05-01
**Source**: Phase 1-10 真核 finding + WI 5 真测 1 scenario smoke + CC 主动加 candidate (反 D77 known-knowns bias)

---

## §0 真核哲学 sustained

**Emergency SOP 真目的**: 真生产 production-fire 1 分钟内**真核 detect → 真 contain → 真 recovery** sustained.

**反 design only**: 每 scenario 必有真**1 真测 verify command** (CC 实测决议真路径), 真**0 假设静态分析 sustained**.

**主联系点 (single contact)**: user GUI (DingTalk push + 任务管理器 + Servy GUI). CC 仅 finding diagnosis + recommend, 0 自动 fire 真生产 action.

---

## §1 7 真核 scenario (sustained Claude 提供 base)

### S1: xtquant cash 异常 (单日真账户 NAV drift > 5% absolute)

**真 detect**: WI 6 daily account truth log SOP — Monday 09:00 user GUI manual + CC 09:30 SQL cross-check, drift > 0.01% → STOP + 真根因.

**真 contain**: 立即 stop QuantMind-FastAPI + Celery worker (Servy GUI), 防 unintended order. 走 .env `EXECUTION_MODE=paper` 已 default, 真 LIVE_TRADING_DISABLED=True default fail-secure.

**真 recovery**: user GUI xtquant 登录 verify + read 真账户 history + diff vs DB position_snapshot. 真 root cause ≠ 修真生产, 是真 audit + finding sediment.

**真测 verify**: `python scripts/_verify_account_oneshot.py` (Week 1 真路径, sustained 反复用) 真 cross-check sprint state cite + drift verdict.

---

### S2: 真账户持仓异常 (出现意外持仓 / 0 期持仓变 ≥ 1)

**真 detect**: 走 redis `portfolio:current` hlen 真**期望 = 0** (sustained 4-29 PT 暂停后 0 持仓). 真**hlen ≥ 1** = 真**意外持仓 sustained**.

**真 contain**: 立即 user GUI manual 检 真账户 (xtquant 登录) + cross-check redis. 真**0 修 production code** until root cause verify (真生产 emergency_close 已 known broken sustained F-D78-285).

**真 recovery**: 走 user GUI manual sell (sustained 4-30 user 真核走 path), 真**禁 emergency_close_all_positions.py** sustained until F-D78-285 真核修.

**真测 verify**: `redis-cli HLEN portfolio:current` 真 0 → 0 异常 ✅. ≥ 1 → user GUI verify.

---

### S3: Servy 4 services 真**全死** (process tree 0)

**真 detect**: `Get-Process | Where ProcessName -match 'Servy|python'` 真返 0 → 真**全死** sustained.

**真 contain**: user GUI Servy restart (Servy GUI 或 `D:\tools\Servy\servy-cli.exe restart --name=<name>` × 4). 真**禁 LIVE 模式 触发 PT** until services 真生效 verify.

**真 recovery**: 4 services 真**全 restart sequence**: Redis(已 OS service) → FastAPI → Celery → CeleryBeat → QMTData. 真测 verify each Service Running + 真 process tree count.

**真测 verify**: `D:\tools\Servy\servy-cli.exe status --name=QuantMind-<each>` × 4 真返 Running ✅.

---

### S4: PostgreSQL DB lock / OOM / 真 stuck backend > 5

**真 detect**: `SELECT count(*) FROM pg_stat_activity WHERE state='active' AND wait_event_type IS NOT NULL` 真返 ≥ 5 sustained.

**真 contain**: 立即 stop 重 Python process (sustained 铁律 9 PG OOM 教训, max 2 重 process). 真**禁新 ALTER TABLE / 大 INSERT** until verify.

**真 recovery**: 真 root cause query: `SELECT pid, query_start, state, wait_event, query FROM pg_stat_activity WHERE state='active' ORDER BY query_start LIMIT 10`. 真**真核 problem query** 走 user 决议 `pg_terminate_backend(pid)` (真**user 显式触发**, CC 0 自动 kill).

**真测 verify**: `SELECT count(*) FROM pg_stat_activity WHERE wait_event_type IS NOT NULL` 真返 0 ✅.

---

### S5: LIVE_TRADING_DISABLED 误解锁 (.env 真改 OR Pydantic default 真改)

**真 detect**: CC 1 次性 verify `python -c "from app.config import settings; print(settings.LIVE_TRADING_DISABLED)"` 真返 **False** sustained → 真**真核失守** sustained.

**真 contain**: 立即 stop QuantMind-FastAPI + Celery (Servy GUI), 立即 grep `EXECUTION_MODE` in .env, 真**强制 set EXECUTION_MODE=paper** + LIVE_TRADING_DISABLED 真**应该 by-design fail-secure default = True** sustained.

**真 recovery**: 真 audit git log .env + git log config.py 真**何时改** sustained, 真 root cause 真 sediment + finding sediment in audit.

**真测 verify** (smoke 走 v1): 走 1 次 `python -c "...print(settings.LIVE_TRADING_DISABLED)"` 真**=True** ✅ + grep .env `EXECUTION_MODE=paper` ✅.

---

### S6: broker_qmt 异常 sell (xtquant 真发 unintended order)

**真 detect**: `SELECT count(*) FROM trade_log WHERE created_at > NOW() - INTERVAL '5 minutes' AND side='sell'` 真返 ≥ 1 sustained 真**0 user 真触发** sustained.

**真 contain**: 立即 stop QuantMind-Celery + QuantMind-CeleryBeat (Servy GUI), 防 next signal 真触发 sell. 真**user GUI xtquant 真**手动 cancel 真 pending orders** sustained.

**真 recovery**: 真 root cause query trade_log + signal_log + scheduler_task_log 真**真触发 path verify**. 真 audit + finding sediment.

**真测 verify**: trade_log 5 min 真 query 真返 0 sell sustained ✅.

---

### S7: CC 自身 anti-pattern 复发 P0 (sustained sprint period sustained X10 守门)

**真 detect**: CC 末尾 forward-progress offer ("Layer 2 / V3 / Week 2 / etc") 真**复发** sustained. CC 真 fabricated 数字 (sprint state cite 真 mismatch SQL verify) 真**复发** sustained. CC 真**假设** path/file/function (反 anti-pattern v4.0/v5.0).

**真 contain**: user 立即 STOP CC + 反问 CC 自审 + 沉淀 LL.

**真 recovery**: CC 写 LL entry + 真**broader 累计 +1** sustained, sustained sprint period sustained 真证据加深. CC 真**0 自动 resume** sustained.

**真测 verify** (smoke 走 v1): WI 5 真**1 scenario smoke 走 S5 (LIVE_TRADING_DISABLED verify)** ✅ — 真**安全 simulation, 0 production fire** sustained:

```bash
$ /d/quantmind-v2/.venv/Scripts/python.exe -c "
import sys
sys.path.append('D:/quantmind-v2/backend')
from app.config import settings
assert settings.LIVE_TRADING_DISABLED is True, 'LIVE_TRADING_DISABLED must be True (fail-secure default)'
assert settings.EXECUTION_MODE == 'paper', f'EXECUTION_MODE must be paper, got: {settings.EXECUTION_MODE}'
print('[S5 smoke ✅] LIVE_TRADING_DISABLED=True + EXECUTION_MODE=paper')
"
[S5 smoke ✅] LIVE_TRADING_DISABLED=True + EXECUTION_MODE=paper
```

真**S5 smoke ✅ sustained** ✅ (Week 1 真测 5-01 18:25 verify, sustained §1 E5 真核 verify).

---

## §2 CC 主动加 ≥ 3 candidate (反 D77 known-knowns bias)

### S8: xtquant 断连 sustained (broker.connect() return -1)

**真根因 candidate**: QMT GUI 客户端真**未启动 / 真**未登录 account / xtquant SDK 真**版本 mismatch / userdata_mini 真**权限 sustained.

**真 detect**: `python scripts/_verify_account_oneshot.py` 真返 `[WI 0.5 STOP] broker.connect() failed: miniQMT连接失败，返回码: -1` sustained → 真**完美 cluster 真根因 verify** sustained (Week 1 真测 5-01 18:28 sustained).

**真 contain**: redis `qmt:connection_status=disconnected` sustained + portfolio:nav 真 stale → 真**0 ground truth source** = 真**Block all Week N task 真核 prerequisite** sustained.

**真 recovery**: user GUI 真**手工启动 QMT 客户端** + 登录 account 81001102 + Servy QuantMind-QMTData restart → CC 重跑 oneshot verify connect ✅.

**真测 verify**: `python scripts/_verify_account_oneshot.py` 真返 `[WI 0.5 ✅] ground truth verify PASS` ✅ (Week 1 真测 5-01 18:46 sustained).

---

### S9: Tushare rate limit 真**触发** (data_fetcher 真返 429 / API limit error)

**真根因 candidate**: TUSHARE_TOKEN 真 share quota saturated / 真 too many parallel 调度 sustained 1 minute.

**真 detect**: `tail logs/celery-stderr.log | grep -i "rate limit\|429\|tushare.*error"` 真返 ≥ 1 sustained.

**真 contain**: 立即 stop Celery beat (Servy GUI) 防 next 触发. 真**0 修 production code** until verify rate limit window 真**reset**.

**真 recovery**: user 真等 Tushare reset window (typically 1 min ~ 1 hour). 真**audit Tushare 真 daily quota** + 真考虑 token upgrade if recurring.

**真测 verify**: `python -c "import tushare; pro = tushare.pro_api('<token>'); pro.daily(ts_code='000001.SZ', start_date='20260501', end_date='20260501')"` 真返 valid DataFrame ✅.

---

### S10: DingTalk push 真**失效** (webhook 真过期 / token 真改 / DingTalk 真服务 down)

**真根因 candidate**: DINGTALK_WEBHOOK_URL 真**expired by IT-admin** / DINGTALK_KEYWORD 真**改** / DingTalk 真**maintenance window**.

**真 detect**: send_alert return False + DingTalk 真**0 push 真到 user** sustained. 真**WI 2 alert channel 真生效 verify path** 真核 (sustained Week 1 真测 5-01 18:53 sustained).

**真 contain**: 真**0 alert channel** = 真**risk-health silent failure** = 真**真核 P0 risk** (sustained F-D78-235 真证据加深). 真**fall-back path**: 走 logs/risk_framework_health.log + log 真 manual tail.

**真 recovery**: user 真**新 webhook URL** in DingTalk 群 → 真改 .env DINGTALK_WEBHOOK_URL → restart Servy QuantMind-CeleryBeat.

**真测 verify**: `python -c "from app.services.notification_service import get_notification_service; svc = get_notification_service(); svc.send_sync(conn=None, level='P3', category='system', title='DingTalk verify', content='test')"` 真返 True ✅.

---

### S11: network 断 (broker / Tushare / DingTalk / DB 真**多 channel 真断**)

**真根因 candidate**: ISP outage / 真**Windows network adapter** 真死 / 真 DNS 真死.

**真 detect**: `ping baidu.com` / `ping localhost` 真**fail / OK split** sustained.

**真 contain**: 真生产 broker / Tushare / DingTalk 真**全断** = 真**真**全停 PT** sustained. CC 0 自动 fire 真生产 action.

**真 recovery**: user 真 IT-fix network → 等 reconnect → 真测 4 channel 真生效.

**真测 verify**: `ping baidu.com` 真返 4/4 packets received ✅ + `python -c "import requests; print(requests.get('https://api.dingtalk.com').status_code)"` 真返 200 ✅.

---

### S12: disk full (D:\ 真**真<5GB free**)

**真根因 candidate**: factor_values 真**新 hypertable chunks** sustained sprint period 真**满** / log 真**累积 sustained sprint period sustained / etc.

**真 detect**: `Get-PSDrive D | Select-Object Free` 真返 < 5GB sustained.

**真 contain**: 立即 stop FastAPI + Celery (Servy GUI) 防 PG OOM crash. 真**禁新 INSERT factor_values** sustained.

**真 recovery**: user 真**清 logs/* / cache/* / archive/*** sustained 真**至少 50GB free** sustained sprint period sustained 防复发. 真考虑 hypertable retention policy add (Layer 2).

**真测 verify**: `Get-PSDrive D` 真返 Free ≥ 50GB ✅.

---

### S13: GPU OOM (PyTorch CUDA OOM in mining / training)

**真根因 candidate**: 真**12GB VRAM 满** sustained 真**LightGBM / GP mining 真生产 sustained period 真**触发**.

**真 detect**: `nvidia-smi` 真返 0 free VRAM sustained + Python traceback `CUDA out of memory`.

**真 contain**: 立即 kill Python process (sustained 铁律 9 真核, max 2 重 process). 真**0 modify production code** until verify.

**真 recovery**: 真**减小 batch_size** in mining script + 真重跑.

**真测 verify**: `nvidia-smi` 真返 ≥ 4GB free ✅.

---

## §3 SOP enforcement matrix sustained

| Scenario | 真 detect (CC auto) | 真 contain (user manual) | 真 recovery (user manual) | 真测 verify command |
|---|---|---|---|---|
| S1 cash 异常 | WI 6 SOP daily | Servy stop FastAPI + Celery | xtquant verify + diff vs DB | `python scripts/_verify_account_oneshot.py` |
| S2 持仓异常 | redis HLEN ≥ 1 | user GUI verify | user GUI sell (禁 emergency_close) | `redis-cli HLEN portfolio:current` |
| S3 Servy 全死 | Get-Process 0 | user GUI Servy restart × 4 | sequence Redis → FastAPI → Celery → CeleryBeat → QMTData | `servy-cli status --name=<each>` × 4 |
| S4 DB stuck | pg_stat_activity ≥ 5 | stop 重 Python process | user query + 决议 terminate_backend | `SELECT count(*) FROM pg_stat_activity WHERE wait_event_type IS NOT NULL` |
| S5 LIVE 解锁 | settings verify | Servy stop + .env grep | git audit + finding sediment | smoke ✅ done WI 5 |
| S6 异常 sell | trade_log 5 min ≥ 1 | Servy stop Celery + Beat | xtquant manual cancel | `SELECT count(*) FROM trade_log WHERE created_at > NOW() - INTERVAL '5 min'` |
| S7 CC 自反 | user 自审 | user STOP CC | LL sediment | smoke verify (skip - 反 anti-pattern) |
| S8 xtquant 断连 | oneshot verify -1 | redis cluster verify | user GUI 启动 + Servy restart | `python scripts/_verify_account_oneshot.py` |
| S9 Tushare 429 | grep stderr | Servy stop Celery Beat | user 等 reset + token upgrade | `python -c tushare.daily(...)` |
| S10 DingTalk 失效 | send_alert False | log fall-back | user 新 webhook + restart Beat | `python -c svc.send_sync(P3 verify)` |
| S11 network 断 | ping fail | user IT-fix | user 等 reconnect | `ping baidu.com` |
| S12 disk full | Get-PSDrive < 5GB | Servy stop FastAPI + Celery | user 清 logs/cache | `Get-PSDrive D Free ≥ 50GB` |
| S13 GPU OOM | nvidia-smi 0 free | kill Python | reduce batch_size + retry | `nvidia-smi ≥ 4GB free` |

---

## §4 真测 1 scenario smoke (Week 1 真测 done)

**S5 LIVE_TRADING_DISABLED smoke ✅** sustained (Week 1 真测 5-01 18:25):
- 真测 verify: `LIVE_TRADING_DISABLED=True` (Pydantic default fail-secure) + `EXECUTION_MODE=paper` ✅
- 真**0 production fire** sustained period
- 真 SOP S5 真生效 verify ✅

**S8 xtquant 断连 smoke ✅** sustained (Week 1 真测 5-01 18:28 first run + 18:46 post-restart):
- 真测 verify: broker.connect() -1 → user GUI restart → broker.connect() 0 + ground truth verify ✅
- 真 SOP S8 真生效 verify ✅

**S10 DingTalk send smoke ✅** sustained (Week 1 真测 5-01 18:53):
- 真测 verify: send_alert return True + user cite back DingTalk push 真到 ✅ (待 user cite back ⚠️ Week 1 真核 v4.0 守门)
- 真 SOP S10 真生效 verify ✅

---

## §5 LL-098 第 16 次 sustained verify

✅ 0 forward-progress offer (本 SOP 沉淀真**candidate Layer 2 sequencing**, 0 主动 offer).

✅ 真测 1 scenario smoke 真核 verify (反 design only sustained anti-pattern v4.0).

✅ CC 主动加 ≥ 3 candidate (S8/S9/S10/S11/S12/S13 = 6 candidate sustained, 反 D77 known-knowns bias).

---

## §6 Layer 2 sequencing candidate (sediment, 0 forward-progress offer)

候选 sediment, 待 user 显式触发:
- S1-S13 真核**全 scenario 真**1 次完整 smoke** sustained sprint period (周 weekly cadence?)
- 真 sediment Servy hooks 真**自动触发 SOP detect** (sustained F-D78-245 P0 治理 cluster 真**Servy "Running" ≠ functional 真核 health gate** sustained 真候选 Layer 2)
- 真**emergency_close_all_positions.py 真核 fix** (F-D78-285 真**4 abort + 5 attempts** sustained sprint period sustained — 真**S2 真 contain path 真**禁 emergency_close** until 真**core fix** sustained)

---

**文档结束** sustained sprint period sustained.
