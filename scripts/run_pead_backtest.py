#!/usr/bin/env python3
"""PEAD 6因子组合回测对比 — v1.1基线 vs v1.2候选(+earnings_surprise_car)。

配置A (v1.1基线): turnover_mean_20(-1) + volatility_20(-1) + reversal_20(+1)
                 + amihud_20(+1) + bp_ratio(+1), Top15月频 IndCap=25%
配置B (v1.2候选): 上述5因子 + earnings_surprise_car(+1), Top15月频 IndCap=25%

PEAD因子(earnings_surprise_car):
  - 来源: financial_indicators.actual_ann_date + klines_daily
  - 公式: CAR[-2,+2] = 公告日前后5日累计超额收益(vs CSI300)
  - PIT对齐: 因子值仅在公告日之后可用
  - 120天有效期: 超过120天的CAR视为过期

回测区间: 2021-01-01 ~ 2025-12-31, 100万初始资金
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.config_guard import print_config_header
from engines.metrics import generate_report
from engines.signal_engine import (
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from run_backtest import (
    load_benchmark,
    load_factor_values,
    load_industry,
    load_price_data,
    load_universe,
)

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"


# ============================================================
# PEAD因子计算
# ============================================================


def compute_pead_factor_panel(conn, start_date: date, end_date: date) -> dict[date, pd.Series]:
    """计算PEAD因子(earnings_surprise_car)的月末截面面板。

    方法:
      1. 从financial_indicators加载公告日
      2. 从klines_daily计算个股日收益 - CSI300日收益 = 超额收益
      3. CAR[-2,+2]: 公告日前后各2个交易日的累计超额收益
      4. PIT: 每个月末取每只股最近的CAR(120天内有效)

    Args:
        conn: psycopg2连接。
        start_date: 回测开始日期。
        end_date: 回测结束日期。

    Returns:
        {月末日期: pd.Series(code→car值)}
    """
    logger.info("计算PEAD因子(earnings_surprise_car)...")
    t0 = time.time()

    # 1. 加载公告日
    ann_df = pd.read_sql(
        """SELECT code, report_date, actual_ann_date
           FROM financial_indicators
           WHERE actual_ann_date IS NOT NULL
             AND actual_ann_date >= %s - INTERVAL '365 days'
           ORDER BY code, actual_ann_date""",
        conn,
        params=(start_date,),
    )
    logger.info(f"  公告记录: {len(ann_df):,}, 覆盖股票: {ann_df['code'].nunique()}")

    # 2. 加载日收益率
    ret_df = pd.read_sql(
        """SELECT code, trade_date, pct_change::float/100 as ret
           FROM klines_daily
           WHERE trade_date >= %s - INTERVAL '400 days'
             AND trade_date <= %s
             AND volume > 0
           ORDER BY trade_date, code""",
        conn,
        params=(start_date, end_date),
    )

    bench_df = pd.read_sql(
        """SELECT trade_date, close::float
           FROM index_daily
           WHERE index_code='000300.SH'
             AND trade_date >= %s - INTERVAL '400 days'
             AND trade_date <= %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )
    bench_df["bench_ret"] = bench_df["close"].pct_change()
    bench_ret = bench_df.set_index("trade_date")["bench_ret"]

    trading_dates = sorted(ret_df["trade_date"].unique())
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}

    ret_wide = ret_df.pivot(index="trade_date", columns="code", values="ret")
    ret_wide = ret_wide.reindex(trading_dates)
    excess_ret_wide = ret_wide.sub(bench_ret, axis=0)

    # 3. 计算CAR[-2, +2]
    logger.info("  计算CAR[-2,+2]...")
    car_records = []
    n_skip = 0
    for _, row in ann_df.iterrows():
        code = row["code"]
        ann_date = row["actual_ann_date"]

        if ann_date not in date_to_idx:
            idx = np.searchsorted(trading_dates, ann_date)
            if idx >= len(trading_dates):
                n_skip += 1
                continue
            ann_date = trading_dates[idx]

        idx = date_to_idx[ann_date]
        start_idx = max(0, idx - 2)
        end_idx = min(len(trading_dates) - 1, idx + 2)

        if end_idx - start_idx < 3:
            n_skip += 1
            continue

        window_dates = trading_dates[start_idx : end_idx + 1]
        if code not in excess_ret_wide.columns:
            n_skip += 1
            continue

        car = excess_ret_wide.loc[window_dates, code].sum()
        if np.isnan(car):
            n_skip += 1
            continue

        car_records.append(
            {
                "code": code,
                "ann_date": ann_date,
                "car": car,
            }
        )

    car_df = pd.DataFrame(car_records)
    logger.info(f"  有效CAR: {len(car_df):,}, 跳过: {n_skip}")

    if len(car_df) < 100:
        logger.error("  CAR数据不足, PEAD因子不可用")
        return {}

    car_df = car_df.sort_values("ann_date")

    # 4. 构建月末截面
    dates_dt = pd.to_datetime(pd.Series(trading_dates))
    month_ends = pd.Series(trading_dates).groupby(dates_dt.dt.to_period("M")).last().values

    result: dict[date, pd.Series] = {}
    for d in month_ends:
        d_date = pd.Timestamp(d).date() if hasattr(pd.Timestamp(d), "date") else d
        if d_date < start_date or d_date > end_date:
            continue

        # PIT: 只取ann_date <= d的CAR
        mask = car_df["ann_date"] <= d
        if mask.sum() == 0:
            continue

        recent_car = car_df[mask].groupby("code")["car"].last()
        # 120天有效期
        recent_dates = car_df[mask].groupby("code")["ann_date"].last()
        cutoff = d_date - pd.Timedelta(days=120)
        fresh = recent_dates[recent_dates >= cutoff].index
        recent_car = recent_car.reindex(fresh).dropna()

        if len(recent_car) >= 100:
            result[d_date] = recent_car

    logger.info(f"  PEAD月末截面: {len(result)}个月, {time.time() - t0:.1f}s")
    return result


# ============================================================
# 信号合成（支持外部因子注入）
# ============================================================


class PEADSignalComposer(SignalComposer):
    """扩展SignalComposer: 支持注入PEAD因子到因子截面中。"""

    def __init__(self, config: SignalConfig, pead_panel: dict[date, pd.Series]):
        """初始化。

        Args:
            config: 信号配置。
            pead_panel: {月末日期: pd.Series(code→car值)}。
        """
        super().__init__(config)
        self.pead_panel = pead_panel

    def compose(
        self, fv: pd.DataFrame, universe: set[str], trade_date: date | None = None
    ) -> pd.Series:
        """合成信号, 注入PEAD因子。

        Args:
            fv: factor_values长表(code, factor_name, neutral_value)。
            universe: 可交易universe。
            trade_date: 当前调仓日(用于查找对应的PEAD截面)。

        Returns:
            pd.Series(code→composite_score)。
        """
        # 如果配置中包含earnings_surprise_car且有PEAD数据, 注入
        if (
            "earnings_surprise_car" in self.config.factor_names
            and trade_date is not None
            and trade_date in self.pead_panel
        ):
            pead_series = self.pead_panel[trade_date]
            # 构造与fv同格式的DataFrame
            pead_rows = pd.DataFrame(
                {
                    "code": pead_series.index,
                    "factor_name": "earnings_surprise_car",
                    "neutral_value": pead_series.values,
                }
            )
            fv = pd.concat([fv, pead_rows], ignore_index=True)

        return super().compose(fv, universe)


# ============================================================
# Bootstrap Sharpe CI
# ============================================================


def bootstrap_sharpe_ci(
    daily_returns: pd.Series, n_bootstrap: int = 1000, ci: float = 0.95
) -> tuple[float, float, float]:
    """计算Sharpe的Bootstrap置信区间。

    Args:
        daily_returns: 日收益率序列。
        n_bootstrap: 抽样次数。
        ci: 置信水平。

    Returns:
        (sharpe_mean, ci_lower, ci_upper)
    """
    returns = daily_returns.dropna().values
    n = len(returns)
    if n < 30:
        return (0.0, 0.0, 0.0)

    rng = np.random.RandomState(42)
    sharpes = []
    for _ in range(n_bootstrap):
        sample = rng.choice(returns, size=n, replace=True)
        mean_r = sample.mean()
        std_r = sample.std()
        if std_r > 0:
            sharpes.append(mean_r / std_r * np.sqrt(252))
    sharpes = np.array(sharpes)
    alpha = (1 - ci) / 2
    return (
        float(np.mean(sharpes)),
        float(np.percentile(sharpes, alpha * 100)),
        float(np.percentile(sharpes, (1 - alpha) * 100)),
    )


# ============================================================
# 主程序
# ============================================================


def run_single_backtest(
    label: str,
    sig_config: SignalConfig,
    bt_config: BacktestConfig,
    rebalance_dates: list[date],
    industry: pd.Series,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    conn,
    pead_panel: dict[date, pd.Series] | None = None,
) -> dict:
    """运行单个回测配置, 返回绩效摘要。

    Args:
        label: 配置标签(如"v1.1"或"v1.2")。
        sig_config: 信号配置。
        bt_config: 回测配置。
        rebalance_dates: 调仓日列表。
        industry: 行业分类Series。
        price_data: 价格数据DataFrame。
        benchmark_data: 基准数据DataFrame。
        conn: DB连接。
        pead_panel: PEAD因子面板(仅v1.2需要)。

    Returns:
        绩效摘要字典。
    """
    logger.info(f"\n{'=' * 60}")
    logger.info(f"  配置: {label}")
    logger.info(f"  因子: {sig_config.factor_names}")
    logger.info(f"{'=' * 60}")

    # 信号生成
    if pead_panel and "earnings_surprise_car" in sig_config.factor_names:
        composer = PEADSignalComposer(sig_config, pead_panel)
    else:
        composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue

        universe = load_universe(rd, conn)

        if isinstance(composer, PEADSignalComposer):
            scores = composer.compose(fv, universe, trade_date=rd)
        else:
            scores = composer.compose(fv, universe)

        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 20 == 0:
            logger.info(f"  [{label}] 信号 [{i + 1}/{len(rebalance_dates)}] {rd}: {len(target)}只")

    logger.info(f"  [{label}] 信号完成: {len(target_portfolios)}个调仓日")

    # 回测
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)

    # 绩效(generate_report用于验证内部一致性)
    _ = generate_report(result, price_data)

    # Bootstrap CI
    sharpe_mean, ci_low, ci_high = bootstrap_sharpe_ci(result.daily_returns)

    # 年度分解
    dr = result.daily_returns.copy()
    dr.index = pd.to_datetime(dr.index)
    annual = {}
    for year in range(2021, 2026):
        mask = dr.index.year == year
        yr = dr[mask]
        if len(yr) > 0:
            ann_ret = (1 + yr).prod() - 1
            ann_sharpe = yr.mean() / yr.std() * np.sqrt(252) if yr.std() > 0 else 0
            # 累计净值 → MDD
            cum = (1 + yr).cumprod()
            drawdown = cum / cum.cummax() - 1
            mdd = drawdown.min()
            annual[year] = {
                "return": float(ann_ret),
                "sharpe": float(ann_sharpe),
                "mdd": float(mdd),
            }

    # 整体
    total_ret = (1 + dr).prod() - 1
    ann_ret = (1 + total_ret) ** (252 / len(dr)) - 1 if len(dr) > 0 else 0
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    cum_nav = (1 + dr).cumprod()
    mdd = (cum_nav / cum_nav.cummax() - 1).min()

    summary = {
        "label": label,
        "factors": sig_config.factor_names,
        "n_factors": len(sig_config.factor_names),
        "total_return": float(total_ret),
        "ann_return": float(ann_ret),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "bootstrap_sharpe_mean": sharpe_mean,
        "bootstrap_ci_low": ci_low,
        "bootstrap_ci_high": ci_high,
        "annual": annual,
        "n_rebalances": len(target_portfolios),
        "n_trades": len(result.trades),
    }

    return summary


def print_comparison(summaries: list[dict]) -> None:
    """打印对比表。

    Args:
        summaries: 各配置的绩效摘要列表。
    """
    print("\n" + "=" * 80)
    print("PEAD 6因子组合回测对比")
    print("=" * 80)

    # 整体对比
    print(f"\n{'指标':<25}", end="")
    for s in summaries:
        print(f"  {s['label']:>15}", end="")
    print()
    print("-" * (25 + 17 * len(summaries)))

    rows = [
        ("因子数", "n_factors", "d"),
        ("总收益", "total_return", ".1%"),
        ("年化收益", "ann_return", ".1%"),
        ("Sharpe", "sharpe", ".3f"),
        ("最大回撤", "mdd", ".1%"),
        ("Bootstrap Sharpe", "bootstrap_sharpe_mean", ".3f"),
        ("  95% CI 下界", "bootstrap_ci_low", ".3f"),
        ("  95% CI 上界", "bootstrap_ci_high", ".3f"),
        ("调仓次数", "n_rebalances", "d"),
        ("成交笔数", "n_trades", "d"),
    ]

    for label, key, fmt in rows:
        print(f"{label:<25}", end="")
        for s in summaries:
            val = s[key]
            print(f"  {val:>15{fmt}}", end="")
        print()

    # 年度分解
    print(f"\n{'年度分解':=^80}")
    for year in range(2021, 2026):
        print(f"\n  {year}年:")
        print(f"  {'指标':<20}", end="")
        for s in summaries:
            print(f"  {s['label']:>15}", end="")
        print()

        for label, key, fmt in [
            ("收益", "return", ".1%"),
            ("Sharpe", "sharpe", ".3f"),
            ("MDD", "mdd", ".1%"),
        ]:
            print(f"  {label:<20}", end="")
            for s in summaries:
                if year in s["annual"]:
                    val = s["annual"][year][key]
                    print(f"  {val:>15{fmt}}", end="")
                else:
                    print(f"  {'N/A':>15}", end="")
            print()

    # 增量效果
    if len(summaries) == 2:
        a, b = summaries
        print(f"\n{'增量效果(B-A)':=^80}")
        print(f"  Sharpe增量: {b['sharpe'] - a['sharpe']:+.3f}")
        print(f"  年化收益增量: {b['ann_return'] - a['ann_return']:+.1%}")
        print(f"  MDD变化: {b['mdd'] - a['mdd']:+.1%}")
        ci_low_delta = b["bootstrap_ci_low"] - a["bootstrap_ci_low"]
        print(f"  Bootstrap CI下界增量: {ci_low_delta:+.3f}")

        # 判定
        print(f"\n{'判定':=^80}")
        if b["sharpe"] > a["sharpe"] and b["mdd"] > a["mdd"]:
            print("  v1.2 Sharpe更高且MDD更小(MDD负数更小=更好)")
            print("  建议: 推荐升级到v1.2")
        elif b["sharpe"] > a["sharpe"]:
            print("  v1.2 Sharpe更高但MDD更大")
            print("  建议: 需评估风险收益比")
        else:
            print("  v1.2 Sharpe未提升")
            print("  建议: 保持v1.1基线")

    print()


def main():
    """PEAD 6因子组合回测主程序。"""
    print_config_header()

    start = date(2021, 1, 1)
    end = date(2025, 12, 31)
    capital = 1_000_000.0

    conn = _get_sync_conn()
    t0 = time.time()

    # 获取调仓日历
    logger.info("获取调仓日历...")
    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    logger.info(f"调仓日: {len(rebalance_dates)}个")

    # 加载公共数据
    logger.info("加载行业分类...")
    industry = load_industry(conn)

    logger.info("加载价格数据...")
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

    # 计算PEAD因子面板
    pead_panel = compute_pead_factor_panel(conn, start, end)
    if not pead_panel:
        logger.error("PEAD因子面板为空, 无法运行6因子回测")
        conn.close()
        sys.exit(1)

    # 配置A: v1.1基线(5因子)
    config_a = SignalConfig(
        factor_names=[
            "turnover_mean_20",
            "volatility_20",
            "reversal_20",
            "amihud_20",
            "bp_ratio",
        ],
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )

    # 配置B: v1.2候选(6因子 = 5基线 + PEAD)
    config_b = SignalConfig(
        factor_names=[
            "turnover_mean_20",
            "volatility_20",
            "reversal_20",
            "amihud_20",
            "bp_ratio",
            "earnings_surprise_car",
        ],
        top_n=15,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=0.25,
        turnover_cap=0.50,
    )

    bt_config = BacktestConfig(
        initial_capital=capital,
        top_n=15,
        rebalance_freq="monthly",
        slippage_bps=10.0,
    )

    # 运行A
    summary_a = run_single_backtest(
        "v1.1(5F基线)",
        config_a,
        bt_config,
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
    )

    # 运行B
    summary_b = run_single_backtest(
        "v1.2(+PEAD)",
        config_b,
        bt_config,
        rebalance_dates,
        industry,
        price_data,
        benchmark_data,
        conn,
        pead_panel=pead_panel,
    )

    conn.close()

    # 输出对比
    print_comparison([summary_a, summary_b])

    elapsed = time.time() - t0
    logger.info(f"回测完成, 总耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    main()
