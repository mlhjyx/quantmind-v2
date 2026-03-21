"""Paper Trading Service — Paper Trading状态查询与毕业标准评估。

CLAUDE.md毕业标准:
- 运行时长 >= 60个交易日
- Sharpe >= 回测Sharpe x 70%
- MDD <= 回测MDD x 1.5倍
- 滑点偏差 < 50%
- 全链路无中断
"""

from datetime import date
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.performance_repository import PerformanceRepository
from app.repositories.trade_repository import TradeRepository


# 毕业标准常量（CLAUDE.md §Paper Trading 毕业标准）
GRADUATION_MIN_DAYS: int = 60
GRADUATION_SHARPE_RATIO: float = 0.7  # >= 回测Sharpe × 70%
GRADUATION_MDD_RATIO: float = 1.5     # <= 回测MDD × 1.5倍
GRADUATION_SLIPPAGE_TOLERANCE: float = 0.5  # 偏差 < 50%


class PaperTradingService:
    """Paper Trading状态查询与毕业标准评估服务。

    通过FastAPI Depends注入session，聚合绩效和交易数据
    计算Paper Trading运行状态与毕业达标情况。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.perf_repo = PerformanceRepository(session)
        self.trade_repo = TradeRepository(session)

    async def get_status(
        self, strategy_id: str
    ) -> dict[str, Any]:
        """获取Paper Trading当前状态。

        Args:
            strategy_id: 策略ID。

        Returns:
            包含当前状态的字典：
            - nav: 最新净值
            - position_count: 持仓数
            - running_days: 已运行交易日数
            - sharpe: 滚动Sharpe
            - mdd: 最大回撤
            - total_return: 累计收益率
            - trade_date: 最新数据日期
            - graduation_ready: 是否达到毕业最低天数
        """
        latest = await self.perf_repo.get_latest_nav(strategy_id, "paper")
        # 用全量数据计算运行天数和统计指标
        full_series = await self.perf_repo.get_nav_series(
            strategy_id, execution_mode="paper"
        )
        running_days = len(full_series)

        rolling = await self.perf_repo.get_rolling_stats(
            strategy_id, lookback_days=running_days, execution_mode="paper"
        ) if running_days > 0 else None

        if not latest:
            return {
                "nav": 0,
                "position_count": 0,
                "running_days": 0,
                "sharpe": 0,
                "mdd": 0,
                "total_return": 0,
                "trade_date": None,
                "graduation_ready": False,
            }

        return {
            "nav": latest["nav"],
            "position_count": latest["position_count"],
            "running_days": running_days,
            "sharpe": rolling["sharpe"] if rolling else 0,
            "mdd": rolling["mdd"] if rolling else 0,
            "total_return": rolling["total_return"] if rolling else 0,
            "trade_date": latest["trade_date"],
            "graduation_ready": running_days >= GRADUATION_MIN_DAYS,
        }

    async def get_graduation_progress(
        self,
        strategy_id: str,
        backtest_sharpe: float = 0,
        backtest_mdd: float = 0,
        model_slippage_bps: float = 0,
    ) -> dict[str, Any]:
        """获取毕业标准达标情况。

        将Paper Trading实际表现与回测基准对比，逐项检查5条毕业标准。

        Args:
            strategy_id: 策略ID。
            backtest_sharpe: 回测Sharpe（来自策略配置/回测报告）。
            backtest_mdd: 回测最大回撤（负数，如-0.12）。
            model_slippage_bps: 模型预估滑点(bps)。

        Returns:
            毕业进度字典，包含：
            - criteria: 各项标准及达标状态列表
            - all_passed: 是否全部达标
            - summary: 达标项数/总项数
        """
        # 获取全量Paper Trading数据
        full_series = await self.perf_repo.get_nav_series(
            strategy_id, execution_mode="paper"
        )
        running_days = len(full_series)

        rolling = await self.perf_repo.get_rolling_stats(
            strategy_id, lookback_days=running_days, execution_mode="paper"
        ) if running_days > 0 else None

        actual_sharpe = rolling["sharpe"] if rolling else 0
        actual_mdd = rolling["mdd"] if rolling else 0

        # 计算实际平均滑点
        actual_slippage = await self._calc_avg_slippage(strategy_id)

        # 逐项检查毕业标准
        sharpe_target = backtest_sharpe * GRADUATION_SHARPE_RATIO
        mdd_limit = backtest_mdd * GRADUATION_MDD_RATIO if backtest_mdd < 0 else 0
        slippage_deviation = (
            abs(actual_slippage - model_slippage_bps) / model_slippage_bps
            if model_slippage_bps > 0
            else 0
        )

        criteria: list[dict[str, Any]] = [
            {
                "name": "运行时长",
                "target": f">= {GRADUATION_MIN_DAYS}个交易日",
                "actual": f"{running_days}个交易日",
                "passed": running_days >= GRADUATION_MIN_DAYS,
            },
            {
                "name": "Sharpe",
                "target": f">= {sharpe_target:.3f} (回测{backtest_sharpe:.3f} x 70%)",
                "actual": f"{actual_sharpe:.3f}",
                "passed": actual_sharpe >= sharpe_target if backtest_sharpe > 0 else False,
            },
            {
                "name": "最大回撤",
                "target": f"<= {mdd_limit:.4f} (回测{backtest_mdd:.4f} x 1.5)",
                "actual": f"{actual_mdd:.4f}",
                "passed": actual_mdd >= mdd_limit if backtest_mdd < 0 else True,
                # MDD是负数，actual >= limit表示回撤更小
            },
            {
                "name": "滑点偏差",
                "target": f"< 50% (模型{model_slippage_bps:.1f}bps)",
                "actual": f"{actual_slippage:.1f}bps (偏差{slippage_deviation:.1%})",
                "passed": slippage_deviation < GRADUATION_SLIPPAGE_TOLERANCE
                if model_slippage_bps > 0
                else True,
            },
            {
                "name": "链路完整性",
                "target": "信号->审批->执行->归因 全链路无中断",
                "actual": "待实现",  # Phase 1完善
                "passed": False,
            },
        ]

        passed_count = sum(1 for c in criteria if c["passed"])
        total_count = len(criteria)

        return {
            "criteria": criteria,
            "all_passed": passed_count == total_count,
            "summary": f"{passed_count}/{total_count}",
        }

    async def _calc_avg_slippage(
        self, strategy_id: str
    ) -> float:
        """计算Paper Trading的平均滑点(bps)。

        Args:
            strategy_id: 策略ID。

        Returns:
            平均滑点，单位bps。无交易记录时返回0。
        """
        trades = await self.trade_repo.get_trades(
            strategy_id, execution_mode="paper", limit=10000
        )
        if not trades:
            return 0

        slippages = [t["slippage_bps"] for t in trades if t["slippage_bps"] > 0]
        if not slippages:
            return 0

        return sum(slippages) / len(slippages)
