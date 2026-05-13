# ADR-029: L1 Realtime Risk Engine + xtquant subscribe_quote Integration + 9 RealtimeRiskRule

**Status**: Committed (reserved 2026-04-29 + formal promote 2026-05-13 via T1.5b-2 Plan v0.2 §A T1.5 Acceptance item (4) closure)
**Date**: 2026-04-29 (decision) / 2026-05-11 (S5 sub-PR 5a/5b/5c implementation closure) / 2026-05-13 (formal promote)
**Decider**: User 4-29 决议 + V3 §S5 sub-PR 17-19 closure (sustained ADR-054)
**Related**: ADR-019 (V3 vision 5+1 层) / ADR-022 (反 silent overwrite) / ADR-027 (L4 STAGED + 反向决策权 + 跌停 fallback) / ADR-054 (V3 §S5 L1 实时化 RealtimeRiskEngine sub-PR 15-17 closure) / ADR-055 (V3 §S7 L3 动态阈值 + S7→S5 wire back) / ADR-056 (V3 §S8 8a L4 STAGED 状态机) / ADR-064 (Plan v0.2 5 决议 lock) / V3_DESIGN §4 (SSOT) + §11.1 row 6 (SSOT)

---

## §1 Context

**Origin (2026-04-29 PT 暂停清仓事件 + 现 PMSRule v1 静态阈值审计)**:

- PMSRule v1 14:30 daily Beat fire only — 真账户 4-29 跌停 detect latency ~6h (远超 V3 §13.1 SLA P99 < 5s baseline)
- PMSRule v1 静态阈值 (PMS_LEVEL1_DROP/LEVEL2_DROP/LEVEL3_DROP) — 0 实时 tick-level adjustment, 0 regime aware
- PMSRule v1 0 risk_event_log INSERT contract (沿用 deprecated path post ADR-010, PR #34 停 Beat + 去重)
- **痛点 surface**: 现 daily-cron-based 风控 不适应 tick-level events (跌停瞬间需 5s P99 detection)

**Why L1 实时化 (vs incremental PMSRule v1 patch)**:

- 5s P99 detection latency 不能用 Celery daily Beat 达成, 需 tick-level event-driven engine
- xtquant `subscribe_quote` API 现有 (国金 miniQMT integration, sustained CLAUDE.md xtquant rules)
- 多 rule (9 RealtimeRiskRule) 复杂度需要 cadence-based engine 分发 + Protocol abstraction
- RiskContext 多源数据 (sentiment / fundamental / regime / market_state / similar_lessons) 需要 inject — PMSRule v1 0 context contract

---

## §2 Decision

### §2.1 Sub-decision #1: RealtimeRiskEngine cadence-based dispatch

**Module path**: `backend/qm_platform/risk/realtime/engine.py` (sustained ADR-031 path 决议)

**Architecture**:
- `RealtimeRiskEngine` 主类 — 单例 production engine + 单例 cache (sustained ADR-055 dynamic threshold cache + S7→S5 wire back)
- Subscribes xtquant tick stream via `XtQuantTickSubscriber` (sustained ADR-031 §6 lazy import + QMTClient Redis 缓存 60s)
- Per-rule cadence dispatch: `tick / 5min / 15min / daily` cadence per `RiskRule.cadence` attribute
- RiskContext inject: sentiment_24h (dict) / fundamental (8 维 JSONB) / regime (Bull/Bear/Neutral/Transitioning) / market_state (Calm/Stress/Crisis) / similar_lessons (RAG top 5, Tier B)
- Threshold dynamic adjustment: per L3 DynamicThresholdEngine S7→S5 wire back (sustained ADR-055 + risk-dynamic-threshold-5min Beat schedule)

**Rule abstract** (V3 §11.2 sustained):

```python
class RiskRule(ABC):
    rule_id: str
    priority: str  # P0/P1/P2/P3
    cadence: str   # tick/5min/15min/daily

    @abstractmethod
    def evaluate(self, positions, market_data, context: RiskContext, thresholds: dict) -> list[RiskEvent]:
        ...
```

### §2.2 Sub-decision #2: 10 RealtimeRiskRule (V3 §4.3 + post-S9a TrailingStop addition cumulative)

**Production-ready 10 rules** (sustained ADR-054 S5 sub-PR 15+16 closure + S9a TrailingStop addition, post reviewer audit 2026-05-13 真值 verify 10 distinct classes in `backend/qm_platform/risk/rules/realtime/`):

| # | rule_id (class name) | priority | cadence | description |
|---|---|---|---|---|
| 1 | LimitDownDetection | P0 | tick | 跌停 detect (9.99%/10.00%/10.01% 主板 vs 科创 不同阈值) |
| 2 | NearLimitDown | P1 | tick | 接近跌停 (e.g. 9.4%/9.5%/9.6% 边缘) |
| 3 | RapidDrop5min | P1 | 5min | 5min 内 急跌 (default 5% threshold, adjustable per L3 regime) |
| 4 | RapidDrop15min | P2 | 15min | 15min 内 急跌 (default 7%) |
| 5 | GapDownOpen | P1 | daily | 开盘 gap down (-5%+) |
| 6 | VolumeSpike | P2 | 5min | 成交量 异常放大 (e.g. 5x avg, sentinel for crisis) |
| 7 | LiquidityCollapse | P0 | 5min | liquidity drop ratio (V3 §6.2 RT_LIQUIDITY_DROP_RATIO 配置) |
| 8 | IndustryConcentration | P1 | 5min | 持仓 N 股同行业, single-industry exposure 集中度 (V3 §6.3) |
| 9 | CorrelatedDrop | P1 | 5min | 多股 同时下跌 (0/1/2/3/4 股 4-6min 时间窗口, V3 §4.3 + V3 §15.2 unit test boundary) |
| 10 | TrailingStop | P1 | tick | 阶梯利润保护 (PMSRule v1 体例 sustained, V3 §7.3, sub-PR S9a `a1ac5f6` ADR-060) |

**Note on rule count**: V3 §4.3 设计稿 cite "9 RealtimeRiskRule (新增, 完整 enumerate)" 但 production 实施真值 = **10 rules** (S5 sub-PR 5a+5b cumulative + S9a TrailingStop addition cumulative). 9 → 10 transition due to S9a `a1ac5f6` TrailingStop sediment. ADR-054 cumulative cite "104 tests PASS" 仅覆盖 S5 scope (sub-PR 5a 45 + sub-PR 5b 43 + sub-PR 5c 16); S9a TrailingStop 加 68 tests via PR #311 (ADR-060 sediment). Cumulative 9-rule + TrailingStop test sum ≈ 172 tests.

**Sub-PR closure timeline** (commit hashes post-squash-merge verified 2026-05-13):
- S5 sub-PR 5a `9c52a4b` (per `git log --grep="sub-PR 5a"`): 5 rules implementation (LimitDownDetection, NearLimitDown, RapidDrop5min, RapidDrop15min, GapDownOpen) + 45 tests + DDL `risk_event_log` +4 columns
- S5 sub-PR 5b `44176e5` (per `git log --grep="sub-PR 5b"`): 4 remaining rules (VolumeSpike, LiquidityCollapse, IndustryConcentration, CorrelatedDrop) + 43 tests
- S5 sub-PR 5c `a656176`: RiskBacktestAdapter 3-Protocol stub (BrokerProtocol + NotifierProtocol + PriceReaderProtocol) + 16 tests (T1.5 prereq, full impl 留 Tier B TB-1 per Plan v0.2)
- S9a sub-PR PR #311 squash `a1ac5f6`: V3 §7.2 BatchedPlanner + V3 §7.3 TrailingStop (10th rule sediment) + 68 tests (ADR-060)

### §2.3 Sub-decision #3: xtquant subscribe_quote 接入

**Module path**: `backend/qm_platform/risk/realtime/subscriber.py` + sustained `app/core/xtquant_path.py` + `app/core/qmt_client.py` (CLAUDE.md xtquant rules)

**Architecture**:
- `XtQuantTickSubscriber`: lazy `import xtquant` (沿用 ADR-031 §6 + CLAUDE.md "xtquant 唯一允许 import 的生产入口 = scripts/qmt_data_service.py")
- subscribe_quote callback → tick event → RealtimeRiskEngine.dispatch(tick) → per-rule evaluate per cadence
- Heartbeat check: 5min 无 tick callback → degrade to 60s sync via QMTClient (V3 §14 #2 fail-mode injection)
- Subscribe pruning: `_subscribe_ids` track + `stop()` 真调 `xtdata.unsubscribe_quote(seq)` (sustained ADR-055 audit-fix S5 P1 fix)
- Avg volume provider: injectable `avg_volume_provider` (default None safe stub, sustained ADR-055 audit-fix S5 P1)

### §2.4 Sub-decision #4: RiskContext multi-source inject contract

**Tier A (现) RiskContext fields** (V3 §11.2):
- `sentiment_24h: dict[str, float]` — symbol -> sentiment score (Tier A minimal, sustained ADR-053 S4 minimal scope)
- `fundamental: dict[str, dict]` — symbol -> 8 维 JSONB (Tier A minimal scope via FundamentalContextService)
- `regime: str` — Bull/Bear/Neutral/Transitioning (Tier B MarketRegimeService, Tier A 静态 "Neutral" stub)
- `market_state: str` — Calm/Stress/Crisis (Tier A via L3 DynamicThresholdEngine 3 级 state)
- `similar_lessons: list[dict]` — RAG top 5 (Tier B RiskMemoryRAG, Tier A empty stub)

**Tier B 扩展**: similar_lessons via RiskMemoryRAG (pgvector + BGE-M3, sustained Plan v0.2 TB-3 + ADR-068 candidate)

### §2.5 Sub-decision #5: Performance + SLA

**V3 §13.1 SLA sustained**: L1 detection latency P99 < 5s (跌停后 5s 内 alert)

**Measurement**: tick callback → risk_event_log INSERT timing (per ADR-054 + S5 sub-PR closure tests)

**Servy service**: `QuantMind-RiskRealtime` (新增 per V3 §12.4): Celery solo pool, 订阅 xtquant tick stream

**Servy restart contract** (post-merge ops 铁律 44 X9): S5 sub-PR closure 后 require Servy QuantMind-RiskRealtime restart (sustained LL-141 4-step + ADR-055 amendment 1 体例)

---

## §3 Consequences

### §3.1 Tier A S5 closure 实施真值落地

post-S5 sub-PR 5a + 5b + 5c (+ S9a TrailingStop addition) cumulative:
- **10 RealtimeRiskRule 全 production-ready** (ADR-054 S5 scope 9 rules + ADR-060 S9a TrailingStop 10th rule, 真值 verify per `backend/qm_platform/risk/rules/realtime/` directory 10 distinct class files 2026-05-13 reviewer audit)
- **104 tests (S5 scope) + 68 tests (S9a scope) = 172 tests cumulative** (sustained ADR-054 S5 cite + ADR-060 S9a cite, cumulative for 10-rule scope)
- RiskBacktestAdapter stub 留 Tier B TB-1 full impl (sustained Plan v0.2 §A TB-1 + ADR-066 candidate)
- xtquant subscribe_quote 接入 lazy import 体例 sustained (CLAUDE.md xtquant rules + ADR-031 §6)
- Servy QuantMind-RiskRealtime + Celery solo pool integration 留 production deploy post Gate A formal close (T1.5 cycle)

### §3.2 5 维 architectural gap closure — Detection latency 部分

- PMSRule v1 14:30 daily Beat fire only → V3 L1 tick-level 5s P99 SLA detection (sustained V3 §13.1)
- 5 维 gap 中 1/5 closure (detection latency), 其余 4 维 (context-blind / decision binary / sentiment / lesson) 通过其他 ADR (ADR-027/028 + ADR-053/054/055 cumulative) 闭环

### §3.3 Tier B TB-1 RiskBacktestAdapter prereq

post-ADR-029 sediment + S5 sub-PR 5c stub `a656176` 140 行 base, Tier B TB-1 (Plan v0.2 §A) full impl prereq 满足:
- 9 RealtimeRiskRule 全 production-ready (本 ADR)
- RiskBacktestAdapter stub Protocol contract sediment (sub-PR 5c + Plan v0.2 §A TB-1 row)
- 2 关键窗口 historical replay (D3=b 决议 lock per ADR-064) 起手 prereq full satisfied

### §3.4 SLA enforcement empirical

- L1 detection latency P99 < 5s SLA baseline 留 Tier B TB-1 (RiskBacktestAdapter replay) + TB-5 (V3 §15.4 4 项 acceptance on replay path) verify
- Tier A 期内 production 环境无 5d wall-clock 真测 (sustained ADR-063 empty-system anti-pattern 反 trivial-pass)
- Tier B replay 等价 transferable path SLA verify (sustained Plan v0.2 §D post-ADR-063 transferable 体例)

### §3.5 Servy + Celery deployment 体例

- post-Tier A formal close + Tier B closure + 横切层 closure + cutover gate (Plan v0.4) 后, Servy QuantMind-RiskRealtime production deploy + LIVE_TRADING_DISABLED=false unlock (sustained 红线 5/5 + Plan v0.4 cutover scope)
- Tier A 期内 RealtimeRiskEngine + 9 rules production-ready 但 deploy paper-mode + 0 真账户 broker call sustained (LIVE_TRADING_DISABLED=true)

---

## §4 Cite

- V3_DESIGN §4 (L1 基础规则层 实时化升级)
- V3_DESIGN §4.3 (8 RealtimeRiskRule 新增 + 完整 enumerate, post-S9a +1 rule cumulative)
- V3_DESIGN §11.1 row 6 (RealtimeRiskEngine 模块)
- V3_DESIGN §11.2 (RiskRule 接口 sustained)
- V3_DESIGN §13.1 (5 SLA — L1 detection latency P99 < 5s)
- V3_DESIGN §18.1 row 9 (本 ADR-029 reserve)
- backend/qm_platform/risk/realtime/engine.py + subscriber.py (实施 SSOT)
- backend/qm_platform/risk/rules/realtime/*.py (9 rules implementation SSOT)
- backend/qm_platform/risk/backtest_adapter.py (sub-PR 5c stub `a656176`, T1.5 prereq sustained)
- app/core/xtquant_path.py + app/core/qmt_client.py (CLAUDE.md xtquant rules)
- scripts/qmt_data_service.py (唯一允许 import xtquant 的生产入口)
- 104 tests cumulative (S5 sub-PR 5a 45 + 5b 43 + 5c 16, sustained ADR-054)

### Related Decisions

- ADR-019 (V3 vision 5+1 层) — V3 §0 设计起点
- ADR-022 (反 silent overwrite + 反 retroactive content edit) — V3 文档治理 pattern sustained
- ADR-027 (L4 STAGED + 反向决策权 + 跌停 fallback) — V3 §7 L4 决议体例 sustained
- ADR-031 (S2 LiteLLMRouter implementation path) — 本 ADR §2.3 xtquant lazy import 体例 引用
- ADR-054 (V3 §S5 L1 实时化 RealtimeRiskEngine sub-PR 15-17 closure) — 本 ADR §2.2 全 9 rules closure ADR 实施真值落地
- ADR-055 (V3 §S7 L3 动态阈值 + S7→S5 wire back) — 本 ADR §2.4 RiskContext market_state inject 来源
- ADR-056 (V3 §S8 8a L4 STAGED 状态机) — 本 ADR §2.4 RiskContext decision 后置 link
- ADR-060 (V3 §7.2 BatchedPlanner + §7.3 TrailingStop) — 本 ADR §2.2 9th rule sediment
- ADR-063 (Gate A item 2 ⏭ DEFERRED + Tier B replay 真测路径) — 本 ADR §3.4 SLA verify path sustained
- ADR-064 (Plan v0.2 5 决议 lock) — Tier B TB-1 RiskBacktestAdapter full impl 决议
