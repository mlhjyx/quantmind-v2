# D3.5 Redis 健康审计 — 2026-04-30

**Scope**: StreamBus 8 streams 真实状态 / portfolio:* / market:* cache / celery-task-meta / 全 keyspace
**0 改动**: 纯 read-only redis-cli (KEYS / TYPE / TTL / DBSIZE)

---

## 1. Q5.1 Redis 全 keyspace (实测)

```
DBSIZE = 2971
KEYS * = 2970 (1 trailing newline)
```

按前缀分组:
- **celery-task-meta-***: **2961** (99.7% — Celery default backend 累积未清理)
- **qm:***: 7 streams (StreamBus)
- **qmt:***: 1 stream
- **portfolio:***: **0** ⚠️
- **market:***: **0** ⚠️

---

## 2. Q5.1 + Q5.4 8 streams 健康度 (实测)

```bash
redis-cli KEYS "qm*"  # 7 hits
redis-cli KEYS "qmt*"  # 1 hit
```

| Key | TYPE | TTL | 状态 |
|---|---|---|---|
| qm:order:routed | **stream** | -1 (持久) | ✅ alive |
| qm:quality:alert | none | -2 (expired) | 🔴 dead key |
| qm:signal:generated | none | -2 | 🔴 dead key |
| qm:ai:monitoring | none | -2 | 🔴 dead key |
| qm:qmt:status | none | -2 | 🔴 dead key |
| qm:health:check_result | none | -2 | 🔴 dead key |
| qm:execution:order_filled | none | -2 | 🔴 dead key |
| qmt:connection_status | none | -2 | 🔴 dead key |

**TYPE=none + TTL=-2 含义**: key 已 expired, redis-cli KEYS 返回是 ghost (扫描时点 stale)

→ **F-D3B-6 (P1)**: 仅 1/8 stream alive (`qm:order:routed`). 文档 (CLAUDE.md L31, "Redis Streams `qm:{domain}:{event_type}`, StreamBus 模块") + memory ("StreamBus 10 streams") 与实测严重漂移.

→ **跨维度联动 D3-A Step 5 spike**: D3-A Step 5 实测 outbox publisher 30s 周期 publish 到 Redis Streams `qm:risk:*`, **0 production consumer**. 实测 8 streams 中**也无 qm:risk:*** — 进一步证 risk events outbox publish **没真到达 streams**, 或 publish 的 stream 名是别的 (e.g. `risk_event_log` 直接走 DB outbox table 不走 Redis stream).

---

## 3. Q5.2 portfolio:current cache (实测)

```bash
redis-cli KEYS "portfolio:*" → 0 hits
```

→ **F-D3B-7 (P0 cross-link D3-A Step 4 T0-16)**: portfolio:current cache **不存在** (vs D3-A Step 4 推断 26 天 stale). 实际:
- qmt_data_service 4-04 起断连 (Step 4 实测)
- 26 天 silent skip 持仓同步 → portfolio:current 没被更新
- key TTL 到期 expired → DBSIZE 不算 + KEYS 不返
- 任何 QMTClient 读 portfolio:current 时 key 不存在 → 触发 fallback 路径 (绕 cache 直读 DB position_snapshot 4-28 stale snapshot)

→ DB 4-28 19 股 stale snapshot 反而是 "fallback 真相" 而非 "Redis cache 推算". Step 4 spike root cause L4 应改: "DB 4-28 19 股 = QMTClient fallback 直读 stale position_snapshot, 不是 stale Redis cache"

---

## 4. Q5.3 其他 keys (LL-063 三问法)

**celery-task-meta-* 2961 个**:
- 用途: Celery default backend 存 task result (默认 24h TTL)
- 命名: `celery-task-meta-<task_uuid>`
- 死 key 候选: 任务 24h 后 key TTL 到期 → 自然清理 (Redis 内置)
- 但实测 2961 累积 — 可能 Celery 配置 result_backend_persistent 或 TTL 比 24h 长

**F-D3B-8 (P3)**: celery-task-meta backlog 2961 keys 累积. 不是 P0 (Redis 自然清, DBSIZE 不影响 prod), 但建议 D3-C 调查 result_backend TTL 配置 + 可能加 cleanup hook.

---

## 5. Q5.4 用例 vs 文档 align

CLAUDE.md L31 "Redis Streams (`qm:{domain}:{event_type}`), StreamBus 模块" + L249 "QMT Data Service 60s 同步: 持仓→portfolio:current (Hash), 资产→portfolio:nav (JSON), 价格→market:latest:{code} (TTL=90s)"

**实测推翻**:
- portfolio:current = 0 keys (qmt_data_service 26 天断连导致 SET 0 次, 老 key TTL 到期消失)
- portfolio:nav = 0 keys (同源)
- market:latest:* = 0 keys (同源)
- StreamBus "10 streams" 实测 1 alive

→ **F-D3B-9 (P1)**: CLAUDE.md L249 "QMT Data Service 60s 同步" 描述与实测 26 天 0 SET 严重漂移. 与 D3-A Step 4 T0-16 同源 (qmt_data_service silent skip 26 天).

---

## 6. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3B-6 | StreamBus 8 streams 7/8 expired (TTL=-2), 仅 qm:order:routed alive | P1 |
| F-D3B-7 | portfolio:current cache 不存在 (D3-A Step 4 root cause L4 应修订: DB 4-28 stale 是 QMTClient fallback 直读 DB, 不是 stale Redis cache) | **P0 cross-link** |
| F-D3B-8 | celery-task-meta-* 2961 keys 累积, result_backend TTL 配置待调查 | P3 |
| F-D3B-9 | CLAUDE.md L249 "QMT Data Service 60s 同步" 与实测 26 天 0 SET 漂移 (T0-16 同源) | P1 |

---

## 7. 处置建议

- **D3-A Step 4 spike 修订**: 加 "L4 修订" 段, root cause 改为 "QMTClient fallback 直读 DB position_snapshot 4-28 stale, 不是 Redis cache stale" (本 D3-B 副产品发现, F-D3B-7)
- **F-D3B-6/9 留 D3-C 整合**: CLAUDE.md L249 + StreamBus 10→1 alive 描述更新
- **F-D3B-8 留 Wave 5+**: Celery result_backend TTL 调优 (低优先级)
