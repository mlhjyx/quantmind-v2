---
adr_id: ADR-010
title: PMS Deprecation + Risk Framework Migration (Wave 3 MVP 3.1)
status: accepted
related_ironlaws: [23, 24, 31, 33, 34, 36, 38]
recorded_at: 2026-04-21
---

## Context

Session 21 (2026-04-21, cutover +18h) 深查 PMS (Profit-Maximizing Stop) v1.0 状态, 发现 **整体死码 5 重失效 (F27-F31)**:

### 五重失效

| # | 问题 | 代码证据 | 影响 |
|---|---|---|---|
| F27 | StreamBus `qm:pms:protection_triggered` 发布无消费者 | `grep XREAD qm:pms backend/` = 0 consumer. daily_pipeline.py:226 + api/pms.py:175 两处 publish 无人 XREAD | **触发即告警, 不真卖**. `update_position_snapshot_after_sell` 方法存在但从未调用. 违反设计初衷 "14:30 自动卖锁利润" |
| F28 | PMS 读 T-1 snapshot, 非实时 QMT | `pms_engine.py:129-136` MAX(trade_date) WHERE execution_mode='live', position_snapshot 写入在 16:30 signal_phase, 14:30 时 MAX=昨日 | 今日 T+1 09:31 新开仓当日盘中无保护 |
| F29 | sync_positions / get_peak_prices / record_trigger 全 hardcoded 'live' | `pms_engine.py:131/194/346` | 4-14 前 paper 命名空间建仓的股 avg_cost=0 → `check_protection` L90 静默 return None. 19 股里约 10+ 只保护失效 |
| F30 | `position_monitor` 表建库 0 行 | `SELECT COUNT(*) FROM position_monitor` = 0 (建库至今) | PMS 从未在生产触发过任何保护, 核心代码路径未经端到端验证 |
| F31 | 触发 publish 逻辑重复在两处 | `daily_pipeline.py:226` + `api/pms.py:175` | 违反 DRY, 两套代码未来必漂移 |

### 实测证据 (4-20 14:30 PMS 执行分解)

```
sync_positions returns 24 positions (读到 4-17 snapshot, 含 5 phantom)
├─ 5 phantom (F19) 无 Redis 价 → "无当前价格，跳过" WARN 5 条 (log 可见)
├─ ~10+ paper 建仓老股 → entry_price=0 → check_protection 静默 None (log 不可见)
└─ ~9 只 live 建仓新股 → check_protection 正常 → 今日涨幅不够 L3 → 0 触发
最终: position_monitor 0 insertion, StreamBus 0 publish, 看似 "正常完成"
```

**真实有效保护覆盖率 ≈ 9/24 = 37%**. 真金 cutover 后 18h 零 PMS 保护, 靠 intraday_monitor 组合告警 (跌 3/5/8%) + 盘后 reconciliation 三道检核守护未出事, 属运气.

### 架构层面: 5 个监控系统互不通信

| 系统 | 数据源 | 频率 | 动作 | 输出表 |
|---|---|---|---|---|
| intraday_monitor | QMT 实时 | 5min × 11 = 55 次/日 | 仅钉钉 | intraday_monitor_log |
| **PMS (本 ADR 对象)** | DB snapshot (T-1) | 14:30 一次 | record + publish (无消费者) | position_monitor (0 行) |
| risk_control_service | DB snapshot | signal_phase 调 | circuit_breaker state | circuit_breaker_state |
| pt_audit | DB + 多源 | 17:35 一次 | 钉钉 + DB | scheduler_task_log |
| pt_watchdog | DB (heartbeat) | 20:00 一次 | 钉钉 | - |

零统一: 5 套数据源逻辑 + 5 套告警通道 + 5 套 event log 格式, 互无跨引用. 重构势在必行.

## Decision

### D1 — 不修 PMS, 并入 Wave 3 Risk Framework

任何对 PMS 的 patch (补 consumer / 改 T-1 → realtime / 解 live hardcoded) 都是在死码上堆技术债, Wave 3 启动时仍需重写. **最高 quality 做法**: 让 PMS 维持现状 (停 Beat 避免继续假跑), 统一架构在 Wave 3 第一个 MVP (Risk Framework) 重生.

### D2 — Risk Framework 定位为 Wave 3 MVP 3.1

QPB v1.5 Wave 3 原 MVP 排序调整:
- **MVP 3.1 Risk Framework** (新, ~1.5-2 周) ← 本 ADR
- MVP 3.2 Strategy Framework (原 3.1)
- MVP 3.3 Signal & Execution (原 3.2)
- MVP 3.4 Event Sourcing (ADR-003 约束)
- MVP 3.5 Eval Gate

Risk 是所有 Wave 3 MVP 的前置依赖 (Strategy 选股 / Signal-Exec 下单 / Event Sourcing 持久化 / Eval Gate 验证), 必须先落地.

### D3 — Risk Framework 核心接口 (细化在 MVP_3_1 spec)

```python
class RiskRule(ABC):
    rule_id: str                     # "pms_l1" / "intraday_portfolio_drop_5pct" / "cb_l2"
    severity: Literal["INFO", "WARNING", "P1", "P0"]
    action: Literal["sell", "alert_only", "bypass"]

    @abstractmethod
    def evaluate(self, context: RiskContext) -> list[RuleResult]: ...

class RiskEngine:
    def register(self, rule: RiskRule) -> None: ...
    def run(self, context: RiskContext) -> list[RiskEvent]: ...
    def execute(self, events: list[RiskEvent]) -> None:
        """直调 broker (sell) + 写 risk_event_log + 钉钉, 不走 StreamBus 3 hops."""

class PositionSource(Protocol):
    def load(self) -> list[Position]: ...   # QMT 实时 (primary) or DB (fallback)
```

### D4 — 统一输出 `risk_event_log` 表

替代 position_monitor + intraday_monitor_log + circuit_breaker_log 三表 (老表迁移完成后 deprecate).

```sql
CREATE TABLE risk_event_log (
    id UUID PRIMARY KEY,
    strategy_id UUID NOT NULL,
    execution_mode VARCHAR(10) NOT NULL,   -- 遵守 ADR-008 命名空间
    rule_id VARCHAR(50) NOT NULL,           -- "pms_l1" / "intraday_p0" / ...
    severity VARCHAR(10) NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    context_snapshot JSONB NOT NULL,        -- positions, prices, portfolio state at trigger
    action_taken VARCHAR(30),               -- "sell" / "alert_only" / "bypass"
    action_result JSONB,                    -- QMT fill / alert response
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON risk_event_log (strategy_id, execution_mode, triggered_at DESC);
CREATE INDEX ON risk_event_log (rule_id, triggered_at DESC);
```

### D5 — 迁移 11 条规则到 Risk Framework

| 旧系统 | 旧规则 | 新 rule_id | 迁移批次 |
|---|---|---|---|
| PMS | L1 (浮盈 30% + 回撤 15%) | `pms_l1` | 批 1 |
| PMS | L2 (浮盈 20% + 回撤 12%) | `pms_l2` | 批 1 |
| PMS | L3 (浮盈 10% + 回撤 10%) | `pms_l3` | 批 1 |
| intraday_monitor | 组合跌 3% | `intraday_portfolio_drop_3pct` | 批 2 |
| intraday_monitor | 组合跌 5% | `intraday_portfolio_drop_5pct` | 批 2 |
| intraday_monitor | 组合跌 8% | `intraday_portfolio_drop_8pct` | 批 2 |
| intraday_monitor | QMT 断连 | `qmt_disconnect` | 批 2 |
| risk_control | L1-L4 circuit breaker (4 规则) | `cb_l1` ... `cb_l4` | 批 3 (风险最高) |

### D6 — PMS 死码今日处置 (Session 22 PR)

1. 停 Celery Beat `pms-daily-check` 调度 (`beat_schedule.py` L54-61 删除 block)
2. `pms_engine.py` + `daily_pipeline.py:pms_check` + `api/pms.py` 加头部注释 `"DEPRECATED per ADR-010, pending Risk Framework MVP 3.1"`
3. 删除 `api/pms.py:170-188` 重复 publish 逻辑 (F31), 留 API GET 端点返回数据 (前端 /pms 页面暂不改)
4. SYSTEM_STATUS.md 标记 PMS DEPRECATED-PENDING-RISK-FRAMEWORK
5. 过渡期补 emergency 个股止损告警 (新 `scripts/emergency_stock_alert.py`, 每 5min Redis 扫所有持仓, 单股当日跌 >8% 钉钉推)

### D7 — 不推进事项 (明确排除)

- ❌ **不废除 L1/L2/L3 阈值逻辑设计** — 三层阶梯 trailing stop 规则本身合理, 迁入 Risk Framework 保留
- ❌ **不立即删 intraday_monitor.py** — 批 2 完成迁移后再 deprecate
- ❌ **不改 Wave 2 已完成 MVP** — 回归风险, 铁律 15
- ❌ **不立即删 position_monitor 表** — 保留 1 sprint 作回滚锚点, Risk Framework 稳定运行 2 周后 drop

## Consequences

### Positive

- 零技术债堆积 (不 patch 死码)
- 架构统一 (5 监控系统 → 1 Risk Framework)
- 端到端可审计 (position_monitor 0 行 → risk_event_log 真实触发记录)
- 对齐 Platform Blueprint Wave 3 路线图
- 过渡期 intraday_monitor 组合告警 + 盘后对账三检守护真金

### Negative

- PMS 个股 trailing stop 空窗 1.5-2 周 (Risk Framework 批 1 完成前)
- **风险缓解**: CORE3+dv_ttm 月度调仓策略很少出现"浮盈 30% 急跌 15%"场景; intraday 组合跌 3% 钉钉是第一道; emergency_stock_alert (单股跌 8%) 作第二道

### Neutral

- Wave 3 启动时间不变 (Risk Framework 本就需建)
- Wave 3 MVP 编号重排 (3.1 新增 Risk Framework, 原 MVP 串后移)

## Follow-up

- **Session 22** (2026-04-22): PR #32 D6 死码处置 (停 Beat + deprecated 注释 + emergency_stock_alert.py + F31 消除)
- **本周**: 完成 `docs/mvp/MVP_3_1_risk_framework.md` 详细 spec 细化 (已草稿)
- **下周**: Wave 3 启动前置评估 (MVP 2.3 U1 Parity 完结状态 / 平台化依赖关系核对)
- **2-3 周后**: Risk Framework 批 1 (PMS L1/L2/L3 迁入) + live smoke 验收
- **1 月后**: 批 2 (intraday 规则) + 批 3 (circuit breaker)
- **~2 月后**: 老 position_monitor / intraday_monitor_log / circuit_breaker_log 三表 DROP

## Related

- ADR-003 Event Sourcing (StreamBus 范围界定, risk 不走 Event Sourcing)
- ADR-008 execution_mode 命名空间 (Risk Framework 全链路动态读 settings)
- ADR-010 (本 ADR)
- QPB v1.5 §Part 2 Framework #6 Signal/Exec (Risk Framework 归属)
- QPB v1.5 §Part 4 Wave 3 MVP (新增 MVP 3.1)
