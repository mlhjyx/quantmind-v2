"""Service层 — 业务逻辑聚合。

所有Service通过FastAPI Depends(get_db)注入AsyncSession。
"""

from app.services.dashboard_service import DashboardService
from app.services.paper_trading_service import PaperTradingService
from app.services.risk_control_service import RiskControlService
from app.services.strategy_service import StrategyService

__all__ = [
    "DashboardService",
    "PaperTradingService",
    "RiskControlService",
    "StrategyService",
]
