"""Framework #6 Signal & Execution — 唯一信号→订单路径, 配置真正 SSOT.

目标: 收编 PAPER_TRADING_CONFIG 硬编码 + pt_live.yaml 分裂, 所有 signal → order
路径走此 Framework, 实现铁律 16 "信号路径唯一且契约化".

关联铁律:
  - 16: 信号路径唯一且契约化
  - 26: 验证不可跳过不可敷衍 (signal 校验链)
  - 32: Service 不 commit (OrderRouter 不自持事务)
  - 34: 配置 single source of truth

实施时机:
  - MVP 3.2 Signal/Exec Framework: SignalPipeline + OrderRouter + 审计链
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .._types import Order, Signal
    from ..strategy.interface import Strategy, StrategyContext


@dataclass(frozen=True)
class AuditChain:
    """fill → order → signal → strategy → factor 反向审计链 (U2 Event Sourcing).

    Args:
      fill_id: 成交记录 ID
      order_id: 订单 ID
      signal_trace: 信号生成轨迹 (含 factor 分解)
      strategy_id: 归属策略
      factor_contributions: 各因子贡献占比
      timestamps: 各环节时间戳 (ISO UTC)
    """

    fill_id: str
    order_id: str
    signal_trace: dict[str, Any]
    strategy_id: str
    factor_contributions: dict[str, float]
    timestamps: dict[str, str]


class SignalPipeline(ABC):
    """信号生成管道 — offline (回测) / online (PT) 同一方法.

    关联铁律 16: 研究脚本 / PT / 回测 必须用同一 SignalPipeline, 禁绕路实现.
    """

    @abstractmethod
    def compose(
        self, factor_pool: list[str], trade_date: date, ctx: StrategyContext
    ) -> list[Signal]:
        """按因子池合成目标仓位信号 (等权 / 加权 / ML 由实现决定).

        Args:
          factor_pool: 因子名列表 (必须在 FactorRegistry 中 ACTIVE)
          trade_date: 信号日
          ctx: 策略上下文 (提供 universe / capital / regime)

        Returns:
          Signal 列表, sum(target_weight) ≤ 1.0.

        Raises:
          FactorStaleError: 某因子数据 stale (DB max_date 落后交易日 > 1)
          UniverseEmpty: 过滤后 universe 空
        """

    @abstractmethod
    def generate(self, strategy: Strategy, ctx: StrategyContext) -> list[Signal]:
        """给定策略 + ctx, 返回信号 (strategy.generate_signals 的 SDK 入口).

        与 compose 区别: 此方法走策略对象, compose 走因子池直合成.
        """


class OrderRouter(ABC):
    """信号 → 订单路由 — 考虑换手限制 / 整手 / 行业 cap / 现金缓冲.

    关联铁律 32: 不自持事务, 调用方 (PT Task) 管理.
    """

    @abstractmethod
    def route(
        self,
        signals: list[Signal],
        current_positions: dict[str, int],
        capital_allocation: dict[str, Decimal],
        turnover_cap: float = 0.5,
    ) -> list[Order]:
        """计算目标持仓 vs 当前持仓的 diff, 产生订单.

        Args:
          signals: 合成后的目标信号
          current_positions: code → quantity (当前 QMT 持仓)
          capital_allocation: strategy_id → allocated capital
          turnover_cap: 换手率上限 (默认 50%)

        Returns:
          Order 列表, 每个 order 幂等键 (order_id hash)

        Raises:
          IdempotencyViolation: 重复 order_id
          InsufficientCapital: 现金不足执行 BUY 侧
        """

    @abstractmethod
    def cancel_stale(self, cutoff_seconds: int = 300) -> list[str]:
        """撤销超时未成交订单.

        Returns:
          已撤 order_id 列表
        """


class ExecutionAuditTrail(ABC):
    """执行审计链 — 反向追溯 fill 到 factor (Event Sourcing U2 消费方).

    用途: 归因分析 / 事故复盘 / 监管审计.
    """

    @abstractmethod
    def trace(self, fill_id: str) -> AuditChain:
        """给定 fill_id 返回完整审计链.

        Raises:
          AuditMissing: 链路中断 (某环节未记录事件)
        """

    @abstractmethod
    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        """记录一个 signal/order/fill 事件 (发 Event Bus + outbox)."""
