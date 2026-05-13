"""V3 §5.3 Bull/Bear regime — pure dataclass + Enum contract (TB-2a foundation).

本模块 0 IO / 0 DB / 0 Redis / 0 LiteLLM (铁律 31 Platform Engine PURE).
所有 IO 由 concrete service (TB-2b service.py) + repository.py 承担.

对齐 V3 §5.3 (Bull/Bear regime detection) + V3 §11.2 line 1227 (MarketRegimeService location)
+ ADR-036 (V4-Pro mapping for BULL_AGENT + BEAR_AGENT + JUDGE) + ADR-064 (Plan v0.2 D2 sustained).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RegimeLabel(StrEnum):
    """V3 §5.3 4-state regime label — 对齐 market_regime_log.regime CHECK constraint.

    Note: str subclass for natural JSON / SQL serialization (.value sustained per
    ADR-029 + ADR-036 Severity enum 体例).
    """

    BULL = "Bull"
    BEAR = "Bear"
    NEUTRAL = "Neutral"
    TRANSITIONING = "Transitioning"


class MarketRegimeError(RuntimeError):
    """MarketRegimeService failures (LLM timeout / parse fail / Judge inconsistency / etc).

    Caller (TB-2b service) raises this for fail-loud 路径 (铁律 33).
    """


@dataclass(frozen=True)
class RegimeArgument:
    """Single Bull or Bear argument from V4-Pro agent.

    Args:
      argument: 论据陈述 (e.g. "北向资金 5 日净流入 ¥120 亿创近月新高").
      evidence: 支撑数据 / 引用 (e.g. "Wind 数据 2026-05-14 收盘").
      weight: agent self-assessed weight ∈ [0, 1]. Judge 最终加权时参考但不强制.
    """

    argument: str
    evidence: str = ""
    weight: float = 0.0

    def __post_init__(self) -> None:
        # 铁律 33 fail-loud: 论据陈述不可为空 (反 silent empty arg → degraded debate).
        if not self.argument or not self.argument.strip():
            raise ValueError("RegimeArgument.argument must be non-empty")
        # weight 范围检查 — agent 输出未校验时 LLM 可能给 1.5 / -0.3.
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError(f"RegimeArgument.weight must be in [0, 1], got {self.weight}")


@dataclass(frozen=True)
class MarketIndicators:
    """V3 §5.3 输入快照 — 5 维 market state input for Bull/Bear/Judge debate.

    Args:
      timestamp: tz-aware datetime (铁律 41 Asia/Shanghai trading session OR UTC).
      sse_return: 上证综指当日 return (e.g. -0.03 = -3%). None when data not available.
      hs300_return: 沪深 300 当日 return.
      breadth_up: 全市场上涨家数.
      breadth_down: 全市场下跌家数.
      north_flow_cny: 北向资金当日净流入 (亿 CNY, 负数 = 流出). None on Tushare timeout.
      iv_50etf: 50ETF 期权隐含波动率 (恐慌指数 proxy, 沿用 V3 §5.3 line 658).

    Note: 所有数值字段 Optional 容忍 source feed timeout (Tushare / Wind / etc) —
    LLM agents 接收 dict 时 None 字段 will be marked "data unavailable" in prompt
    per TB-2b prompt 体例.
    """

    timestamp: datetime
    sse_return: float | None = None
    hs300_return: float | None = None
    breadth_up: int | None = None
    breadth_down: int | None = None
    north_flow_cny: float | None = None
    iv_50etf: float | None = None

    def __post_init__(self) -> None:
        # 铁律 41 timezone-aware 强制 (反 naive datetime silent drift).
        if self.timestamp.tzinfo is None:
            raise ValueError("MarketIndicators.timestamp must be tz-aware (铁律 41 sustained)")
        # breadth 计数自然数检查
        if self.breadth_up is not None and self.breadth_up < 0:
            raise ValueError(f"breadth_up must be ≥ 0, got {self.breadth_up}")
        if self.breadth_down is not None and self.breadth_down < 0:
            raise ValueError(f"breadth_down must be ≥ 0, got {self.breadth_down}")

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for market_indicators JSONB column.

        Returns:
            Dict with timestamp ISO + 5 numeric fields (None preserved as null).
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "sse_return": self.sse_return,
            "hs300_return": self.hs300_return,
            "breadth_up": self.breadth_up,
            "breadth_down": self.breadth_down,
            "north_flow_cny": self.north_flow_cny,
            "iv_50etf": self.iv_50etf,
        }


@dataclass(frozen=True)
class MarketRegime:
    """V3 §5.3 Bull/Bear regime detection result — MarketRegimeService.classify() output.

    Args:
      timestamp: tz-aware datetime when classification ran (铁律 41).
      regime: RegimeLabel Enum (Bull/Bear/Neutral/Transitioning).
      confidence: Judge confidence ∈ [0, 1] (CHECK constrained in DDL).
      bull_arguments: tuple of 3 RegimeArgument from Bull Agent V4-Pro.
      bear_arguments: tuple of 3 RegimeArgument from Bear Agent V4-Pro.
      judge_reasoning: Judge V4-Pro reasoning text (full LLM output, may be long).
      indicators: MarketIndicators input snapshot (audit trail).
      cost_usd: total cost across Bull + Bear + Judge calls (LiteLLM router audit).

    Frozen + immutable per Platform Engine 体例 (sustained V3 §11.4 + interface.py:21-22).
    """

    timestamp: datetime
    regime: RegimeLabel
    confidence: float
    bull_arguments: tuple[RegimeArgument, ...] = field(default_factory=tuple)
    bear_arguments: tuple[RegimeArgument, ...] = field(default_factory=tuple)
    judge_reasoning: str = ""
    indicators: MarketIndicators | None = None
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        # 铁律 41 timezone-aware 强制.
        if self.timestamp.tzinfo is None:
            raise ValueError("MarketRegime.timestamp must be tz-aware (铁律 41 sustained)")
        # confidence 范围对齐 DDL CHECK.
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"MarketRegime.confidence must be in [0, 1], got {self.confidence}")
        # cost_usd 非负 (LiteLLM router 反向报负成本 = audit drift).
        if self.cost_usd < 0:
            raise ValueError(f"MarketRegime.cost_usd must be ≥ 0, got {self.cost_usd}")

    def bull_arguments_jsonable(self) -> list[dict[str, Any]]:
        """Serialize bull_arguments tuple to JSONB-ready list of dicts."""
        return [
            {"argument": a.argument, "evidence": a.evidence, "weight": a.weight}
            for a in self.bull_arguments
        ]

    def bear_arguments_jsonable(self) -> list[dict[str, Any]]:
        """Serialize bear_arguments tuple to JSONB-ready list of dicts."""
        return [
            {"argument": a.argument, "evidence": a.evidence, "weight": a.weight}
            for a in self.bear_arguments
        ]
