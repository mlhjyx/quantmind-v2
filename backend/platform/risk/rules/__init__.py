"""Framework Risk — RiskRule concrete 实现.

批 1: pms.py (PMSRule L1/L2/L3 顺序命中)
批 2: intraday.py (PortfolioDrop3/5/8 + QMTDisconnect)
批 3: circuit_breaker_adapter.py (方案 C Hybrid wrapper, ADR-010 addendum)
"""
from .pms import PMSRule

__all__ = ["PMSRule"]
