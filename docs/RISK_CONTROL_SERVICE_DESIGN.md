# RiskControlService 接口设计文档

> **Sprint 1.1 目标** | 作者: strategy agent | 日期: 2026-03-22
> **来源**: DESIGN_V5 8.1 + CLAUDE.md 风控层 + 当前 `check_circuit_breaker()` 简版升级

---

## 1. 背景与动机

当前 Paper Trading 的 `check_circuit_breaker()` 函数（`scripts/run_paper_trading.py:167`）存在以下局限：

1. **无状态**: 每次调用重新从 `performance_series` 计算，不记录熔断状态本身
2. **无恢复逻辑**: 触发 L3 降仓后，无法自动检测恢复条件并回补仓位
3. **L4 无审批流程**: 停止交易后只能手动改代码重启，缺少正式审批机制
4. **状态未持久化**: 重启进程后熔断状态丢失
5. **未与通知系统集成**: 状态变更通知散落在调用方

---

## 2. 4级熔断状态机

### 2.1 状态定义

```
NORMAL (L0) ── 正常交易
L1_PAUSED   ── 单策略日亏>3%, 暂停1天
L2_HALTED   ── 总组合日亏>5%, 全部暂停
L3_REDUCED  ── 月亏(滚动20日)>10%, 降仓50%
L4_STOPPED  ── 累计亏损>25%, 停止所有交易, 人工审批
```

### 2.2 状态转换规则

```
触发方向（升级）:
  NORMAL  → L1_PAUSED   : daily_return < -3%
  NORMAL  → L2_HALTED   : daily_return < -5%
  NORMAL  → L3_REDUCED  : rolling_20d_return < -10%
  NORMAL  → L4_STOPPED  : cumulative_return < -25%
  L1      → L2_HALTED   : daily_return < -5%（L1期间继续恶化）
  L1      → L3_REDUCED  : rolling_20d_return < -10%
  L3      → L4_STOPPED  : cumulative_return < -25%

恢复方向（降级）:
  L1_PAUSED  → NORMAL    : 次日自动恢复（1个交易日冷却）
  L2_HALTED  → NORMAL    : 次日自动恢复（1个交易日冷却）
  L3_REDUCED → NORMAL    : 连续5个交易日累计盈利 > 2%
  L4_STOPPED → NORMAL    : 人工审批通过（approval_queue）

注意:
  - 升级判断优先级: L4 > L3 > L2 > L1（先检查最严重级别）
  - 任何状态都可以直接跳到更高级别（不需要逐级升级）
  - 恢复只能降到 NORMAL（不存在 L4→L3 这种中间恢复）
```

### 2.3 状态行为矩阵

| 状态 | 允许调仓 | 仓位约束 | 自动恢复 | 告警级别 |
|------|---------|---------|---------|---------|
| NORMAL | 是 | 无 | - | - |
| L1_PAUSED | 否（跳过调仓） | 维持现有 | 次日自动 | P2 |
| L2_HALTED | 否（全部暂停） | 维持现有 | 次日自动 | P0 |
| L3_REDUCED | 是（只允许减仓） | 目标仓位 x 0.5 | 连续5日盈利>2% | P0 |
| L4_STOPPED | 否 | 清仓或冻结 | 人工审批 | P0 |

---

## 3. 数据模型

### 3.1 新增表: `circuit_breaker_state`

```sql
CREATE TABLE circuit_breaker_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategy(id),
    execution_mode  VARCHAR(10) NOT NULL DEFAULT 'paper',  -- paper/live
    current_level   SMALLINT NOT NULL DEFAULT 0,           -- 0=NORMAL, 1-4
    entered_at      TIMESTAMPTZ NOT NULL,                  -- 进入当前状态的时间
    entered_date    DATE NOT NULL,                         -- 进入当前状态的交易日
    trigger_reason  TEXT,                                  -- 触发原因描述
    trigger_metrics JSONB,                                 -- {"daily_return": -0.051, "rolling_20d": -0.12, ...}
    -- L3 恢复追踪
    recovery_streak_days  INT DEFAULT 0,                   -- 连续盈利天数(L3恢复用)
    recovery_streak_return DECIMAL(12,8) DEFAULT 0,        -- 连续盈利累计收益(L3恢复用)
    -- L3 仓位管理
    position_multiplier   DECIMAL(4,2) DEFAULT 1.0,        -- 仓位系数(L3=0.5, NORMAL=1.0)
    -- L4 审批
    approval_id     UUID REFERENCES approval_queue(id),    -- L4恢复关联的审批记录
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strategy_id, execution_mode)                    -- 每个策略+模式只有一行当前状态
);
COMMENT ON TABLE circuit_breaker_state IS '熔断状态机当前状态(每策略一行, 覆盖更新)';
```

### 3.2 新增表: `circuit_breaker_log`

```sql
CREATE TABLE circuit_breaker_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategy(id),
    execution_mode  VARCHAR(10) NOT NULL DEFAULT 'paper',
    trade_date      DATE NOT NULL,
    prev_level      SMALLINT NOT NULL,                     -- 变更前级别
    new_level       SMALLINT NOT NULL,                     -- 变更后级别
    transition_type VARCHAR(10) NOT NULL,                  -- 'escalate'/'recover'/'manual'
    reason          TEXT NOT NULL,
    metrics         JSONB,                                 -- 触发时的指标快照
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_cb_log_strategy_date ON circuit_breaker_log(strategy_id, trade_date DESC);
COMMENT ON TABLE circuit_breaker_log IS '熔断状态变更历史(只追加, 用于审计和复盘)';
```

---

## 4. 接口定义

```python
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


# ─────────────────────────────────────────────
# 枚举 & 数据结构
# ─────────────────────────────────────────────

class CircuitBreakerLevel(enum.IntEnum):
    """熔断级别。数值越大越严重。"""
    NORMAL = 0
    L1_PAUSED = 1    # 单策略日亏>3%, 暂停1天
    L2_HALTED = 2    # 总组合日亏>5%, 全部暂停
    L3_REDUCED = 3   # 月亏>10%, 降仓50%
    L4_STOPPED = 4   # 累计>25%, 停止交易


class TransitionType(str, enum.Enum):
    """状态变更类型。"""
    ESCALATE = "escalate"   # 升级(恶化)
    RECOVER = "recover"     # 自动恢复
    MANUAL = "manual"       # 人工审批恢复


@dataclass(frozen=True)
class CircuitBreakerState:
    """熔断状态快照, check_and_update 的返回值。"""
    level: CircuitBreakerLevel
    entered_date: date                    # 进入当前状态的交易日
    trigger_reason: str                   # 人类可读原因
    trigger_metrics: dict[str, Any]       # 触发时的量化指标
    position_multiplier: Decimal          # 仓位系数 (1.0=满仓, 0.5=半仓, 0.0=清仓)
    recovery_streak_days: int             # L3恢复: 连续盈利天数
    recovery_streak_return: Decimal       # L3恢复: 连续盈利累计收益
    can_rebalance: bool                   # 当前是否允许调仓
    approval_id: UUID | None              # L4关联的审批ID

    @property
    def is_normal(self) -> bool:
        return self.level == CircuitBreakerLevel.NORMAL

    @property
    def requires_manual_approval(self) -> bool:
        return self.level == CircuitBreakerLevel.L4_STOPPED


@dataclass(frozen=True)
class RiskMetrics:
    """每日风控指标, 由调用方组装后传入。"""
    trade_date: date
    daily_return: Decimal                 # 当日策略收益率
    nav: Decimal                          # 当日净值
    initial_capital: Decimal              # 初始资金
    cumulative_return: Decimal            # 累计收益率 (nav/initial - 1)
    rolling_20d_return: Decimal | None    # 滚动20日累计收益率 (不足20日传None)


@dataclass(frozen=True)
class CircuitBreakerTransition:
    """一次状态变更事件, 用于通知系统。"""
    strategy_id: UUID
    execution_mode: str
    trade_date: date
    prev_level: CircuitBreakerLevel
    new_level: CircuitBreakerLevel
    transition_type: TransitionType
    reason: str
    metrics: dict[str, Any]


# ─────────────────────────────────────────────
# 阈值配置
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class CircuitBreakerThresholds:
    """熔断阈值配置, 从 strategy_configs 或系统配置加载。

    硬编码默认值来自 DESIGN_V5 §8.1, AI无权修改(Level 0硬编码)。
    """
    l1_daily_loss: Decimal = Decimal("-0.03")       # 单日亏损 > 3%
    l2_daily_loss: Decimal = Decimal("-0.05")       # 单日亏损 > 5%
    l3_rolling_loss: Decimal = Decimal("-0.10")     # 滚动20日 > 10%
    l3_rolling_window: int = 20                     # 滚动窗口(交易日)
    l4_cumulative_loss: Decimal = Decimal("-0.25")  # 累计亏损 > 25%
    l3_position_multiplier: Decimal = Decimal("0.5")  # L3降仓系数
    l3_recovery_days: int = 5                       # L3恢复需连续盈利天数
    l3_recovery_return: Decimal = Decimal("0.02")   # L3恢复需累计盈利 > 2%


# ─────────────────────────────────────────────
# Service 接口
# ─────────────────────────────────────────────

class RiskControlService:
    """4级熔断风控Service。

    职责:
      1. 每日检查熔断触发条件, 更新状态机
      2. 管理L3降仓/恢复的仓位系数
      3. 管理L4人工审批流程
      4. 持久化状态到DB (circuit_breaker_state + circuit_breaker_log)
      5. 状态变更时发送通知

    依赖:
      - AsyncSession (FastAPI Depends注入)
      - NotificationService (发送钉钉/站内通知)

    调用时机:
      - Paper Trading / 实盘每日调度链路中, 在信号生成之后、执行调仓之前调用
      - 对应当前 run_paper_trading.py Step 5.9 的位置

    使用示例:
        risk_svc = RiskControlService(session, notification_svc)
        state = await risk_svc.check_and_update(strategy_id, "paper", metrics)
        if not state.can_rebalance:
            # 跳过调仓或仅允许减仓
            ...
        target_weights = {k: v * float(state.position_multiplier) for k, v in raw_weights.items()}
    """

    def __init__(
        self,
        session: "AsyncSession",
        notification_service: "NotificationService",
        thresholds: CircuitBreakerThresholds | None = None,
    ) -> None:
        """初始化风控Service。

        Args:
            session: SQLAlchemy异步会话 (通过Depends注入)
            notification_service: 通知服务实例 (通过Depends注入)
            thresholds: 熔断阈值配置, None时使用DESIGN_V5默认值
        """
        ...

    # ── 核心方法 ──

    async def check_and_update(
        self,
        strategy_id: UUID,
        execution_mode: str,
        metrics: RiskMetrics,
    ) -> CircuitBreakerState:
        """每日熔断检查: 评估触发条件 + 评估恢复条件 + 更新状态 + 发通知。

        这是每日调度链路的主入口, 完成以下步骤:
          1. 从DB加载当前状态 (首次运行自动初始化为NORMAL)
          2. 如果当前非NORMAL, 先检查恢复条件:
             - L1/L2: 是否已过冷却期(1个交易日)
             - L3: 连续盈利天数和累计收益是否达标
             - L4: 对应的approval_queue记录是否已approved
          3. 如果恢复条件满足, 降级到NORMAL
          4. 不管是否刚恢复, 都重新检查触发条件(防止恢复当日又触发)
          5. 如果状态变更, 写入circuit_breaker_log + 更新circuit_breaker_state
          6. 如果状态变更, 调用通知服务

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"
            metrics: 当日风控指标

        Returns:
            CircuitBreakerState: 更新后的当前状态

        Raises:
            ValueError: metrics参数不合法
        """
        ...

    async def get_current_state(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> CircuitBreakerState:
        """获取当前熔断状态(只读, 不触发检查)。

        用于前端展示、其他Service查询当前风控状态。
        如果DB中无记录(首次), 返回NORMAL默认状态。

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"

        Returns:
            CircuitBreakerState: 当前状态快照
        """
        ...

    # ── 恢复管理 ──

    async def request_l4_recovery(
        self,
        strategy_id: UUID,
        execution_mode: str,
        reviewer_note: str,
    ) -> UUID:
        """发起L4人工审批恢复请求。

        创建一条approval_queue记录, 关联到当前circuit_breaker_state。
        审批通过后, 下次check_and_update会自动检测并恢复到NORMAL。

        前置条件: 当前状态必须是L4_STOPPED。

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"
            reviewer_note: 审批请求说明(为什么认为可以恢复)

        Returns:
            UUID: approval_queue记录ID

        Raises:
            InvalidStateError: 当前不是L4状态
        """
        ...

    async def approve_l4_recovery(
        self,
        approval_id: UUID,
        approved: bool,
        reviewer_note: str = "",
    ) -> CircuitBreakerState | None:
        """审批L4恢复请求。

        如果approved=True, 立即更新circuit_breaker_state为NORMAL。
        如果approved=False, 更新approval_queue为rejected, 状态保持L4。

        Args:
            approval_id: approval_queue记录ID
            approved: 是否批准
            reviewer_note: 审批意见

        Returns:
            CircuitBreakerState: 审批通过时返回新状态; 拒绝时返回None
        """
        ...

    # ── L3 仓位管理 ──

    async def get_position_multiplier(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> Decimal:
        """获取当前仓位系数。

        NORMAL=1.0, L3=0.5, L4=0.0, L1/L2=1.0(不调仓但不改系数)。
        调仓逻辑用此系数缩放目标权重:
          actual_target = raw_target * position_multiplier

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"

        Returns:
            Decimal: 仓位系数 (0.0 ~ 1.0)
        """
        ...

    async def update_recovery_streak(
        self,
        strategy_id: UUID,
        execution_mode: str,
        daily_return: Decimal,
    ) -> None:
        """更新L3恢复追踪的连续盈利计数。

        内部方法, 由check_and_update调用。独立出来便于测试。

        规则:
          - 如果当日盈利(daily_return > 0): streak_days += 1, streak_return 累积
          - 如果当日亏损(daily_return <= 0): streak_days = 0, streak_return = 0 (重置)
          - streak_days >= 5 且 streak_return > 2%: 满足恢复条件

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"
            daily_return: 当日收益率
        """
        ...

    # ── 查询 & 审计 ──

    async def get_transition_history(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
        limit: int = 50,
    ) -> list[CircuitBreakerTransition]:
        """获取熔断状态变更历史。

        从circuit_breaker_log读取, 按trade_date降序。
        用于前端风控历史页面和复盘分析。

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"
            limit: 最大返回条数

        Returns:
            list[CircuitBreakerTransition]: 变更历史列表(最新在前)
        """
        ...

    async def get_risk_summary(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> dict[str, Any]:
        """获取风控概览摘要, 供前端Dashboard展示。

        返回内容:
          - current_level: 当前熔断级别
          - days_in_current_state: 在当前状态已持续天数
          - total_escalations: 历史升级次数
          - last_escalation_date: 最近一次升级日期
          - l3_recovery_progress: L3恢复进度 (如 "3/5天, 1.2%/2.0%")
          - thresholds: 当前使用的阈值配置

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"

        Returns:
            dict: 风控概览
        """
        ...

    # ── 初始化 & 工具 ──

    async def initialize_state(
        self,
        strategy_id: UUID,
        execution_mode: str = "paper",
    ) -> CircuitBreakerState:
        """初始化熔断状态(首次运行时)。

        在circuit_breaker_state表中插入NORMAL状态记录。
        如果记录已存在, 直接返回现有状态(幂等)。

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"

        Returns:
            CircuitBreakerState: 初始状态
        """
        ...

    async def force_reset(
        self,
        strategy_id: UUID,
        execution_mode: str,
        reason: str,
    ) -> CircuitBreakerState:
        """强制重置到NORMAL状态(运维用, 需记录审计日志)。

        仅限运维紧急情况使用。会在circuit_breaker_log中记录
        transition_type='manual'。

        Args:
            strategy_id: 策略UUID
            execution_mode: "paper" 或 "live"
            reason: 强制重置原因(必填, 用于审计)

        Returns:
            CircuitBreakerState: 重置后状态
        """
        ...

    # ── 内部方法 ──

    async def _check_trigger_conditions(
        self,
        metrics: RiskMetrics,
    ) -> tuple[CircuitBreakerLevel, str, dict[str, Any]]:
        """评估熔断触发条件(纯计算, 不写DB)。

        按严重程度从高到低检查: L4 → L3 → L2 → L1 → NORMAL。

        Args:
            metrics: 当日风控指标

        Returns:
            tuple: (触发级别, 原因描述, 指标快照)
        """
        ...

    async def _check_recovery_conditions(
        self,
        state: CircuitBreakerState,
        metrics: RiskMetrics,
    ) -> bool:
        """评估恢复条件(纯计算, 不写DB)。

        L1/L2: entered_date < metrics.trade_date (已过1个交易日)
        L3: recovery_streak_days >= 5 且 recovery_streak_return > 2%
        L4: 关联的approval_queue.status == 'approved'

        Args:
            state: 当前熔断状态
            metrics: 当日风控指标

        Returns:
            bool: 是否满足恢复条件
        """
        ...

    async def _persist_transition(
        self,
        strategy_id: UUID,
        execution_mode: str,
        transition: CircuitBreakerTransition,
        new_state: CircuitBreakerState,
    ) -> None:
        """持久化状态变更: 更新state表 + 追加log表(单事务)。"""
        ...

    async def _notify_transition(
        self,
        transition: CircuitBreakerTransition,
    ) -> None:
        """状态变更通知: 通过NotificationService发送。

        通知规则:
          - L1: P2级别, 站内通知
          - L2: P0级别, 钉钉 + 站内通知
          - L3: P0级别, 钉钉 + 站内通知
          - L4: P0级别, 钉钉 + 站内通知 + 邮件
          - 恢复到NORMAL: P2级别, 站内通知
        """
        ...
```

---

## 5. 调用方集成

### 5.1 每日调度链路中的调用位置

```python
# 在 run_paper_trading.py (或未来的 Celery task) 中:

# Step 5.9: 熔断检查
metrics = RiskMetrics(
    trade_date=exec_date,
    daily_return=Decimal(str(latest_daily_return)),
    nav=Decimal(str(latest_nav)),
    initial_capital=Decimal(str(initial_capital)),
    cumulative_return=Decimal(str(latest_nav / initial_capital - 1)),
    rolling_20d_return=Decimal(str(rolling_20d)) if rolling_20d is not None else None,
)

state = await risk_svc.check_and_update(strategy_id, "paper", metrics)

if state.level >= CircuitBreakerLevel.L4_STOPPED:
    logger.error(f"[L4 HALT] {state.trigger_reason}")
    sys.exit(1)

if not state.can_rebalance:
    logger.warning(f"[L{state.level}] 跳过调仓: {state.trigger_reason}")
else:
    # 用 position_multiplier 缩放目标权重
    hedged_target = {
        k: v * float(state.position_multiplier)
        for k, v in raw_target.items()
    }
```

### 5.2 前端 API 路由

```python
# GET /api/risk/state/{strategy_id}
#   → risk_svc.get_current_state()
#   → 返回当前熔断状态

# GET /api/risk/history/{strategy_id}?limit=50
#   → risk_svc.get_transition_history()
#   → 返回变更历史

# GET /api/risk/summary/{strategy_id}
#   → risk_svc.get_risk_summary()
#   → 返回风控概览

# POST /api/risk/l4-recovery/{strategy_id}
#   → risk_svc.request_l4_recovery()
#   → 发起L4恢复审批

# POST /api/risk/l4-approve/{approval_id}
#   → risk_svc.approve_l4_recovery()
#   → 审批L4恢复
```

---

## 6. L3 降仓与回补流程

```
触发降仓:
  1. check_and_update 检测到 rolling_20d < -10%
  2. 状态升级到 L3_REDUCED, position_multiplier 设为 0.5
  3. 调用方用 multiplier 缩放目标权重: target * 0.5
  4. 执行调仓(只允许卖出方向, 不允许新开仓)

L3 期间:
  5. 每日 check_and_update 调用 update_recovery_streak
  6. 如果当日盈利: streak_days++, streak_return 累积
  7. 如果当日亏损: streak 重置为 0

恢复回补:
  8. 连续5天盈利且累计>2%: 恢复到 NORMAL
  9. position_multiplier 恢复为 1.0
  10. 下次调仓按正常目标权重执行(自然回补, 不是一次性加仓)

注意:
  - L3期间如果 cumulative_return < -25%, 直接升级到 L4
  - 回补是渐进式的: 恢复NORMAL后按正常调仓频率自然填充仓位
  - 不做一次性从50%仓位跳到100%仓位的操作(冲击成本+风险)
```

---

## 7. 与现有系统的关系

| 组件 | 交互方式 |
|------|---------|
| `performance_series` 表 | 调用方从此表计算 RiskMetrics 后传入(Service 本身不读此表) |
| `approval_queue` 表 | L4 恢复审批写入此表, approve_l4_recovery 更新此表 |
| `notifications` 表 | 通过 NotificationService 写入 |
| `circuit_breaker_state` 表 | **新增**, Service 独占读写 |
| `circuit_breaker_log` 表 | **新增**, Service 独占写入, 前端可读 |
| `strategy_configs` | 可选: 从中加载自定义阈值覆盖默认值 |

---

## 8. 测试策略

### 8.1 单元测试(必须覆盖)

1. **状态转换完整性**: 验证所有合法转换路径(升级+恢复)
2. **非法转换拒绝**: 验证不存在的转换路径被拒绝(如 L4→L3)
3. **L3恢复计数**: 连续5天盈利恢复、中间亏损重置、累计不足2%不恢复
4. **L4审批流程**: 未审批不恢复、审批通过恢复、审批拒绝保持
5. **阈值边界**: daily_return 恰好等于 -3%/-5% 的边界行为
6. **首次运行**: 无历史数据时自动初始化为 NORMAL
7. **幂等性**: 重复调用 check_and_update 同一天数据结果一致

### 8.2 集成测试

1. **完整升级-恢复周期**: NORMAL → L3 → (5天盈利) → NORMAL
2. **跨日状态持久化**: 重启进程后状态从DB恢复
3. **通知发送**: 状态变更时 NotificationService 被正确调用
4. **与调仓联动**: position_multiplier 正确影响目标权重
