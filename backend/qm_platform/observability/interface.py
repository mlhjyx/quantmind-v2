"""Framework #7 Observability — Metric / Alert / Event 统一接口.

目标: 6 个散落监控脚本 (pt_watchdog / monitor_factor_ic / health_check 等)
收编到 MetricExporter, 替代临时 print + log.

关联铁律:
  - 33: 禁止 silent failure (所有异常必发 Alert)

实施时机:
  - MVP 4.1 Observability Framework
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .._types import Severity


@dataclass(frozen=True)
class Metric:
    """标量指标记录.

    Args:
      name: 指标名 (dotted, e.g. "pt.signal.count")
      value: 数值 (float)
      labels: 标签 (e.g. {"strategy": "S1", "trade_date": "2026-04-17"})
      timestamp_utc: ISO UTC 字符串 (铁律 41: 内部必 UTC)
    """

    name: str
    value: float
    labels: dict[str, str]
    timestamp_utc: str


@dataclass(frozen=True)
class Alert:
    """告警事件.

    Args:
      title: 简短标题
      severity: P0 / P1 / P2 / INFO
      source: 发源模块 (e.g. "factor_lifecycle")
      details: 详细上下文
      trade_date: 关联交易日 (可空)
      timestamp_utc: 触发时间
    """

    title: str
    severity: Severity
    source: str
    details: dict[str, Any]
    trade_date: str | None
    timestamp_utc: str


class MetricExporter(ABC):
    """指标导出 — 走 StreamBus / Prometheus / 日志 (实现择其一).

    Application 用 SDK: MetricExporter.gauge / counter / histogram.
    禁止 Application 自建 print/log 代替 metric.
    """

    @abstractmethod
    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """记录瞬时值 (e.g. current_nav, signal_count)."""

    @abstractmethod
    def counter(self, name: str, increment: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """递增计数器 (e.g. orders_filled_total)."""

    @abstractmethod
    def histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """记录分布 (e.g. signal_generation_latency_ms)."""


class AlertRouter(ABC):
    """告警路由 — P0 → 短信/电话, P1 → 邮件, P2 → 日志, INFO → 丢弃.

    实现可以连 Telegram / Slack / 本地邮件.
    """

    @abstractmethod
    def fire(self, alert: Alert) -> None:
        """发送告警.

        Raises:
          AlertDispatchError: 所有 channel 都失败 (fail-loud, 铁律 33)
        """

    @abstractmethod
    def get_history(self, severity: Severity | None = None, limit: int = 100) -> list[Alert]:
        """查历史告警 (debug / 复盘用)."""


class EventBus(ABC):
    """事件总线 — Redis Streams (qm:{domain}:{event_type}) 的 Platform 抽象.

    U2 Event Sourcing 基础设施: 所有跨 Framework 通信走 EventBus,
    禁止直接 import (铁律 16 / Platform 分层).
    """

    @abstractmethod
    def publish(self, stream: str, event_type: str, payload: dict[str, Any]) -> str:
        """发布事件.

        Args:
          stream: 流名 (如 "qm:signal:generated")
          event_type: 类型 (如 "signal_generated")
          payload: 事件体

        Returns:
          event_id (Redis Streams XADD 返回的 ID)
        """

    @abstractmethod
    def subscribe(self, stream: str, consumer_group: str) -> None:
        """订阅流 (consumer group 模式, 支持 horizontal scale)."""
