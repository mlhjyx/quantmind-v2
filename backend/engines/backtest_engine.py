"""回测引擎 — SimpleBacktester + SimBroker。

Phase 0 核心组件, 严格遵守 CLAUDE.md 回测可信度规则:
1. 涨跌停封板必须处理
2. 整手约束和资金T+1必须建模
3. 确定性测试用固定数据快照
4. 回测结果必须有统计显著性
5. 隔夜跳空必须统计
6. 交易成本敏感性分析
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Protocol

import numpy as np
import pandas as pd

from engines.base_broker import BaseBroker
from engines.slippage_model import SlippageConfig, volume_impact_slippage

logger = logging.getLogger(__name__)


# ============================================================
# 数据类型定义
# ============================================================

@dataclass
class BacktestConfig:
    """回测配置。"""
    initial_capital: float = 1_000_000.0
    top_n: int = 20
    rebalance_freq: str = "biweekly"
    slippage_bps: float = 10.0   # 基础滑点 (bps), fixed模式使用
    slippage_mode: str = "volume_impact"  # 'volume_impact' | 'fixed'
    slippage_config: SlippageConfig = field(default_factory=SlippageConfig)
    commission_rate: float = 0.0000854  # 佣金万0.854（国金证券实际费率）
    stamp_tax_rate: float = 0.0005   # 印花税千0.5(仅卖出)
    transfer_fee_rate: float = 0.00001  # 过户费万0.1
    lot_size: int = 100  # A股最小交易单位
    turnover_cap: float = 0.50
    benchmark_code: str = "000300.SH"


@dataclass
class Fill:
    """成交记录。"""
    code: str
    trade_date: date
    direction: str  # 'buy' or 'sell'
    price: float
    shares: int
    amount: float
    commission: float
    tax: float
    slippage: float
    total_cost: float


@dataclass
class PendingOrder:
    """封板未成交的补单记录（回测引擎内部使用）。

    仅买入方向。涨停封板时创建，T+1日尝试补单，最多补1次。
    """
    code: str
    signal_date: date
    exec_date: date          # 封板发生日
    target_weight: float     # 目标权重
    original_score: float    # 原始composite score（排序用）
    direction: str = "buy"
    status: str = "pending"  # pending / filled / cancelled
    cancel_reason: str = ""


@dataclass
class PendingOrderStats:
    """补单统计。"""
    total_pending: int = 0           # 总封板次数
    filled_count: int = 0            # 补单成功次数
    cancelled_count: int = 0         # 放弃次数
    fill_rate: float = 0.0           # 补单成功率 = filled / total
    avg_retry_return_1d: float = 0.0 # 补单股票T+1日平均涨幅
    cancel_reasons: dict = field(default_factory=dict)  # {reason: count}


@dataclass
class BacktestResult:
    """回测结果。"""
    daily_nav: pd.Series         # date → NAV
    daily_returns: pd.Series     # date → daily return
    benchmark_nav: pd.Series     # date → benchmark NAV
    benchmark_returns: pd.Series # date → benchmark return
    trades: list[Fill]
    holdings_history: dict       # date → {code: shares}
    config: BacktestConfig
    turnover_series: pd.Series   # date → turnover ratio
    pending_order_stats: Optional[PendingOrderStats] = None


# ============================================================
# SimBroker — 模拟交易执行
# ============================================================

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

    def can_trade(
        self,
        code: str,
        direction: str,
        row: pd.Series,
        symbols_info: Optional[pd.DataFrame] = None,
    ) -> bool:
        """判断是否可以成交。

        CLAUDE.md 规则1: 涨跌停封板必须处理。
        - 停牌(volume=0) → False
        - 买入+收盘价==涨停价+换手率<1% → False
        - 卖出+收盘价==跌停价+换手率<1% → False
        """
        # 1. 成交量为0 → 停牌
        if row.get("volume", 0) == 0:
            return False

        close = row.get("close", 0)
        pre_close = row.get("pre_close", 0)

        if close == 0 or pre_close == 0:
            return False

        # 2. 获取涨跌停价(优先用数据中的up_limit/down_limit)
        up_limit = row.get("up_limit", None)
        down_limit = row.get("down_limit", None)

        # 如果没有limit数据，用board类型推算
        if up_limit is None or down_limit is None:
            price_limit = 0.10  # 默认主板10%
            if symbols_info is not None and code in symbols_info.index:
                price_limit = float(symbols_info.loc[code, "price_limit"])
            up_limit = round(pre_close * (1 + price_limit), 2)
            down_limit = round(pre_close * (1 - price_limit), 2)

        turnover = row.get("turnover_rate", 999)  # 默认高换手(不限制)

        # 3. 封板判断
        if direction == "buy":
            # 涨停封板: 收盘价≈涨停价 且 换手率<1%
            if abs(close - up_limit) < 0.015 and turnover < 1.0:
                return False
        elif direction == "sell":
            # 跌停封板: 收盘价≈跌停价 且 换手率<1%
            if abs(close - down_limit) < 0.015 and turnover < 1.0:
                return False

        return True

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
            daily_amount = row.get("amount", 0)
            # daily.amount单位是千元(TUSHARE_DATA_SOURCE_CHECKLIST)，转为元
            # 千元范围: 典型值1e3~1e7(=百万~百亿元), 阈值1e9区分
            # 已是元的值(如5e7)不会被误转(5e7 < 1e9会转→5e10，但回测数据
            # 统一用千元入库，所以实际不会出现已转换的元值)
            if daily_amount > 0 and daily_amount < 1e9:
                daily_amount *= 1000
            daily_volume = row.get("volume", 0)
            market_cap = row.get("total_mv", 0)
            # total_mv单位是万元(daily_basic)，转为元
            # 万元范围: 最大~3e8万元(=3万亿元), 阈值1e10区分万元/元
            if market_cap > 0 and market_cap < 1e10:
                market_cap *= 10000
            total_bps = volume_impact_slippage(
                trade_amount=amount,
                daily_volume=daily_volume,
                daily_amount=daily_amount,
                market_cap=market_cap,
                direction=direction,
                config=self.config.slippage_config,
            )
            return price * total_bps / 10000
        else:
            return price * self.config.slippage_bps / 10000

    def execute_sell(self, code: str, shares: int, row: pd.Series) -> Optional[Fill]:
        """执行卖出。"""
        price = row["open"]  # 次日开盘价成交
        slippage = self.calc_slippage(price, shares * price, row, direction="sell")
        exec_price = price - slippage  # 卖出价格偏低

        amount = exec_price * shares
        commission = max(amount * self.config.commission_rate, 5.0)  # 最低5元
        tax = amount * self.config.stamp_tax_rate  # 印花税仅卖出
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

    def execute_buy(self, code: str, target_amount: float, row: pd.Series) -> Optional[Fill]:
        """执行买入。

        CLAUDE.md 规则2: 整手约束。
        actual_shares = floor(target_value / price / 100) * 100
        """
        price = row["open"]  # 次日开盘价成交
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


# ============================================================
# SimpleBacktester — 单次回测
# ============================================================

class SimpleBacktester:
    """Phase 0 简单回测引擎。

    流程:
    1. 遍历每个交易日
    2. 处理封板补单（如果有pending_orders）
    3. 在调仓日: 读取目标持仓 → 先卖后买 → 记录成交（封板记录为pending）
    4. 非调仓日: 更新NAV
    5. 计算绩效指标
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.pending_orders: list[PendingOrder] = []
        self.max_retry_orders: int = 3         # 单次调仓最多补3只
        self.retry_weight_cap: float = 0.10    # 单只补单上限10%
        self.min_days_to_next_rebal: int = 5   # 距下次调仓<5天不补

    def run(
        self,
        target_portfolios: dict[date, dict[str, float]],
        price_data: pd.DataFrame,
        benchmark_data: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """执行回测。

        Args:
            target_portfolios: {signal_date: {code: weight}}
                signal_date是信号日(周五), 执行在下一个交易日
            price_data: 全量价格数据 (code, trade_date, open, close, ...)
                        必须包含up_limit, down_limit, turnover_rate
            benchmark_data: 基准指数数据 (trade_date, close)

        Returns:
            BacktestResult
        """
        broker = SimBroker(self.config)

        # 准备数据
        all_dates = sorted(price_data["trade_date"].unique())
        signal_dates = sorted(target_portfolios.keys())

        # 构建执行日映射: signal_date → exec_date (下一个交易日)
        exec_map = {}
        for sd in signal_dates:
            # 找到signal_date之后的第一个交易日
            future_dates = [d for d in all_dates if d > sd]
            if future_dates:
                exec_map[future_dates[0]] = sd

        # 价格索引: (code, date) → row
        price_data = price_data.sort_values(["trade_date", "code"])
        price_idx = {}
        for _, row in price_data.iterrows():
            price_idx[(row["code"], row["trade_date"])] = row

        # 每日收盘价
        daily_close = {}
        for d in all_dates:
            day_data = price_data[price_data["trade_date"] == d]
            daily_close[d] = dict(zip(day_data["code"], day_data["close"]))

        # 回测主循环
        nav_series = {}
        trades = []
        holdings_history = {}
        turnover_dates = {}
        prev_weights = {}
        self.pending_orders = []  # 重置pending_orders

        for i, td in enumerate(all_dates):
            broker.new_day()

            # ===== 处理封板补单 =====
            if self.pending_orders:
                self._process_pending_orders(
                    broker, td, price_idx, daily_close.get(td, {}),
                    all_dates, exec_map, trades
                )

            # 检查是否是执行日
            if td in exec_map:
                signal_date = exec_map[td]
                target = target_portfolios[signal_date]

                # 计算当前组合市值
                portfolio_value = broker.get_portfolio_value(daily_close.get(td, {}))

                # 先卖后买（封板记录为pending）
                day_fills, new_pending = self._rebalance_with_pending(
                    broker, target, portfolio_value, td, price_idx,
                    daily_close.get(td, {}), signal_date
                )
                trades.extend(day_fills)
                self.pending_orders.extend(new_pending)

                # 记录换手率
                new_weights = {}
                for code, shares in broker.holdings.items():
                    p = daily_close.get(td, {}).get(code, 0)
                    if portfolio_value > 0:
                        new_weights[code] = shares * p / portfolio_value

                turnover = sum(
                    abs(new_weights.get(c, 0) - prev_weights.get(c, 0))
                    for c in set(new_weights) | set(prev_weights)
                ) / 2
                turnover_dates[td] = turnover
                prev_weights = new_weights

                holdings_history[td] = dict(broker.holdings)

            # 每日NAV
            prices = daily_close.get(td, {})
            nav_series[td] = broker.get_portfolio_value(prices)

        # 转换结果
        nav = pd.Series(nav_series).sort_index()
        daily_ret = nav.pct_change().fillna(0)

        # 基准
        if benchmark_data is not None and not benchmark_data.empty:
            bench = benchmark_data.set_index("trade_date")["close"]
            bench_nav = bench / bench.iloc[0] * self.config.initial_capital
            bench_ret = bench.pct_change().fillna(0)
        else:
            bench_nav = pd.Series(self.config.initial_capital, index=nav.index)
            bench_ret = pd.Series(0.0, index=nav.index)

        turnover = pd.Series(turnover_dates).sort_index()

        # 补单统计
        po_stats = self._calc_pending_order_stats(price_idx)

        return BacktestResult(
            daily_nav=nav,
            daily_returns=daily_ret,
            benchmark_nav=bench_nav,
            benchmark_returns=bench_ret,
            trades=trades,
            holdings_history=holdings_history,
            config=self.config,
            turnover_series=turnover,
            pending_order_stats=po_stats,
        )

    def _rebalance(
        self,
        broker: SimBroker,
        target: dict[str, float],
        portfolio_value: float,
        exec_date: date,
        price_idx: dict,
        today_close: dict,
    ) -> list[Fill]:
        """执行调仓: 先卖后买（向后兼容，不记录pending）。"""
        fills, _ = self._rebalance_with_pending(
            broker, target, portfolio_value, exec_date, price_idx,
            today_close, exec_date,
        )
        return fills

    def _rebalance_with_pending(
        self,
        broker: SimBroker,
        target: dict[str, float],
        portfolio_value: float,
        exec_date: date,
        price_idx: dict,
        today_close: dict,
        signal_date: date,
    ) -> tuple[list[Fill], list[PendingOrder]]:
        """执行调仓: 先卖后买，封板记录为PendingOrder。

        Returns:
            (成交列表, 新增pending_orders列表)
        """
        fills = []
        new_pending = []

        # 1. 计算目标持仓股数
        target_shares = {}
        for code, weight in target.items():
            close_price = today_close.get(code, 0)
            if close_price > 0:
                target_value = portfolio_value * weight
                shares = int(target_value / close_price / self.config.lot_size) * self.config.lot_size
                if shares > 0:
                    target_shares[code] = shares

        # 2. 卖出 (持有但不在目标中的, 或需要减仓的)
        sell_codes = []
        for code, curr_shares in list(broker.holdings.items()):
            target_s = target_shares.get(code, 0)
            if curr_shares > target_s:
                sell_codes.append((code, curr_shares - target_s))

        for code, sell_shares in sell_codes:
            row = price_idx.get((code, exec_date))
            if row is None:
                continue
            if not broker.can_trade(code, "sell", row):
                logger.debug(f"[{exec_date}] {code} 卖出受限(封板/停牌)")
                continue
            fill = broker.execute_sell(code, sell_shares, row)
            if fill:
                fills.append(fill)

        # 3. 买入 (封板记录为pending)
        buy_orders = []
        for code, target_s in target_shares.items():
            curr_shares = broker.holdings.get(code, 0)
            if target_s > curr_shares:
                buy_amount = (target_s - curr_shares) * today_close.get(code, 0)
                weight = target.get(code, 0)
                buy_orders.append((code, buy_amount, weight))

        # 按金额降序买入(优先买最大权重)
        buy_orders.sort(key=lambda x: -x[1])

        for code, buy_amount, weight in buy_orders:
            if broker.cash < buy_amount * 0.1:  # 现金太少停止买入
                break
            row = price_idx.get((code, exec_date))
            if row is None:
                continue

            if not broker.can_trade(code, "buy", row):
                # ===== 封板: 记录为pending_order =====
                logger.debug(f"[{exec_date}] {code} 买入封板，加入补单队列")
                new_pending.append(PendingOrder(
                    code=code,
                    signal_date=signal_date,
                    exec_date=exec_date,
                    target_weight=weight,
                    original_score=buy_amount,  # 用金额排序（等权下weight相同）
                ))
                continue

            fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
            if fill:
                fills.append(fill)

        return fills, new_pending

    def _process_pending_orders(
        self,
        broker: SimBroker,
        today: date,
        price_idx: dict,
        today_close: dict,
        all_dates: list[date],
        exec_map: dict[date, date],
        trades_list: list[Fill],
    ) -> None:
        """处理封板补单。T+1日尝试买入。

        规则（SPRINT_1_3B_STRATEGY_DESIGN.md §2.2）:
        - 仅买入方向
        - 最多补1次（T+1日尝试，失败放弃）
        - 距下次调仓<5天不补
        - 单次最多补3只
        - 单只不超过组合市值10%
        """
        actionable = []
        today_idx = all_dates.index(today) if today in all_dates else -1

        for po in self.pending_orders:
            if po.status != "pending":
                continue

            # 找到exec_date的下一个交易日作为retry_date
            retry_date = None
            for d in all_dates:
                if d > po.exec_date:
                    retry_date = d
                    break

            if retry_date is None or retry_date != today:
                # 不是今天该处理的
                if retry_date is not None and today > retry_date:
                    po.status = "cancelled"
                    po.cancel_reason = "expired"
                continue

            # 检查距下次调仓是否太近
            next_rebal_dates = [d for d in exec_map.keys() if d > today]
            if next_rebal_dates:
                next_rebal = min(next_rebal_dates)
                next_rebal_idx = all_dates.index(next_rebal) if next_rebal in all_dates else len(all_dates)
                days_to_next = next_rebal_idx - today_idx
                if days_to_next <= self.min_days_to_next_rebal:
                    po.status = "cancelled"
                    po.cancel_reason = f"too_close_to_next_rebalance({days_to_next}d)"
                    continue

            actionable.append(po)

        # 按original_score降序，最多补3只
        actionable.sort(key=lambda x: -x.original_score)
        to_execute = actionable[:self.max_retry_orders]

        # 超出数量上限的标记取消
        for po in actionable[self.max_retry_orders:]:
            po.status = "cancelled"
            po.cancel_reason = "exceeded_max_retry_count"

        for po in to_execute:
            row = price_idx.get((po.code, today))
            if row is None:
                po.status = "cancelled"
                po.cancel_reason = "no_price_data"
                continue

            if not broker.can_trade(po.code, "buy", row):
                po.status = "cancelled"
                po.cancel_reason = "still_limit_up_or_suspended"
                continue

            # 按当前组合市值重算目标金额
            portfolio_value = broker.get_portfolio_value(today_close)
            target_amount = portfolio_value * min(po.target_weight, self.retry_weight_cap)

            # 检查能否买入1手
            open_price = row.get("open", 0)
            if open_price <= 0 or target_amount < open_price * self.config.lot_size:
                po.status = "cancelled"
                po.cancel_reason = "insufficient_for_one_lot"
                continue

            fill = broker.execute_buy(po.code, min(target_amount, broker.cash), row)
            if fill:
                trades_list.append(fill)
                po.status = "filled"
                logger.debug(f"[{today}] 补单成功: {po.code} {fill.shares}股")
            else:
                po.status = "cancelled"
                po.cancel_reason = "insufficient_cash"

    def _calc_pending_order_stats(self, price_idx: dict) -> PendingOrderStats:
        """计算补单统计。"""
        stats = PendingOrderStats()
        if not self.pending_orders:
            return stats

        stats.total_pending = len(self.pending_orders)
        stats.filled_count = sum(1 for po in self.pending_orders if po.status == "filled")
        stats.cancelled_count = sum(1 for po in self.pending_orders if po.status == "cancelled")
        stats.fill_rate = (
            stats.filled_count / stats.total_pending
            if stats.total_pending > 0 else 0.0
        )

        # cancel_reasons统计
        for po in self.pending_orders:
            if po.status == "cancelled" and po.cancel_reason:
                stats.cancel_reasons[po.cancel_reason] = (
                    stats.cancel_reasons.get(po.cancel_reason, 0) + 1
                )

        # 补单股票T+1日平均涨幅（衡量追涨风险）
        retry_returns = []
        for po in self.pending_orders:
            if po.status == "filled":
                row = price_idx.get((po.code, po.exec_date))
                if row is not None:
                    pre_close = row.get("close", 0)
                    # 找retry_date的close
                    # retry_date = exec_date + 1 trading day，用open近似
                    open_price = row.get("open", 0)
                    if pre_close > 0 and open_price > 0:
                        retry_returns.append(open_price / pre_close - 1)

        stats.avg_retry_return_1d = (
            float(np.mean(retry_returns)) if retry_returns else 0.0
        )

        return stats
