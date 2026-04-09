"""执行器抽象。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from engines.backtest.types import Fill

if TYPE_CHECKING:
    from engines.backtest.broker import SimBroker

# ============================================================
# BaseExecutor — 执行器抽象 (Phase 4)
# ============================================================

class BaseExecutor:
    """执行器基类。将交易决策转为实际成交。

    Phase 4前置: 为NestedExecutor(月度→日度多层执行)预留扩展点。
    当前仅有SimpleExecutor(直接调用SimBroker)。
    """

    def execute(
        self,
        trade_decision: dict[str, float],
        broker: SimBroker,
        portfolio_value: float,
        exec_date: date,
        price_idx,
        daily_close: dict,
    ) -> list[Fill]:
        """执行交易决策。

        Args:
            trade_decision: {code: target_weight}
            broker: SimBroker实例
            portfolio_value: 当前组合市值
            exec_date: 执行日期
            price_idx: 价格索引
            daily_close: {code: close}

        Returns:
            成交记录列表
        """
        raise NotImplementedError


class SimpleExecutor(BaseExecutor):
    """直接执行: 先卖后买, 委托SimBroker。"""

    def execute(self, trade_decision, broker, portfolio_value, exec_date, price_idx, daily_close):
        fills = []
        target = trade_decision

        # 先卖(不在目标或超配)
        for code in list(broker.holdings.keys()):
            if code not in target:
                row = price_idx.get((code, exec_date))
                if row is not None and broker.can_trade(code, "sell", row):
                    shares = broker.holdings.get(code, 0)
                    if shares > 0:
                        fill = broker.execute_sell(code, shares, row)
                        if fill:
                            fills.append(fill)

        # 后买
        for code, weight in sorted(target.items(), key=lambda x: -x[1]):
            if code in broker.holdings:
                continue
            row = price_idx.get((code, exec_date))
            if row is None or not broker.can_trade(code, "buy", row):
                continue
            buy_amount = portfolio_value * weight
            if broker.cash < buy_amount * 0.1:
                break
            fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
            if fill:
                fills.append(fill)

        return fills
