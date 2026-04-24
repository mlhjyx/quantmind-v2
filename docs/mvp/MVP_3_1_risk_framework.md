# MVP 3.1 · Risk Framework

> **Wave**: 3 第 1 步 (Wave 3 启动 MVP, 所有其他 Wave 3 MVP 前置)
> **耗时**: **2-2.7 周** (批 0 spike 完成 Session 27 2026-04-24: CB 方案 C adapter 复用
> `check_circuit_breaker_sync`, 批 3 从 1030 行 async→sync 重写 → ~200 行 wrapper, 总耗时下修)
> **依赖**: MVP 1.1 Platform Skeleton ✅ / MVP 2.1 Data Framework ✅ / ADR-010 PMS Deprecation ✅ / **ADR-010 addendum CB feasibility ✅**
> **风险**: 中 (批 3 adapter 不触老状态机核心 1030 行; 过渡期零自动卖 1.5-3 周)
> **Scope 原则**: 统一规则引擎 + 实时数据源 + 直接执行 + 单表事件日志 (不做风控策略优化, 不动 PMS 阈值参数本身)
> **铁律**: 22 / 23 / 24 / 31 / 33 / 34 / 36 / 38 / 40

---

## 目标 (4 项)

1. **统一 Risk Engine** — `RiskRule` abstract + `RiskEngine` concrete + `PositionSource` protocol, 取代 5 个独立监控系统
2. **实时数据源** — QMT 实时持仓为 primary (非 DB snapshot), 消除 F28 T-1 滞后
3. **直接执行** — 触发即调 broker (sell), 不走 StreamBus 3 hops (F27 根治)
4. **统一事件日志** — `risk_event_log` 单表, 取代 position_monitor + intraday_monitor_log + circuit_breaker_log

## 非目标 (明确推后)

- ❌ L1/L2/L3 阈值调参 → 保留 v1.0 配置, 参数优化另议
- ❌ 新风控策略 (VaR / CVaR / stress test) → Wave 4 Observability 后评估
- ❌ 前端 /pms 页面改造 → 迁入完成后统一 /risk dashboard (Wave 4)
- ❌ Risk Engine 内循环调度优化 → MVP 3.0 Resource Orchestration 后评估

## 实施结构 (批 0 feasibility spike + 3 批分批落地)

```
批 0 ✅ 完成 (Session 27 2026-04-24): 批 3 CB 状态机 feasibility spike
├── 结论: 现 RiskRule/RiskContext 抽象**不适合**直接承载 CB L1-L4 完整状态机
│   (cross-invocation state / L4 human approval / action 非"sell" / 双向 escalate-recover)
├── 决策: **方案 C — Hybrid wrapper** CircuitBreakerRule 薄 adapter 复用
│   check_circuit_breaker_sync (L1349, 现成 sync API) → 不重写 1030 行 async 状态机
├── 影响: 批 3 工作量 ~500 行 → **~200 行**, 耗时 1-1.5 周 → **0.5-0.7 周**
└── 文档: docs/adr/ADR-010-addendum-cb-feasibility.md ✅

批 1 (~1 周): Framework core + PMS L1/L2/L3 迁入
├── backend/platform/risk/                       ⭐ NEW
│   ├── __init__.py                               统一导出
│   ├── interface.py                              RiskRule / RiskEngine / PositionSource / RiskContext / RiskEvent
│   ├── engine.py                                 PlatformRiskEngine concrete + _execute_sell 直调 broker
│   ├── sources/
│   │   ├── qmt_realtime.py                       QMTPositionSource (primary, 读 Redis portfolio:current)
│   │   └── db_snapshot.py                        DBPositionSource (fallback, 读 position_snapshot live)
│   └── rules/pms.py                              PMSLevel1Rule / PMSLevel2Rule / PMSLevel3Rule
├── backend/migrations/
│   ├── risk_event_log.sql                        ⭐ NEW (ADR-010 D4 schema)
│   └── risk_event_log_rollback.sql               配对
├── backend/app/tasks/daily_pipeline.py           ⚠️ pms_check task 改走 RiskEngine (保留 14:30 Beat)
└── backend/tests/
    ├── test_risk_engine.py                       ~15 unit
    ├── test_risk_rules_pms.py                    ~10 unit (每 Level 3 scenario: 触发/不触发/边界)
    └── smoke/test_mvp_3_1_risk_live.py           ⭐ NEW live smoke (模拟 L1 触发 → QMT sell → DB → 钉钉)

批 2 (~0.5 周): intraday_monitor 规则迁入
├── backend/platform/risk/rules/intraday.py       PortfolioDrop3pct / 5pct / 8pct / QMTDisconnect
├── scripts/intraday_monitor.py                   ⚠️ 改走 RiskEngine (保留 5min schtasks 触发)
└── backend/tests/test_risk_rules_intraday.py     ~8 unit

批 3 (~0.5-0.7 周, 批 0 spike 后下修): circuit_breaker **adapter** 接入 Risk Engine
├── backend/platform/risk/rules/circuit_breaker_adapter.py  CircuitBreakerRule (薄 wrapper,
│                                                            1 rule 统一 L1-L4 状态变更事件)
├── ⚠️ **不**重写 risk_control_service.py (1030 行 async 保留, adapter 调现成 check_circuit_breaker_sync)
├── backend/tests/test_risk_rules_cb_adapter.py     ~8 unit (wrapper + 4 level transition + risk_event_log 格式)
└── 批 3 末尾若 CB 运行稳定, 可二次重构把 wrapper inline + drop 老 service (batch 3b, Wave 4+)
```

**规模预估**: ~400 行 platform + ~200 行 migration/rules + **~200 行 CB adapter + tests** + ~450 行 其他 tests ≈ **~1250 行, 2-2.7 周**

**对比 v1.0 原估**: ~1500 行 / 2.5-3.5 周 → -300 行 / -0.5-0.8 周 (批 0 spike 决策方案 C adapter 节省 async→sync 重写)

---

## 关键设计 (D1-D5)

### D1. `RiskContext` dataclass (铁律 31 纯数据)

```python
@dataclass(frozen=True)
class RiskContext:
    strategy_id: str
    execution_mode: str              # settings.EXECUTION_MODE (ADR-008)
    timestamp: datetime              # tz-aware UTC (铁律 41)
    positions: list[Position]        # 来自 PositionSource.load() 实时
    current_prices: dict[str, float] # Redis market:latest (已 Session 18 修 high/low gap)
    portfolio_nav: float
    prev_close_nav: float | None     # intraday 规则需要
    peak_prices: dict[str, float]    # PMS 规则需要 (从 klines_daily max close since entry)
```

### D2. `RiskRule` abstract (铁律 24 单一职责)

```python
class RiskRule(ABC):
    rule_id: str                     # unique, 用作 risk_event_log FK
    severity: Severity               # INFO / WARNING / P1 / P0
    action: Literal["sell", "alert_only", "bypass"]

    @abstractmethod
    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """返回触发事件列表 (空列表=未触发)."""

    def __init_subclass__(cls) -> None:
        """强制实现 rule_id + severity + action."""
```

### D3. `PositionSource` 优先级 (F28 **部分**改进, 非完全根治)

```python
# platform/risk/engine.py
def _load_positions(self) -> list[Position]:
    try:
        return self._primary.load()       # QMTPositionSource (Redis portfolio:current, 60s 刷新)
    except (ConnectionError, ValueError):
        logger.warning("[risk] QMT source 失败, fallback DB")
        return self._fallback.load()      # DBPositionSource (读当前 live snapshot)
```

**F28 改进** (不是根治, v1.1 review 澄清):
- **Redis primary 60s 刷新**: 对"月度调仓 + 月度 trailing stop"足够, 但对"3 分钟急跌 15% flash-crash stop-loss"仍有 60s 延迟
- **DBPositionSource fallback gap**: `position_snapshot` 在 16:30 signal_phase 写入, 所以 **09:31-16:30 之间若 Redis 挂**, DB fallback 返回**昨日** snapshot = 同 PMS v1 的 T-1 盲区. 此窗口需告警
- 真实时 tick-level (单笔成交推送) 是 Wave 4 Observability + Event Sourcing 后的增强, 本 MVP 不做

**peak_prices 计算**: Engine 在 `build_context()` 时查 `klines_daily` SELECT MAX(close) WHERE code AND trade_date >= entry_date (hardcoded execution_mode='live' → Risk Engine 动态 settings.EXECUTION_MODE). 迁自 pms_engine.py:174 get_peak_prices, 保持同语义.

### D4. 直接执行 (F27 根治)

```python
def execute(self, events: list[RiskEvent]) -> None:
    for event in events:
        if event.action == "sell":
            # 直调 broker, 不走 StreamBus
            result = self._broker.sell(
                event.code, event.shares,
                reason=f"risk:{event.rule_id}",
                timeout=5.0,
            )
            self._log_event(event, action_result=result)  # risk_event_log
            self._alert_dingding(event)                    # 钉钉
        elif event.action == "alert_only":
            self._log_event(event, action_result={"alert": "sent"})
            self._alert_dingding(event)
```

**Broker wiring (v1.1 review 明示)**: `self._broker` 在 `live` 模式注入 `execution_ops.py` 的 QMT sell 路径 (复用 execution_service._save_live_fills 等现成 fill 记录逻辑); `paper` 模式注入 `paper_broker.py`. Engine 不直 import xtquant (铁律 "xtquant 唯一生产入口" QMT Data Service).

**废除 StreamBus `qm:pms:protection_triggered`** — publish 无 consumer 的 dead stream. ADR-003 Event Sourcing 专注 signal/trade 事件, 不扩 risk 事件 (risk 是同步决策, 异步 stream 反而增加延迟).

### D6. `risk_event_log` retention + governance (v1.1 review 新增)

ADR-010 D4 schema 基础上补:
- **Retention**: 保留 **90 天** (与 event_outbox 7 天 / log_rotate 7 天平衡), 之后 DELETE. 每日 log_rotate cron 做
- **TimescaleDB hypertable**: 按 `triggered_at` 月度 partition, chunk 自动 drop 超 90 天
- **日志策略**: 仅触发事件写入 (非触发 evaluations 不 log, 避免爆表). Dry-run / backtest 模式下 writer 可关, 只进 logger
- **单行大小**: context_snapshot JSONB ~5-10KB (20+ positions + prices + portfolio state), 预计 ~1000 rows/年 (主要 intraday 组合跌 3/5/8% + PMS L1-L3 + CB 触发合计)

### D5. execution_mode 命名空间 (ADR-008 对齐, F29 根治)

- `risk_event_log.execution_mode` = `settings.EXECUTION_MODE` 动态
- `RiskContext.execution_mode` 从启动时注入, 全链路传递
- **禁止 hardcoded** — 铁律 34 SSOT, config_guard 启动时检查

---

## 验收标准

- ✅ **26+ unit tests PASS** (批 1-3 合计)
- ✅ **live smoke** `test_mvp_3_1_risk_live.py`: 模拟 L1 触发 → QMT sell order → risk_event_log 写入 → 钉钉发送, 端到端 side effect 全验证
- ✅ 批 1 完成后: `SELECT COUNT(*) FROM risk_event_log WHERE rule_id LIKE 'pms_%'` **必须有非触发 dry-run 证据** (单测 + live smoke 模拟触发至少 1 行)
- ✅ 批 2 完成后: `intraday_monitor.py` 走 RiskEngine, 老告警函数加 `@deprecated`
- ✅ 批 3 完成后: `CircuitBreakerRule` adapter 接入 RiskEngine, CB 状态变更事件入
  `risk_event_log` (单 rule_id `cb_state_change`); `check_circuit_breaker_sync` **保留**
  (方案 C adapter 调, 非 deprecated); circuit_breaker_state 表保留, circuit_breaker_log
  记录通过 adapter 映射进 risk_event_log
- ✅ **regression**: `pytest -m smoke` 全绿, baseline fail count 不增加 (铁律 40)
- ✅ **文档**: SYSTEM_STATUS.md 更新 Risk Framework 状态, DEV_BACKEND.md §监控架构章节重写, CLAUDE.md 铁律如有新增 (如"Dead code 识别")
- ✅ **PMS 死码清理**: `pms_engine.py` + `daily_pipeline.py:pms_check` + `api/pms.py` 迁入后删除 (保留 1 sprint 供回滚, 完成后永久 drop)

---

## 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| ~~**批 3 CB async→sync 迁移低估**~~ (批 0 spike 2026-04-24 已消除) | ~~批 3 卡住, 批 1-2 已上线 split-brain~~ | 批 0 spike 决策**方案 C Hybrid wrapper**: adapter 复用 check_circuit_breaker_sync, 不重写 1030 行 async. 批 3 重估 **0.5-0.7 周**, 总 **2-2.7 周**, split-brain 风险消除 (ADR-010-addendum) |
| 批 3 circuit breaker 改动误伤真金路径 | 熔断失灵 = 灾难 | 批 3 最后做, 先验证批 1-2 稳定运行 2 周 |
| **过渡期零自动卖 1.5-3 周** (v1.1 review P1) | intraday_monitor + emergency_stock_alert + 盘后三检全是 alert-only, 人工响应延迟 3-5 min | `emergency_stock_alert.py` 必须**先建**再停 PMS Beat (ADR-010 D6 调顺序); 过渡期间尽量不做大额调仓, 机器必开钉钉 |
| QMTPositionSource Redis 60s 延迟 | flash-crash 场景 stop-loss 仍可能滞后 | Redis primary 对月度策略足够; 未来 Wave 4 可加 tick-level event stream; 当前窗口接受 60s 延迟 |
| QMTPositionSource Redis 失联, DB fallback 09:31-16:30 仍 T-1 | 日内股票价格信息缺失 | 15 min 内 Redis 不恢复 → P0 钉钉人工介入; 此窗口 Risk Engine 视为"无可信实时数据" |
| RiskEngine execute 调 broker, broker 超时不响应 | 卡住 Engine 循环 | timeout 5s + 失败重试 1 次, 再失败 P0 钉钉人工介入 |
| 批 1 迁入后老 position_monitor 表 0 行 (同 PMS v1 盲区) | 同样无验证 | live smoke **强制模拟触发**, 验证 risk_event_log 端到端有行 (验收标准第 3 条) |
| `risk_event_log` JSONB context_snapshot 膨胀 (v1.1 review) | 单表无限增长吞磁盘 | 90 天 TimescaleDB partition retention + 仅触发事件写入 (非 evaluations) |
| Wave 2 MVP 2.3 U1 Parity 未完结即启动 Wave 3 | 依赖破, 回归风险 | Session 22 开始前先确认 MVP 2.3 Sub3 已完结, 文档标记 |
| pt_audit / pt_watchdog 定位 (v1.1 review 隐藏风险) | 强耦合进 RiskEngine 可能破坏原独立性 | **不** 迁入 RiskRule, 保持独立 schtasks. 改为 `risk_event_log` 的**下游消费者** (read-only 对账), 不 block 其告警路径 |

---

## 过渡期保护 (Risk Framework 完成前)

PMS 死码处置后, 个股 trailing stop 空窗期由 3 道独立防线守护:

1. **intraday_monitor** (09:35-15:00 每 5min) — 组合跌 3/5/8% + QMT 断连钉钉
2. **emergency_stock_alert** (新 ADR-010 D6 过渡脚本) — 每 5min Redis 扫所有持仓, 单股当日跌 >8% 钉钉
3. **盘后检核** — daily_reconciliation 15:40 + pt_audit 17:35 + pt_watchdog 20:00

真金曝险评估: CORE3+dv_ttm 月度低换手策略, 单股"浮盈 30% 急跌 15%"场景罕见, 过渡期风险可接受.

---

## Follow-up

- **Wave 3 MVP 3.2 Strategy Framework** — 依赖 Risk Framework (策略触发 trade → Risk Engine pre-check)
- **Wave 3 MVP 3.3 Signal & Execution** — Risk Engine 的 execute 路径扩展为完整订单生命周期管理
- **Wave 3 MVP 3.4 Event Sourcing** — risk_event_log 与 event_outbox 结合 (ADR-003)
- **Wave 4 Observability** — Risk Engine metrics 接 Prometheus + Grafana dashboard
- **Wave 4 前端** — 统一 /risk dashboard 替代 /pms 页面
