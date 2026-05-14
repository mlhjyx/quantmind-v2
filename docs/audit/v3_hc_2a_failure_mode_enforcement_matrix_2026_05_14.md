# V3 §14 失败模式 Enforcement Matrix — HC-2a (横切层 Gate D item 2)

> **本文件 = V3 横切层 Plan v0.3 §A HC-2a deliverable** — V3 §14 失败模式表 15 模式 enforcement matrix audit + gap list. HC-2a = verify-heavy audit doc (每 mode `file:line` cite); gap list 驱动 HC-2b (缺失 detection/degrade path wire + unit tests); 灾备演练 synthetic injection 留 HC-2c.
>
> **Status**: HC-2a sediment (docs-only 直 push 铁律 42). Sprint HC-2 = chunked 3 sub-PR (HC-2a 本 + HC-2b gap wire + HC-2c 灾备演练 + ADR-074).
>
> **Date**: 2026-05-14 (Session 53+27)
>
> **关联**: Plan v0.3 §A HC-2 row + §H Finding #1 (15 vs 12 真值差异) / V3 §14 失败模式表 (spec authoritative source, line 1445-1461) / ADR-073 (HC-1 元监控 alert-on-alert closure — 元告警 column 真值依赖 HC-1 5-rule layer) / ADR-074 reserved (HC-2 closure) / 铁律 36 (precondition 核) / 铁律 45 (cite source fresh verify)

---

## §1 Context + Methodology

**Scope**: V3 §14 失败模式表 enumerate **15 模式** (Plan v0.3 §H Finding #1 真值 — Constitution §L10.4 checklist cite "12 项" 是 V3 §14 表演进前 stale cite; mode 13 BGE-M3 OOM / mode 14 RiskReflector V4-Pro 失败 / mode 15 LIVE_TRADING_DISABLED 双锁失效 是表演进新增). HC-2 enforce 全 15 superset (反 silent skip mode 13/14/15).

**每 mode audit 5 attribute** (V3 §14 表列):
1. **触发条件** — failure 触发条件代码定义/检查点
2. **检测 mechanism** — detection 代码
3. **降级路径** — fallback/degrade 行为代码
4. **恢复条件** — recovery 路径代码
5. **元告警 flag** — 是否 raise 元告警 (HC-1 alert-on-alert layer wire 真值)

**Status 分级**: ✅ EXISTS (`file:line` + 实现) / 🟡 PARTIAL (`file:line` + 缺口) / ❌ MISSING (gap — 驱动 HC-2b).

**Methodology + cite 可信度声明** (铁律 28 honest disclosure): 起手 3 个 Explore subagent 并行 audit (mode 1-5 / 6-10 / 11-15) → **agent #2 (mode 6-10) 自承可能用 stale indexed content, 实测其 `file:line` 系统性漂移** (cite line 12 的常量实际在 line 41; cite line 20-35 的代码实际在 line 64-273). 故 **CC 主进程 self-verify 全部 load-bearing cite** — full read: `l4_sweep_tasks.py` / `tushare_api.py` / `news/pipeline.py` / `meta_alert_rules.py` / `meta_monitor_service.py` / `db.py` / `dynamic_threshold/cache.py` / `realtime/engine.py` / `embedding_service.py`; targeted grep: `router.py` / `dingtalk_alert.py` / `config_guard.py` / `risk_reflector_tasks.py` / `batched_planner.py` / `live_trading_guard.py` 等. 本 matrix 的 `file:line` = CC self-verified 真值, NOT subagent raw output (sustained 铁律 45 + Plan v0.3 §B risk #1).

---

## §2 15-Mode Enforcement Matrix

### Mode 1 — LiteLLM cloud 全挂 (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | 🟡 PARTIAL | `qm_platform/llm/_internal/router.py:193-195` — LiteLLM Router `allowed_fails=3` / `cooldown_time=30` internal counting; **无 app 层显式 ">50% error rate" 判定** (spec 触发条件 = 失败率 > 50%) |
| 检测 | 🟡 PARTIAL | `router.py:368` `_is_fallback()` substring 检测 (actual_model vs primary alias) — 检测 "fallback 已发生", 非 "失败率窗口" |
| 降级路径 | ✅ EXISTS | `router.py:120` `FALLBACK_ALIAS="qwen3-local"` (Ollama 本地) + `router.py:196` LiteLLM `fallbacks` config chain |
| 恢复条件 | 🟡 PARTIAL | `router.py:195` `cooldown_time=30` — LiteLLM cooldown 后自动重试 primary; 无显式 "恢复" detection/log |
| 元告警 flag | ✅ EXISTS | `meta_alert_rules.py:77-109` `evaluate_litellm_failure_rate` + `meta_monitor_service.py:284-314` `_collect_litellm` 真查 `llm_call_log` (HC-1b real collector, 5min Beat cadence) |

### Mode 2 — xtquant subscribe_quote 断连 (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ❌ MISSING | `realtime/engine.py` — `RealtimeRiskEngine` 无 tick-timestamp 追踪, 无 "5min 无 tick" 触发条件定义 |
| 检测 | ❌ MISSING | `realtime/engine.py:137-157` `on_tick`/`on_5min_beat`/`on_15min_beat` — 无 heartbeat staleness 检查 |
| 降级路径 | ❌ MISSING | 无 "degrade 到 60s sync" 代码 (engine 无 fallback 到 static path) |
| 恢复条件 | ❌ MISSING | 无重连 detection |
| 元告警 flag | 🟡 PARTIAL | `meta_alert_rules.py:37-74` `evaluate_l1_heartbeat` rule EXISTS, 但 `meta_monitor_service.py:347-365` `_collect_l1_heartbeat` = **no-signal (DEFERRED per ADR-073 D3** — 无 production XtQuantTickSubscriber runner, instrument 永不触发) |

### Mode 3 — PG OOM / lock (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | 🟡 PARTIAL | `app/services/db.py:104` `_active_count >= _MAX_CONNECTIONS(15)` — client-side count, **非 PG-side `pg_stat_activity > 50 idle in tx`** (spec 触发条件) |
| 检测 | 🟡 PARTIAL | `db.py:104-109` — `_active_count` 达上限仅 `logger.warning`, 不查 `pg_stat_activity`, 不检测 lock contention |
| 降级路径 | ❌ MISSING | 无 "risk_event_log 仅读 + INSERT to memory cache + 重试" degrade — `get_sync_conn` 达上限仍 `psycopg2.connect()` (仅 warn) |
| 恢复条件 | 🟡 PARTIAL | `db.py:48-79` `_TrackedConnection.close()` + `__del__` finalizer counter decrement — counter 恢复, 非真 PG 资源恢复检测 |
| 元告警 flag | ❌ MISSING | 无 PG 健康 meta-alert rule (HC-1 5-rule 不含 PG) |

### Mode 4 — Redis 不可用 (spec 元告警 ✅ P1)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | 🟡 PARTIAL | `dynamic_threshold/cache.py:80-109` `_ensure_redis()` lazy 连接 — 首次 get/set 时探测, 无持续 health 监控 |
| 检测 | ✅ EXISTS | `cache.py:94-109` `_ensure_redis()` → `redis.ping()` (line 98), 异常捕获 + `_connect_attempted=True` (反 per-tick 2s 阻塞) |
| 降级路径 | ✅ EXISTS | `cache.py:39-65` `InMemoryThresholdCache` + `cache.py:111-113` `RedisThresholdCache.get()` Redis 不可用 returns None → caller fallback in-memory; `meta_monitor_service.py:434-440` News collector Redis error fail-soft |
| 恢复条件 | ❌ MISSING | `cache.py:87` docstring 真值: "Redis 恢复需进程重启" — 无自动 reconnect / health recheck |
| 元告警 flag | ❌ MISSING | 无 Redis 健康 meta-alert rule (HC-1 5-rule 不含 Redis) |

### Mode 5 — DingTalk webhook fail (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ✅ EXISTS | `dingtalk_alert.py:150` Step 4 真 POST; `:139-148` 无 webhook → reason="no_webhook" |
| 检测 | ✅ EXISTS | `dingtalk_alert.py:272-300` `_post_to_dingtalk` httpx POST (`:292`) + **retry 1 次** (注: spec 写 "retry 3 次", 实现 1 次 — 见 §4 divergence); `:163-165` `_record_push_outcome` 记 alert_dedup |
| 降级路径 | ✅ EXISTS | `meta_monitor_service.py:172-276` `_push_via_channel_chain` 主 DingTalk → 备 email → 极端 log-P0 (HC-1b2). 注: 此 channel chain 仅 **元告警** path; 一般 alert 的 email backup 不在此链 |
| 恢复条件 | ✅ EXISTS | `_post_to_dingtalk` retry + 元告警 next-tick (5min Beat) re-eval |
| 元告警 flag | ✅ EXISTS | `meta_alert_rules.py:112-144` `evaluate_dingtalk_push` + `meta_monitor_service.py:367-404` `_collect_dingtalk` 真查 `alert_dedup.last_push_ok` (HC-1b3 real collector) |

### Mode 6 — News 6 源全 timeout (spec 元告警 ⚠️ P1)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ✅ EXISTS | `qm_platform/news/pipeline.py:41` `DEFAULT_HARD_TIMEOUT_SECONDS=30.0` (V3 §3.1 line 329); `:146` `as_completed(timeout=hard_timeout_s)` |
| 检测 | ✅ EXISTS | `pipeline.py:186-193` `TimeoutError` 捕获 + `:159-166` early-return logic (`success_count >= early_return_threshold`) |
| 降级路径 | ✅ EXISTS | `pipeline.py:167-185` per-source `NewsFetchError` fail-soft (audit log + skip); 全源 fail → 空 list 返 (fail-open: alert 仍发, 仅缺 sentiment context) |
| 恢复条件 | 🟡 PARTIAL | 下一 News Beat cadence (`hour=3,7,11,15,19,23`) 自然重试; 无显式 "任 1 源恢复" detection |
| 元告警 flag | ✅ EXISTS | `meta_alert_rules.py:147-174` `evaluate_news_sources_timeout` + `meta_monitor_service.py:406-446` `_collect_news` 真读 Redis `qm:news:last_run_stats` (HC-1b3 real collector); `pipeline.py:200-233` `_last_run_stats` memo + `get_last_run_stats` |

### Mode 7 — Tushare API 限速 (spec 元告警 ⚠️ P2)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ✅ EXISTS | `app/data_fetcher/tushare_api.py:107-109` `is_rate_limit = any(kw in err_msg for kw in ("每分钟","频率","频次","limit","too many"))` |
| 检测 | ✅ EXISTS | `tushare_api.py:90-135` retry loop 内 `is_rate_limit` 判定 |
| 降级路径 | ✅ EXISTS | `tushare_api.py:112-113` rate-limit → 固定 60s 冷却; `:115` 非 rate-limit → 指数退避 `min(2**attempt, 300)`; `:127-133` max_retries 后 raise (downstream caller fallback) |
| 恢复条件 | ✅ EXISTS | `tushare_api.py:90-135` retry loop 60s/退避后 re-attempt (max 3) |
| 元告警 flag | ❌ MISSING | 无 Tushare rate-limit meta-alert rule (HC-1 5-rule 不含 Tushare) — spec ⚠️ P2 |

### Mode 8 — user 离线 (DingTalk 未读) (spec 元告警 ❌ 不元告警, 设计行为)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ✅ EXISTS | `app/tasks/l4_sweep_tasks.py:154-165` SELECT `execution_plans WHERE status='PENDING_CONFIRM' AND cancel_deadline < NOW()` |
| 检测 | ✅ EXISTS | `l4_sweep_tasks.py:64-73` `sweep_pending_confirm_plans` Celery Beat (`* 9-14 * * 1-5` Asia/Shanghai, 每 1min) |
| 降级路径 | ✅ EXISTS | `l4_sweep_tasks.py:182-193` race-safe UPDATE → `TIMEOUT_EXECUTED` + `:206-253` broker.sell wire (StagedExecutionService.execute_plan) — STAGED default 执行 (反向决策权) |
| 恢复条件 | ✅ EXISTS | user 重新上线 → webhook CONFIRM/CANCEL (race-safe UPDATE `WHERE status='PENDING_CONFIRM'` 互斥 `:188-190`) |
| 元告警 flag | ✅ EXISTS (设计正确) | spec = ❌ 不元告警 (30min auto-execute 是设计行为). 注: **>35min PENDING_CONFIRM = cancel_deadline 机制失效** 是另一回事 → `meta_alert_rules.py:177-216` `evaluate_staged_overdue` (HC-1) 覆盖此失效变体 (ADR-073 D1) |

### Mode 9 — 千股跌停极端 regime (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | 🟡 PARTIAL | Crisis = L3 regime state (enum 散落 `dynamic_threshold/engine.py` / `regime/default_indicators_provider.py` 等 14 file); **无显式 "大盘 -7% / 跌停家数 > 500" 硬阈值** 单点定义 |
| 检测 | 🟡 PARTIAL | L3 regime classification 检测 Crisis state (`market_regime_service.py` + regime engine) — 连续 regime 推断, 非离散 crisis 硬阈值 |
| 降级路径 | ✅ EXISTS | `qm_platform/risk/execution/batched_planner.py` (V3 §7.2 BatchedPlanner — Crisis regime → batched 平仓, 5min interval, batch 间 re-evaluation) |
| 恢复条件 | ✅ EXISTS | `batched_planner.py:8` batch 间重评估: 市场反弹 + alert 清除 → 停止后续 batch |
| 元告警 flag | ❌ MISSING | 无 Crisis regime meta-alert rule (HC-1 5-rule 不含 Crisis) — spec ✅ P0 |

### Mode 10 — 误触发 (高 false positive) (spec 元告警 ⚠️ P2)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ❌ MISSING | `qm_platform/risk/reflector/agent.py` — **无 "weekly 误报率 > 30%" 量化硬阈值**; RiskReflector 走 V4-Pro 定性反思 |
| 检测 | 🟡 PARTIAL | `reflector/agent.py:203-268` V4-Pro 5 维反思 (detection/threshold/action/context/strategy) — 定性 finding + candidates, 非 "30% rate" 量化触发 |
| 降级路径 | 🟡 PARTIAL | `reflector/agent.py:252-268` 每维 `candidates` list (阈值/action 调整建议) → caller 处理 (反思候选阈值调整 + user approve) |
| 恢复条件 | 🟡 PARTIAL | 下一 weekly reflection cycle; 精确 threshold re-tune 闭环未单点 verify |
| 元告警 flag | ❌ MISSING | 无 false-positive-rate meta-alert rule — spec ⚠️ P2 |

### Mode 11 — RealtimeRiskEngine crash (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ❌ MISSING | RealtimeRiskEngine 无 production runner (HC-1 + scripts grep 实证 — `scripts/` 0 `RealtimeRiskEngine` ref); 无 Servy service for it |
| 检测 | ❌ MISSING | 无 RealtimeRiskEngine 专属 Servy heartbeat (`pt_watchdog.py` 监控 PT heartbeat file, `qmt_data_service.py` 有 LL-081 heartbeat — 均非 RealtimeRiskEngine) |
| 降级路径 | ❌ MISSING | 无 "Servy auto-restart + 状态恢复 (从 risk_event_log)" — RealtimeRiskEngine 无 production Celery task |
| 恢复条件 | ❌ MISSING | 无 restart-success detection |
| 元告警 flag | 🟡 PARTIAL | `meta_alert_rules.py:37-74` `evaluate_l1_heartbeat` rule 可覆盖 crash 后 heartbeat stale, 但 `_collect_l1_heartbeat` no-signal (DEFERRED, 同 mode 2 — 共享 "无 production realtime runner" 根因) |

### Mode 12 — broker_qmt 接口故障 (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | 🟡 PARTIAL | spec = "sell 单 INSERT 但无 status 更新 / status 卡 EXECUTED 超 5min" — `l4_sweep_tasks.py` 处理 PENDING_CONFIRM 过期, **无 "EXECUTED stuck > 5min" 专属检测** |
| 检测 | 🟡 PARTIAL | `staged_execution_service.py` broker.sell outcome → EXECUTED/FAILED 持久化; 无独立 "卡 EXECUTED" sweep |
| 降级路径 | 🟡 PARTIAL | `l4_sweep_tasks.py:217-253` broker FAILED 状态持久化 + 结构化 log; **"沉淀到 reconciliation 队列 + push user 手工干预" 未单点 verify** |
| 恢复条件 | 🟡 PARTIAL | broker 恢复后 retry — Celery retry policy; 无显式 reconciliation 恢复闭环 |
| 元告警 flag | 🟡 PARTIAL | `evaluate_staged_overdue` 覆盖 PENDING_CONFIRM >35min, **非 spec mode 12 的 "EXECUTED stuck >5min"** — 检测语义不完全对齐 |

### Mode 13 — embedding model 故障 (BGE-M3 OOM) (spec 元告警 ⚠️ P2)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | 🟡 PARTIAL | `qm_platform/risk/memory/embedding_service.py:206-239` `encode()` — OOM 不显式 trap, 依赖 sentence-transformers 异常冒泡 |
| 检测 | ✅ EXISTS | `embedding_service.py:192-200` model load fail → `RiskMemoryError` (chained); `:233-239` encode fail → `RiskMemoryError`; `:255-262` dim mismatch → `RiskMemoryError` (fail-loud 铁律 33) |
| 降级路径 | 🟡 PARTIAL | `embedding_service.py` 仅 raise `RiskMemoryError` — spec "RAG retrieval 跳过 (alert 仍发, 仅缺 lessons)" 的 skip path 须在 RAG orchestration caller (rag.py/risk_memory_rag.py 当前路径不存在 — TB-3c rag service 状态待 HC-2b 核) |
| 恢复条件 | 🟡 PARTIAL | 下次 encode 时 model reload; 无显式 "重启 embedding service" 自动机制 |
| 元告警 flag | ❌ MISSING | 无 embedding 故障 meta-alert rule — spec ⚠️ P2 |

### Mode 14 — L5 RiskReflector V4-Pro 失败 (spec 元告警 ⚠️ P1)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ✅ EXISTS | `app/tasks/risk_reflector_tasks.py:475-476` `soft_time_limit=90` / `time_limit=180` (weekly task) |
| 检测 | ✅ EXISTS | `risk_reflector_tasks.py:475-476` Celery soft/hard time limit (90s graceful / 180s 强杀) |
| 降级路径 | 🟡 PARTIAL | spec = "重试一次 + 失败则跳过本周 + 元告警" — `risk_reflector_tasks.py:56` fail-loud propagate Celery retry, **无显式 "retry 一次后跳过本周" 逻辑**; 下周 crontab 是事实上的 retry |
| 恢复条件 | ✅ EXISTS | `risk_reflector_tasks.py:22` crontab Sunday 19:00 下周重跑 + `:501` `dedup_key` 防重复反思 |
| 元告警 flag | ❌ MISSING | 无 RiskReflector 失败 meta-alert rule — spec ⚠️ P1 **且 spec 降级路径明确写 "+ 元告警"** |

### Mode 15 — LIVE_TRADING_DISABLED 双锁失效 (spec 元告警 ✅ P0)

| attr | status | cite + 实现 |
|---|---|---|
| 触发条件 | ✅ EXISTS | `app/config.py:79-82` `LIVE_TRADING_DISABLED: bool = True` (默认 True fail-secure); `.env` 误改为 false 是触发条件 |
| 检测 | 🟡 PARTIAL | `app/security/live_trading_guard.py` `assert_live_trading_allowed` **per-broker-call guard** (单源 `settings.LIVE_TRADING_DISABLED` + 双因素 OVERRIDE) — 注: spec 写 "config_guard 启动 raise", 实现是 **call-time guard 非 startup raise**; `config_guard.py`/`auditor.py` grep 实证 **0 `LIVE_TRADING_DISABLED` 检查** (config_guard 仅校验 EXECUTION_MODE) — startup-time drift 检测缺失 (见 §4 divergence) |
| 降级路径 | ✅ EXISTS | `app/exceptions.py:15` `LIVE_TRADING_DISABLED=True` + OVERRIDE 双因素 不全 → raise (阻断 broker call); `engines/broker_qmt.py:412` 真金保护默认 |
| 恢复条件 | ✅ EXISTS | user 修 `.env` (双因素 OVERRIDE 显式设置) |
| 元告警 flag | 🟡 PARTIAL | call-time guard raise 阻断交易, **无主动 push 元告警** — spec "拒启动 + 元告警" 的 push 部分缺失 |

---

## §3 Gap List (驱动 HC-2b)

按严重度排序 — HC-2b wire 缺失 detection/degrade path + unit tests:

| # | mode | gap | 严重度 | HC-2b 候选 wire |
|---|---|---|---|---|
| G1 | mode 11 | RealtimeRiskEngine crash — 触发/检测/降级/恢复 全 MISSING (无 production runner) | P0 但**根因 = 无 production realtime runner**, 同 mode 2 | ⏭ **DEFER to Plan v0.4 cutover** (sustained ADR-073 D3 — instrument 永不触发; HC-2b 不 wire 不存在的源) |
| G2 | mode 2 | xtquant 断连 — 触发/检测/降级 全 MISSING (engine 无 heartbeat) | P0 但根因同 G1 | ⏭ **DEFER to Plan v0.4 cutover** (sustained ADR-073 D3) |
| G3 | mode 3 | PG OOM — 降级路径 MISSING (无 memory-cache fallback) + 检测 PARTIAL (无 `pg_stat_activity`) + 元告警 MISSING | P0 | 🟡 HC-2b 候选: `pg_stat_activity` 检测 + memory-cache degrade — **但范围大, 可能需 user 决议拆分** |
| G4 | mode 9 | Crisis regime — 触发条件无单点硬阈值 + 元告警 MISSING | P0 | 🟡 HC-2b 候选: Crisis 硬阈值单点化 + Crisis meta-alert rule |
| G5 | mode 14 | RiskReflector 失败 — 元告警 MISSING (spec 降级路径明确写 "+ 元告警") + 降级 PARTIAL (无显式 retry-once-skip) | P1 | ✅ HC-2b: RiskReflector 失败 meta-alert rule + retry-once-then-skip 逻辑 (体量小, clean) |
| G6 | mode 15 | LIVE_TRADING_DISABLED — startup-time drift 检测 MISSING (config_guard 0 检查) + 元告警 push MISSING | P0 (红线 enforcement) | ✅ HC-2b: config_guard LIVE_TRADING_DISABLED startup 校验 wire (双锁第 2 锁 startup gate) |
| G7 | mode 12 | broker 故障 — "EXECUTED stuck >5min" 专属检测 MISSING + reconciliation 队列未 verify | P0 | 🟡 HC-2b 候选: EXECUTED-stuck sweep + reconciliation 队列 |
| G8 | mode 4 | Redis 不可用 — 恢复条件 MISSING (需进程重启) + 元告警 MISSING | P1 | 🟡 HC-2b 候选: Redis auto-reconnect health recheck (轻量) |
| G9 | mode 1 | LiteLLM — 触发条件/检测 PARTIAL (无 app 层 ">50%" 判定, 靠 LiteLLM 内部) | P0 但**元告警层已补** (`evaluate_litellm_failure_rate` 真查 llm_call_log 即 app 层失败率判定) | ⚪ 低优先 — 元告警 layer 已提供 app 层失败率真值, app 层 detection 实质已覆盖 |
| G10 | mode 7 | Tushare rate-limit — 元告警 MISSING | P2 | ⚪ 低优先 (spec P2) — HC-2b 可选 |
| G11 | mode 13 | BGE-M3 — 降级路径 PARTIAL (RAG-skip caller 未 verify) + 元告警 MISSING | P2 | ⚪ 低优先 (spec P2) — HC-2b 先 verify rag orchestration caller 是否 catch RiskMemoryError |
| G12 | mode 10 | false-positive — 触发条件 MISSING (无 30% 量化阈值) + 元告警 MISSING | P2 | ⚪ 低优先 (spec P2) — RiskReflector 定性反思 ≈ 设计选择, 量化阈值是否必要留 HC-2b 决议 |

**HC-2b scope 预判** (sustained Constitution §L0.4 — 若超 baseline 1.5x → STOP + push user): G1/G2 DEFER (根因 = cutover scope); **G5 + G6 是 HC-2b clean core** (体量小, P0/P1, 红线相关); G3/G4/G7/G8 范围较大, HC-2b 起手 precondition 核后可能需 AskUserQuestion 拆分; G9-G12 低优先 (P2 或元告警层已实质覆盖). 真值: 15 mode 中 **5 fully-EXISTS (mode 5/6/7/8 + mode 1 元告警补)** / **大部分 PARTIAL** / **2 根因-DEFER (mode 2/11)**.

---

## §4 Spec-vs-Impl Divergences (铁律 28 报告)

起手 audit surface 的 spec 与实现差异 (NOT gap, 是 spec cite 漂移 / 实现演进 — 决议 record, Constitution §L10.4 amend 留 HC-4c batch closure 标注):

1. **mode 5 retry 次数**: V3 §14 表 spec "retry 3 次", 实现 `dingtalk_alert.py:11,279` = "retry 1 次". 实现演进真值 (sync httpx single-attempt + 1 retry); 元告警 channel chain (HC-1b2) 提供更强的 DingTalk→email→log-P0 兜底, retry 次数 less critical. **决议**: 不改实现 (channel chain 已是更优兜底); V3 §14 表 cite 留 HC-4c 标注 "retry 1 次 + channel fallback chain".
2. **mode 15 检测机制**: V3 §14 表 spec "config_guard 启动 raise", 实现 = `live_trading_guard.py` **per-broker-call guard** (call-time, 非 startup). Call-time guard 是 defense-at-mutation-point (更强), 但 **startup-time drift 检测确实缺失** (config_guard 0 `LIVE_TRADING_DISABLED` 校验) → G6 真 gap. **决议**: HC-2b wire config_guard startup 校验 (补 startup 锁), call-time guard 保留 (双层); V3 §14 表 cite 留 HC-4c 标注。
3. **Constitution §L10.4 / §0.1 footer "失败模式 12 项"**: V3 §14 表真值 15 模式 (Plan v0.3 §H Finding #1). 本 matrix enforce 全 15. **决议**: Constitution amend "12 → 15" 留 HC-4c batch closure 标注 (sustained ADR-022 反 retroactive content edit)。

---

## §5 元告警 column 真值小结 (HC-1 alert-on-alert layer 依赖)

HC-1 (ADR-073) wire 的 5-rule meta-alert layer 覆盖 15 mode 中的:
- ✅ **真覆盖 (real collector)**: mode 1 (LiteLLM `evaluate_litellm_failure_rate`) / mode 5 (DingTalk `evaluate_dingtalk_push`) / mode 6 (News `evaluate_news_sources_timeout`) / mode 8>35min 失效变体 (`evaluate_staged_overdue`)
- 🟡 **rule EXISTS 但 collector DEFERRED**: mode 2 + mode 11 (`evaluate_l1_heartbeat` — `_collect_l1_heartbeat` no-signal, ADR-073 D3 — 无 production realtime runner)
- ❌ **无 meta-alert rule**: mode 3 (PG) / mode 4 (Redis) / mode 7 (Tushare) / mode 9 (Crisis) / mode 10 (false-positive) / mode 13 (BGE-M3) / mode 14 (RiskReflector) — 其中 mode 14 spec 降级路径明确写 "+ 元告警" → G5 HC-2b core
- N/A: mode 12 (`evaluate_staged_overdue` 语义不完全对齐 — 见 G7) / mode 15 (call-time guard raise, 非 async meta-alert)

---

## §6 Cumulative cite footer

- **HC-2a deliverable**: 本 matrix doc (docs-only 直 push 铁律 42) — 15-mode enforcement matrix + 12-item gap list + 3 spec-impl divergence + 元告警 column 真值小结
- **HC-2 chunked 3 sub-PR**: HC-2a (本 — matrix + gap list) → HC-2b (gap wire G5/G6 core + G3/G4/G7/G8 precondition 核后可能拆分 + unit tests) → HC-2c (灾备演练 synthetic injection mode 1-12 + `docs/risk_reflections/disaster_drill/` sediment + ADR-074)
- **关联**: Plan v0.3 §A HC-2 row + §H Finding #1 / V3 §14 失败模式表 line 1445-1461 / ADR-073 (HC-1 元监控 closure — 元告警 column 依赖) / ADR-074 reserved (HC-2 closure) / 铁律 28 (发现即报告 — 3 divergence) / 铁律 36 (precondition 核) / 铁律 45 (cite fresh verify — agent #2 line-drift caught + CC self-verify)
- **5/5 红线 sustained**: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 — HC-2a = read-only audit, 0 code change / 0 broker / 0 .env / 0 DB mutation
