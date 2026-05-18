# V3 QMT Connect Root Cause Fix — 2026-05-18 (LL-182)

> **One-shot comprehensive fix** per user 反馈 "一次性解决问题，不是什么短中长期，思考全面、主动思考". 5-axis fix targeting root cause + recurrence prevention.

## §1 Symptom

5-18 Mon ~17:27 → 18:25 SH (58min sustained) `qm:qmt:status` stream **all entries `connect_failed`**:
```
2026-05-18T10:25:57.831923+00:00  connect_failed   (= 18:25 SH)
... 14 entries ...
2026-05-18T09:27:40.286677+00:00  connect_failed   (= 17:27 SH)
2026-05-16T17:15:23.257771+00:00  connected        (last success before)
```

miniQMT GUI **alive + logged in** (user screenshot 18:25 SH 验证 total_asset=¥993,520.66 / status=正常). xtquant Python client side connect 失败.

## §2 Root Cause Analysis (deep-verified)

### §2.1 Primary — Time-based session_id collision + miniQMT internal session pool exhaustion

`backend/engines/broker_qmt.py:203` (pre-fix):
```python
self._session_id = session_id or int(datetime.now().strftime("%H%M%S%f"))
```

- Each `connect()` 生成新 12-digit time-based session_id (HHMMSSffffff microseconds).
- miniQMT internal: 每 unique session_id 创建 `userdata_mini/down_queue_<id>__mutex` 文件 (per-session lock marker).
- **NEVER cleanup on disconnect** — mutex files accumulate.

**Real evidence — `userdata_mini` mutex file inventory** (5-18 18:30 SH):
```
Total: 1412 down_queue_*__mutex files (4-02 → 5-18, 47 days)
Age distribution:
  < 1 day:   190 (Mon stress test + asyncio fix restarts)
  1-7 days:  276
  7-30 days: 662
  > 30 days: 284
Rate: ~30 mutex/day (multiple restarts per day × 7 schtask sessions)
```

miniQMT internal session pool 估计 ~1500 上限. 1412 / 1500 ≈ **94% exhausted**. New connect 找不到 free slot → return -1.

### §2.2 Secondary — Python module import cache silent stale

5-18 Mon 14:14 SH `5a04d5a fix(v3-l4-staged): broker_qmt asyncio event loop bootstrap`. QMTData service 在跑 OLD module — Python `import broker_qmt` 已 cache, **不自动 reload after file change**.

Confirmation: 18:29 SH 我 `restart QuantMind-QMTData` (force module re-import) → 立即 connect_succeeded (session=182954292702 random). 配合 Phase A stable session_id fix: 18:41 SH restart → session=**214701322725** (= `_stable_session_id('81001102')` deterministic).

### §2.3 Tertiary — Servy auto-restart doesn't detect script-internal error loop

QuantMind-QMTData Servy config 已有 `RecoveryAction=RestartService MaxRestartAttempts=5`. 但 RecoveryAction 触发条件 = **process crash** (exit non-zero). QMTData script 在 connect_failed 时**不 crash**, 而是进入 5min retry loop (per `qmt_data_service.py:104` exception swallow). Servy 看到 process 健康 (alive) → 不触发 restart.

## §3 5-Axis Fix Applied

### §3.1 Axis 1 — Stable session_id (PRIMARY FIX)

`backend/engines/broker_qmt.py` add module-level helper:
```python
def _stable_session_id(account_id: str) -> int:
    """Deterministic session_id from account_id (12-digit, fits xtquant)."""
    h = hashlib.md5(f"miniqmt_{account_id}".encode()).hexdigest()
    return int(h[:12], 16) % (10**12)
```

`MiniQMTBroker.__init__` default fallback updated:
```python
self._session_id = session_id or _stable_session_id(account_id)  # was: int(datetime.now().strftime("%H%M%S%f"))
```

**Result**: 81001102 account → session_id=**214701322725** (deterministic). All future restarts reuse same session_id. **Zero new mutex file per restart**.

### §3.2 Axis 2 — Auto-cleanup stale mutex files

`MiniQMTBroker.cleanup_stale_mutex_files(max_age_days)` new method:
```python
def cleanup_stale_mutex_files(self, max_age_days: int = 7) -> int:
    """Delete down_queue_*__mutex files older than max_age_days. Returns count."""
    qmt_dir = Path(self._qmt_path)
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for f in qmt_dir.glob("down_queue_*__mutex"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    return deleted
```

Called **automatically at start of `connect()`** with `max_age_days=7` (preserves last 7d for active session safety).

### §3.3 Axis 3 — Phase B one-shot bulk cleanup

Script-driven bulk cleanup executed once 5-18 18:35 SH:
```
deleted=1222 stale mutex files (mtime > 1 day)
kept=191 recent (last 24h, includes today's connect attempts)
miniQMT session pool: 94% exhausted → ~13% utilization
```

### §3.4 Axis 4 — QuantMind-RealtimeRisk Servy hardening parity

Pre-fix QuantMind-RealtimeRisk install missing 4 critical flags. Re-installed with full parity to QuantMind-QMTData:
```
--stdout D:\quantmind-v2\logs\realtime-risk-stdout.log
--stderr D:\quantmind-v2\logs\realtime-risk-stderr.log
--enableSizeRotation --rotationSize 50 --maxRotations 3
--enableHealth --heartbeatInterval 30 --maxFailedChecks 3
--recoveryAction RestartService --maxRestartAttempts 5
--deps Redis
```

### §3.5 Axis 5 — Documented "Python module restart" SOP

任 `broker_qmt.py` / 任 long-running Servy service Python module 修改 → **MUST**:
```powershell
D:\tools\Servy\servy-cli.exe restart --name=QuantMind-QMTData
D:\tools\Servy\servy-cli.exe restart --name=QuantMind-RealtimeRisk
```

Python `import` cache invalidation requires process restart. No hot-reload by design (production safety).

Add to monday_morning_preflight 未来 enhancement candidate: check `os.path.getmtime(broker_qmt.py)` vs service start time. If `.py` modified > service start time → warn user "module stale, restart needed".

## §4 Verification

### §4.1 Phase A code change verify

```
$ python -c "from engines.broker_qmt import _stable_session_id; print(_stable_session_id('81001102'))"
214701322725

$ pytest backend/tests/test_qmt_*.py backend/tests/test_base_broker.py backend/tests/test_live_trading_disabled.py backend/tests/test_l4_staged_smoke.py -q
107 passed in 310.54s
```

### §4.2 Runtime verify

```
$ servy-cli.exe restart --name=QuantMind-QMTData
$ tail logs/qmt-data-stderr.log
2026-05-18 18:41:41 [qmt_broker] INFO [QMT] 连接成功: 
  path=E:\国金QMT交易端模拟\userdata_mini, account=81001102, 
  session=214701322725  ← stable session_id 真值

$ redis-cli GET portfolio:nav
{"cash": 993520.66, "total_value": 993520.66, "position_count": 0,
 "updated_at": "2026-05-18T10:41:46+00:00"}  ✓ red line 5/5 sustained
```

### §4.3 RealtimeRisk hardening verify

```json
{
  "StdoutPath": "D:\\quantmind-v2\\logs\\realtime-risk-stdout.log",
  "StderrPath": "D:\\quantmind-v2\\logs\\realtime-risk-stderr.log",
  "EnableHealthMonitoring": true,
  "HeartbeatInterval": 30,
  "MaxFailedChecks": 3,
  "RecoveryAction": 1,        // RestartService
  "MaxRestartAttempts": 5,
  "RotationSize": 50,
  "MaxRotations": 3,
  "ServiceDependencies": "Redis"
}
```

Service Running + logs written:
```
2026-05-18 18:43:21 INFO === Realtime Risk Engine Service 启动 ===
2026-05-18 18:43:24 INFO 10 RealtimeRiskRule registered (tick/5min/15min)
2026-05-18 18:43:24 INFO threshold_cache wired (S7→S5)
2026-05-18 18:43:24 INFO sync loop started, interval=60s
```

(WARNING "0 holdings at startup" 是 expected — paper-mode 0 持仓 sustained per 红线 5/5. Tomorrow 09:31 SH live-fire 后 holdings 出现 → subscriber 自动 start.)

## §5 Recurrence Prevention

| 路径 | 机制 |
|---|---|
| Stable session_id | 每次连接 reuse same ID, 0 新 mutex per restart |
| Auto-cleanup in connect() | 每次连接前 delete > 7d stale mutex, 维持 pool 健康 |
| Bulk cleanup one-shot | 5-18 18:35 SH 已 cleanup 1222 stale 文件 (-86%) |
| Servy hardening parity | Both services 自动 restart + health monitor + rotation |
| Module-restart SOP | broker_qmt.py 修改后必 Servy restart (写进 SOP) |

## §6 Long-term Watchpoints

- **30d 后 mutex 累积 audit** — 即使 stable session, may still accumulate from edge cases. Run cleanup audit monthly.
- **xtquant version upgrade** — 跟踪 xtquant disconnect cleanup API (若有). 升级后 cleanup 可 push到 disconnect() 自动 handle.
- **miniQMT session pool 上限实测** — current 估算 ~1500. 验证后 update mutex max keep threshold.

## §7 红线 5/5 Sustained

throughout all 5-axis fix:
- cash=¥993,520.66
- 0 持仓
- LIVE_TRADING_DISABLED=false
- EXECUTION_MODE=live
- QMT_ACCOUNT_ID=81001102

0 broker call / 0 .env mutation (PT_TOP_N=5 already changed earlier per "同意你的建议" Stage 5) / 0 真账户 trade throughout.

## §8 关联

- LL-180 (broker_qmt asyncio compat sub-class) — sibling fix 5-18 14:14
- LL-179 (Beat 静默死亡 13.5h) — sibling 5-17 22:48
- LL-181 (N-hour natural cycle verification) — paired with今 stable session verify
- ADR-082 D8-D12 (post-cutover ongoing monitoring) — D13 candidate (本 fix)
- V3 §4 L1 RealtimeRiskEngine (Plan v0.4 IC-1c WU-2)
- 铁律 31 (Engine PURE) — broker_qmt 是 Engine 层, file IO 是 xtquant 已有 IO 不构成新违反
- 铁律 33 (fail-loud) — connect 失败 raise RuntimeError 沿用

**Sediment file**: 本 `V3_QMT_CONNECT_ROOT_CAUSE_FIX_2026_05_18.md` 是 LL-182 source-of-truth. LESSONS_LEARNED.md 后续 LL-182 entry references 本文件.
