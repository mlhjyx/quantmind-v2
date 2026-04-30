"""Framework Risk — RiskRule concrete 实现.

批 1 ✅ Session 29: pms.py (PMSRule L1/L2/L3 顺序命中)
批 2 ✅ Session 30: intraday.py (PortfolioDrop3/5/8 + QMTDisconnect)
批 3 ✅ Session 30 末: circuit_breaker.py (方案 C Hybrid wrapper, ADR-010 addendum)
MVP 3.1b Phase 1 ✅ Session 44: single_stock.py (SingleStockStopLossRule, P0 真生产事件驱动)
MVP 3.1b Phase 1.5b ✅ Session 44: holding_time.py + new_position.py (时间维度)
批 2 P0 修 ✅ Session 45 (2026-04-30): qmt_fallback.py (T0-15 LL-081 v2 扩 cache fallback)
"""
from .circuit_breaker import CircuitBreakerRule
from .holding_time import PositionHoldingTimeRule
from .intraday import (
    IntradayPortfolioDrop3PctRule,
    IntradayPortfolioDrop5PctRule,
    IntradayPortfolioDrop8PctRule,
    IntradayPortfolioDropRule,
    QMTConnectionReader,
    QMTDisconnectRule,
)
from .new_position import NewPositionVolatilityRule
from .pms import PMSRule, PMSThreshold
from .qmt_fallback import QMTFallbackTriggeredRule, RedisCacheHealthReader
from .single_stock import SingleStockStopLossRule, StopLossThreshold

__all__ = [
    # 批 1
    "PMSRule",
    "PMSThreshold",
    # 批 2
    "IntradayPortfolioDropRule",  # abstract base
    "IntradayPortfolioDrop3PctRule",
    "IntradayPortfolioDrop5PctRule",
    "IntradayPortfolioDrop8PctRule",
    "QMTDisconnectRule",
    "QMTConnectionReader",  # Protocol for DI
    # 批 3
    "CircuitBreakerRule",  # Hybrid wrapper adapter (铁律 31 例外)
    # MVP 3.1b Phase 1 (单股层补全, Session 44 真生产事件驱动)
    "SingleStockStopLossRule",
    "StopLossThreshold",
    # MVP 3.1b Phase 1.5b (时间维度补全, Session 44)
    "PositionHoldingTimeRule",
    "NewPositionVolatilityRule",
    # 批 2 P0 修 (Session 45, T0-15 LL-081 v2)
    "QMTFallbackTriggeredRule",
    "RedisCacheHealthReader",  # Protocol for DI
]
