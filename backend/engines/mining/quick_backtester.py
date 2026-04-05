"""QuickBacktester — GP适应度函数专用快速回测器。

GP进化循环中每个个体需要评估适应度，完整SimBroker回测太慢（~10秒/因子）。
本模块提供极简版本，目标 <2秒/因子，供GP Engine调用。

设计文档对照:
  - docs/GP_CLOSED_LOOP_DESIGN.md §5: QuickBacktester规格
  - docs/GP_CLOSED_LOOP_DESIGN.md §3.5: 适应度函数设计
  - docs/DEV_BACKTEST_ENGINE.md: 回测可信度规则

简化约定（与生产SimBroker的差异）:
  - 无滑点（GP筛选阶段，精度要求低）
  - 无整手约束（等权权重直接分配）
  - 无风控检查（只做因子排序→等权→净值）
  - 等权Top-N（与v1.1一致: Top15）
  - 月度调仓（与v1.1一致）
  - 最近1年窗口（~250个交易日，~12次调仓）

性能优化:
  - 行情数据按需预加载缓存（调用方传入预处理好的DataFrame）
  - 月度调仓日预计算
  - 单次回测目标: <2秒（基准: 250个交易日×~3000只股票）
"""

from __future__ import annotations

import structlog
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

logger = structlog.get_logger(__name__)

# 年化交易日数（A股）
_TRADING_DAYS_PER_YEAR = 244

# 默认配置（与v1.1一致）
_DEFAULT_TOP_N = 15
_DEFAULT_INITIAL_CAPITAL = 1_000_000.0


@dataclass
class QuickBacktestResult:
    """快速回测结果。

    Attributes:
        sharpe: 年化Sharpe比率（无风险利率=0）。异常返回 -999。
        mdd: 最大回撤（正数，如 0.15 表示 15% 回撤）。
        turnover: 平均单次调仓换手率（双边，[0, 1]）。
        ic_mean: 因子与下期收益的 IC 均值（Spearman）。
        n_rebalances: 实际调仓次数。
        daily_returns: 日收益率序列（用于高级分析，可选）。
        error: 回测失败时的错误信息，None 表示成功。
    """

    sharpe: float
    mdd: float
    turnover: float
    ic_mean: float
    n_rebalances: int
    daily_returns: pd.Series | None = None
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        """回测结果是否有效（未出错）。"""
        return self.error is None and self.sharpe != -999.0


# ---------------------------------------------------------------------------
# 核心类
# ---------------------------------------------------------------------------


class QuickBacktester:
    """GP适应度专用快速回测器。

    使用方法:
        # 预加载行情数据（调用方负责缓存，避免每次GP评估重复读DB）
        qt = QuickBacktester(price_data=price_df, top_n=15)

        # GP进化中调用
        result = qt.backtest(factor_values)
        fitness = result.sharpe  # 适应度 = Sharpe

    Args:
        price_data: 行情DataFrame，必须包含列:
            - trade_date: date
            - code: str (ts_code格式)
            - close: float (复权收盘价)
            - open: float (复权开盘价，用于T+1执行价)
            - volume: float (成交量，用于停牌过滤)
        top_n: 选股数量，默认 15（与v1.1一致）。
        initial_capital: 初始资金，默认100万。
        lookback_days: 回测窗口天数，默认365天（~1年）。
    """

    def __init__(
        self,
        price_data: pd.DataFrame,
        top_n: int = _DEFAULT_TOP_N,
        initial_capital: float = _DEFAULT_INITIAL_CAPITAL,
        lookback_days: int = 365,
    ) -> None:
        self.top_n = top_n
        self.initial_capital = initial_capital
        self.lookback_days = lookback_days

        # 预处理行情数据，缓存到内存
        self._price_data = self._prepare_price_data(price_data)
        self._all_dates: list[date] = sorted(self._price_data["trade_date"].unique().tolist())
        self._rebalance_dates: list[date] = self._calc_monthly_rebalance_dates()

        logger.debug(
            "[QuickBacktester] 初始化完成: %d 个交易日, %d 只股票, %d 次月度调仓",
            len(self._all_dates),
            self._price_data["code"].nunique(),
            len(self._rebalance_dates),
        )

    # ----------------------------------------------------------------
    # 主入口
    # ----------------------------------------------------------------

    def backtest(self, factor_values: pd.DataFrame) -> QuickBacktestResult:
        """执行快速回测，返回 QuickBacktestResult。

        Args:
            factor_values: 因子值 DataFrame，必须包含列:
                - trade_date: date (信号日，月末)
                - code: str (ts_code)
                - factor_value: float (因子截面值，已处理 NaN)

        Returns:
            QuickBacktestResult: sharpe/mdd/turnover/ic_mean。
            异常时 sharpe=-999，error 字段说明原因。
        """
        try:
            return self._run(factor_values)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[QuickBacktester] 回测异常: %s", exc, exc_info=True)
            return QuickBacktestResult(
                sharpe=-999.0,
                mdd=1.0,
                turnover=0.0,
                ic_mean=0.0,
                n_rebalances=0,
                error=str(exc),
            )

    # ----------------------------------------------------------------
    # 内部实现
    # ----------------------------------------------------------------

    def _run(self, factor_values: pd.DataFrame) -> QuickBacktestResult:
        """回测主逻辑。

        流程:
        1. 遍历调仓日（月末），按因子值排序选Top-N
        2. 下一个交易日开盘价执行（T+1 open，与生产一致）
        3. 等权持仓，计算每日NAV
        4. 最后计算 Sharpe / MDD / 换手率 / IC
        """
        if factor_values.empty:
            raise ValueError("factor_values 为空")

        required_cols = {"trade_date", "code", "factor_value"}
        missing = required_cols - set(factor_values.columns)
        if missing:
            raise ValueError(f"factor_values 缺少列: {missing}")

        # 构建因子索引: trade_date → {code: value}
        factor_idx: dict[date, dict[str, float]] = {}
        for _, row in factor_values.iterrows():
            td = row["trade_date"]
            if isinstance(td, pd.Timestamp):
                td = td.date()
            factor_idx.setdefault(td, {})[row["code"]] = float(row["factor_value"])

        # 构建价格索引: (code, trade_date) → {open, close}
        price_idx: dict[tuple[str, date], dict[str, float]] = {}
        for _, row in self._price_data.iterrows():
            td = row["trade_date"]
            if isinstance(td, pd.Timestamp):
                td = td.date()
            price_idx[(row["code"], td)] = {
                "open": float(row["open"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 1)),
            }

        # 每日收盘价: date → {code: close}
        daily_close: dict[date, dict[str, float]] = {}
        for td in self._all_dates:
            td_key = td if isinstance(td, date) else td.date()
            day_rows = self._price_data[self._price_data["trade_date"] == td]
            daily_close[td_key] = dict(zip(day_rows["code"], day_rows["close"], strict=False))

        if not self._all_dates:
            raise ValueError("价格数据无交易日")

        # NAV序列
        nav = self.initial_capital
        daily_navs: list[tuple[date, float]] = []
        current_portfolio: dict[str, float] = {}  # code → weight
        turnovers: list[float] = []
        n_rebalances = 0

        # 确定哪些调仓日有因子数据
        valid_rebal_dates = [d for d in self._rebalance_dates if d in factor_idx]

        if not valid_rebal_dates:
            raise ValueError(
                f"无有效调仓日: 调仓日={len(self._rebalance_dates)}, "
                f"因子日={len(factor_idx)}"
            )

        # 执行日映射: signal_date → exec_date (下一个交易日)
        exec_map: dict[date, date] = {}
        for sd in valid_rebal_dates:
            sd_key = sd if isinstance(sd, date) else sd.date()
            future = [d for d in self._all_dates if (
                (d if isinstance(d, date) else d.date()) > sd_key
            )]
            if future:
                exec_d = future[0]
                if isinstance(exec_d, pd.Timestamp):
                    exec_d = exec_d.date()
                exec_map[exec_d] = sd_key

        # 主循环
        for raw_td in self._all_dates:
            td = raw_td if isinstance(raw_td, date) else raw_td.date()

            closes = daily_close.get(td, {})

            # 调仓执行
            if td in exec_map:
                signal_date = exec_map[td]
                factor_snapshot = factor_idx.get(signal_date, {})

                # 选Top-N（因子值越大越好，假设因子值已处理方向）
                valid_codes = [
                    (code, val)
                    for code, val in factor_snapshot.items()
                    if not math.isnan(val)
                    and price_idx.get((code, td), {}).get("volume", 0) > 0
                ]
                valid_codes.sort(key=lambda x: x[1], reverse=True)
                selected = [code for code, _ in valid_codes[: self.top_n]]

                if selected:
                    new_portfolio = {code: 1.0 / len(selected) for code in selected}

                    # 计算换手率（双边）
                    all_codes = set(new_portfolio) | set(current_portfolio)
                    turnover = sum(
                        abs(new_portfolio.get(c, 0.0) - current_portfolio.get(c, 0.0))
                        for c in all_codes
                    ) / 2.0
                    turnovers.append(turnover)

                    current_portfolio = new_portfolio
                    n_rebalances += 1

            # 更新NAV（用持仓的收盘价加权）
            if current_portfolio and closes:
                portfolio_return = 0.0
                for code, weight in current_portfolio.items():
                    if code in closes:
                        # 前日收盘价
                        prev_close = _get_prev_close(closes, code, price_idx, td, self._all_dates)
                        if prev_close and prev_close > 0:
                            ret = (closes[code] - prev_close) / prev_close
                            portfolio_return += weight * ret

                nav = nav * (1.0 + portfolio_return)

            daily_navs.append((td, nav))

        if len(daily_navs) < 2:
            raise ValueError(f"回测数据点不足: {len(daily_navs)}")

        # 构建NAV序列
        nav_series = pd.Series(
            {d: v for d, v in daily_navs},
            name="nav",
        )
        daily_returns = nav_series.pct_change().dropna()

        sharpe = _calc_sharpe(daily_returns)
        mdd = _calc_mdd(nav_series)
        avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0
        ic_mean = _calc_ic_mean(factor_values, self._price_data)

        return QuickBacktestResult(
            sharpe=sharpe,
            mdd=mdd,
            turnover=avg_turnover,
            ic_mean=ic_mean,
            n_rebalances=n_rebalances,
            daily_returns=daily_returns,
        )

    def _prepare_price_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """预处理行情数据：过滤窗口、标准化列名、去掉停牌。

        Args:
            df: 原始行情DataFrame。

        Returns:
            处理后的DataFrame，按 (trade_date, code) 索引。
        """
        required = {"trade_date", "code", "close", "open"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"price_data 缺少列: {missing}")

        df = df.copy()

        # 标准化日期类型
        if df["trade_date"].dtype == object or str(df["trade_date"].dtype).startswith("datetime"):
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        # 截取最近 lookback_days
        max_date = df["trade_date"].max()
        cutoff = max_date - pd.Timedelta(days=self.lookback_days)
        if isinstance(cutoff, pd.Timestamp):
            cutoff = cutoff.date()
        df = df[df["trade_date"] >= cutoff].copy()

        # 过滤无效数据
        df = df[(df["close"] > 0) & (df["open"] > 0)].copy()

        if "volume" not in df.columns:
            df["volume"] = 1.0

        return df.reset_index(drop=True)

    def _calc_monthly_rebalance_dates(self) -> list[date]:
        """计算月度调仓日（每月最后一个交易日）。

        Returns:
            调仓日列表，按升序排列。
        """
        if not self._all_dates:
            return []

        dates = pd.Series(self._all_dates)
        if not pd.api.types.is_datetime64_any_dtype(dates):
            dates = pd.to_datetime(dates)

        # 每月最后一个交易日
        month_ends: list[date] = []
        for _month_key, group in dates.groupby(dates.dt.to_period("M")):
            last_day = group.max()
            if isinstance(last_day, pd.Timestamp):
                month_ends.append(last_day.date())
            else:
                month_ends.append(last_day)

        return sorted(month_ends)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_prev_close(
    current_closes: dict[str, float],
    code: str,
    price_idx: dict[tuple[str, date], dict[str, float]],
    td: date,
    all_dates: list,
) -> float | None:
    """获取前一交易日收盘价。

    Args:
        current_closes: 当日收盘价字典。
        code: 股票代码。
        price_idx: 全量价格索引。
        td: 当前交易日。
        all_dates: 全部交易日列表。

    Returns:
        前日收盘价，找不到时返回 None。
    """
    all_dates_norm = [d if isinstance(d, date) else d.date() for d in all_dates]
    try:
        idx = all_dates_norm.index(td)
    except ValueError:
        return None
    if idx == 0:
        return None
    prev_td = all_dates_norm[idx - 1]
    row = price_idx.get((code, prev_td))
    if row:
        return row.get("close")
    return None


def _calc_sharpe(daily_returns: pd.Series, rf: float = 0.0) -> float:
    """计算年化Sharpe比率（无风险利率=0）。

    Args:
        daily_returns: 日收益率序列。
        rf: 年化无风险利率，默认 0。

    Returns:
        年化Sharpe。标准差接近零时返回 0。
    """
    if len(daily_returns) < 5:
        return 0.0
    std = daily_returns.std()
    if std < 1e-12:
        return 0.0
    excess = daily_returns - rf / _TRADING_DAYS_PER_YEAR
    return float(excess.mean() / std * math.sqrt(_TRADING_DAYS_PER_YEAR))


def _calc_mdd(nav_series: pd.Series) -> float:
    """计算最大回撤。

    Args:
        nav_series: NAV时序。

    Returns:
        最大回撤（正数，如 0.15 表示 15%）。
    """
    if len(nav_series) < 2:
        return 0.0
    cummax = nav_series.cummax()
    drawdown = (cummax - nav_series) / cummax
    return float(drawdown.max())


def _calc_ic_mean(
    factor_values: pd.DataFrame,
    price_data: pd.DataFrame,
    forward_days: int = 20,
) -> float:
    """计算因子与前向收益的 Spearman IC 均值。

    使用月度截面IC，与 Factor Gate G1 定义一致。

    Args:
        factor_values: 因子值 DataFrame (trade_date/code/factor_value)。
        price_data: 行情 DataFrame (trade_date/code/close)。
        forward_days: 前向收益窗口，默认 20 日。

    Returns:
        月度IC均值。数据不足时返回 0.0。
    """
    from scipy import stats as sp_stats

    try:
        # 构建收盘价索引
        close_idx: dict[tuple[str, date], float] = {}
        for _, row in price_data.iterrows():
            td = row["trade_date"]
            if isinstance(td, pd.Timestamp):
                td = td.date()
            close_idx[(row["code"], td)] = float(row["close"])

        all_dates = sorted({
            d if isinstance(d, date) else d.date()
            for d in price_data["trade_date"].unique()
        })

        ics: list[float] = []
        for _, grp in factor_values.groupby("trade_date"):
            if grp.empty:
                continue
            td = grp["trade_date"].iloc[0]
            if isinstance(td, pd.Timestamp):
                td = td.date()

            # 找前向 forward_days 日
            future_dates = [d for d in all_dates if d > td]
            if len(future_dates) < forward_days:
                continue
            fwd_date = future_dates[forward_days - 1]

            f_vals = []
            f_rets = []
            for _, row in grp.iterrows():
                code = row["code"]
                c0 = close_idx.get((code, td))
                c1 = close_idx.get((code, fwd_date))
                if c0 and c1 and c0 > 0 and not math.isnan(float(row["factor_value"])):
                    f_vals.append(float(row["factor_value"]))
                    f_rets.append((c1 - c0) / c0)

            if len(f_vals) < 10:
                continue

            ic, _ = sp_stats.spearmanr(f_vals, f_rets)
            if not math.isnan(ic):
                ics.append(float(ic))

        return float(np.mean(ics)) if ics else 0.0

    except Exception as exc:  # noqa: BLE001
        logger.debug("[QuickBacktester] IC计算失败: %s", exc)
        return 0.0
