# MVP 3.1 批 1 · Framework Core + PMS L1-L3 迁入 (详细 Plan)

> **父文档**: `docs/mvp/MVP_3_1_risk_framework.md`
> **ADR**: `docs/adr/ADR-010-pms-deprecation-risk-framework.md` + addendum
> **批次**: 批 1 (批 0 spike ✅ Session 27 已完成, 批 2/3 后续)
> **耗时**: ~1 周 (~400 行 platform + ~200 行 migration/rules + ~250 行 tests ≈ ~850 行)
> **创建**: 2026-04-24 Session 28, Opus (架构模式)
> **状态**: plan 待用户确认后进入实施模式

---

## 1 · 批 1 目标 (批 2/3 另立)

**In-scope** (批 1 必交付):
1. `backend/platform/risk/` 骨架 + `interface.py` 契约 + `engine.py` concrete
2. `PositionSource` Protocol + 2 实现 (QMT primary + DB fallback)
3. `PMSLevel{1,2,3}Rule` 迁自 `pms_engine.py::check_protection`
4. `risk_event_log` 表 migration + rollback (TimescaleDB hypertable + 90 天 retention)
5. `daily_pipeline.py::pms_check` task 改走 `PlatformRiskEngine`
6. live smoke 1 条 (模拟 L1 触发 → risk_event_log 有行 + 钉钉发送)
7. ~30 单测 (engine + rules + sources + context builder)

**Out-of-scope** (批 2/3):
- intraday_monitor 3/5/8% + QMT 断连 (批 2)
- `CircuitBreakerRule` adapter (批 3, ADR-010 addendum 方案 C)
- 前端 /risk dashboard (Wave 4)
- `pms_engine.py` 物理删除 (保留 1 sprint 供回滚)

---

## 2 · 文件结构 (批 1 交付物)

```
backend/platform/risk/                       ⭐ NEW (批 1 创建)
├── __init__.py                               导出 PlatformRiskEngine / RiskRule / 类型
├── interface.py                              ~120 行: RiskRule ABC + RiskContext + RuleResult + RiskEvent + PositionSource Protocol + Position dataclass
├── engine.py                                 ~150 行: PlatformRiskEngine concrete (register / build_context / run / execute / _log_event)
├── sources/
│   ├── __init__.py
│   ├── qmt_realtime.py                       ~40 行: QMTPositionSource 读 Redis portfolio:current
│   └── db_snapshot.py                        ~40 行: DBPositionSource 读 position_snapshot live
└── rules/
    ├── __init__.py
    └── pms.py                                ~100 行: PMSLevel1Rule / PMSLevel2Rule / PMSLevel3Rule (迁自 pms_engine.check_protection)

backend/migrations/
├── risk_event_log.sql                        ⭐ NEW ~40 行 CREATE TABLE + 2 index + hypertable + retention
└── risk_event_log_rollback.sql               ~8 行 DROP TABLE

backend/app/tasks/daily_pipeline.py           ⚠️ MODIFY pms_check task (~30 行 delta): 老 PMSEngine → 新 PlatformRiskEngine, 保留 14:30 Celery Beat schedule

backend/tests/
├── test_risk_engine.py                       ~150 行 ~12 unit (build_context/register/run 分发/execute 直调 broker/log event)
├── test_risk_rules_pms.py                    ~120 行 ~12 unit (3 Level × 3 scenario: 触发/边界/不触发 + peak<entry 异常 + neg price)
├── test_risk_sources.py                      ~80 行 ~6 unit (QMT Redis 读 / DB fallback / primary 挂 fallback 切换)
└── smoke/test_mvp_3_1_risk_live.py           ⭐ NEW ~80 行 L4 live smoke 模拟 L1 触发 → broker sell mock → risk_event_log INSERT → 钉钉 publish mock
```

**代码体量核算**:

| 文件 | 行数 est |
|---|---|
| platform/risk/ 全部 | ~400 |
| migrations SQL | ~50 |
| daily_pipeline 修改 | ~30 delta |
| tests | ~430 |
| **合计** | **~910** |

---

## 3 · 关键接口契约

### 3.1 `RiskContext` (frozen dataclass)

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Position:
    code: str                        # DB 代码带后缀 "600519.SH"
    shares: int
    entry_price: float               # 加权平均买入成本
    peak_price: float                # 持仓期间历史最高收盘价
    current_price: float             # Redis market:latest 实时

@dataclass(frozen=True)
class RiskContext:
    strategy_id: str
    execution_mode: str              # settings.EXECUTION_MODE 动态 (ADR-008)
    timestamp: datetime              # tz-aware UTC (铁律 41)
    positions: tuple[Position, ...]  # tuple 保 frozen, 非 list
    portfolio_nav: float
    prev_close_nav: float | None     # intraday 批 2 需要, 批 1 可 None
```

**关键决策**:
- `Position` 单对象含 entry + peak + current, 消费方不需再 lookup 3 dict (decrease complexity)
- `current_price` 在 `build_context()` 时从 Redis 读, rule evaluate 不再 IO
- `peak_price` 在 `build_context()` 时查 `klines_daily MAX(close) WHERE entry_date`, 迁自 `pms_engine.get_peak_prices` 同语义

### 3.2 `RiskRule` ABC

```python
from abc import ABC, abstractmethod
from typing import Literal
from backend.platform._types import Severity

@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    code: str                        # 触发的股票代码 (组合级规则用 ""=ALL)
    shares: int                      # sell 动作的股数 (alert_only=0)
    reason: str                      # 人类可读触发原因
    metrics: dict[str, float]        # {pnl_pct, dd_pct, peak_price, ...}

class RiskRule(ABC):
    rule_id: str                     # 子类类变量, 必设
    severity: Severity               # 复用 platform._types.Severity
    action: Literal["sell", "alert_only", "bypass"]

    @abstractmethod
    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """空列表 = 未触发. 非空 = 触发的 positions."""

    def __init_subclass__(cls, **kwargs) -> None:
        """强制子类设 rule_id / severity / action (fail-loud 启动)."""
        super().__init_subclass__(**kwargs)
        for attr in ("rule_id", "severity", "action"):
            if not hasattr(cls, attr):
                raise TypeError(f"{cls.__name__} missing class attr '{attr}'")
```

### 3.3 `PositionSource` Protocol

```python
from typing import Protocol

class PositionSource(Protocol):
    def load(self, strategy_id: str, execution_mode: str) -> list[Position]:
        """加载当前持仓, 必 raise ConnectionError/ValueError on 失败 (非 return [])."""
```

**2 实现**:
- `QMTPositionSource`: 读 Redis `portfolio:current` hash (xtquant Data Service 60s 同步), 构造 Position list. 读不到 → `raise ConnectionError`
- `DBPositionSource`: 读 `position_snapshot` 最新 trade_date + `trade_log` 算 entry_price + `klines_daily` 算 peak_price (全迁自 pms_engine.sync_positions + get_peak_prices)

### 3.4 `PlatformRiskEngine`

```python
class PlatformRiskEngine:
    def __init__(
        self,
        primary_source: PositionSource,
        fallback_source: PositionSource,
        broker,                       # execution_ops.QMTBroker or paper_broker
        conn_factory,                 # callable → psycopg2 conn
        dingding_notifier,            # 可 no-op for tests
    ):
        self._rules: list[RiskRule] = []
        self._primary = primary_source
        self._fallback = fallback_source
        self._broker = broker
        self._conn_factory = conn_factory
        self._notifier = dingding_notifier

    def register(self, rule: RiskRule) -> None:
        """rule_id 唯一, 重复 raise ValueError."""

    def build_context(self, strategy_id: str) -> RiskContext:
        """1. positions = _load_positions() (primary fallback)
           2. current_prices 从 Redis market:latest:{code}
           3. peak_prices 查 klines_daily (迁 pms_engine.get_peak_prices)
           4. 构造 Position tuple + RiskContext"""

    def run(self, context: RiskContext) -> list[RuleResult]:
        """for each registered rule: rule.evaluate(context) → flatten."""

    def execute(self, results: list[RuleResult], context: RiskContext) -> None:
        """分发 action:
             sell → broker.sell() + _log_event + _notify
             alert_only → _log_event + _notify
             bypass → _log_event only (debug)"""

    def _log_event(self, result: RuleResult, context: RiskContext, action_result: dict) -> None:
        """INSERT INTO risk_event_log (...) 含 context_snapshot JSONB."""
```

---

## 4 · `risk_event_log` 迁移 (ADR-010 D4)

```sql
-- backend/migrations/risk_event_log.sql
BEGIN;

CREATE TABLE IF NOT EXISTS risk_event_log (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    strategy_id UUID NOT NULL,                    -- 对齐 signals/trade_log/position_snapshot (非 VARCHAR, reviewer P1-1)
    execution_mode VARCHAR(10) NOT NULL,          -- ADR-008 namespace
    rule_id VARCHAR(50) NOT NULL,
    severity VARCHAR(10) NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    code VARCHAR(12) NOT NULL DEFAULT '',        -- "" = 组合级
    shares INT NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    context_snapshot JSONB NOT NULL,             -- positions + prices + NAV
    action_taken VARCHAR(30) NOT NULL,           -- sell/alert_only/bypass
    action_result JSONB,                         -- broker fill / alert response
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_event_log_strategy_time
    ON risk_event_log (strategy_id, execution_mode, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_event_log_rule_time
    ON risk_event_log (rule_id, triggered_at DESC);

-- TimescaleDB hypertable (90 天 retention)
SELECT create_hypertable(
    'risk_event_log', 'triggered_at',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);
SELECT add_retention_policy('risk_event_log', INTERVAL '90 days', if_not_exists => TRUE);

-- Migration idempotency fail-loud guard
DO $$
DECLARE missing_cols INT;
BEGIN
    SET LOCAL statement_timeout = '30s';
    SELECT COUNT(*) INTO missing_cols
    FROM information_schema.columns
    WHERE table_name = 'risk_event_log'
      AND column_name IN ('id', 'strategy_id', 'rule_id', 'context_snapshot', 'action_taken');
    IF missing_cols < 5 THEN
        RAISE EXCEPTION 'risk_event_log migration incomplete: only % of 5 required columns', missing_cols;
    END IF;
END $$;

COMMIT;
```

**Rollback**: `DROP TABLE IF EXISTS risk_event_log CASCADE;` (含 hypertable 元数据自动清理)

---

## 5 · PMS 规则迁移映射

| 老位置 | 新位置 | 行为保持 |
|---|---|---|
| `pms_engine.check_protection(entry, peak, current, levels)` L1 分支 | `PMSLevel1Rule.evaluate()` | 浮盈 ≥ `PMS_LEVEL1_GAIN` 且 回撤 ≥ `PMS_LEVEL1_DRAWDOWN` → sell |
| 同上 L2 | `PMSLevel2Rule.evaluate()` | gain≥L2/dd≥L2 → sell |
| 同上 L3 | `PMSLevel3Rule.evaluate()` | gain≥L3/dd≥L3 → sell |
| `pms_engine.get_peak_prices` | `PlatformRiskEngine.build_context()` 内部 | SELECT MAX(close) FROM klines_daily WHERE entry_date (同 SQL) |
| `pms_engine.sync_positions` | `DBPositionSource.load()` + `QMTPositionSource.load()` | 读 Redis (primary) / position_snapshot+trade_log (fallback) |
| `pms_engine.check_all_positions` | `PlatformRiskEngine.run()` | loop rules × positions |
| `pms_engine.record_trigger → position_monitor` | `PlatformRiskEngine._log_event → risk_event_log` | 单表替代, JSONB context_snapshot |
| `daily_pipeline.publish StreamBus qm:pms:protection_triggered` | **废除** (F27 根因) | 同步直调 broker + 钉钉 |

**规则优先级** (原 pms_engine L117-119 for-loop 早退): PMSLevel1 > L2 > L3 (阈值高者优先). 新 engine: 3 rule 独立 register, 冲突时 `run()` 返 3 RuleResult, `execute()` 按 severity 排序优先卖 L1 对应股. 同股多 level 触发? 原逻辑 L1 早退 → 新 engine 保持: Rule 内按 L1→L2→L3 顺序 check, 首次命中即 append 停止 (单 Rule 只返 1 RuleResult per position).

**更简洁方案**: 仅 1 个 `PMSRule` (非 3 个), 内部按 L1→L2→L3 顺序命中, 符合原语义 + rule_id 用 `"pms_l1"`/`"pms_l2"`/`"pms_l3"` 动态生成. **建议采此方案**, 减少 3 类冗余. MVP 3.1 spec D3 提及 3 类是接口描述, 实施层 1 类即可.

---

## 6 · daily_pipeline 改造 (~30 行 delta)

老 `pms_check` task (L200+ 估):
```python
def pms_check():
    conn = get_conn()
    engine = PMSEngine()
    positions = engine.sync_positions(conn, strategy_id)
    peaks = engine.get_peak_prices(conn, [p["code"] for p in positions])
    prices = qmt_client.get_current_prices()
    signals = engine.check_all_positions(positions, peaks, prices)
    for sig in signals:
        engine.record_trigger(conn, sig, strategy_id, today)
        stream_bus.publish("qm:pms:protection_triggered", ...)  # F27
    conn.commit()
```

新:
```python
def pms_check():
    """DEPRECATED name → 改名 risk_check, 保留 alias 1 sprint."""
    from backend.platform.risk import PlatformRiskEngine
    from backend.platform.risk.sources import QMTPositionSource, DBPositionSource
    from backend.platform.risk.rules.pms import PMSRule  # 单类方案
    from app.services.execution_ops import get_broker  # 按 execution_mode 返 QMT/paper broker

    engine = PlatformRiskEngine(
        primary_source=QMTPositionSource(redis_client),
        fallback_source=DBPositionSource(conn_factory=get_conn),
        broker=get_broker(settings.EXECUTION_MODE),
        conn_factory=get_conn,
        dingding_notifier=get_dingding(),
    )
    engine.register(PMSRule())

    context = engine.build_context(strategy_id=settings.PT_STRATEGY_ID)
    results = engine.run(context)
    engine.execute(results, context)
```

**Celery Beat 保留 14:30** (ADR-010 D6 D7 — 原 `pms_engine` Beat 已 Session 21 PR #34 停, 现批 1 重启 on 新 task 名 `risk_check`). Beat schedule: `beat_schedule.py::risk-daily-check` 14:30 MoFr.

---

## 7 · 测试策略 (4 层)

| 层 | 文件 | tests | 覆盖 |
|---|---|---|---|
| **L1 Unit** (纯逻辑) | `test_risk_rules_pms.py` | ~12 | PMSRule 3 Level × 3 scenario (触发/边界/不触发) + neg price / entry=0 / peak<entry 异常 |
| **L1 Unit** (engine) | `test_risk_engine.py` | ~12 | register 去重 / build_context fallback 切换 / run 分发 / execute broker 调用 / _log_event INSERT |
| **L2 Integration** (Source × DB/Redis mock) | `test_risk_sources.py` | ~6 | QMTSource 读 Redis / DBSource 读 position_snapshot+trade_log / primary 挂 fallback 切 |
| **L4 E2E smoke** | `smoke/test_mvp_3_1_risk_live.py` | 1 | subprocess 启动 pms_check task → broker mock 记录 sell() 被调 → risk_event_log 有 1 行 → dingding mock 收到通知 |

**验收数字**: 31 新 tests PASS, baseline fail 不增 (铁律 40), pre-push smoke 30+1 = 31 PASS.

---

## 8 · 实施顺序 (8 commit / 8 PR 单 session 不现实, 拆 3-4 PR)

**建议 3 PR 拆分** (LL-059 9 步闭环 × 3 轮):

| PR | 内容 | 行数 | 硬门 | 预 reviewer |
|---|---|---|---|---|
| **PR 1** | migrations risk_event_log + rollback + smoke migration 自跑验证 | ~80 | migration apply + rollback + re-apply 幂等 | database-reviewer |
| **PR 2** | platform/risk/ 骨架 (interface + engine + sources + rules) + 30 unit | ~700 | pytest 30 PASS + smoke fail 数不增 + ruff clean | code + python |
| **PR 3** | daily_pipeline pms_check → risk_check wire + L4 live smoke + Beat schedule rename | ~130 | live smoke PASS + 14:30 Beat Celery inspect 注册 | code + architect |

**单 PR 单提交 = 代码审查友好 + 回滚原子 + 风险隔离**. PR 1 不通过 PR 2 不开工.

---

## 9 · Precondition 硬门 (进实施模式前必 ✅)

- [x] MVP 3.1 父 doc 已读 (217 行, 本 session)
- [x] ADR-010 + addendum 已读 (187 + 251 行)
- [x] pms_engine.py 已读 (414 行, 迁移源完整)
- [x] backend/platform/_types.py 已读 (156 行, Severity 复用)
- [x] backend/platform/factor/interface.py 已读 (254 行, ABC 模式)
- [ ] `backend/app/services/execution_ops.py` broker 接口 (PR 2 前读)
- [ ] `backend/app/tasks/daily_pipeline.py::pms_check` 当前实现 (PR 3 前读)
- [ ] Redis `portfolio:current` hash schema (PR 2 前验: redis-cli HGETALL)
- [ ] `position_snapshot` + `trade_log` FK (PR 2 前验: DDL check)
- [ ] `PMS_LEVEL{1,2,3}_GAIN/DRAWDOWN` in `.env` (settings 生效确认)

**其余 5 项在对应 PR 开工前读, 不提前**.

---

## 10 · 风险 & 缓解 (批 1 specific)

| 风险 | 影响 | 缓解 |
|---|---|---|
| QMT Redis portfolio:current 60s 刷新延迟 | 14:30 跑时可能读到 14:29 数据, peak/current 轻微 stale | 月度策略可接受 (MVP 3.1 父 doc D3 已明示) |
| DBPositionSource fallback 读 T-1 (16:30 signal_phase 写, 14:30 跑) | 回归 PMS v1 T-1 盲区 | Redis primary 健康时零问题; primary 挂 → P0 钉钉人工介入 15 min |
| broker.sell timeout 卡 Engine | 14:30 跑超时 → Celery task timeout | execute() 内每次 broker 调用 5s timeout + 失败重试 1 次 + 再失败 raise → Celery task retry 策略兜底 |
| risk_event_log JSONB 单行 5-10KB × 触发爆量 | 磁盘膨胀 | 90 天 hypertable retention 自动 drop + 仅触发写入 (非 evaluation) |
| migration 部分失败 (CREATE TABLE 成但 hypertable 失败) | 表存在但无 retention 策略 | DO block 检查 5 列齐 + RAISE EXCEPTION; rollback.sql 幂等 DROP CASCADE |
| Celery Beat `risk-daily-check` 未正确注册 | 14:30 不跑 | PR 3 硬门: `celery inspect scheduled` 列出 + 一次手动 trigger 验证 |

---

## 11 · 启动时机

**用户确认本 plan 后**:
1. 进入实施模式 (铁律 39 显式声明)
2. 开 feature branch `feat/mvp-3-1-batch-1-risk-framework`
3. LL-059 9 步闭环 × 3 PR (见 §8)
4. 预 3-5 session 完成 (单 session 1 PR 节奏, 避免单 session 过重)

**Session 28 建议启动 PR 1** (最小最安全: 纯 DB migration, ~80 行, 1 reviewer, 可今晚收敛).

---

## 12 · Non-goals 重申

- ❌ 不动 L1/L2/L3 阈值 (`.env` 参数保留)
- ❌ 不迁 intraday_monitor (批 2)
- ❌ 不做 CB adapter (批 3)
- ❌ 不删 `pms_engine.py` (批 3 结束后删)
- ❌ 不改前端 /pms (Wave 4)
- ❌ 不做 VaR/CVaR (Wave 4+)

---

**END of MVP 3.1 批 1 详细 Plan**
