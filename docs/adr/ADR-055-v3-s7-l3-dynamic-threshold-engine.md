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
