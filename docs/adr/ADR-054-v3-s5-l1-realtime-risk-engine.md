# ADR-054: V3 §S5 L1 实时化 RealtimeRiskEngine 架构决议

**Status**: committed (2026-05-11, V3 Tier A S5 closure)
**Source**: V3 governance batch closure S5 sub-PR 15-17
**关联 ADR**: ADR-022/031/047/048/049/050/053
**关联 LL**: LL-145/146/147/148/149

## §1 背景

V3 §4 L1 基础规则层实时化是 4-29 痛点 fix 核心。传统 PlatformRiskEngine 是 Beat 驱动 (5min/14:30), 无法做秒级 tick-based 跌停检测。需要新建 RealtimeRiskEngine 实现 xtquant subscribe_quote → tick → rule evaluation 的实时链路。

## §2 Decision 1: Cadence-based engine (tick/5min/15min)

**决议**: RealtimeRiskEngine 按 cadence 分组注册规则:
- `register(rule, cadence="tick")`: tick 级 (每 tick 触发)
- `register(rule, cadence="5min")`: 5min 级 (每 5min 触发)
- `register(rule, cadence="15min")`: 15min 级 (每 15min 触发)

**论据**:
1. 不同规则有不同评估频率需求 (LimitDownDetection 每 tick, RapidDrop5min 每 5min)
2. Cadence-based 分组避免每 tick 评估所有规则 (节省 CPU)
3. Per-rule crash isolation: 单规则异常不阻塞同级其他规则

**替代方案**: 
- A) 每 tick 评估所有规则 → CPU 浪费
- B) RealtimeRiskEngine 继承 PlatformRiskEngine → 违反单一职责

## §3 Decision 2: RiskContext.realtime 扩展 (backward compatible)

**决议**: `RiskContext` 加 `realtime: dict[str, dict[str, Any]] | None = field(default=None)`. None 默认值确保所有现有规则 0 改动.

**论据**:
1. 不改变 RiskRule ABC 接口 (evaluate 签名不变)
2. Realtime 数据通过 context 注入, 规则按需读取 (铁律 31: 规则纯计算)
3. Dict 结构扩展灵活: {code: {prev_close, open_price, price_5min_ago, ...}}

## §4 Decision 3: XtQuantTickSubscriber lazy import

**决议**: xtquant 不在模块 import 时加载, 首次 subscribe_quote 时才 import (铁律 31).

**论据**:
1. 非 QMT 环境 (测试/CI) 不依赖 xtquant 也能 import 模块
2. Rolling window 维护在 subscriber 内, get_current_realtime() 提供标准化 dict

## §5 Decision 4: RiskBacktestAdapter 三 Protocol 桩

**决议**: RiskBacktestAdapter 单类实现 BrokerProtocol + NotifierProtocol + PriceReaderProtocol:
- sell() → stub result (0 filled, 0 broker call)
- send() → 内存记录 (0 DingTalk push)
- get_prices() → 注入字典 (0 Redis)

**论据**: S10 paper-mode 5d dry-run 需要 0 副作用的运行环境. T1.5 扩展时替换为完整 12 年 counterfactual replay adapter.

## §6 Decision 5: 9 RealtimeRiskRule (8 V3 §4.3 + 1 扩展)

**决议**: 实现 9 条实时规则, 比 V3 §4.3 的 8 条多 1 条 (LiquidityCollapse 流动性枯竭).

**分类**:
- P0 tick: LimitDownDetection, NearLimitDown, GapDownOpen, CorrelatedDrop
- P1 5min/15min: RapidDrop5min, RapidDrop15min, VolumeSpike, LiquidityCollapse
- P2 15min: IndustryConcentration

## §7 已知限制

1. avg_daily_volume 和 industry 字段需外部 enrichment (当前 XtQuantTickSubscriber 不提供, VolumeSpike/LiquidityCollapse/IndustryConcentration silently skip 或无数据时触发)
2. L1 detection P99<5s SLA baseline deferred to S10 paper-mode 5d
3. GapDownOpen cadence 实际为 tick (pre_market cadence 未实现), 文档标注为 pre_market
