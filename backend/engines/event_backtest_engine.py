"""EVENT回测引擎 — 事件触发式回测。

与月度Top-N回测的核心差异:
- 触发: 因子值超过阈值时买入（非固定日期调仓）
- 持有: 每只股票独立计算持有期（非统一月度换仓）
- 仓位: 增量买入/到期卖出，持仓滚动更新

A股特殊处理:
- T+1: 信号T日 → T+1日开盘买入
- 涨跌停: 封板时跳过买入
- 停牌: 持有期顺延（停牌天不计入hold_days）
- 整手: floor到100股
- 印花税: 仅卖出收0.05%

用法:
    config = EventBacktestConfig(trigger_factor='mf_divergence', ...)
    bt = EventBacktester(config)
    result = bt.run(factor_data, price_data)
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# 复用现有成本参数
COMMISSION_RATE = 0.0000854  # 万0.854
MIN_COMMISSION = 5.0  # 最低佣金5元
STAMP_TAX_RATE = 0.0005  # 千0.5, 仅卖出
TRANSFER_FEE_RATE = 0.00001  # 万0.1
LOT_SIZE = 100


@dataclass
class EventBacktestConfig:
    """EVENT回测配置。"""

    trigger_factor: str = "mf_divergence"
    trigger_threshold: float = 0.8
    trigger_direction: str = "above"  # 'above': 因子>阈值买; 'below': 因子<阈值买
    hold_days: int = 20  # 持有交易日数
    max_positions: int = 10
    position_size: str = "equal"  # 'equal' 或 'signal_weighted'
    initial_capital: float = 1_000_000.0
    start_date: date = field(default_factory=lambda: date(2021, 1, 1))
    end_date: date = field(default_factory=lambda: date(2025, 12, 31))
    volume_cap_pct: float = 0.10  # 单笔成交不超过日成交额10%
    use_neutralized: bool = True  # 用中性化后的因子值触发


@dataclass
class EventFill:
    """单笔成交记录。"""

    code: str
    trade_date: date
    direction: str  # 'buy' / 'sell'
    price: float
    shares: int
    amount: float
    commission: float
    tax: float
    total_cost: float
    signal_date: date | None = None  # 触发信号的日期
    signal_value: float = 0.0  # 触发时的因子值


@dataclass
class Position:
    """持仓记录。"""

    code: str
    entry_date: date  # 实际买入日
    entry_price: float
    shares: int
    signal_date: date  # 信号触发日
    signal_value: float
    hold_trading_days: int = 0  # 已持有的交易日数（不含停牌）


@dataclass
class EventBacktestResult:
    """EVENT回测结果。"""

    daily_nav: pd.Series  # date → NAV
    daily_returns: pd.Series
    trades: list[EventFill]
    total_signals: int  # 信号触发总次数
    total_buys: int  # 实际买入次数
    total_sells: int
    avg_hold_days: float
    max_concurrent_positions: int


class EventBacktester:
    """事件触发式回测引擎。"""

    def __init__(self, config: EventBacktestConfig) -> None:
        self.config = config

    def run(
        self,
        factor_data: pd.DataFrame,
        price_data: pd.DataFrame,
        benchmark_data: pd.DataFrame | None = None,
    ) -> EventBacktestResult:
        """执行EVENT回测。

        Args:
            factor_data: columns=[code, trade_date, value] 日频因子值。
            price_data: columns=[code, trade_date, open, close, volume, amount,
                                 up_limit, down_limit, pre_close]。
            benchmark_data: optional, columns=[trade_date, close]。

        Returns:
            EventBacktestResult。
        """
        cfg = self.config
        cash = cfg.initial_capital
        positions: list[Position] = []
        trades: list[EventFill] = []
        nav_history: dict[date, float] = {}
        pending_buys: list[dict] = []  # T日信号→T+1买入

        # 构建数据索引
        trading_dates = sorted(price_data["trade_date"].unique())
        trading_dates = [d for d in trading_dates if cfg.start_date <= d <= cfg.end_date]

        price_idx = {}
        for _, row in price_data.iterrows():
            price_idx[(row["code"], row["trade_date"])] = row

        factor_idx = {}
        for _, row in factor_data.iterrows():
            key = (row["code"], row["trade_date"])
            factor_idx[key] = float(row["value"])

        total_signals = 0
        total_buys = 0
        total_sells = 0
        max_concurrent = 0
        hold_days_list: list[int] = []

        logger.info(
            "[EventBT] 开始: factor=%s threshold=%.2f hold=%dd max_pos=%d dates=%d",
            cfg.trigger_factor, cfg.trigger_threshold, cfg.hold_days,
            cfg.max_positions, len(trading_dates),
        )

        for _day_idx, td in enumerate(trading_dates):
            # ── Step 1: 处理T-1日的pending买入 ──
            new_pending = []
            for pb in pending_buys:
                code = pb["code"]
                px = price_idx.get((code, td))
                if px is None:
                    continue  # 当日无数据（停牌/退市）

                open_price = float(px["open"])
                if open_price <= 0:
                    continue

                # 涨停检查: 开盘即涨停无法买入
                if self._is_limit_up(px):
                    continue  # 涨停封板跳过

                # 计算可买入股数
                pos_value = cash / max(cfg.max_positions - len(positions), 1)
                shares = int(pos_value / open_price / LOT_SIZE) * LOT_SIZE
                if shares <= 0:
                    continue

                # 成交额限制
                daily_amount = float(px.get("amount", 0))
                if daily_amount > 0 and cfg.volume_cap_pct > 0:
                    max_shares = int(daily_amount * cfg.volume_cap_pct / open_price / LOT_SIZE) * LOT_SIZE
                    shares = min(shares, max_shares)
                    if shares <= 0:
                        continue

                amount = open_price * shares
                comm = max(amount * COMMISSION_RATE, MIN_COMMISSION)
                transfer = amount * TRANSFER_FEE_RATE
                total_cost = comm + transfer

                if amount + total_cost > cash:
                    shares = int((cash - MIN_COMMISSION) / open_price / LOT_SIZE) * LOT_SIZE
                    if shares <= 0:
                        continue
                    amount = open_price * shares
                    comm = max(amount * COMMISSION_RATE, MIN_COMMISSION)
                    transfer = amount * TRANSFER_FEE_RATE
                    total_cost = comm + transfer

                cash -= amount + total_cost
                positions.append(Position(
                    code=code, entry_date=td, entry_price=open_price,
                    shares=shares, signal_date=pb["signal_date"],
                    signal_value=pb["signal_value"], hold_trading_days=0,
                ))
                trades.append(EventFill(
                    code=code, trade_date=td, direction="buy",
                    price=open_price, shares=shares, amount=amount,
                    commission=comm, tax=0, total_cost=total_cost,
                    signal_date=pb["signal_date"], signal_value=pb["signal_value"],
                ))
                total_buys += 1

            pending_buys = new_pending

            # ── Step 2: 更新持有天数 + 到期卖出 ──
            remaining_positions = []
            for pos in positions:
                px = price_idx.get((pos.code, td))
                is_suspended = px is None or float(px.get("volume", 0)) == 0

                if not is_suspended:
                    pos.hold_trading_days += 1

                if pos.hold_trading_days >= cfg.hold_days and not is_suspended:
                    # 到期卖出（用收盘价近似，实际应T+1 open但简化处理）
                    sell_price = float(px["close"])
                    if sell_price <= 0:
                        remaining_positions.append(pos)
                        continue

                    # 跌停检查
                    if self._is_limit_down(px):
                        remaining_positions.append(pos)
                        continue

                    amount = sell_price * pos.shares
                    comm = max(amount * COMMISSION_RATE, MIN_COMMISSION)
                    tax = amount * STAMP_TAX_RATE
                    transfer = amount * TRANSFER_FEE_RATE
                    total_cost = comm + tax + transfer

                    cash += amount - total_cost
                    trades.append(EventFill(
                        code=pos.code, trade_date=td, direction="sell",
                        price=sell_price, shares=pos.shares, amount=amount,
                        commission=comm, tax=tax, total_cost=total_cost,
                        signal_date=pos.signal_date, signal_value=pos.signal_value,
                    ))
                    total_sells += 1
                    hold_days_list.append(pos.hold_trading_days)
                else:
                    remaining_positions.append(pos)

            positions = remaining_positions
            max_concurrent = max(max_concurrent, len(positions))

            # ── Step 3: 检查新信号（T日因子值 → T+1买入） ──
            if len(positions) + len(pending_buys) < cfg.max_positions:
                held_codes = {p.code for p in positions}
                pending_codes = {pb["code"] for pb in pending_buys}

                # 获取当日所有股票的因子值
                triggered = []
                for (code, fdate), fval in factor_idx.items():
                    if fdate != td:
                        continue
                    if code in held_codes or code in pending_codes:
                        continue

                    if cfg.trigger_direction == "above" and fval > cfg.trigger_threshold or cfg.trigger_direction == "below" and fval < cfg.trigger_threshold:
                        triggered.append((code, fval))

                total_signals += len(triggered)

                # 按信号强度排序取前N个
                if cfg.trigger_direction == "above":
                    triggered.sort(key=lambda x: x[1], reverse=True)
                else:
                    triggered.sort(key=lambda x: x[1])

                slots = cfg.max_positions - len(positions) - len(pending_buys)
                for code, fval in triggered[:slots]:
                    pending_buys.append({
                        "code": code,
                        "signal_date": td,
                        "signal_value": fval,
                    })

            # ── Step 4: 计算当日NAV ──
            position_value = 0.0
            for pos in positions:
                px = price_idx.get((pos.code, td))
                if px is not None:
                    position_value += float(px["close"]) * pos.shares

            nav_history[td] = cash + position_value

        # ── 清仓剩余持仓 ──
        last_date = trading_dates[-1] if trading_dates else cfg.end_date
        for pos in positions:
            px = price_idx.get((pos.code, last_date))
            if px is not None:
                sell_price = float(px["close"])
                amount = sell_price * pos.shares
                comm = max(amount * COMMISSION_RATE, MIN_COMMISSION)
                tax = amount * STAMP_TAX_RATE
                transfer = amount * TRANSFER_FEE_RATE
                cash += amount - (comm + tax + transfer)
                hold_days_list.append(pos.hold_trading_days)
                total_sells += 1

        nav_series = pd.Series(nav_history).sort_index()
        daily_returns = nav_series.pct_change().fillna(0)

        avg_hold = np.mean(hold_days_list) if hold_days_list else 0

        logger.info(
            "[EventBT] 完成: signals=%d buys=%d sells=%d avg_hold=%.1fd max_pos=%d final_nav=%.0f",
            total_signals, total_buys, total_sells, avg_hold, max_concurrent,
            nav_series.iloc[-1] if len(nav_series) > 0 else 0,
        )

        return EventBacktestResult(
            daily_nav=nav_series,
            daily_returns=daily_returns,
            trades=trades,
            total_signals=total_signals,
            total_buys=total_buys,
            total_sells=total_sells,
            avg_hold_days=avg_hold,
            max_concurrent_positions=max_concurrent,
        )

    def _is_limit_up(self, px) -> bool:
        """涨停封板检查。"""
        close = float(px.get("close", 0) or 0)
        up_limit = float(px.get("up_limit", 0) or 0)
        turnover = float(px.get("turnover_rate", 0) or 0)
        return (
            up_limit > 0 and close > 0
            and abs(close - up_limit) / up_limit < 0.001
            and turnover < 1.0
        )

    def _is_limit_down(self, px) -> bool:
        """跌停封板检查。"""
        close = float(px.get("close", 0) or 0)
        down_limit = float(px.get("down_limit", 0) or 0)
        turnover = float(px.get("turnover_rate", 0) or 0)
        return (
            down_limit > 0 and close > 0
            and abs(close - down_limit) / down_limit < 0.001
            and turnover < 1.0
        )


def generate_event_report(result: EventBacktestResult, config: EventBacktestConfig) -> dict:
    """生成EVENT回测报告。"""
    nav = result.daily_nav
    rets = result.daily_returns

    if len(rets) < 20:
        return {"error": "insufficient data"}

    # 基础指标
    total_return = (nav.iloc[-1] / nav.iloc[0] - 1) if len(nav) > 0 else 0
    n_years = len(rets) / 244
    annual_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Sharpe
    excess = rets - 0  # 无风险利率近似0
    sharpe = excess.mean() / (excess.std() + 1e-12) * np.sqrt(244)

    # MDD
    cummax = nav.cummax()
    drawdown = (nav - cummax) / cummax
    max_drawdown = drawdown.min()

    # Calmar
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # 单笔统计
    buy_fills = [t for t in result.trades if t.direction == "buy"]
    sell_fills = [t for t in result.trades if t.direction == "sell"]

    pnl_per_trade = []
    for sf in sell_fills:
        # 找对应买入
        matching_buy = [b for b in buy_fills if b.code == sf.code and b.trade_date < sf.trade_date]
        if matching_buy:
            buy = matching_buy[-1]
            pnl = (sf.price - buy.price) / buy.price
            pnl_per_trade.append(pnl)

    win_rate = np.mean([p > 0 for p in pnl_per_trade]) if pnl_per_trade else 0
    avg_pnl = np.mean(pnl_per_trade) if pnl_per_trade else 0

    # 年度分解
    annual = {}
    for year in range(config.start_date.year, config.end_date.year + 1):
        mask = rets.index.map(lambda d: d.year) == year
        yr = rets[mask]
        if len(yr) > 0 and yr.std() > 0:
            annual[year] = {
                "return": (1 + yr).prod() - 1,
                "sharpe": yr.mean() / yr.std() * np.sqrt(244),
            }

    return {
        "factor": config.trigger_factor,
        "threshold": config.trigger_threshold,
        "direction": config.trigger_direction,
        "hold_days": config.hold_days,
        "max_positions": config.max_positions,
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_drawdown, 4),
        "calmar": round(calmar, 3),
        "total_signals": result.total_signals,
        "total_buys": result.total_buys,
        "total_sells": result.total_sells,
        "avg_hold_days": round(result.avg_hold_days, 1),
        "max_concurrent": result.max_concurrent_positions,
        "win_rate": round(win_rate, 3),
        "avg_pnl_per_trade": round(avg_pnl, 4),
        "annual_breakdown": annual,
    }
