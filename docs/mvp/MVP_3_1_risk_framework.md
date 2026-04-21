# MVP 3.1 · Risk Framework

> **Wave**: 3 第 1 步 (Wave 3 启动 MVP, 所有其他 Wave 3 MVP 前置)
> **耗时**: 1.5-2 周 (3 批次分阶段落地)
> **依赖**: MVP 1.1 Platform Skeleton ✅ / MVP 2.1 Data Framework ✅ / ADR-010 PMS Deprecation ✅
> **风险**: 中-高 (批 3 触碰熔断真金路径, 最后做)
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

## 实施结构 (3 批分批落地)

```
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

批 3 (~0.5 周): circuit breaker L1-L4 迁入 (末位, 风险最高)
├── backend/platform/risk/rules/circuit_breaker.py  CBL1Rule / CBL2Rule / CBL3Rule / CBL4Rule
├── backend/app/services/risk_control_service.py    ⚠️ check_circuit_breaker_sync 改走 RiskEngine
└── backend/tests/test_risk_rules_cb.py             ~12 unit (含 L4 recovery 路径)
```

**规模预估**: ~400 行 platform + ~150 行 migration/rules + ~100 行 service 改造 + ~350 行 tests ≈ 1000 行, 1.5-2 周工程

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

### D3. `PositionSource` 优先级 (F28 根治)

```python
# platform/risk/engine.py
def _load_positions(self) -> list[Position]:
    try:
        return self._primary.load()       # QMTPositionSource (Redis portfolio:current, 60s 刷新)
    except (ConnectionError, ValueError):
        logger.warning("[risk] QMT source 失败, fallback DB")
        return self._fallback.load()      # DBPositionSource (读当前 live snapshot)
```

**关键**: 不再读 T-1 snapshot. Redis 60s 同步, 当日新开仓 max 1 分钟延迟进 Risk Engine 视野.

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

**废除 StreamBus `qm:pms:protection_triggered`** — publish 无 consumer 的 dead stream. ADR-003 Event Sourcing 专注 signal/trade 事件, 不扩 risk 事件 (risk 是同步决策, 异步 stream 反而增加延迟).

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
- ✅ 批 3 完成后: `risk_control_service.check_circuit_breaker_sync` deprecated, circuit_breaker_log 停止写入
- ✅ **regression**: `pytest -m smoke` 全绿, baseline fail count 不增加 (铁律 40)
- ✅ **文档**: SYSTEM_STATUS.md 更新 Risk Framework 状态, DEV_BACKEND.md §监控架构章节重写, CLAUDE.md 铁律如有新增 (如"Dead code 识别")
- ✅ **PMS 死码清理**: `pms_engine.py` + `daily_pipeline.py:pms_check` + `api/pms.py` 迁入后删除 (保留 1 sprint 供回滚, 完成后永久 drop)

---

## 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 批 3 circuit breaker 改动误伤真金路径 | 熔断失灵 = 灾难 | 批 3 最后做, 先验证批 1-2 稳定运行 2 周 |
| QMTPositionSource Redis 失联, fallback DB 也陈旧 | Risk Engine 看不到实时 | DBPositionSource 读 position_snapshot 当日 live (比 PMS v1 的 T-1 已改进, 但仍可能延迟), 失联时 P0 钉钉 |
| RiskEngine execute 调 broker, broker 超时不响应 | 卡住 Engine 循环 | timeout 5s + 失败重试 1 次, 再失败 P0 钉钉人工介入 |
| 批 1 迁入后老 position_monitor 表 0 行 (同 PMS v1 盲区) | 同样无验证 | live smoke **强制模拟触发**, 验证 risk_event_log 端到端有行 (验收标准第 3 条) |
| Wave 2 MVP 2.3 U1 Parity 未完结即启动 Wave 3 | 依赖破, 回归风险 | Session 22 开始前先确认 MVP 2.3 Sub3 已完结, 文档标记 |

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
