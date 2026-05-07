# SOP — 应用层应急 / 实盘事件响应

> QuantMind V2 应用层 fire / 实盘账户保护 / 生产事件响应 SOP
> 版本: v0.1 (草稿) | 日期: 2026-05-01
> 范围补充: 与 `docs/SOP_DISASTER_RECOVERY.md` 配对
> - DR (L1-L5): 进程崩溃 / 系统蓝屏 / PG 损坏 / 磁盘故障 / 换机 — **基础设施层**
> - 本 SOP: 应用 zombie / 真账户异常 / Servy 链停 / DB 连接池 / 紧急清仓 / 实盘事件 — **应用层**
> 生效前提: `EXECUTION_MODE=paper` (backend/.env:17) + `settings.LIVE_TRADING_DISABLED=True` (config.py:44 默认)

---

## 目录

1. [应用层 fire — Servy RUNNING 但 zombie](#1-应用层-fire--servy-running-但-zombie)
2. [实盘账户异常 — xtquant 漂移 / NAV 异常](#2-实盘账户异常--xtquant-漂移--nav-异常)
3. [Servy 服务全死 — 4 服务 STOPPED](#3-servy-服务全死--4-服务-stopped)
4. [DB 连接池耗尽 / 连接泄漏](#4-db-连接池耗尽--连接泄漏)
5. [emergency_close 紧急清仓 SOP](#5-emergency_close-紧急清仓-sop)
6. [实盘事件 decision tree](#6-实盘事件-decision-tree)
7. [附录 A: 真账户 ground truth query 命令](#附录-a-真账户-ground-truth-query-命令)
8. [附录 B: Servy + schtasks 真实清单](#附录-b-servy--schtasks-真实清单)

---

## 1. 应用层 fire — Servy RUNNING 但 zombie

### 触发症状 (任一即触发, 阈值实测)

| # | 症状 | 检测命令 | 阈值 |
|---|------|---------|------|
| 1.1 | celerybeat-schedule.dat 停止更新 | `Get-Item logs/celerybeat-schedule.dat \| Select LastWriteTime` | `now - LastWriteTime > 10 min` |
| 1.2 | portfolio:nav Redis key stale | `redis-cli GET portfolio:nav \| jq .updated_at` | `now - updated_at > 5 min` (盘中) |
| 1.3 | qm:signal:generated stream 长时间无新事件 | `redis-cli XREVRANGE qm:signal:generated + - COUNT 1` | 盘中无新增 > 30 min |
| 1.4 | ServicesHealthCheck 钉钉告警 P0 | (被动) | 自动 (96/日) |

**前置概念**: 服务进程 RUNNING 但应用层逻辑卡死 = "zombie"。Beat 静默死亡 7h (LL-074, 2026-04-25), QMT sync_loop zombie 4h17m (LL-081, 2026-04-27 真生产首日)。

### 响应步骤

**Step 1** — 真测当前状态 (用附录 A.4 一键命令快速 dump):
```bash
# Beat heartbeat
ls -la logs/celerybeat-schedule.dat
# Redis nav freshness
redis-cli GET portfolio:nav
redis-cli TTL portfolio:nav
# 最近 stream 事件
redis-cli XREVRANGE qm:health:check_result + - COUNT 1
redis-cli XREVRANGE qm:qmt:status + - COUNT 1
```

**Step 2** — 主动跑 ServicesHealthCheck 一次性诊断:
```powershell
.\.venv\Scripts\python.exe scripts\services_healthcheck.py
```
退出码: 0=ok / 1=warn (dedup window 内) / 2=error.

**Step 3** — 定位 zombie 进程并 restart (依顺序):

zombie 是 Beat → restart Beat:
```powershell
D:\tools\Servy\servy-cli.exe restart --name="QuantMind-CeleryBeat"
```

zombie 是 qmt_data_service (portfolio:nav stale) → restart QMTData:
```powershell
D:\tools\Servy\servy-cli.exe restart --name="QuantMind-QMTData"
```

zombie 是 Worker (signal stream stuck) → restart Worker **+ 显式 start Beat** (LL-077: Servy cascade STOP 但不 cascade START):
```powershell
D:\tools\Servy\servy-cli.exe restart --name="QuantMind-Celery"
# 等 30s graceful shutdown
D:\tools\Servy\servy-cli.exe start --name="QuantMind-CeleryBeat"
```

**Step 4** — 等 15min, 验证 ServicesHealthCheck 下次周期 (schtask `QuantMind_ServicesHealthCheck` Repetition 15min) 转 ok 钉钉:
```powershell
schtasks /query /tn QuantMind_ServicesHealthCheck /v /fo list | Select-String "Last Run|Last Result|Next Run"
```

### 决策树 (操作者用)

```
钉钉告警 "Services Health DEGRADED"
│
├─ failures 含 "QuantMind-CeleryBeat" 服务 STOPPED?
│   └─ Step 3 restart Beat (sync 等 servy-cli 返回)
│
├─ failures 含 "beat:heartbeat stale Xmin"?
│   ├─ X < 30 → 等 1 cycle 看是否自恢复
│   └─ X ≥ 30 → restart Beat (zombie 卡死)
│
├─ failures 含 "portfolio:nav stale" 或 "key not found"?
│   ├─ 检查 QMTData 服务 RUNNING? → 否则 start
│   └─ 是 → restart QMTData (sync_loop zombie)
│
└─ failures 仅 "<service> not RUNNING"?
    └─ Servy start (Step 3 对应服务)
```

### 红线

- ❌ **禁** 用 `taskkill /F` 强杀 Worker — Celery graceful shutdown 需 30s, 强杀会丢未 ack 的 task (CLAUDE.md §部署规则)
- ❌ **禁** 仅看 `servy-cli status` 判断健康 — RUNNING ≠ alive (LL-074-C)
- ❌ **禁** 在 zombie 时绕过 ServicesHealthCheck 直接重启 PT 链 — 必先 root cause

### 教训 anchor

- LL-074 (Session 35, PR #74): CeleryBeat 静默死亡 0 logs → schedule.dat freshness 突破
- LL-074 v2.0 amendment (Session 38, PR #103 = LL-081 PR-X3): Redis portfolio:nav freshness 第二层兜底
- LL-077 (Session 36): Servy 依赖配置 cascade STOP 但不 cascade START → 必显式 start protocol
- LL-081 (Session 38, 2026-04-27 Monday 真生产首日): QMT zombie 4h17m
- LL-087 (Session 40, PR #113): transition-only event audit log ≠ heartbeat (撤 qm:qmt:status stream 检查, 因为 qmt:status 仅 transition 时写, 静默状态本就 0 事件)
- LL-088 (Session 40): Resource counter GC finalizer 防假告警

---

## 2. 实盘账户异常 — xtquant 漂移 / NAV 异常

### 触发症状

| # | 症状 | 检测 | 阈值 |
|---|------|------|------|
| 2.1 | DB ↔ xtquant 持仓 drift | 附录 A 双源对比 | 单股 qty 差异 ≠ 0 OR cash diff > ¥1000 |
| 2.2 | NAV 单日跌幅异常 | `redis-cli GET portfolio:nav` 历史比较 | 日跌 > -3% (无对应大盘事件) |
| 2.3 | 单股最新行情 vs 持仓均价巨幅偏离 | 钉钉告警 SingleStockStopLossRule (PR #139, -8% 阈值, 14:30 14:50 触发) | 单股 -8%+ 触发 |
| 2.4 | DB position_snapshot stale | `SELECT MAX(trade_date) FROM position_snapshot WHERE execution_mode='live'` | `today - max > 1 交易日` |

**前置概念**: 4-29 真生产事件 — 卓然 (688121.SH) 当日 -29.17% / 南玻 (000012.SZ) -9.75% (sprint state cite), 30天 risk_event_log 0 P0 行触发, user 上午 ~10:43 通过 chat 授权 CC 用 emergency_close 实战清仓 18 股 (D3-C F-D3C-13 实测 narrative v4, SHUTDOWN_NOTICE §3-4)。

### 响应步骤

**Step 1** — 取双源 ground truth (绝不互信单源):

```bash
# 源 A: xtquant 真账户 (实时, 缓存 60s 写一次)
redis-cli GET portfolio:nav
# 期望 JSON: {"cash": ..., "total_value": ..., "position_count": ..., "updated_at": "..."}

# 源 B: DB cb_state.live nav (Risk Framework 用)
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT execution_mode, current_level, trigger_reason, \
          (trigger_metrics->>'nav')::numeric AS nav, updated_at \
   FROM circuit_breaker_state ORDER BY updated_at DESC LIMIT 5;"

# 源 C: DB position_snapshot 最新 live
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT trade_date, execution_mode, COUNT(*), SUM(quantity), \
          SUM(market_value)::numeric(16,2) \
   FROM position_snapshot WHERE execution_mode='live' \
     AND trade_date >= CURRENT_DATE - 7 \
   GROUP BY trade_date, execution_mode ORDER BY trade_date DESC;"
```

**Step 2** — 三源对比, drift 分类:

| 场景 | drift | 行动 |
|---|---|---|
| A=B=C ✅ | 0 | 无异常, 关闭工单 |
| A ≠ B (Redis vs DB cb_state) | NAV 差 > ¥1k | T0-15/16 相关 (LL-081 cache silent drift), restart QMTData + 跑 audit script |
| A ≠ C (Redis vs DB position_snapshot) | 持仓数差 > 0 | DB stale snapshot, 缺 daily reconciliation. 走 [`scripts/audit/check_pt_restart_gate.py`](scripts/audit/check_pt_restart_gate.py) |
| A=C 但 B 有旧 entry | cb_state 未 reset | 走 PR #171 模式 (DELETE stale + UPDATE cb_state.nav) |

**Step 3** — 若 NAV 跌幅触发风控 (PR #139 SingleStockStopLossRule -8%):
- 钉钉告警自动到. 检查 `risk_event_log` 是否有当日 entry:
```sql
  SELECT triggered_at, severity, rule_id, code, action_taken, LEFT(reason, 100)
  FROM risk_event_log WHERE triggered_at::date = CURRENT_DATE;
  ```
- 若告警发但 event_log 0 行 → silent failure (PR #149 LL-081 guard 修过), 立即 restart Beat + 走 §1 zombie 流程

**Step 4** — 用户决策点 (这一步永远 user 显式确认, CC 不自主):
- 大盘事件 (沪深 -3%+ 同步) → 不动 (系统性, PMS 设计内)
- 单股黑天鹅 → user 决议: 持仓观察 / 部分减仓 / 全清仓
- 系统逻辑错误 → 暂停 PT (走 link_paused 模式), 修代码

### 决策树

```
NAV 跌幅 / 持仓异常告警
│
├─ 单股 -8%+ (SingleStockStopLossRule 钉钉)?
│   ├─ 大盘同步跌? → 不动 (系统性)
│   ├─ 个股黑天鹅 → user 显式决议持仓 / 减仓 / 清仓
│   └─ user 决议清仓 → 走 §5 emergency_close
│
├─ Redis NAV vs DB cb_state drift > ¥1k?
│   └─ §3 章节 + restart QMTData + 跑 PR #171 cleanup 模板
│
├─ DB position_snapshot 与 xtquant 持仓不符?
│   └─ T0-19 audit gap (PR #168 phase 2 修过, 但仅 emergency_close 路径). 走 audit script
│
└─ NAV 单日跌 > -5% 但无单股触发?
    └─ 大概率风控盲点, 钉钉手工告警 user, user 决议
```

### 红线

- ❌ **禁** 凭 DB 单源判定真账户 (4-28 stale 4 天 drift 19 股 ¥18k 教训, SHUTDOWN_NOTICE §3)
- ❌ **禁** 凭 Redis 单源判定 (qmt_data_service 60s sync zombie 时 cache stale, LL-081)
- ❌ **禁** 在 LIVE_TRADING_DISABLED=true 状态下绕开 guard 直发单 — 必走 OVERRIDE 双因素 (§5)
- ❌ **禁** "再观察一会儿" 拖延 — 异常超过 1 个 trading bar (5-15 min) 必决策

### 教训 anchor

- 4-29 实盘事件 (SHUTDOWN_NOTICE §1-§4 v3 narrative): 30天 risk_event_log 0 行 + user 上午 chat 授权清仓
- LL-081 (Session 38, PR #100/#101/#103/#105): QMT zombie + Redis status 无 TTL → 4h+ silent failure
- LL-097 X9 (PR #170): schedule / config 注释 ≠ 停服, 必显式 restart
- T0-15/16/18 已 closed (PR #170 batch-2-p0): QMTFallbackTriggeredRule + qmt_data_service fail-loud + namespace assert
- T0-19 (PR #167/#168 phase 1+2): emergency_close 后 trade_log/risk_event_log/perf_series 自动写 audit hook

---

## 3. Servy 服务全死 — 4 服务 STOPPED

### 触发症状

`Get-Service QuantMind-*` 多个 Status=Stopped, OR Windows 重启后未恢复, OR ServicesHealthCheck 多 fail。

### 服务依赖真实拓扑 (实测 2026-05-01 PowerShell)

```
RPCSS (Windows 内置)
   └─ PostgreSQL16 ─────────┐
   └─ Redis ─┬──────────────┤
             ├─ QuantMind-Celery ─── QuantMind-CeleryBeat
             ├─ QuantMind-FastAPI (← PostgreSQL16 + Redis)
             └─ QuantMind-QMTData
```

> ⚠️ Beat → Worker 是 Servy 配置的 hard dependency, **cascade STOP 但不 cascade START** (LL-077). 启动顺序必显式遵守。

### 响应步骤 (按依赖顺序启动)

**Step 1** — 验证基础设施层 (DR §3.2 已覆盖, 此处仅验证):
```powershell
Get-Service PostgreSQL16, Redis | Format-Table Name, Status, StartType -AutoSize
```
任一非 Running → 走 SOP_DISASTER_RECOVERY §3.2 L2 流程, 然后回本节继续。

**Step 2** — 按依赖顺序启动 4 应用服务:
```powershell
# 1. Worker 先 (Beat 依赖)
D:\tools\Servy\servy-cli.exe start --name="QuantMind-Celery"
# 等 ~10s 让 worker 完成 import + import strategy bootstrap
Start-Sleep -Seconds 10

# 2. Beat (依赖 Worker)
D:\tools\Servy\servy-cli.exe start --name="QuantMind-CeleryBeat"

# 3. FastAPI (依赖 Redis + PG, 与 Beat 平行)
D:\tools\Servy\servy-cli.exe start --name="QuantMind-FastAPI"

# 4. QMTData (依赖 Redis, 数据缓存, 与上平行)
D:\tools\Servy\servy-cli.exe start --name="QuantMind-QMTData"
```

**Step 3** — 全启动验证清单:
```powershell
# (a) 服务全 Running
Get-Service QuantMind-* | Format-Table Name, Status -AutoSize
# (b) FastAPI health
Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing
# (c) Celery worker 响应
.\.venv\Scripts\python.exe -m celery -A app.tasks inspect ping
# (d) QMTData 写入 Redis
redis-cli GET portfolio:nav   # 应在 60s 内有新 updated_at
# (e) Beat schedule.dat 心跳
Get-Item logs/celerybeat-schedule.dat | Select-Object LastWriteTime
```

**Step 4** — 跑 ServicesHealthCheck 强制验证:
```powershell
.\.venv\Scripts\python.exe scripts\services_healthcheck.py
# 期望 exit=0
```

### 决策树

```
多服务 Stopped
│
├─ Windows 刚重启? → 等 5min 让自启动完成, 再 Step 2
├─ Redis Stopped? → SOP_DR §3.2 先, 再回本节
├─ PG Stopped? → SOP_DR §3.2 先 (注意 Servy 启动时 PG 未 ready 会 fail, LL-079)
└─ 单纯 4 应用服务 Stopped → Step 2 按顺序启动
```

### 红线

- ❌ **禁** 一次性 `Start-Service QuantMind-*` 不分顺序 — Beat 在 Worker 未 ready 时启会立即 STOP 进入 cascade 死锁
- ❌ **禁** 跳过 Step 4 直接放行使用 — 必跑 ServicesHealthCheck 一次性确认
- ❌ **禁** 在 PG/Redis 未 Running 前启 QM 应用服务 — 失败后 Servy 自动重试 N 次会导致服务 disabled (LL-079 教训)

### 教训 anchor

- LL-077 (Session 36): Servy cascade STOP 但不 cascade START
- LL-079 (Session 36 末): pg_ctl restart 不刷新 Windows Service 状态 — Servy 依赖检测失效
- SOP_DISASTER_RECOVERY §3.2 (本 SOP 配对): L2 系统重启后基础设施层验证

---

## 4. DB 连接池耗尽 / 连接泄漏

### 触发症状

| # | 症状 | 检测 | 阈值 |
|---|------|------|------|
| 4.1 | Celery 日志 "sync连接数达到上限(15)" | `grep "连接数达到上限" logs/celery-stderr.log` | 任一 |
| 4.2 | psql 拒接 "FATAL: too many connections" | `tail -F D:\pgdata16\pg_log\*.log` | 任一 |
| 4.3 | FastAPI request 卡 30s+ 不返回 | curl `/health` 超时 | timeout |

**前置概念**: LESSONS_LEARNED:2627 实测 4-28 14:55 出现 "sync连接数达到上限(15)" warning。Engine 层不开 connection (铁律 31), Service 不 commit (铁律 32), Router/Celery task 用 `with conn:` context manager 管事务。泄漏几乎都是缺 close 或 except 路径漏 close。

### 响应步骤

**Step 1** — 实测当前 PG 连接情况:
```bash
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT state, COUNT(*), MAX(now() - state_change) AS max_age \
   FROM pg_stat_activity WHERE datname='quantmind_v2' \
   GROUP BY state ORDER BY max_age DESC;"
```

**Step 2** — 找最老的 idle in transaction 连接 (泄漏候选):
```bash
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT pid, application_name, state, now()-state_change AS age, \
          LEFT(query, 100) AS q \
   FROM pg_stat_activity WHERE datname='quantmind_v2' \
     AND state IN ('idle in transaction', 'idle in transaction (aborted)') \
   ORDER BY state_change ASC LIMIT 10;"
```

**Step 3** — 临时缓解 (kill 长 idle 连接, 不影响 active query):
```sql
-- 仅 kill state='idle in transaction' AND age > 10 min 的连接
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname='quantmind_v2'
  AND state IN ('idle in transaction', 'idle in transaction (aborted)')
  AND now() - state_change > interval '10 minutes';
```

**Step 4** — Restart Celery Worker 释放泄漏 (graceful, 等 30s):
```powershell
D:\tools\Servy\servy-cli.exe restart --name="QuantMind-Celery"
# 等 30s, 必显式 start Beat (LL-077)
Start-Sleep -Seconds 30
D:\tools\Servy\servy-cli.exe start --name="QuantMind-CeleryBeat"
```

**Step 5** — root cause 分析 (本 task 范围外, 沉淀 finding):
- grep 当日 stderr 找 stack trace 中的 except 路径
- 检查最近 PR diff 是否有 `with conn:` / `cursor()` 缺 close
- 沉淀到 `docs/audit/` 作为 finding, 安排 Layer 2+ 修

### 决策树

```
连接池告警
│
├─ active query 多 (> 10 在跑)? → 真实负载, 等任务完成
├─ idle in transaction 多 (> 5)? → Step 3 kill + Step 4 restart Worker
├─ idle 多但 state_change 老 (> 30 min)? → connection pool 配置过大或泄漏, Step 4
└─ pg_stat_activity 也连不上? → PG 已挂或 max_connections 太低, 走 SOP_DR §3.3
```

### 红线

- ❌ **禁** 直接 `Restart-Service postgresql-x64-16` 当 active query 在跑 — 会丢未 commit 的事务
- ❌ **禁** 提高 max_connections 当作解决 — 治标不治本, 32GB RAM PG shared_buffers=2GB 是固定开销
- ❌ **禁** 在不查 pg_stat_activity 的情况下盲 kill — 可能误杀正常长查询 (例如 fast_neutralize_batch 17min)

### 教训 anchor

- LESSONS_LEARNED:2627 实测 (4-28 14:55): Celery sync 连接数 15 上限警告
- 铁律 9 (重数据 max 2 并发): 32GB 硬约束, 违反 → PG OOM (2026-04-03 事件)
- 铁律 32 (Service 不 commit): 事务边界由 Router/Celery 管, 缺 close 是泄漏头号源

---

## 5. emergency_close 紧急清仓 SOP

### 适用场景 (任一即触发)

- §2 决策树底部 user 决议清仓 (单股黑天鹅 / 系统性事件)
- 实盘风控失效 + user 显式 chat 授权 (4-29 案例 narrative v4)
- 系统逻辑层错误 + 持仓暴露不可控

### 工具真实位置

`scripts/emergency_close_all_positions.py` (358 行)

### 真实 abort 路径 (源码 emergency_close.py 实测)

| 路径 | 行号 | 退出码 | 触发条件 |
|---|---:|---:|---|
| `_resolve_positions_via_qmt()` connect fail | L267-271 | 2 | QMT 路径错 / 账户错 / xtquant 不可用 |
| `not sellable` (空持仓 OR 全 BJ/UNKNOWN) | L275-277 | 0 | 没什么可卖 |
| `not args.execute` (默认 dry-run) | L279-283 | 0 | 未传 --execute, 仅打印清单 |
| `not _confirm_execute()` (interactive 'YES SELL ALL' 失败) | L291-293 | 1 | EOF / 输错 |
| 顶层 `except` | L351-357 | 2 | 任意未捕获 exception |

### 安全保护 (源码实测)

1. **默认 dry-run** (无 --execute = 仅列清单, 0 单)
2. **Interactive 确认** ("YES SELL ALL" 精确匹配, EOFError 自动 abort)
3. **--confirm-yes flag** (chat-driven 授权用, audit trail 自动 log + stderr `[AUDIT]` 时戳 + pid)
4. **xtquant guard 双因素** ([backend/app/security/live_trading_guard.py:48](backend/app/security/live_trading_guard.py:48), 由 broker_qmt.place_order 前置调用):
   - `LIVE_TRADING_FORCE_OVERRIDE=1` (单独不够)
   - `LIVE_TRADING_OVERRIDE_REASON='<非空 reason>'` (strip 后非空)
   - 缺一即 raise `LiveTradingDisabledError`
   - bypass 时 logger.warning audit + DingTalk P0 (silent_ok 兜底)
5. **xtquant API 直 query 持仓** (不读 DB stale snapshot, 防 4-28 stale 重演)
6. **BJ 北交所自动 SKIP** (xtquant 五档撮合不支持 BJ, 留 user 手工 GUI)
7. **0.2s sleep 节流** (防 QMT 短时间大量下单限流)
8. **T0-19 audit hook** (PR #168 phase 2, L309-324) 写 trade_log + risk_event_log + perf_series + cb_state nav reset (silent_ok 不阻 sells 完成)

### 标准操作流程 (4 步)

**Step 1 — 必先 dry-run** (无任何环境变量, 不会发任何单):
```powershell
.\.venv\Scripts\python.exe scripts\emergency_close_all_positions.py
```
输出: 持仓清单 + 估算成交额 + 日志路径。检查清单是否符合预期 (代码 / qty / 估值)。

**Step 2 — 设双因素 OVERRIDE**:
```cmd
:: Windows cmd
set LIVE_TRADING_FORCE_OVERRIDE=1
set LIVE_TRADING_OVERRIDE_REASON="Emergency close 2026-05-01: <具体原因>"
```
```bash
# bash
export LIVE_TRADING_FORCE_OVERRIDE=1
export LIVE_TRADING_OVERRIDE_REASON="Emergency close 2026-05-01: <具体原因>"
```

**Step 3 — 执行** (interactive 模式):
```powershell
.\.venv\Scripts\python.exe scripts\emergency_close_all_positions.py --execute
# 提示输入, 必须精确输 'YES SELL ALL' (含空格大小写)
```

OR chat-driven 授权 (CC 自主, audit trail 自动写):
```powershell
.\.venv\Scripts\python.exe scripts\emergency_close_all_positions.py --execute --confirm-yes
```

**Step 4 — 收单后立即 audit**:
```bash
# (a) 检查 logs/emergency_close_*.log 最新文件 (期望 13KB+ 含 18 股 trace, 4-29 forensic 模板)
ls -t logs/emergency_close_*.log | head -1

# (b) 真账户 ground truth 复查 (附录 A.1)
redis-cli GET portfolio:nav

# (c) DB 三表自动写入验证 (T0-19 audit hook)
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT trade_date, COUNT(*) FROM trade_log WHERE trade_date=CURRENT_DATE GROUP BY trade_date;"
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT severity, rule_id, action_taken, LEFT(reason, 100) \
   FROM risk_event_log WHERE triggered_at::date=CURRENT_DATE ORDER BY triggered_at DESC;"

# (d) 取消 OVERRIDE env (防误用)
```
```cmd
set LIVE_TRADING_FORCE_OVERRIDE=
set LIVE_TRADING_OVERRIDE_REASON=
```

### 决策树

```
user 决议紧急清仓
│
├─ 持仓 < 5 只 + 实盘账户 < ¥100k? → user 走 QMT GUI 手工 (本工具 overhead 不值得)
│
├─ 持仓 5-20 只 (4-29 同模式)?
│   ├─ Step 1 dry-run → 看清单
│   ├─ user chat 授权 OK?
│   │   ├─ 是 → Step 2-3 with --confirm-yes (audit log)
│   │   └─ 否 → Step 2-3 interactive 'YES SELL ALL'
│   └─ Step 4 audit
│
└─ 含 BJ 北交所持仓? → 工具自动 SKIP, user 必走 GUI 手工卖 (xtquant 限制)
```

### 红线

- ❌ **禁** 跳过 Step 1 dry-run 直 --execute (4-29 forensic: 10:38-10:41 三次 ImportError dry-run failed → 10:43:54 才 sell, 反向证明 dry-run 起到了防护)
- ❌ **禁** OVERRIDE_REASON 写空字符串 / "test" / "ok" 等非具体内容 — 双因素加固 1 会 raise (audit 价值)
- ❌ **禁** 在 LIVE_TRADING_DISABLED guard fail 时绕开走 paper_broker — paper 不发单, 不解决问题 (但物理隔离设计如此, 不要拼凑)
- ❌ **禁** 反复 --confirm-yes (audit log 已写, OVERRIDE env 持久会被未来 schtask 误用)
- ❌ **禁** sells 后未跑 Step 4 audit 即认为完成 (4-29 forensic 实测: trade_log 0 行 since 4-17, 因为 4-29 emergency_close 当时还没有 T0-19 audit hook, 直到 PR #168 phase 2 才修)

### 4-29 案例 forensic (SHUTDOWN_NOTICE §4 v3)

5 个 emergency_close_*.log 文件实测时序:

| 时间 | 文件 | size | 事件 |
|---|---|---:|---|
| 10:38:25 | emergency_close_20260429_103825.log | 669 B | ImportError: 'QMTBroker' (FAIL #1) |
| 10:39:36 | emergency_close_20260429_103936.log | 644 B | ModuleNotFoundError: 'xtquant' (FAIL #2) |
| 10:40:22 | emergency_close_20260429_104022.log | 317 B | dry-run 18 持仓 |
| 10:41:14 | emergency_close_20260429_104114.log | 317 B | dry-run #2 |
| **10:43:54** | **emergency_close_20260429_104354.log** | **13,992 B** | **--execute --confirm-yes 成交 18 股** |

教训: dry-run 抓出 2 次 ImportError 是工具的防护 (LL-074 类 fail-loud 设计), 第 5 次才真发单。

### 教训 anchor

- 4-29 narrative v3+v4 (PR #165, PR #169 D3-C 实测): user 上午 ~10:40 chat 授权, CC 10:43:54 执行
- LL-095 (PR #169 D3 v4): emergency_close status=57 cancel 因综合判定 (不假设单一原因)
- LL-096 (PR #169): forensic 类 spike 修订不可一次性结论
- T0-19 (PR #167 phase 1 + #168 phase 2): emergency_close 后 trade_log/risk_event_log/perf_series 自动写 audit hook (4-29 当时没有, 现在有)
- link_paused_2026_04_29.md (PR #150): T1 sprint link-pause 4 件事 (LIVE_TRADING_DISABLED + 2 Beat 注释 + 2 smoke skip), 还原前置见该文档

---

## 6. 实盘事件 decision tree

### 输入触发 (任一即进入决策)

钉钉 P0/P1 告警 OR user 手工发现 OR ServicesHealthCheck fail OR 单股监控告警。

### 决策树 (整合 §1-§5)

```
告警进入 (任一来源)
│
├─ 告警类型: 服务/进程层?
│   └─ § 1 应用层 fire (zombie / Beat death / QMT sync_loop) OR §3 Servy 全死
│
├─ 告警类型: 数据/账户层?
│   ├─ NAV / 持仓 drift 钉钉?
│   │   └─ §2 实盘账户异常 → 三源对比 → drift 分类
│   │
│   ├─ 单股 -8%+ SingleStockStopLossRule (PR #139)?
│   │   ├─ 大盘同步? → 不动 (系统性, PMS 设计内)
│   │   └─ 黑天鹅? → user 显式决议 → §5 emergency_close (如清仓)
│   │
│   └─ DB 连接池告警?
│       └─ §4 连接池耗尽 → kill idle in transaction + restart Worker
│
├─ 告警类型: 风控层?
│   ├─ risk_event_log 当日 0 行 + 有 NAV 跌? (4-29 同模式)
│   │   └─ silent failure (LL-081 模式), restart Beat + LL-081 guard 检查 + user 决议
│   │
│   └─ MVP 3.1 Risk Framework 周一首生产 (Monday 09:00)?
│       └─ checklist_monday_4_27_first_production.md 模板 (memory)
│
└─ 告警类型: 多重 (复合事件)?
    │
    ├─ Servy 全死 + DB drift? → §3 先 → §2 后 (基础设施先恢复)
    ├─ Beat zombie + NAV stale? → §1 先 → §2 后
    └─ 全 PT 暂停决议 → link_paused_2026_04_29 模式 (4 件事打包 PR)
```

### 复合事件案例 (4-29 真生产, narrative v4)

```
1. 14:00-14:30 user 上午观察单股暴跌 (688121 -29% / 000012 -10%)
2. user chat 授权 CC 用 emergency_close
3. CC 10:38-10:41 三次 ImportError dry-run (工具自防护)
4. CC 10:43:54 修复路径 + --confirm-yes 成交 18 股
5. CC 14:00 写 risk_event_log audit recovery 行 (severity=p0)
6. user 14:00+ 决议 "全清仓暂停 PT + 加固风控"
7. CC PR #150 link-pause T1-sprint (LIVE_TRADING_DISABLED + 2 Beat 注释 + 2 smoke skip)
8. CC PR #170 batch-2-p0 (T0-15/16/18 + LL-097 X9)
9. CC PR #171 PT restart gate cleanup (DELETE 4-28 stale + cb_state nav reset)
10. CC PR #167+#168 T0-19 audit hook (emergency_close 后自动写 trade_log)
```

### 红线 (跨章节)

- ❌ **禁** 单源决策 (DB only / Redis only / 钉钉 only)
- ❌ **禁** 跨日不结案 (异常 > 1 trading day 未决议 = 风险滚动)
- ❌ **禁** 跳过 Step 4 audit / verification 即认为修复完成
- ❌ **禁** silent failure 容忍 — 钉钉发了但 DB 0 行 = bug, 必修不绕
- ❌ **禁** 模糊决议 ("先观察", "稍后再说") — user 必显式 ✅/❌/⚠️

### 不在本 SOP 覆盖范围 (走其他流程)

- 进程崩溃 (NSSM/Servy 自动重启) → SOP_DR §3.1 L1
- 系统蓝屏后 → SOP_DR §3.2 L2
- PG 数据损坏 / 误删 → SOP_DR §3.3 L3
- 主磁盘故障 / 换机 → SOP_DR §3.4-§3.5 L4-L5
- 数据接入异常 (Tushare / Baostock 限流) → DEV_BACKEND
- 因子计算异常 → 不阻断生产, 走 audit
- AI 闭环异常 → DEV_AI_EVOLUTION

---

## 附录 A: 真账户 ground truth query 命令

### A.1 Redis A-lite cache (qmt_data_service 60s sync 写入)

```bash
# JSON String, TTL ~60-90s 由 SETEX 设置
redis-cli GET portfolio:nav
# 期望输出: {"cash": 993520.66, "total_value": ..., "position_count": 0, "updated_at": "..."}

redis-cli TTL portfolio:nav
# 正常: 0-90s 区间循环
```

### A.2 DB cb_state (Risk Framework 用)

```sql
SELECT execution_mode, current_level, trigger_reason,
       (trigger_metrics->>'nav')::numeric AS nav_logged, updated_at
FROM circuit_breaker_state
ORDER BY updated_at DESC LIMIT 5;
```

### A.3 xtquant API 直 query (慎用 — 需 connect, 占 QMT session, 仅 audit 用)

```python
# scripts/audit/check_pt_restart_gate.py 类似模式
import sys, pathlib
sys.path.insert(0, str(pathlib.Path("backend").resolve()))
from app.config import settings
from app.core.xtquant_path import ensure_xtquant_path
ensure_xtquant_path()
from engines.broker_qmt import MiniQMTBroker
broker = MiniQMTBroker(qmt_path=settings.QMT_PATH, account_id=settings.QMT_ACCOUNT_ID)
broker.connect()
asset = broker.query_asset()        # cash / market_value / total_asset
positions = broker.query_positions() # list of {stock_code, volume, can_use_volume, avg_price, market_value}
print(asset, positions)
```

### A.4 一键 dump (监测脚本可借鉴)

```bash
echo "=== Redis nav ==="; redis-cli GET portfolio:nav; redis-cli TTL portfolio:nav
echo "=== Redis stream tails ==="
redis-cli XREVRANGE qm:qmt:status + - COUNT 1
redis-cli XREVRANGE qm:health:check_result + - COUNT 1
redis-cli XREVRANGE qm:signal:generated + - COUNT 1
echo "=== Beat heartbeat ==="; ls -la logs/celerybeat-schedule.dat
echo "=== DB cb_state ==="
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT execution_mode, current_level, (trigger_metrics->>'nav')::numeric AS nav, updated_at FROM circuit_breaker_state ORDER BY updated_at DESC LIMIT 3;"
echo "=== DB position_snapshot live last 7d ==="
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT trade_date, COUNT(*), SUM(quantity), SUM(market_value)::numeric(16,2) FROM position_snapshot WHERE execution_mode='live' AND trade_date >= CURRENT_DATE - 7 GROUP BY trade_date ORDER BY trade_date DESC;"
echo "=== Risk events recent ==="
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT triggered_at, severity, rule_id, code, action_taken, LEFT(reason, 80) FROM risk_event_log WHERE triggered_at >= CURRENT_DATE - 7 ORDER BY triggered_at DESC LIMIT 10;"
```

---

## 附录 B: Servy + schtasks 真实清单

### B.1 Servy 服务 (实测 2026-05-01)

| Name | Status | StartType | Depends |
|---|---|---|---|
| PostgreSQL16 | Running | Automatic | RPCSS |
| Redis | Running | Automatic | (none) |
| QuantMind-Celery | Running | Automatic | Redis |
| QuantMind-CeleryBeat | Running | Automatic | Redis, QuantMind-Celery |
| QuantMind-FastAPI | Running | Automatic | Redis, PostgreSQL16 |
| QuantMind-QMTData | Running | Automatic | Redis |

### B.2 schtasks 任务 (实测 2026-05-01)

**Active (PT 暂停期仍跑)**:

| TaskName | NextRun | 用途 |
|---|---|---|
| QuantMind_ServicesHealthCheck | repeat 15min | LL-074/081 zombie 监控, 钉钉去重 |
| QuantMind_PT_Watchdog | 17:35-20:00 | 1/日 PT 链路终态确认 |
| QuantMind_PTAudit | 17:35 | PT 持仓 / NAV 对账 |
| QuantMind_RiskFrameworkHealth | 18:45 | Risk Framework 健康 (Beat 自愈兜底) |
| QuantMind_DailyIC | 18:00 (Mon-Fri) | 因子 IC backfill (LL-066 subset) |
| QuantMind_IcRolling | 18:15 (Mon-Fri) | IC ma20/60 rolling |
| QuantMind_DailyMoneyflow | 17:30 | Tushare moneyflow 拉取 |
| QuantMind_FactorHealthDaily | 17:30 | 因子健康度 |
| QuantMind_DataQualityCheck | 18:30 | 数据质量审计 |
| QuantMind_PTDailySummary | 17:35 | PT 日报 |
| QuantMind_MVP31SunsetMonitor | 04:00 | MVP 3.1 sunset transition |
| QM-DailyBackup | 02:00 | PG 每日备份 (DR §6 用) |
| QuantMind_MiniQMT_AutoStart | onStart | QMT 自启动 |

**Disabled (PT 暂停决议, link_paused_2026_04_29 §B+§C 模式)**:

| TaskName | 原状态 |
|---|---|
| QuantMind_DailySignal | 17:15 (旧 stale, 现 disabled) |
| QuantMind_DailyExecute | (disabled) |
| QuantMind_DailyReconciliation | 15:40 (disabled) |
| QuantMind_IntradayMonitor | (disabled) |
| QuantMind_CancelStaleOrders | (disabled) |

> ⚠️ disable schtask 是停跑 (vs Beat schedule 注释 = LL-097 X9 坑). 但 schtask 重启命令是 `schtasks /change /tn <name> /enable`。

---

## 文档版本 / 维护

- **v0.1** (2026-05-01): 初稿, 6 节 + 2 附录, 基于 Stage A+B 实测
- 后续 v0.2+ 扩展: 实战触发后沉淀 case 到对应章节红线 / 教训 anchor 段
- 维护频次: 每次实战 fire 后 24h 内必更 (LL-066 实战驱动模式)
- 关联文档: SOP_DISASTER_RECOVERY.md (基础设施层) / link_paused_2026_04_29.md (T1 sprint 暂停清单) / SHUTDOWN_NOTICE_2026_04_30.md (4-29 narrative v4) / IRONLAWS.md (33/41/X10 等)
