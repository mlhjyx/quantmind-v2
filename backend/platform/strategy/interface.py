"""Framework #3 Strategy — "策略" 成为一等公民, 支持 multi-strategy.

目标: 当前 PT 单策略 (CORE3+dv_ttm) 需升级为 S1, 为 Wave 3 第 2 策略 (PEAD) 铺路.

关联铁律:
  - 16: 信号路径唯一且契约化 (Strategy.generate_signals 是唯一入口)
  - 18: 回测成本与实盘对齐 (Strategy.cost_model 声明)

实施时机:
  - MVP 3.1 Strategy Framework: Strategy 基类 + Registry DB 表
  - MVP 3.0a PEAD 前置: PIT bias 修复 + PMS v2 + cost H0-v2 (平行 3 周)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.platform._types import Signal


class RebalanceFreq(Enum):
    """调仓频率.

    DAILY / WEEKLY / MONTHLY / EVENT — 由因子 IC decay 决定.
    EVENT: 事件驱动 (如 PEAD, 由 announcement 触发).
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    EVENT = "event"


class StrategyStatus(Enum):
    """策略状态."""

    DRAFT = "draft"              # 设计阶段
    BACKTEST = "backtest"        # 回测验证中
    DRY_RUN = "dry_run"          # PT dry-run (paper)
    LIVE = "live"                # 真实交易
    PAUSED = "paused"            # 暂停 (保留仓位)
    RETIRED = "retired"          # 退役 (清仓后)


@dataclass(frozen=True)
class StrategyContext:
    """策略执行上下文 (由调度器注入).

    Args:
      trade_date: 当前交易日
      capital: 策略分配的资本
      universe: 当日可交易 universe (已 filter 停牌/ST/BJ/新股)
      regime: 当前 regime 标签 (e.g. "bull_small_cap")
      metadata: 扩展上下文 (如盘中实时行情)
    """

    trade_date: date
    capital: Decimal
    universe: list[str]
    regime: str
    metadata: dict[str, Any]


class Strategy(ABC):
    """策略基类 — 所有策略 (S1 monthly ranking / S2 PEAD event-driven / ...) 必须继承.

    子类必须声明类级属性:
      strategy_id: str — 唯一标识
      factor_pool: list[str] — 依赖因子清单 (必须都在 FactorRegistry 中 ACTIVE)
      rebalance_freq: RebalanceFreq
    """

    strategy_id: str
    factor_pool: list[str]
    rebalance_freq: RebalanceFreq
    status: StrategyStatus

    @abstractmethod
    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        """根据当日上下文生成目标仓位信号.

        Returns:
          Signal 列表, target_weight 已归一化 sum ≤ 1.0.
          空列表合法 (e.g. event-driven 无触发日).

        Raises:
          DataUnavailable: 依赖因子数据缺失 (fail-loud, 铁律 33)
          ConfigDrift: 因子 ACTIVE 状态变化未同步配置
        """

    @abstractmethod
    def validate_signals(self, signals: list[Signal], ctx: StrategyContext) -> list[Signal]:
        """信号校验 + 过滤 (涨跌停 / 停牌 / 流动性).

        默认调用 Platform 公共 validator. 子类可覆盖自定义规则.
        """


class StrategyRegistry(ABC):
    """策略注册表 — 生产 PT 只跑 status=LIVE 的策略."""

    @abstractmethod
    def register(self, strategy: Strategy) -> None:
        """注册策略 (写入 strategy_registry DB 表)."""

    @abstractmethod
    def get_live(self) -> list[Strategy]:
        """返回所有 LIVE 状态策略 (PT 调度遍历用)."""

    @abstractmethod
    def get_by_id(self, strategy_id: str) -> Strategy:
        """按 ID 取策略实例.

        Raises:
          StrategyNotFound: ID 不存在
        """

    @abstractmethod
    def update_status(
        self, strategy_id: str, new_status: StrategyStatus, reason: str
    ) -> None:
        """变更策略状态 (带审计日志)."""


class CapitalAllocator(ABC):
    """跨策略资本分配 — 解决 multi-strategy 共享 100 万的问题.

    MVP 3.1: 先等权 (1/N).
    Wave 3+: Risk Budgeting (vol-target / max-drawdown budget).
    """

    @abstractmethod
    def allocate(
        self, strategies: list[Strategy], total_capital: Decimal, regime: str
    ) -> dict[str, Decimal]:
        """返回 strategy_id → 分配资本映射.

        Args:
          strategies: 参与分配的活跃策略
          total_capital: 总资本 (扣除 cash buffer)
          regime: 当前 regime (用于 regime-dependent 分配)

        Returns:
          dict, sum(values) ≤ total_capital
        """
