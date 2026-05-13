# ADR-055: V3 §S7 L3 动态阈值 DynamicThresholdEngine 架构决议

**Status**: committed (2026-05-11, V3 Tier A S7 closure)
**Source**: V3 governance batch closure S7 sub-PR 19
**关联 ADR**: ADR-022/054
**关联 LL**: LL-145/146/147/148/149

## §1 背景

V3 §6 L3 动态阈值层: 实时市场状态 + 个股状态 + 行业联动反馈到 L1 阈值, 让 detection 不是静态死规则.

## §2 Decision 1: 3 级 MarketState (Calm/Stress/Crisis)

**决议**: MarketIndicators → assess_market_state() → 3 级输出:
- Calm: default (1.0x market multiplier)
- Stress: regime=Bear or 大盘≤-2% or 跌停>50 (0.8x)
- Crisis: 大盘≤-5% or 跌停>200 (0.5x, 最高优先)

**论据**: Crisis 先于 Stress 检查, 阈值 0.5/0.8/1.0 对应 V3 §6.1 规范.

## §3 Decision 2: StockMultiplier 乘法叠加

**决议**: 个股阈值调整采用乘法叠加 (非 max/min/加权):
- High beta (>1.5): ×1.2
- Low liquidity (<20%): ×1.5
- High ATR (>5%): ×1.5
- 综合: 1.0 × (1.2 if high beta) × (1.5 if low liq) × (1.5 if high ATR)

**论据**: 各因子独立产生效果, 乘法自然表达叠加关系. 最大值 2.7x (三者全触发).

## §4 Decision 3: Industry adjustment for CorrelatedDrop

**决议**: 同行业 ≥2 股 + 行业 day ≤-3% → CorrelatedDrop min_count 3→2.

**论据**: V3 §6.3 规范, 防 4-29 多股同跌场景. 仅第一个满足条件的行业触发调整.

## §5 Decision 4: ThresholdCache 双层 (InMemory + Redis)

**决议**: 
- ThresholdCache Protocol: get/set_batch/flush
- InMemoryThresholdCache: dict-backed, 测试/fallback
- RedisThresholdCache: pipeline SETEX, 5min TTL, lazy connect, 首次失败后停止重试

**论据**: 
1. Redis 低延迟适合 L1 per-tick 读取
2. 首次连接失败后停止重试 — 反 per-tick 2s 阻塞
3. InMemory 提供无 Redis 环境 fallback

## §6 Decision 5: S7→S5 wire via update_threshold()

**决议**: RealtimeRiskEngine.set_threshold_cache() + 规则.update_threshold():
- Engine 在每次 on_tick/on_5min/on_15min 前调用 _apply_dynamic_thresholds()
- 规则暴露 update_threshold(new_value) 方法 (不改变 RiskRule ABC)
- CorrelatedDrop 额外暴露 update_min_count()

**论据**: 
1. 不改 RiskRule ABC (向后兼容)
2. DynamicThresholdEngine 输出直接注入规则, 无中间层
3. 没有 cache 时规则使用 __init__ threshold (fallback 静态 .env)

## §7 已知限制

1. northbound_flow 字段未接入 assess_market_state (留 L2 集成)
2. MarketRegimeService (L2 Bull/Bear) 是 Tier B scope, 当前 regime 字段为 stub
3. Redis 不可用时 thresholds_cache 为 None, 规则回退到静态 .env
4. DDL dynamic_threshold_adjustments 仅记录 audit log, 不参与运行时决策

## §8 Amendment 1: Production Beat wire + reviewer P1+P2 fixes (audit fix PR #306, 2026-05-13)

**触发**: User flagged S5/S6/S7 initial closure (sub-PR 19 by deepseek) had Plan §A acceptance gaps. Audit re-verification found 1 P0 + 2 P1 gaps in S5/S7. PR #306 closes all 3.

### §8.1 P0 fix: S7 Celery Beat 5min wire (was completely unwired)

**Gap**: Plan §A S7 acceptance line 150 cites `"dynamic threshold 5min Beat (risk-dynamic-threshold-5min)"`. ADR-055 §5/§6 decided ThresholdCache + S7→S5 wire patterns, but **no Celery task module and no Beat schedule entry existed**. Production `thresholds_cache` would never be populated; S7→S5 reverse loop only worked in unit tests.

**Fix** (PR #306, commit `5b1aba0` → squash-merged as `c55662e`):
- NEW `backend/app/tasks/dynamic_threshold_tasks.py` — `compute_dynamic_thresholds()` Celery task with module-level singleton `_engine` / `_cache`
- EDIT `backend/app/tasks/beat_schedule.py` — `risk-dynamic-threshold-5min` entry, `crontab(minute="*/5", hour="9-14", day_of_week="1-5")` Asia/Shanghai, `expires=240s`
- EDIT `backend/app/tasks/celery_app.py` — module added to `imports` list

### §8.2 P1+P2 reviewer-driven robustness (post-审查 commit `9593d75`)

| # | Severity | Fix |
|---|----------|-----|
| P1-1 | TTL race | `ttl_seconds` 300 → 360 (Beat cadence + 20% headroom; closes expiry-just-before-next-Beat race) |
| P1-2 | Silent cache failure | `RedisThresholdCache.set_batch` re-raises on `pipe.execute()` failure (silent absorb removed); task body propagates → Celery retry. Redis-unavailable path (`_ensure_redis` False) still silent no-op (intentional fallback) |
| P1-4 | xtquant API verify | TODO comment + iron law 1 citation added at `subscriber.py:198` `unsubscribe_quote(seq)` call. Production activation must verify against installed xtquant SDK version |
| P2-5 | Provider rate-limit | `_provider_error_count` on `XtQuantTickSubscriber`; first failure + every 100th consecutive → ERROR (operator-visible); reset on success |
| P2-6 | Stub invisibility | One-time `_stub_warned` WARNING on first `compute_dynamic_thresholds` fire — surfaces "real CSI300/holdings wire deferred to S10" posture in production logs |

### §8.3 Deferred to follow-up sub-PR

- **Reviewer P1-3** (`cache.py:105` `_connected` bool semantically inverted on failure path) — pre-existing in cache.py; out of PR #306 scope. Filed for follow-up rename `_connect_attempted` + restore `_connected` as true success flag.
- **Real production wire of `_build_market_indicators` / `_build_stock_metrics`** — stub helpers return all-None / empty dict; engine returns CALM regardless. Real CSI300/limit_down/ATR/beta/positions wire deferred to S10 paper-mode 5d dry-run period per Plan §A S10 acceptance + LL-141 4-step sustainability sediment.

**Test delta**: PR #306 net 264/264 PASS (was 259 pre-fix, +5 new tests). Pre-push smoke 55 PASS. Ruff clean.

**关联**: PR #306 / LL-149 Part 2 / 铁律 1 / 33 / 44 X9 / Plan §A S7 amendment
