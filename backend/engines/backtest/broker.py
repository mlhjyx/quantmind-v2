"""SimBroker — 模拟交易执行。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import structlog

from engines.backtest.config import BacktestConfig
from engines.backtest.types import CorporateAction, Fill
from engines.backtest.validators import ValidatorChain
from engines.base_broker import BaseBroker
from engines.slippage_model import overnight_gap_cost, volume_impact_slippage

logger = structlog.get_logger(__name__)


class SimBroker(BaseBroker):
    """Paper Trading模拟交易器。

    CLAUDE.md 回测可信度规则强制要求:
    - 涨跌停封板检测 (can_trade)
    - 整手约束 (100股为最小单位)
    - 资金T+1 (卖出资金当日可用于买入)

    继承BaseBroker提供统一查询接口（延迟导入避免循环依赖）。
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.cash = config.initial_capital
        self.holdings: dict[str, int] = {}  # code → shares
        self._sell_proceeds_today = 0.0  # 当日卖出回款(T+0可用)
        self._validator = ValidatorChain()  # Phase 3: 可组合验证器

    def can_trade(
        self,
        code: str,
        direction: str,
        row: pd.Series,
        symbols_info: pd.DataFrame | None = None,
    ) -> bool:
        """判断是否可以成交。委托给ValidatorChain，拒绝原因可追溯。"""
        ok, reason = self._validator.can_trade(code, direction, row)
        if not ok and reason:
            logger.debug("交易拒绝: %s %s %s — %s", code, direction, row.get("trade_date", "?"), reason)
        return ok

    def calc_slippage(
        self,
        price: float,
        amount: float,
        row: pd.Series,
        direction: str = "buy",
    ) -> float:
        """计算滑点。

        slippage_mode='volume_impact': 市值分层Volume-Impact模型（DEV_BACKTEST_ENGINE.md §4.5）。
        slippage_mode='fixed': 固定bps（向后兼容）。
        """
        if self.config.slippage_mode == "volume_impact":
            import math as _math

            # P17: 单位已在DataFeed.standardize_units()中统一转为元
            daily_amount = row.get("amount", 0)
            daily_volume = row.get("volume", 0)  # volume: 手
            market_cap = row.get("total_mv", 0)  # total_mv: 元(已转换)

            # Bouchaud 2018: 从行情数据获取volatility_20(年化)转日波动率
            vol_20 = row.get("volatility_20", None)
            if vol_20 is not None and vol_20 > 0:
                sigma_daily = vol_20 / _math.sqrt(252)
            else:
                sigma_daily = 0.02  # 默认≈30%年化

            total_bps = volume_impact_slippage(
                trade_amount=amount,
                daily_volume=daily_volume,
                daily_amount=daily_amount,
                market_cap=market_cap,
                direction=direction,
                config=self.config.slippage_config,
                sigma_daily=sigma_daily,
            )

            # P5: 接入隔夜跳空成本(R4研究: ~10-15bps/笔)
            open_price = row.get("open", 0)
            prev_close = row.get("pre_close", 0)
            if open_price > 0 and prev_close > 0:
                gap_penalty = (
                    self.config.slippage_config.gap_penalty_factor
                    if self.config.slippage_config is not None
                    else 0.5
                )
                gap_bps = overnight_gap_cost(
                    open_price=float(open_price),
                    prev_close=float(prev_close),
                    gap_penalty_factor=gap_penalty,
                )
                total_bps += gap_bps

            return price * total_bps / 10000
        else:
            return price * self.config.slippage_bps / 10000

    def _daily_amount_yuan(self, row: pd.Series) -> float:
        """从行情行中提取当日成交额（元）。

        P17: 单位已在DataFeed.standardize_units()中统一为元。
        数据缺失或为0时返回0.0（调用方跳过volume cap检查）。
        """
        daily_amount = row.get("amount", 0)
        if daily_amount is None or pd.isna(daily_amount):
            return 0.0
        return float(daily_amount)

    def execute_sell(self, code: str, shares: int, row: pd.Series) -> Fill | None:
        """执行卖出。

        A5修复: 单笔成交额上限 = daily_amount * volume_cap_pct (DEV_BACKTEST_ENGINE §4.9)。
        超过上限时截断股数到上限，数据缺失时跳过检查。
        """
        price = row["open"]  # 次日开盘价成交

        # A5: 成交量约束 — 卖出
        if self.config.volume_cap_pct > 0:
            daily_amt = self._daily_amount_yuan(row)
            if daily_amt > 0:
                max_sell_value = daily_amt * self.config.volume_cap_pct
                max_shares = int(max_sell_value / price / self.config.lot_size) * self.config.lot_size
                if max_shares > 0 and shares > max_shares:
                    logger.debug(
                        "volume_cap卖出截断: code=%s shares=%d→%d (cap=%.0f元)",
                        code, shares, max_shares, max_sell_value,
                    )
                    shares = max_shares
        slippage = self.calc_slippage(price, shares * price, row, direction="sell")
        exec_price = price - slippage  # 卖出价格偏低

        amount = exec_price * shares
        commission = max(amount * self.config.commission_rate, 5.0)  # 最低5元
        # P3: 印花税历史税率(2023-08-28起0.05%, 之前0.1%)
        if self.config.historical_stamp_tax:
            trade_date = row.get("trade_date", date.today())
            if isinstance(trade_date, str):
                trade_date = date.fromisoformat(trade_date)
            stamp_tax_rate = 0.0005 if trade_date >= date(2023, 8, 28) else 0.001
        else:
            stamp_tax_rate = self.config.stamp_tax_rate
        tax = amount * stamp_tax_rate  # 印花税仅卖出
        transfer_fee = amount * self.config.transfer_fee_rate
        total_cost = commission + tax + transfer_fee

        net_proceeds = amount - total_cost

        # 更新持仓
        self.holdings[code] = self.holdings.get(code, 0) - shares
        if self.holdings[code] <= 0:
            del self.holdings[code]

        # 卖出回款当日可用(T+0可用)
        self.cash += net_proceeds
        self._sell_proceeds_today += net_proceeds

        return Fill(
            code=code,
            trade_date=row.get("trade_date", date.today()),
            direction="sell",
            price=exec_price,
            shares=shares,
            amount=amount,
            commission=commission,
            tax=tax,
            slippage=slippage * shares,
            total_cost=total_cost,
        )

    def execute_buy(self, code: str, target_amount: float, row: pd.Series) -> Fill | None:
        """执行买入。

        CLAUDE.md 规则2: 整手约束。
        actual_shares = floor(target_value / price / 100) * 100

        A5修复: 单笔成交额上限 = daily_amount * volume_cap_pct (DEV_BACKTEST_ENGINE §4.9)。
        超过上限时截断到上限，数据缺失时跳过检查。
        """
        price = row["open"]  # 次日开盘价成交

        # A5: 成交量约束 — 买入
        if self.config.volume_cap_pct > 0:
            daily_amt = self._daily_amount_yuan(row)
            if daily_amt > 0:
                max_buy_value = daily_amt * self.config.volume_cap_pct
                if target_amount > max_buy_value:
                    logger.debug(
                        "volume_cap买入截断: code=%s amount=%.0f→%.0f (cap=%.0f元)",
                        code, target_amount, max_buy_value, max_buy_value,
                    )
                    target_amount = max_buy_value
        slippage = self.calc_slippage(price, target_amount, row, direction="buy")
        exec_price = price + slippage  # 买入价格偏高

        # 整手约束
        shares = int(target_amount / exec_price / self.config.lot_size) * self.config.lot_size
        if shares <= 0:
            return None

        amount = exec_price * shares
        commission = max(amount * self.config.commission_rate, 5.0)
        transfer_fee = amount * self.config.transfer_fee_rate
        total_cost = commission + transfer_fee  # 买入无印花税

        total_needed = amount + total_cost

        if total_needed > self.cash:
            # 资金不足，减少股数
            shares = int(self.cash / (exec_price * (1 + self.config.commission_rate + self.config.transfer_fee_rate)) / self.config.lot_size) * self.config.lot_size
            if shares <= 0:
                return None
            amount = exec_price * shares
            commission = max(amount * self.config.commission_rate, 5.0)
            transfer_fee = amount * self.config.transfer_fee_rate
            total_cost = commission + transfer_fee
            total_needed = amount + total_cost

        self.cash -= total_needed
        self.holdings[code] = self.holdings.get(code, 0) + shares

        return Fill(
            code=code,
            trade_date=row.get("trade_date", date.today()),
            direction="buy",
            price=exec_price,
            shares=shares,
            amount=amount,
            commission=commission,
            tax=0.0,
            slippage=slippage * shares,
            total_cost=total_cost,
        )

    def get_portfolio_value(self, prices: dict[str, float]) -> float:
        """计算组合市值 = 持仓市值 + 现金。"""
        holdings_value = sum(
            shares * prices.get(code, 0)
            for code, shares in self.holdings.items()
        )
        return holdings_value + self.cash

    # ── BaseBroker统一接口 ──

    def get_positions(self) -> dict[str, int]:
        """获取当前持仓。"""
        return dict(self.holdings)

    def get_cash(self) -> float:
        """获取当前可用现金。"""
        return self.cash

    def get_total_value(self, prices: dict[str, float]) -> float:
        """计算组合总市值。"""
        return self.get_portfolio_value(prices)

    def new_day(self):
        """每日开始时重置日内状态。"""
        self._sell_proceeds_today = 0.0

    def process_corporate_actions(
        self, actions: list[CorporateAction],
    ) -> list[dict]:
        """处理分红/送股事件(P1+P2)，在每日开盘前调用。

        Args:
            actions: 当日除权除息事件列表。

        Returns:
            处理记录列表，用于日志追踪。
        """
        records = []
        for action in actions:
            code = action.code
            shares = self.holdings.get(code, 0)
            if shares <= 0:
                continue

            record = {"code": code, "ex_date": action.ex_date, "shares_before": shares}

            # P1: 现金分红(税后)
            if action.cash_div_per_share > 0:
                tax_rate = action.tax_rate
                net_div = action.cash_div_per_share * (1 - tax_rate)
                cash_received = net_div * shares
                self.cash += cash_received
                record["cash_dividend"] = cash_received
                record["tax_rate"] = tax_rate

            # P2: 送股/拆股(持仓数量调整，NAV不变因为除权日股价已调整)
            if action.stock_div_ratio > 0:
                new_shares = int(shares * (1 + action.stock_div_ratio))
                self.holdings[code] = new_shares
                record["shares_after"] = new_shares
                record["stock_div_ratio"] = action.stock_div_ratio

            records.append(record)

        if records:
            logger.info("分红/送股处理: %d笔", len(records))
        return records
