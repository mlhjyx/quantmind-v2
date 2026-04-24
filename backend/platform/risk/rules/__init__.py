"""Framework Risk — RiskRule concrete 实现.

批 1 ✅ Session 29: pms.py (PMSRule L1/L2/L3 顺序命中)
批 2 ✅ Session 30: intraday.py (PortfolioDrop3/5/8 + QMTDisconnect)
批 3 后续: circuit_breaker_adapter.py (方案 C Hybrid wrapper, ADR-010 addendum)
"""
from .intraday import (
    IntradayPortfolioDrop3PctRule,
    IntradayPortfolioDrop5PctRule,
    IntradayPortfolioDrop8PctRule,
    IntradayPortfolioDropRule,
    QMTConnectionReader,
    QMTDisconnectRule,
)
from .pms import PMSRule, PMSThreshold

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
]
