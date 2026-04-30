# D3.4 Servy 服务依赖图审计 — 2026-04-30

**Scope**: 4 服务依赖关系 / 启动顺序 / 失败级联 / restart 冲击 / Servy 配置健康
**0 改动**: 纯 read-only Servy export (json) + grep

---

## 1. Q4.1 4 服务 Servy 配置矩阵 (实测)

```bash
D:/tools/Servy/servy-cli.exe export --name=<svc> --config=json --path=/tmp/<svc>.json -q
```

| 服务 | ServiceDependencies | HeartbeatInterval | MaxRestartAttempts | StdoutPath | RecoveryAction |
|---|---|---:|---:|---|---:|
| QuantMind-FastAPI | **Redis; PostgreSQL16** | 15s | 5 | logs/fastapi-stdout.log | 1 |
| QuantMind-Celery | **Redis** | 15s | 5 | logs/celery-stdout.log | 1 |
| QuantMind-CeleryBeat | **Redis; QuantMind-Celery** | 30s | 5 | logs/celery-beat-stdout.log | 1 |
| QuantMind-QMTData | **Redis** | 30s | 5 | logs/qmt-data-stdout.log | 1 |

---

## 2. F-D3C-7 (P1) — Celery + QMTData 缺 PostgreSQL16 依赖声明

**关键漂移**:
- FastAPI 依赖 `Redis; PostgreSQL16` ✅
- **Celery 仅依赖 `Redis`** ❌ (但 Celery worker tasks 真生产做 PG INSERT scheduler_task_log / risk_event_log / alert_dedup / etc)
- **QMTData 仅依赖 `Redis`** ❌ (但 qmt_data_service.py 也读 DB get_positions fallback path, 沿用 D3-B F-D3B-7 实测 portfolio:current 0 keys → fallback DB)
- CeleryBeat 依赖 `Redis; QuantMind-Celery` ✅ (正确, Beat 触发 task 经 Celery worker 消费)

→ **F-D3C-7 (P1)**: Celery + QMTData 缺 PG 依赖声明. PG service 重启 → 这 2 服务 silent fail (PG 重连过渡期 ~5-30s 内的 task 全 raise + Servy 不感知, 仅 RecoveryAction=1 RestartService 在 heartbeat 失败时触发, 但 PG 临时不可用不会触发 process exit, 只是 task 失败).

**风险场景**: Sunday PG maintenance window (Session 36 末 sunday_pg_maintenance.ps1, shared_buffers 升级 5-30s 中断) → Celery / QMTData 应**先停后启**, 否则 5-30s 间所有 PG-touching task 都 silent fail.

**修法**: Servy import 命令改 `ServiceDependencies = "Redis; PostgreSQL16"` for Celery + QMTData. ~5min.

---

## 3. Q4.2 启动顺序硬性

基于实测依赖图 (上表):

```
[PostgreSQL16] ──┬──→ FastAPI
                 │
[Redis] ─────────┼──→ Celery
                 │     │
                 │     └──→ CeleryBeat
                 └──→ FastAPI / QMTData
```

**正确启动顺序**: PostgreSQL16 → Redis → (并行) FastAPI / Celery / QMTData → CeleryBeat (Celery 完启动后)

**Servy 自动**: 系统启动时按 ServiceDependencies 拓扑排序自动. 但 **Celery + QMTData 缺 PG 依赖** → Servy 假定 PG 不必先于这 2 服务, 实际开机若 PG 慢启动 (Windows Service Control Manager 5-30s 启动) → Celery / QMTData 启动后 2-3s 内 task 触发但 PG 不可用 silent fail.

→ **F-D3C-8 (P2)**: 开机启动顺序 race condition 潜在风险, F-D3C-7 修后自愈.

---

## 4. Q4.3 失败级联场景

| 失败源 | 直接级联 | 真生产风险 |
|---|---|---|
| Redis down | FastAPI 部分功能 (Streams / dedup) / Celery 完全 / Beat 完全 / QMTData 完全 | **P0 — 实质全停** |
| PG down | FastAPI DB 端点 / Celery PG-touching task / QMTData fallback DB | **P0 — 实质全停 (但 F-D3C-7 漏声明)** |
| Celery down | Beat 触发但 task 无 worker 消费 (积压 Redis broker queue) | P1 (Beat 不知道 worker 死, 持续 schedule) |
| Beat down | 调度任务全 missed (沿用 PR #150 link-pause 经验) | P0 真生产事故来源 |
| FastAPI down | API 端点 503 / 健康检查失败 | P1 (UI / monitor 受影响, 主链不阻断) |
| QMTData down | portfolio:current Redis cache 不更新 (沿用 D3-A Step 4 修订 26 天 silent skip case study) | P0 silent (silent ≠ alarm) |

→ **F-D3C-9 (P1)**: QMTData down 是 silent failure 模式, **Servy heartbeat 不检测连接性**, 仅检测进程 alive. 4-04 起 26 天 silent skip 的根因之一 (T0-16). 修法: 加 application-level health endpoint + Servy PreLaunch script verify 真连通.

---

## 5. Q4.4 restart 冲击实测 (沿用 PR #161 案例)

PR #161 D3-A Step 5 落地 restart QuantMind-CeleryBeat 实测:

```
4-30 14:07 (PR #150 link-pause 后未重启的 stale process)
  ↓ 73 次 intraday_risk_check error 累计 (Beat schedule cache 仍跑旧 schedule)
4-30 15:35:51 servy-cli.exe restart QuantMind-CeleryBeat
  ↓ Beat process kill + new process boot
  ↓ stderr "primary source failed" 0 entry 自 14:55 (verified D3-A Step 5)
  ↓ DingTalk 静音
4-30 16:52 (本 D3-C audit 时点, restart 后 ~75min)
  ↓ celery-beat-stderr.log 725 KB (有内容, 但无 spam error)
```

→ **F-D3C-10 (INFO)**: Beat restart **0 副作用** (沿用 PR #161 实测), 30s tick 不丢任务 (next tick 自然恢复). 其他 3 服务 restart 冲击未实测, 推断:
- FastAPI restart: HTTP 5xx 5-30s 间 (workers=2 graceful), API caller 重试自愈
- Celery restart: in-flight task 30s graceful drain, 丢 in-flight task ack (但 task retry 配置覆盖)
- QMTData restart: 60s 同步循环错过 1 次, Redis cache 60-120s 不更新 (实测 4-30 15:35 Beat restart 同时 4 服务都 Running, 沿用)

---

## 6. Q4.5 Servy 自身配置健康

实测每服务 Servy 配置:
- ✅ EnableHealthMonitoring = true (4/4)
- ✅ EnableRotation = true, RotationSize = 100 MB, MaxRotations = 5 (4/4)
- ✅ RecoveryAction = 1 (RestartService) + MaxRestartAttempts = 5 (4/4)
- ⚠️ HeartbeatInterval: FastAPI/Celery=15s vs Beat/QMTData=30s (差 2x, 推测 Beat/QMTData 心跳低频更合理因为 task 周期更长)
- ✅ RunAsLocalSystem = true (4/4, no per-user secret manager 依赖)
- ⚠️ EnableDebugLogs = false (4/4) — 生产合理但 audit 期间无法获详细启停 log

→ **F-D3C-11 (INFO)**: Servy 配置健康整体 ✅, F-D3C-7/8/9 是设计/声明层 gap.

---

## 7. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3C-7 | Celery + QMTData 缺 PostgreSQL16 依赖声明, 开机/PG-restart race 潜在 silent fail | P1 |
| F-D3C-8 | 开机启动顺序 race condition 潜在风险, F-D3C-7 修后自愈 | P2 |
| F-D3C-9 | QMTData Servy heartbeat 仅检测进程 alive, 不检测连接性, 4-04 起 26 天 silent skip 根因之一 (T0-16) | P1 |
| F-D3C-10 | Beat restart 0 副作用 (沿用 PR #161 实测), 其他 3 服务 restart 冲击推断 OK | INFO |
| F-D3C-11 | Servy 配置健康整体 ✅, F-D3C-7/8/9 是设计/声明层 gap | INFO |

---

## 8. 处置建议

- **F-D3C-7 (P1)**: 单 PR Servy import 改 ServiceDependencies for Celery + QMTData (~5min)
- **F-D3C-9 (P1)**: T0-16 修法范围扩 — qmt_data_service.py fail-loud 改造 + Servy PreLaunch script verify 连通性 (~1h)
- **F-D3C-8 (P2)**: F-D3C-7 修后自愈
- INFO 留 D3 整合 / Wave 5+

---

## 9. 关联

- T0-16 qmt_data_service 26 天 silent skip
- D3-A Step 4 修订 v2 L4 NEW v2 (QMTClient fallback 直读 DB self-loop)
- D3-A Step 5 F-D3A-NEW-6 PR #150 link-pause Beat restart 失效
- PR #161 D3-A Step 5 落地 (Beat restart verified 0 副作用)
- Sunday PG maintenance window (Session 36 末 sunday_pg_maintenance.ps1)
- Servy v7.6 替代 NSSM (2026-04-04 迁移)
