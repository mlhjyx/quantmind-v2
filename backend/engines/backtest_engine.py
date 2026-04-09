"""回测引擎 — SimpleBacktester + SimBroker + Hybrid入口。

Hybrid回测架构 (DEV_BACKTEST_ENGINE §3.1):
- Phase A (vectorized_signal.py): 因子合成→排序→目标持仓, 纯numpy/pandas
- Phase B (本文件 SimpleBacktester): 事件驱动执行, 逐日循环处理约束
- run_hybrid_backtest(): 统一入口, 先Phase A再Phase B

Phase 0 核心组件, 严格遵守 CLAUDE.md 回测可信度规则:
1. 涨跌停封板必须处理
2. 整手约束和资金T+1必须建模
3. 确定性测试用固定数据快照
4. 回测结果必须有统计显著性
5. 隔夜跳空必须统计
6. 交易成本敏感性分析
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import structlog

from engines.base_broker import BaseBroker
from engines.slippage_model import SlippageConfig, overnight_gap_cost, volume_impact_slippage

if TYPE_CHECKING:
    from engines.datafeed import DataFeed

logger = structlog.get_logger(__name__)


# ============================================================
# 数据类型定义
# ============================================================

@dataclass
class PMSConfig:
    """利润保护配置(Position Management System)。

    阶梯式利润保护: 盈利越多,允许的回撤越大。
    tiers: [(pnl_threshold, trailing_stop), ...] 按pnl从高到低排列。
    例: [(0.30, 0.15), (0.20, 0.12), (0.10, 0.10)]
      = 盈利>30%且从高点回撤>15%卖出
      = 盈利>20%且从高点回撤>12%卖出
      = 盈利>10%且从高点回撤>10%卖出

    exec_mode:
      'next_open': 收盘后发现→T+1日开盘卖(保守/真实)
      'same_close': 盘中发现→当日收盘卖(乐观)
    """
    enabled: bool = False
    tiers: list[tuple[float, float]] = field(default_factory=lambda: [
        (0.30, 0.15), (0.20, 0.12), (0.10, 0.10),
    ])
    exec_mode: str = "next_open"  # 'next_open' | 'same_close'


@dataclass
class BacktestConfig:
    """回测配置。"""
    initial_capital: float = 1_000_000.0
    top_n: int = 20
    rebalance_freq: str = "monthly"  # 与PT配置对齐(之前默认biweekly导致回测与PT不一致)
    slippage_bps: float = 10.0   # 基础滑点 (bps), fixed模式使用
    slippage_mode: str = "volume_impact"  # 'volume_impact' | 'fixed'
    slippage_config: SlippageConfig = field(default_factory=SlippageConfig)
    commission_rate: float = 0.0000854  # 佣金万0.854（国金证券实际费率）
    stamp_tax_rate: float = 0.0005   # 印花税千0.5(仅卖出), historical_stamp_tax=True时此值被覆盖
    historical_stamp_tax: bool = True  # P3: 启用历史税率(2023-08-28前0.1%, 后0.05%)
    transfer_fee_rate: float = 0.00001  # 过户费万0.1
    lot_size: int = 100  # A股最小交易单位
    turnover_cap: float = 0.50
    benchmark_code: str = "000300.SH"
    volume_cap_pct: float = 0.10  # 单笔成交额上限(占当日成交额比例) DEV_BACKTEST_ENGINE §4.9
    pms: PMSConfig = field(default_factory=PMSConfig)  # 利润保护


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
class CorporateAction:
    """分红/送股/拆股事件（P1+P2）。

    ex_date当日开盘前处理:
    - cash_div_per_share: 每股现金分红(税前，元)
    - stock_div_ratio: 送股比例(如10送5=0.5)
    - tax_rate: 红利税率(持股>1年免税=0, <1月=0.20, 1月-1年=0.10)
    """
    code: str
    ex_date: date
    cash_div_per_share: float = 0.0
    stock_div_ratio: float = 0.0
    tax_rate: float = 0.10  # 默认10%(持股1月-1年)


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
    pending_order_stats: PendingOrderStats | None = None
    pms_events: list[dict] = field(default_factory=list)  # 利润保护触发事件

    def metrics(self, num_trials: int = 69, **kwargs):
        """生成完整绩效报告(Phase 2: P9)。

        Args:
            num_trials: M = FACTOR_TEST_REGISTRY累计测试数, 用于DSR计算。
        """
        from engines.metrics import generate_report
        return generate_report(self, num_trials=num_trials, **kwargs)


def _infer_price_limit(code: str) -> float:
    """从股票代码推断涨跌停幅度（纯计算，无IO）。

    板块规则:
    - 创业板(300/301开头): ±20%
    - 科创板(688开头): ±20%
    - 北交所(8/4开头): ±30%
    - ST股(代码无法判断，需symbols_info): 默认归入主板10%
    - 主板(其余): ±10%

    注意: ST股需要name字段判断，仅靠代码无法识别。
    当symbols_info可用时应优先使用其price_limit字段。
    """
    # code统一为带后缀格式(000001.SZ), startswith仍可正确匹配板块
    if code.startswith("68"):
        return 0.20  # 科创板
    if code.startswith("30"):
        return 0.20  # 创业板
    if code.startswith("8") or code.startswith("4") or code.endswith(".BJ"):
        return 0.30  # 北交所
    return 0.10  # 主板(含ST fallback — ST需symbols_info.price_limit覆盖)


# ============================================================
# ValidatorChain — 可组合的交易验证器 (Phase 3)
# ============================================================

class BaseValidator:
    """交易验证器基类。返回None=通过, 返回str=拒绝原因。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        raise NotImplementedError


class SuspensionValidator(BaseValidator):
    """停牌检测: volume=0。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        if row.get("volume", 0) == 0:
            return "停牌(volume=0)"
        return None


class DataCompletenessValidator(BaseValidator):
    """数据完整性: close/pre_close不为0。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        close = row.get("close", 0)
        pre_close = row.get("pre_close", 0)
        if close == 0 or pre_close == 0:
            return f"数据不完整(close={close}, pre_close={pre_close})"
        return None


class PriceLimitValidator(BaseValidator):
    """涨跌停封板检测。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        close = row.get("close", 0)
        pre_close = row.get("pre_close", 0)
        if close == 0 or pre_close == 0:
            return None  # DataCompletenessValidator已处理

        up_limit = row.get("up_limit", None)
        down_limit = row.get("down_limit", None)
        if up_limit is None or down_limit is None:
            price_limit = _infer_price_limit(code)
            up_limit = round(pre_close * (1 + price_limit), 2)
            down_limit = round(pre_close * (1 - price_limit), 2)

        _t = row.get("turnover_rate")
        turnover = 999.0 if (_t is None or pd.isna(_t)) else float(_t)

        if direction == "buy" and abs(close - up_limit) < 0.015 and turnover < 1.0:
            return f"涨停封板(close={close}≈up_limit={up_limit}, turnover={turnover:.1f}%)"
        if direction == "sell" and abs(close - down_limit) < 0.015 and turnover < 1.0:
            return f"跌停封板(close={close}≈down_limit={down_limit}, turnover={turnover:.1f}%)"
        return None


class ValidatorChain:
    """可组合的验证器链。按顺序执行，第一个拒绝即停止。"""

    def __init__(self, validators: list[BaseValidator] | None = None):
        self.validators = validators or [
            SuspensionValidator(),
            DataCompletenessValidator(),
            PriceLimitValidator(),
        ]

    def can_trade(self, code: str, direction: str, row: pd.Series) -> tuple[bool, str | None]:
        """返回(can_trade, reject_reason)。"""
        for v in self.validators:
            reason = v.validate(code, direction, row)
            if reason:
                return False, reason
        return True, None


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
        benchmark_data: pd.DataFrame | None = None,
        dividend_calendar: dict[date, list[CorporateAction]] | None = None,
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

        # P17: 单位标准化(千元→元, 万元→元) — 在索引构建前完成
        from engines.datafeed import DataFeed as _DataFeed
        _feed = _DataFeed(price_data)
        _feed.standardize_units()
        price_data = _feed.df

        # 价格索引: MultiIndex (code, trade_date) → 快速.loc查询
        # P15: 替代iterrows()遍历6M行，回测启动从分钟级→秒级
        if "code" not in price_data.columns or "trade_date" not in price_data.columns:
            raise ValueError("price_data必须包含code和trade_date列")
        price_data = price_data.sort_values(["code", "trade_date"], kind="mergesort")
        # 构建(code,trade_date)→row dict, 避免MultiIndex set_index消耗大量内存
        _price_dict: dict[tuple, int] = {}
        for idx, (code, td) in enumerate(
            zip(price_data["code"].values, price_data["trade_date"].values, strict=False)
        ):
            _price_dict[(code, td)] = idx

        class _PriceIdx:
            """price_idx.get((code, date))兼容层，底层用dict→iloc查询。"""
            __slots__ = ()
            def get(self, key, default=None):
                idx = _price_dict.get(key)
                if idx is not None:
                    return price_data.iloc[idx]
                return default

        price_idx = _PriceIdx()

        # 每日收盘价: groupby构建(避免pivot_table OOM, 12年×5000+股)
        daily_close: dict[date, dict[str, float]] = {}
        for td, grp in price_data.groupby("trade_date"):
            daily_close[td] = dict(zip(grp["code"], grp["close"], strict=False))

        # 每日adj_close: PMS用(避免除权日false trigger)
        _has_adj_close = "adj_close" in price_data.columns
        daily_adj_close: dict[date, dict[str, float]] = {}
        if _has_adj_close:
            for td, grp in price_data.groupby("trade_date"):
                daily_adj_close[td] = dict(zip(grp["code"], grp["adj_close"], strict=False))

        # 回测主循环
        nav_series = {}
        trades = []
        holdings_history = {}
        turnover_dates = {}
        prev_weights = {}
        self.pending_orders = []  # 重置pending_orders

        # PMS利润保护状态: {code: {buy_price, buy_date, max_price}}
        pms_state: dict[str, dict] = {}
        pms_pending_sells: list[str] = []  # next_open模式下延迟到T+1卖出的code
        pms_events: list[dict] = []  # 记录触发事件

        # P14: 退市检测状态
        _delist_count: dict[str, int] = {}  # code → 连续无数据天数
        _last_known_price: dict[str, float] = {}  # code → 最后已知收盘价

        for _i, td in enumerate(all_dates):
            broker.new_day()

            # ===== P1+P2: 分红/送股处理(开盘前) =====
            if dividend_calendar:
                day_actions = dividend_calendar.get(td, [])
                if day_actions:
                    broker.process_corporate_actions(day_actions)

            # ===== P14: 退市检测+自动清算 =====
            if broker.holdings:
                today_codes = daily_close.get(td, {})
                for code in list(broker.holdings.keys()):
                    if code in today_codes:
                        # 有价格数据 → 清除退市计数
                        _delist_count.pop(code, None)
                    else:
                        # 无价格数据 → 累计天数
                        _delist_count[code] = _delist_count.get(code, 0) + 1
                        if _delist_count[code] >= 20:
                            # 连续20日无数据 → 退市清算(按最后已知价格)
                            shares = broker.holdings.pop(code, 0)
                            last_price = _last_known_price.get(code, 0)
                            if shares > 0 and last_price > 0:
                                proceeds = shares * last_price
                                broker.cash += proceeds
                                logger.warning(
                                    "[%s] %s 退市清算: %d股 @ %.2f = ¥%.0f",
                                    td, code, shares, last_price, proceeds,
                                )
                            _delist_count.pop(code, None)
                    # 记录最后已知价格
                    if code in today_codes and today_codes[code] > 0:
                        _last_known_price[code] = today_codes[code]

            # ===== PMS: 执行T+1延迟卖出 =====
            if self.config.pms.enabled and pms_pending_sells:
                for code in list(pms_pending_sells):
                    if code not in broker.holdings:
                        pms_pending_sells.remove(code)
                        continue
                    row = price_idx.get((code, td))
                    if row is None:
                        continue
                    if not broker.can_trade(code, "sell", row):
                        continue  # 跌停卖不出,保留在pending
                    shares = broker.holdings.get(code, 0)
                    if shares > 0:
                        fill = broker.execute_sell(code, shares, row)
                        if fill:
                            trades.append(fill)
                            pms_state.pop(code, None)
                    pms_pending_sells.remove(code)

            # ===== 处理封板补单 =====
            if self.pending_orders:
                self._process_pending_orders(
                    broker, td, price_idx, daily_close.get(td, {}),
                    all_dates, exec_map, trades
                )

            # ===== PMS: 日频利润保护检查(用adj_close避免除权日false trigger) =====
            if self.config.pms.enabled and broker.holdings:
                today_prices = daily_close.get(td, {})
                today_adj = daily_adj_close.get(td, {}) if _has_adj_close else {}
                for code in list(broker.holdings.keys()):
                    if code in pms_pending_sells:
                        continue  # 已在待卖队列
                    close = today_prices.get(code, 0)
                    if close <= 0:
                        continue
                    state = pms_state.get(code)
                    if state is None:
                        continue  # 无买入记录(不应发生)

                    # 用adj_close做PMS判断(除权日raw close跳变不代表真实亏损)
                    adj = today_adj.get(code, close)  # fallback to raw if no adj

                    # 更新max_price(adj_close)
                    state["max_price"] = max(state["max_price"], adj)

                    # 计算PnL和从峰值回撤
                    pnl = (adj - state["buy_price"]) / state["buy_price"]
                    dd = (adj - state["max_price"]) / state["max_price"] if state["max_price"] > 0 else 0

                    # 阶梯式检查(tiers按pnl从高到低)
                    triggered = False
                    for pnl_thresh, trail_stop in self.config.pms.tiers:
                        if pnl > pnl_thresh and dd < -trail_stop:
                            triggered = True
                            pms_events.append({
                                "date": td, "code": code,
                                "pnl": pnl, "dd": dd,
                                "tier": f">{pnl_thresh:.0%}/>{trail_stop:.0%}",
                                "buy_price": state["buy_price"],
                                "close": close, "max_price": state["max_price"],
                            })
                            break

                    if triggered:
                        if self.config.pms.exec_mode == "same_close":
                            # 当日收盘卖(乐观)
                            row = price_idx.get((code, td))
                            if row is not None and broker.can_trade(code, "sell", row):
                                shares = broker.holdings.get(code, 0)
                                if shares > 0:
                                    fill = broker.execute_sell(code, shares, row)
                                    if fill:
                                        trades.append(fill)
                                        pms_state.pop(code, None)
                        else:
                            # next_open: 延迟到T+1
                            pms_pending_sells.append(code)

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

                # PMS: 记录新买入股票的buy_price(用adj_close避免除权日偏差)
                if self.config.pms.enabled:
                    today_adj_pms = daily_adj_close.get(td, {}) if _has_adj_close else {}
                    for fill in day_fills:
                        if fill.direction == "buy":
                            adj_buy = today_adj_pms.get(fill.code, fill.price)
                            pms_state[fill.code] = {
                                "buy_price": adj_buy,
                                "buy_date": fill.trade_date,
                                "max_price": adj_buy,
                            }
                    # 清理已卖出的pms_state
                    for code in list(pms_state.keys()):
                        if code not in broker.holdings:
                            pms_state.pop(code, None)

                holdings_history[td] = dict(broker.holdings)

            # P13: 每日记录换手率(含PMS卖出/封板补单, 不限于调仓日)
            pv = broker.get_portfolio_value(daily_close.get(td, {}))
            new_weights = {}
            for code, shares in broker.holdings.items():
                p = daily_close.get(td, {}).get(code, 0)
                if pv > 0:
                    new_weights[code] = shares * p / pv

            turnover = sum(
                abs(new_weights.get(c, 0) - prev_weights.get(c, 0))
                for c in set(new_weights) | set(prev_weights)
            ) / 2
            if turnover > 0.001:  # 忽略浮点噪声
                turnover_dates[td] = turnover
            prev_weights = new_weights

            # 每日NAV
            nav_series[td] = pv

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
            pms_events=pms_events,
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
            next_rebal_dates = [d for d in exec_map if d > today]
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


# ============================================================
# Hybrid 回测入口
# ============================================================

def run_hybrid_backtest(
    factor_df: pd.DataFrame,
    directions: dict[str, int],
    price_data: pd.DataFrame,
    config: BacktestConfig,
    benchmark_data: pd.DataFrame | None = None,
    signal_config: Any | None = None,  # SignalConfig (unused, kept for API compat)
    datafeed: DataFeed | None = None,
    dividend_calendar: dict[date, list[CorporateAction]] | None = None,
) -> BacktestResult:
    """Hybrid回测: Phase A向量化信号 → Phase B事件驱动执行。

    DEV_BACKTEST_ENGINE §3.1 Hybrid架构统一入口。

    Args:
        factor_df: 因子长表 (code, trade_date, factor_name, raw_value)
        directions: {factor_name: direction} (+1正向, -1反向)
        price_data: 全量价格数据（当datafeed非None时忽略此参数）
        config: 回测配置（Phase B使用）
        benchmark_data: 基准指数数据
        signal_config: Phase A信号配置（默认从config推断）
        datafeed: DataFeed数据源（优先于price_data）

    Returns:
        BacktestResult
    """
    from engines.signal_engine import PortfolioBuilder, SignalComposer
    from engines.signal_engine import SignalConfig as SEConfig
    from engines.vectorized_signal import compute_rebalance_dates

    # DataFeed兼容: 如果传入DataFeed对象，提取底层DataFrame
    if datafeed is not None:
        from engines.datafeed import DataFeed
        if isinstance(datafeed, DataFeed):
            price_data = datafeed.df

    # Phase A: 统一信号生成 (SignalComposer + PortfolioBuilder)
    se_config = SEConfig(
        factor_names=list(directions.keys()),
        top_n=config.top_n,
        weight_method="equal",
        rebalance_freq=config.rebalance_freq,
        industry_cap=1.0,    # 回测默认无行业约束(可通过config覆盖)
        turnover_cap=1.0,    # 回测默认无换手约束
        cash_buffer=0.0,     # 回测默认无现金缓冲
    )
    # 覆盖FACTOR_DIRECTION: 用调用方传入的directions
    from engines.signal_engine import FACTOR_DIRECTION
    saved_directions = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(directions)

    composer = SignalComposer(se_config)
    builder = PortfolioBuilder(se_config)

    trading_days = sorted(price_data["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(trading_days, config.rebalance_freq)

    # 确保factor_df有neutral_value列(兼容raw_value输入)
    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # 构建per-date排除集(ST/停牌/新股/BJ) — 替代旧的set-level ST过滤
    _has_status = "is_st" in price_data.columns
    _status_by_date: dict[date, set[str]] = {}
    if _has_status:
        for col in ("is_st", "is_suspended", "is_new_stock"):
            if col in price_data.columns:
                excluded = price_data.loc[price_data[col] == True, ["code", "trade_date"]]  # noqa: E712
                for td, grp in excluded.groupby("trade_date"):
                    if td not in _status_by_date:
                        _status_by_date[td] = set()
                    _status_by_date[td].update(grp["code"].tolist())
        # BJ股(board='bse')
        if "board" in price_data.columns:
            bj = price_data.loc[price_data["board"] == "bse", ["code", "trade_date"]]
            for td, grp in bj.groupby("trade_date"):
                if td not in _status_by_date:
                    _status_by_date[td] = set()
                _status_by_date[td].update(grp["code"].tolist())

    target_portfolios: dict[date, dict[str, float]] = {}
    for rd in rebal_dates:
        day_data = factor_df[factor_df["trade_date"] <= rd]
        if day_data.empty:
            continue
        latest_date = day_data["trade_date"].max()
        day_data = day_data[day_data["trade_date"] == latest_date]

        # per-date排除
        exclude = _status_by_date.get(latest_date, set())
        scores = composer.compose(day_data, exclude=exclude)
        if scores.empty:
            continue
        weights = builder.build(scores, pd.Series(dtype=str))
        if weights:
            target_portfolios[rd] = weights

    # 恢复FACTOR_DIRECTION
    FACTOR_DIRECTION.clear()
    FACTOR_DIRECTION.update(saved_directions)

    if not target_portfolios:
        raise ValueError("Phase A信号生成失败: target_portfolios为空")

    logger.info(
        "Phase A信号生成完成(SignalComposer): %d个调仓日, %d个因子, Top-%d",
        len(target_portfolios), len(directions), config.top_n,
    )

    # Phase B: 事件驱动执行
    tester = SimpleBacktester(config)
    return tester.run(target_portfolios, price_data, benchmark_data, dividend_calendar)


# ============================================================
# Composite 回测入口 (Phase 4)
# ============================================================

def run_composite_backtest(
    factor_df: pd.DataFrame,
    directions: dict[str, int],
    price_data: pd.DataFrame,
    config: BacktestConfig,
    modifiers: list | None = None,
    benchmark_data: pd.DataFrame | None = None,
    signal_config: Any | None = None,  # SignalConfig (unused, kept for API compat)
    datafeed: DataFeed | None = None,
    dividend_calendar: dict[date, list[CorporateAction]] | None = None,
    conn=None,  # DB连接(Modifier需要查询北向等数据)
) -> BacktestResult:
    """CompositeStrategy回测: Phase A核心信号 + Modifier调节 → Phase B执行。

    与run_hybrid_backtest的区别: 在Phase A生成基础权重后，
    逐日应用Modifier链调节权重(RegimeModifier等)再交给Phase B执行。

    Args:
        factor_df: 因子长表 (code, trade_date, factor_name, raw_value)
        directions: {factor_name: direction}
        price_data: 全量价格数据
        config: 回测配置
        modifiers: ModifierBase实例列表(为None时等同run_hybrid_backtest)
        benchmark_data: 基准指数数据
        signal_config: Phase A信号配置
        datafeed: DataFeed数据源
        dividend_calendar: 分红日历

    Returns:
        BacktestResult
    """
    from engines.signal_engine import FACTOR_DIRECTION, PortfolioBuilder, SignalComposer
    from engines.signal_engine import SignalConfig as SEConfig
    from engines.vectorized_signal import compute_rebalance_dates

    if datafeed is not None:
        from engines.datafeed import DataFeed
        if isinstance(datafeed, DataFeed):
            price_data = datafeed.df

    # Phase A: 统一信号生成 (SignalComposer + PortfolioBuilder)
    se_config = SEConfig(
        factor_names=list(directions.keys()),
        top_n=config.top_n,
        weight_method="equal",
        rebalance_freq=config.rebalance_freq,
        industry_cap=1.0,
        turnover_cap=1.0,
        cash_buffer=0.0,
    )
    saved_directions = dict(FACTOR_DIRECTION)
    FACTOR_DIRECTION.update(directions)

    composer = SignalComposer(se_config)
    builder = PortfolioBuilder(se_config)

    trading_days = sorted(price_data["trade_date"].unique())
    rebal_dates = compute_rebalance_dates(trading_days, config.rebalance_freq)

    if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # 构建per-date排除集(同run_hybrid_backtest逻辑)
    _has_status_c = "is_st" in price_data.columns
    _status_by_date_c: dict[date, set[str]] = {}
    if _has_status_c:
        for col in ("is_st", "is_suspended", "is_new_stock"):
            if col in price_data.columns:
                excluded = price_data.loc[price_data[col] == True, ["code", "trade_date"]]  # noqa: E712
                for td, grp in excluded.groupby("trade_date"):
                    if td not in _status_by_date_c:
                        _status_by_date_c[td] = set()
                    _status_by_date_c[td].update(grp["code"].tolist())
        if "board" in price_data.columns:
            bj = price_data.loc[price_data["board"] == "bse", ["code", "trade_date"]]
            for td, grp in bj.groupby("trade_date"):
                if td not in _status_by_date_c:
                    _status_by_date_c[td] = set()
                _status_by_date_c[td].update(grp["code"].tolist())

    target_portfolios: dict[date, dict[str, float]] = {}
    for rd in rebal_dates:
        day_data = factor_df[factor_df["trade_date"] <= rd]
        if day_data.empty:
            continue
        latest_date = day_data["trade_date"].max()
        day_data = day_data[day_data["trade_date"] == latest_date]
        exclude = _status_by_date_c.get(latest_date, set())
        scores = composer.compose(day_data, exclude=exclude)
        if scores.empty:
            continue
        weights = builder.build(scores, pd.Series(dtype=str))
        if weights:
            target_portfolios[rd] = weights

    FACTOR_DIRECTION.clear()
    FACTOR_DIRECTION.update(saved_directions)

    if not target_portfolios:
        raise ValueError("Phase A信号生成失败: target_portfolios为空")

    # Phase A.5: Modifier调节
    if modifiers:
        from engines.base_strategy import StrategyContext

        adjusted_portfolios: dict[date, dict[str, float]] = {}
        for signal_date, base_weights in target_portfolios.items():
            ctx = StrategyContext(
                strategy_id="backtest",
                trade_date=signal_date,
                factor_df=factor_df[factor_df["trade_date"] == signal_date]
                if "trade_date" in factor_df.columns
                else factor_df,
                universe=set(base_weights.keys()),
                industry_map={},
                prev_holdings=None,
                conn=conn,
            )

            adjusted = dict(base_weights)
            for modifier in modifiers:
                if modifier.should_trigger(ctx):
                    result = modifier.compute_adjustments(adjusted, ctx)
                    if result.triggered:
                        # 应用调节因子(不归一化 — 缩放意味着减仓到现金)
                        for code, factor in result.adjustment_factors.items():
                            if code in adjusted:
                                adjusted[code] *= max(
                                    modifier.clip_low,
                                    min(factor, modifier.clip_high),
                                )
                        logger.info(
                            "[Composite] %s: %s triggered (%s), weight_sum=%.2f",
                            signal_date, modifier.name, result.reasoning,
                            sum(adjusted.values()),
                        )

            adjusted_portfolios[signal_date] = adjusted
        target_portfolios = adjusted_portfolios

    # Phase B: 事件驱动执行
    tester = SimpleBacktester(config)
    return tester.run(target_portfolios, price_data, benchmark_data, dividend_calendar)
