"""多频率回测对比 — 同一因子组合在不同调仓频率下的表现比较。

标准化回测协议:
- 同期: 2021-2025
- 同成本: 国金万0.854
- 同Universe: 全A标准过滤
- 输出: 频率 | Sharpe | CI | MDD | 换手率

用法:
    runner = MultiFreqBacktestRunner(conn)
    results = runner.run_comparison(
        factor_names=["turnover_mean_20", "volatility_20", ...],
        freqs=["weekly", "biweekly", "monthly"],
    )
    runner.print_comparison(results)
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import structlog

from engines.backtest_engine import BacktestConfig, BacktestResult, SimpleBacktester
from engines.signal_engine import (
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)

logger = structlog.get_logger(__name__)


# 标准化成本参数（国金证券）
STANDARD_COST = {
    "commission_rate": 0.0000854,  # 万0.854
    "stamp_tax_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
    "slippage_bps": 10.0,
}


@dataclass
class FreqBacktestResult:
    """单频率回测结果摘要。"""

    freq: str
    sharpe: float
    sharpe_ci_low: float
    sharpe_ci_high: float
    annual_return: float
    max_drawdown: float
    calmar: float
    annual_turnover: float
    avg_holding_period: float  # 平均持仓周期(交易日)
    full_result: BacktestResult | None = None


@dataclass
class MultiFreqComparison:
    """多频率对比结果。"""

    factor_names: list[str]
    top_n: int
    period: str  # "2021-2025"
    results: list[FreqBacktestResult] = field(default_factory=list)
    best_freq: str = ""
    recommended_freq: str = ""


class MultiFreqBacktestRunner:
    """多频率回测对比运行器。"""

    def __init__(
        self,
        conn: Any,
        initial_capital: float = 1_000_000.0,
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        self.conn = conn
        self.initial_capital = initial_capital
        self.start_date = start_date or date(2021, 1, 1)
        self.end_date = end_date or date(2025, 12, 31)

    def run_comparison(
        self,
        factor_names: list[str],
        top_n: int = 15,
        industry_cap: float = 0.25,
        turnover_cap: float = 0.50,
        freqs: list[str] | None = None,
        price_data: pd.DataFrame | None = None,
        factor_data: pd.DataFrame | None = None,
        industry_map: dict[str, str] | None = None,
        benchmark_data: pd.DataFrame | None = None,
    ) -> MultiFreqComparison:
        """运行多频率回测对比。

        Args:
            factor_names: 因子名称列表
            top_n: 持仓数
            industry_cap: 单行业上限
            turnover_cap: 换手率上限
            freqs: 频率列表，默认["weekly", "biweekly", "monthly"]
            price_data: 价格数据(可注入，不传则从DB读)
            factor_data: 因子数据(可注入)
            industry_map: 行业映射(可注入)
            benchmark_data: 基准数据(可注入)

        Returns:
            MultiFreqComparison: 对比结果
        """
        if freqs is None:
            freqs = ["weekly", "biweekly", "monthly"]

        # 加载数据（如果未注入）
        if price_data is None:
            price_data = self._load_price_data()
        if factor_data is None:
            factor_data = self._load_factor_data(factor_names)
        if industry_map is None:
            industry_map = self._load_industry_map()

        comparison = MultiFreqComparison(
            factor_names=factor_names,
            top_n=top_n,
            period=f"{self.start_date.year}-{self.end_date.year}",
        )

        for freq in freqs:
            logger.info(f"[MultiFreq] 运行 {freq} 回测...")
            result = self._run_single_freq(
                factor_names=factor_names,
                top_n=top_n,
                industry_cap=industry_cap,
                turnover_cap=turnover_cap,
                freq=freq,
                price_data=price_data,
                factor_data=factor_data,
                industry_map=industry_map,
                benchmark_data=benchmark_data,
            )
            comparison.results.append(result)

        # 确定最优频率（Sharpe最高）
        if comparison.results:
            best = max(comparison.results, key=lambda r: r.sharpe)
            comparison.best_freq = best.freq
            # 推荐频率: Sharpe最高且CI下界>0
            valid = [r for r in comparison.results if r.sharpe_ci_low > 0]
            if valid:
                comparison.recommended_freq = max(
                    valid, key=lambda r: r.sharpe
                ).freq
            else:
                comparison.recommended_freq = best.freq

        return comparison

    def _run_single_freq(
        self,
        factor_names: list[str],
        top_n: int,
        industry_cap: float,
        turnover_cap: float,
        freq: str,
        price_data: pd.DataFrame,
        factor_data: pd.DataFrame,
        industry_map: dict[str, str],
        benchmark_data: pd.DataFrame | None,
    ) -> FreqBacktestResult:
        """运行单个频率的回测。"""
        config = SignalConfig(
            factor_names=factor_names,
            top_n=top_n,
            weight_method="equal",
            industry_cap=industry_cap,
            rebalance_freq=freq,
            turnover_cap=turnover_cap,
        )

        # 获取调仓日历
        rebalance_dates = get_rebalance_dates(
            self.start_date, self.end_date, freq=freq, conn=self.conn,
        )

        if freq == "daily":
            # daily: 每个交易日都调仓
            rebalance_dates = sorted(
                price_data["trade_date"].unique()
            )
            rebalance_dates = [
                d for d in rebalance_dates
                if self.start_date <= d <= self.end_date
            ]

        # 生成每个调仓日的目标持仓
        composer = SignalComposer(config)
        builder = PortfolioBuilder(config)
        industry_series = pd.Series(industry_map)

        target_portfolios: dict[date, dict[str, float]] = {}
        prev_holdings: dict[str, float] | None = None

        for rd in rebalance_dates:
            # 获取该日因子数据
            day_factors = factor_data[factor_data["trade_date"] == rd]
            if day_factors.empty:
                continue

            # 合成得分
            scores = composer.compose(pd.DataFrame(day_factors))
            if scores.empty:
                continue

            # 构建目标持仓
            target = builder.build(scores, industry_series, prev_holdings)
            if target:
                target_portfolios[rd] = target
                prev_holdings = target

        if not target_portfolios:
            logger.warning(f"[MultiFreq] {freq}: 无有效调仓日")
            return FreqBacktestResult(
                freq=freq, sharpe=0.0, sharpe_ci_low=0.0,
                sharpe_ci_high=0.0, annual_return=0.0,
                max_drawdown=0.0, calmar=0.0,
                annual_turnover=0.0, avg_holding_period=0.0,
            )

        # 执行回测
        bt_config = BacktestConfig(
            initial_capital=self.initial_capital,
            top_n=top_n,
            rebalance_freq=freq,
            turnover_cap=turnover_cap,
            commission_rate=STANDARD_COST["commission_rate"],
            stamp_tax_rate=STANDARD_COST["stamp_tax_rate"],
            transfer_fee_rate=STANDARD_COST["transfer_fee_rate"],
            slippage_bps=STANDARD_COST["slippage_bps"],
        )

        backtester = SimpleBacktester(bt_config)
        bt_result = backtester.run(
            target_portfolios=target_portfolios,
            price_data=price_data,
            benchmark_data=benchmark_data,
        )

        # 计算指标
        sharpe, ci_low, ci_high = self._calc_sharpe_ci(bt_result.daily_returns)
        annual_ret = self._calc_annual_return(bt_result.daily_nav)
        mdd = self._calc_max_drawdown(bt_result.daily_nav)
        calmar = annual_ret / abs(mdd) if mdd != 0 else 0.0
        annual_turnover = self._calc_annual_turnover(bt_result.turnover_series)
        avg_hold = self._calc_avg_holding_period(freq)

        return FreqBacktestResult(
            freq=freq,
            sharpe=sharpe,
            sharpe_ci_low=ci_low,
            sharpe_ci_high=ci_high,
            annual_return=annual_ret,
            max_drawdown=mdd,
            calmar=calmar,
            annual_turnover=annual_turnover,
            avg_holding_period=avg_hold,
            full_result=bt_result,
        )

    def _calc_sharpe_ci(
        self, daily_returns: pd.Series, n_bootstrap: int = 1000
    ) -> tuple[float, float, float]:
        """Bootstrap Sharpe 95% CI。"""
        if daily_returns.empty or daily_returns.std() == 0:
            return 0.0, 0.0, 0.0

        sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))

        # Bootstrap
        rng = np.random.RandomState(42)
        n = len(daily_returns)
        values = np.asarray(daily_returns.values)
        bootstrap_sharpes = []

        for _ in range(n_bootstrap):
            sample = rng.choice(values, size=n, replace=True)
            std = sample.std()
            if std > 0:
                bootstrap_sharpes.append(sample.mean() / std * np.sqrt(252))

        if bootstrap_sharpes:
            ci_low = float(np.percentile(bootstrap_sharpes, 2.5))
            ci_high = float(np.percentile(bootstrap_sharpes, 97.5))
        else:
            ci_low, ci_high = sharpe, sharpe

        return sharpe, ci_low, ci_high

    def _calc_annual_return(self, nav: pd.Series) -> float:
        """年化收益率。"""
        if len(nav) < 2:
            return 0.0
        total_return = nav.iloc[-1] / nav.iloc[0] - 1
        years = len(nav) / 252
        if years <= 0:
            return 0.0
        return float((1 + total_return) ** (1 / years) - 1)

    def _calc_max_drawdown(self, nav: pd.Series) -> float:
        """最大回撤。"""
        if nav.empty:
            return 0.0
        peak = nav.cummax()
        dd = (nav - peak) / peak
        return float(dd.min())

    def _calc_annual_turnover(self, turnover_series: pd.Series) -> float:
        """年化换手率。"""
        if turnover_series.empty:
            return 0.0
        total = turnover_series.sum()
        years = len(turnover_series) / 252
        if years <= 0:
            return 0.0
        return float(total / years)

    def _calc_avg_holding_period(self, freq: str) -> float:
        """估算平均持仓周期(交易日)。"""
        freq_days = {
            "daily": 1,
            "weekly": 5,
            "biweekly": 10,
            "monthly": 21,
        }
        return float(freq_days.get(freq, 21))

    def _load_price_data(self) -> pd.DataFrame:
        """从DB加载价格数据。"""
        query = """
            SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                   k.volume, k.pre_close, k.up_limit, k.down_limit,
                   db.turnover_rate
            FROM klines_daily k
            LEFT JOIN daily_basic db ON k.code = db.ts_code
                AND k.trade_date = db.trade_date
            WHERE k.trade_date BETWEEN %s AND %s
            ORDER BY k.trade_date, k.code
        """
        return pd.read_sql(query, self.conn, params=(self.start_date, self.end_date))

    def _load_factor_data(self, factor_names: list[str]) -> pd.DataFrame:
        """从DB加载因子数据。"""
        placeholders = ",".join(["%s"] * len(factor_names))
        query = f"""
            SELECT s.code, fv.trade_date, fv.factor_name, fv.neutral_value
            FROM factor_values fv
            JOIN symbols s ON fv.symbol_id = s.id
            WHERE fv.trade_date BETWEEN %s AND %s
              AND fv.factor_name IN ({placeholders})
            ORDER BY fv.trade_date, s.code
        """
        params = [self.start_date, self.end_date] + factor_names
        return pd.read_sql(query, self.conn, params=params)

    def _load_industry_map(self) -> dict[str, str]:
        """从DB加载行业映射。"""
        query = """
            SELECT code, industry_sw1 FROM symbols
            WHERE industry_sw1 IS NOT NULL
        """
        df = pd.read_sql(query, self.conn)
        return dict(zip(df["code"], df["industry_sw1"], strict=False))

    @staticmethod
    def print_comparison(comparison: MultiFreqComparison) -> str:
        """格式化输出对比结果。

        Returns:
            格式化的对比表格字符串
        """
        lines = [
            "=== 多频率回测对比 ===",
            f"因子: {', '.join(comparison.factor_names)}",
            f"Top-N: {comparison.top_n} | 期间: {comparison.period}",
            "",
            f"{'频率':<10} {'Sharpe':>8} {'CI_low':>8} {'CI_high':>8} "
            f"{'年化收益':>10} {'MDD':>8} {'Calmar':>8} {'年化换手':>10}",
            f"{'-'*80}",
        ]

        for r in comparison.results:
            marker = " *" if r.freq == comparison.best_freq else ""
            lines.append(
                f"{r.freq:<10} {r.sharpe:>8.3f} {r.sharpe_ci_low:>8.3f} "
                f"{r.sharpe_ci_high:>8.3f} {r.annual_return:>9.1%} "
                f"{r.max_drawdown:>7.1%} {r.calmar:>8.3f} "
                f"{r.annual_turnover:>9.1f}x{marker}"
            )

        lines.append("")
        lines.append(f"最优频率(Sharpe最高): {comparison.best_freq}")
        lines.append(f"推荐频率(CI下界>0): {comparison.recommended_freq}")

        output = "\n".join(lines)
        logger.info(output)
        return output
