#!/usr/bin/env python3
"""G2.5 动态仓位研究 — 20d市场等权收益三档仓位控制。

机制:
  mean_return_Nd = universe内所有股票过去N日等权日收益的累积值
  if cumulative > 0:     position_scale = 1.0 (满仓)
  if cumulative < 0:     position_scale = 0.5 (半仓)
  if cumulative < -0.10: position_scale = 0.0 (空仓/清仓)

与vol_regime的区别:
  - vol_regime: 高波动降仓 → 但2021/2025高波动+上涨 → alpha被砍
  - 动态仓位: 市场下跌降仓 → 2022/2024下跌时降仓保护资金

实验:
  7. equal + dynamic_position(20d)
  8. equal + dynamic_position(10d)
  9. equal + dynamic_position(40d)
"""

import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.config_guard import print_config_header
from engines.metrics import generate_report
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from engines.slippage_model import SlippageConfig
from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# 配置
# ============================================================
START = "2021-01-01"
END = "2026-03-31"
CAPITAL = 1_000_000
TOP_N = 15
FREQ = "monthly"
FACTOR_NAMES = PAPER_TRADING_CONFIG.factor_names

EXPERIMENTS = [
    {"name": "1_equal_baseline",  "dp_lookback": 0,  "desc": "等权基线(无动态仓位)"},
    {"name": "7_dp_20d",          "dp_lookback": 20, "desc": "等权+动态仓位(20日)"},
    {"name": "8_dp_10d",          "dp_lookback": 10, "desc": "等权+动态仓位(10日)"},
    {"name": "9_dp_40d",          "dp_lookback": 40, "desc": "等权+动态仓位(40日)"},
]


# ============================================================
# 数据加载
# ============================================================
def load_factor_values(trade_date, conn):
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
        conn, params=(trade_date,),
    )


def load_universe(trade_date, conn):
    df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s AND k.volume > 0
             AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000""",
        conn, params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def load_industry(conn):
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'", conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start_date, end_date, conn):
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn, params=(start_date, end_date),
    )


def load_benchmark(start_date, end_date, conn):
    return pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn, params=(start_date, end_date),
    )


# ============================================================
# 动态仓位核心逻辑
# ============================================================
def compute_daily_market_return(price_data: pd.DataFrame) -> pd.Series:
    """计算每日全市场等权平均收益率。

    返回: pd.Series (index=trade_date, value=cross-sectional mean daily return)
    """
    # 每只股票的日收益率 = close / pre_close - 1
    price_data = price_data.copy()
    price_data["daily_ret"] = price_data["close"] / price_data["pre_close"] - 1

    # 过滤异常值（停牌/涨跌停导致的异常收益）
    price_data["daily_ret"] = price_data["daily_ret"].clip(-0.11, 0.11)

    # 每日截面等权平均
    daily_mean = price_data.groupby("trade_date")["daily_ret"].mean()
    return daily_mean.sort_index()


def compute_position_scale_series(
    daily_market_return: pd.Series,
    lookback: int = 20,
) -> pd.Series:
    """计算每日仓位缩放系数。

    机制:
      cumulative_return = sum(daily_market_return[-lookback:])
      if cumulative > 0:     scale = 1.0 (满仓)
      if cumulative < 0:     scale = 0.5 (半仓)
      if cumulative < -0.10: scale = 0.0 (空仓)

    Args:
        daily_market_return: 每日市场等权平均收益率
        lookback: 回看窗口（交易日）

    Returns:
        pd.Series (index=trade_date, value=position_scale)
    """
    # 滚动累积收益
    cumulative = daily_market_return.rolling(lookback, min_periods=lookback).sum()

    scale = pd.Series(1.0, index=cumulative.index)
    scale[cumulative < 0] = 0.5
    scale[cumulative < -0.10] = 0.0

    # lookback不足的早期日期: 满仓
    scale[cumulative.isna()] = 1.0

    return scale


def inject_dynamic_targets(
    base_targets: dict[date, dict[str, float]],
    position_scale: pd.Series,
    all_trading_days: list[date],
) -> dict[date, dict[str, float]]:
    """将动态仓位注入target_portfolios。

    逻辑:
    1. 月度调仓日: 正常选股权重 × position_scale
    2. 非调仓日scale变为0(空仓): 注入空portfolio触发清仓
    3. 非调仓日scale从0恢复: 注入上一个有效portfolio × scale

    这样backtest engine会在scale变化时执行交易。
    """
    result = {}
    last_base_target = {}  # 最近一次月度调仓的原始等权目标
    prev_scale = 1.0

    rebalance_dates = set(base_targets.keys())

    for td in all_trading_days:
        td_date = td if isinstance(td, date) else td.date()
        scale_val = position_scale.get(td_date, 1.0)
        if pd.isna(scale_val):
            scale_val = 1.0

        if td_date in rebalance_dates:
            # 月度调仓日: 更新base target + 应用scale
            last_base_target = base_targets[td_date]
            if scale_val > 0:
                result[td_date] = {c: w * scale_val for c, w in last_base_target.items()}
            else:
                result[td_date] = {}  # 空仓
            prev_scale = scale_val

        else:
            # 非调仓日: 检查scale是否发生关键变化
            scale_changed = False

            # 从有仓位 → 空仓 (scale从>0变为0)
            if prev_scale > 0 and scale_val == 0:
                scale_changed = True
                result[td_date] = {}  # 清仓信号

            # 从空仓 → 有仓位 (scale从0变为>0)
            elif prev_scale == 0 and scale_val > 0 and last_base_target:
                scale_changed = True
                result[td_date] = {c: w * scale_val for c, w in last_base_target.items()}

            # 从满仓 → 半仓 或 半仓 → 满仓
            elif prev_scale != scale_val and last_base_target:
                # 只在跨档时触发（1.0→0.5 或 0.5→1.0），不在同档内波动
                prev_tier = _scale_tier(prev_scale)
                curr_tier = _scale_tier(scale_val)
                if prev_tier != curr_tier:
                    scale_changed = True
                    if scale_val > 0:
                        result[td_date] = {c: w * scale_val for c, w in last_base_target.items()}
                    else:
                        result[td_date] = {}

            if scale_changed:
                prev_scale = scale_val

    return result


def _scale_tier(scale: float) -> int:
    """将连续scale值映射到离散档位: 0=空仓, 1=半仓, 2=满仓。"""
    if scale <= 0:
        return 0
    elif scale <= 0.5:
        return 1
    else:
        return 2


# ============================================================
# 分析模块
# ============================================================
def analyze_position_dynamics(position_scale: pd.Series, start_d, end_d):
    """分析仓位动态特征。"""
    ps = position_scale[(position_scale.index >= start_d) & (position_scale.index <= end_d)]

    # 年度统计
    yearly = {}
    for yr in range(start_d.year, end_d.year + 1):
        yr_data = ps[(ps.index >= date(yr, 1, 1)) & (ps.index <= date(yr, 12, 31))]
        if yr_data.empty:
            continue

        # 档位切换次数
        tiers = yr_data.apply(_scale_tier)
        switches = (tiers.diff().abs() > 0).sum()

        yearly[yr] = {
            "full_pct": (yr_data == 1.0).mean() * 100,
            "half_pct": ((yr_data > 0) & (yr_data < 1.0)).mean() * 100,
            "empty_pct": (yr_data == 0).mean() * 100,
            "switches": int(switches),
            "mean_scale": yr_data.mean(),
        }

    # 总体
    tiers_all = ps.apply(_scale_tier)
    total_switches = (tiers_all.diff().abs() > 0).sum()
    years = (end_d - start_d).days / 365.25
    annual_switches = total_switches / years if years > 0 else 0

    return {
        "yearly": yearly,
        "total_switches": int(total_switches),
        "annual_switches": annual_switches,
        "overall_full_pct": (ps == 1.0).mean() * 100,
        "overall_half_pct": ((ps > 0) & (ps < 1.0)).mean() * 100,
        "overall_empty_pct": (ps == 0).mean() * 100,
        "overall_mean_scale": ps.mean(),
    }


def paired_bootstrap_test(returns_a: pd.Series, returns_b: pd.Series, n_boot=5000):
    """Paired bootstrap test for Sharpe ratio difference."""
    diff_returns = returns_a - returns_b
    # Align dates
    common = returns_a.index.intersection(returns_b.index)
    ra = returns_a.reindex(common).dropna()
    rb = returns_b.reindex(common).dropna()
    common2 = ra.index.intersection(rb.index)
    ra, rb = ra.loc[common2], rb.loc[common2]

    if len(ra) < 30:
        return {"sharpe_diff": np.nan, "p_value": np.nan}

    sharpe_a = ra.mean() / ra.std() * np.sqrt(244)
    sharpe_b = rb.mean() / rb.std() * np.sqrt(244)
    observed_diff = sharpe_a - sharpe_b

    boot_diffs = []
    n = len(ra)
    for _ in range(n_boot):
        idx = np.random.randint(0, n, n)
        boot_a = ra.iloc[idx]
        boot_b = rb.iloc[idx]
        s_a = boot_a.mean() / boot_a.std() * np.sqrt(244) if boot_a.std() > 0 else 0
        s_b = boot_b.mean() / boot_b.std() * np.sqrt(244) if boot_b.std() > 0 else 0
        boot_diffs.append(s_a - s_b)

    boot_diffs = np.array(boot_diffs)
    # Two-sided p-value: proportion of bootstrap diffs with opposite sign
    if observed_diff > 0:
        p_value = (boot_diffs <= 0).mean()
    else:
        p_value = (boot_diffs >= 0).mean()

    return {
        "sharpe_diff": observed_diff,
        "p_value": p_value,
        "ci_lo": np.percentile(boot_diffs, 2.5),
        "ci_hi": np.percentile(boot_diffs, 97.5),
    }


# ============================================================
# 单次实验
# ============================================================
def run_experiment(exp, rebalance_dates, industry, price_data, benchmark_data,
                   daily_market_return, all_trading_days, conn):
    """运行单个实验。"""
    name = exp["name"]
    dp_lookback = exp["dp_lookback"]
    logger.info(f"=== 实验 {name}: {exp['desc']} ===")

    sig_config = SignalConfig(
        factor_names=FACTOR_NAMES,
        top_n=TOP_N,
        rebalance_freq=FREQ,
        weight_method="equal",
    )
    bt_config = BacktestConfig(
        initial_capital=CAPITAL,
        top_n=TOP_N,
        rebalance_freq=FREQ,
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
    )

    # Step 1: 生成月度等权目标持仓（标准流程）
    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    base_targets = {}
    prev_weights = {}

    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        target = builder.build(scores, industry, prev_weights)
        if target:
            base_targets[rd] = target
            prev_weights = target

    # Step 2: 应用动态仓位
    position_scale_series = None
    position_dynamics = None

    if dp_lookback > 0:
        position_scale_series = compute_position_scale_series(daily_market_return, dp_lookback)
        target_portfolios = inject_dynamic_targets(
            base_targets, position_scale_series, all_trading_days,
        )
        start_d = datetime.strptime(START, "%Y-%m-%d").date()
        end_d = datetime.strptime(END, "%Y-%m-%d").date()
        position_dynamics = analyze_position_dynamics(position_scale_series, start_d, end_d)
    else:
        target_portfolios = base_targets

    # Step 3: 回测
    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    report = generate_report(result, price_data)

    return report, result, position_scale_series, position_dynamics


# ============================================================
# 报告
# ============================================================
def format_report(all_results, baseline_result):
    """格式化对比报告。"""
    lines = []
    lines.append("\n" + "=" * 100)
    lines.append("G2.5 动态仓位研究 — 对比报告")
    lines.append("=" * 100)
    lines.append(f"回测: {START} ~ {END} | 5因子等权Top15月度 | volume_impact | 资金{CAPITAL:,.0f}")
    lines.append(f"动态仓位: 全市场等权20d累积收益 → 满仓(>0)/半仓(<0)/空仓(<-10%)")

    # 核心指标
    lines.append("\n--- 核心指标对比 ---")
    header = f"{'实验':<25} {'Sharpe':>8} {'AdjSh':>8} {'CAGR':>8} {'MDD':>8} {'Calmar':>8} {'换手率':>8} {'CI_lo':>8} {'CI_hi':>8}"
    lines.append(header)
    lines.append("-" * len(header))

    for name, report, _, _, _ in all_results:
        ar = report.annual_return
        mdd = report.max_drawdown
        # Determine if values are fractions or percentages
        ar_pct = ar * 100 if abs(ar) < 5 else ar
        mdd_pct = mdd * 100 if abs(mdd) < 5 else mdd
        ci = report.bootstrap_sharpe_ci
        lines.append(
            f"{name:<25} {report.sharpe_ratio:>8.2f} {report.autocorr_adjusted_sharpe_ratio:>8.2f} "
            f"{ar_pct:>7.1f}% {mdd_pct:>7.1f}% "
            f"{report.calmar_ratio:>8.2f} {report.annual_turnover:>8.2f} "
            f"{ci[1]:>8.2f} {ci[2]:>8.2f}"
        )

    # 年度Sharpe
    lines.append("\n--- 年度Sharpe对比 ---")
    years = sorted(all_results[0][1].annual_breakdown.index)
    header2 = f"{'实验':<25} " + " ".join(f"{y:>8}" for y in years)
    lines.append(header2)
    lines.append("-" * len(header2))
    for name, report, _, _, _ in all_results:
        ab = report.annual_breakdown
        vals = [f"{ab.loc[y, 'sharpe']:>8.2f}" if y in ab.index else f"{'N/A':>8}" for y in years]
        lines.append(f"{name:<25} {' '.join(vals)}")

    # 年度MDD
    lines.append("\n--- 年度MDD对比 ---")
    lines.append(header2)
    lines.append("-" * len(header2))
    for name, report, _, _, _ in all_results:
        ab = report.annual_breakdown
        vals = [f"{ab.loc[y, 'mdd']:>7.1f}%" if y in ab.index else f"{'N/A':>8}" for y in years]
        lines.append(f"{name:<25} {' '.join(vals)}")

    # 年度收益
    lines.append("\n--- 年度收益对比 ---")
    lines.append(header2)
    lines.append("-" * len(header2))
    for name, report, _, _, _ in all_results:
        ab = report.annual_breakdown
        vals = [f"{ab.loc[y, 'return']:>7.1f}%" if y in ab.index else f"{'N/A':>8}" for y in years]
        lines.append(f"{name:<25} {' '.join(vals)}")

    # 动态仓位分析
    lines.append("\n--- 仓位动态分析 ---")
    for name, _, _, _, dynamics in all_results:
        if dynamics is None:
            continue
        lines.append(f"\n  {name}:")
        lines.append(f"    总切换次数: {dynamics['total_switches']}, "
                      f"年均: {dynamics['annual_switches']:.1f}次")
        lines.append(f"    总体: 满仓{dynamics['overall_full_pct']:.1f}% | "
                      f"半仓{dynamics['overall_half_pct']:.1f}% | "
                      f"空仓{dynamics['overall_empty_pct']:.1f}% | "
                      f"平均scale={dynamics['overall_mean_scale']:.3f}")
        lines.append(f"    {'年度':<6} {'满仓%':>8} {'半仓%':>8} {'空仓%':>8} {'切换':>6} {'均值scale':>10}")
        for yr in sorted(dynamics["yearly"].keys()):
            d = dynamics["yearly"][yr]
            lines.append(f"    {yr:<6} {d['full_pct']:>7.1f}% {d['half_pct']:>7.1f}% "
                          f"{d['empty_pct']:>7.1f}% {d['switches']:>6} {d['mean_scale']:>10.3f}")

    # Paired bootstrap
    lines.append("\n--- Paired Bootstrap显著性检验 (vs 基线) ---")
    if baseline_result is not None:
        baseline_returns = baseline_result.daily_returns
        for name, _, bt_result, _, _ in all_results:
            if "baseline" in name:
                continue
            boot = paired_bootstrap_test(bt_result.daily_returns, baseline_returns)
            sig = "***" if boot["p_value"] < 0.01 else "**" if boot["p_value"] < 0.05 else "*" if boot["p_value"] < 0.10 else "n.s."
            lines.append(
                f"  {name} vs baseline: "
                f"Sharpe diff={boot['sharpe_diff']:+.3f}, "
                f"p={boot['p_value']:.3f} {sig}, "
                f"95% CI=[{boot.get('ci_lo', 0):.3f}, {boot.get('ci_hi', 0):.3f}]"
            )

    return "\n".join(lines)


# ============================================================
# 主程序
# ============================================================
def main():
    print_config_header()
    t0 = time.time()

    start = datetime.strptime(START, "%Y-%m-%d").date()
    end = datetime.strptime(END, "%Y-%m-%d").date()

    conn = _get_sync_conn()

    # 共享数据
    logger.info("加载共享数据...")
    rebalance_dates = get_rebalance_dates(start, end, freq=FREQ, conn=conn)
    industry = load_industry(conn)
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)

    # 计算每日市场等权收益
    logger.info("计算每日全市场等权收益...")
    daily_market_return = compute_daily_market_return(price_data)
    logger.info(f"市场收益序列: {len(daily_market_return)}天, "
                f"均值={daily_market_return.mean():.5f}, std={daily_market_return.std():.4f}")

    # 所有交易日列表
    all_trading_days = sorted(price_data["trade_date"].unique())
    logger.info(f"共享数据就绪: {len(rebalance_dates)}调仓日, {len(all_trading_days)}交易日")

    # 运行实验
    all_results = []  # [(name, report, bt_result, position_scale, dynamics)]
    baseline_result = None

    for exp in EXPERIMENTS:
        exp_t0 = time.time()
        report, bt_result, pos_scale, dynamics = run_experiment(
            exp, rebalance_dates, industry, price_data, benchmark_data,
            daily_market_return, all_trading_days, conn,
        )

        if "baseline" in exp["name"]:
            baseline_result = bt_result

        all_results.append((exp["name"], report, bt_result, pos_scale, dynamics))
        elapsed = time.time() - exp_t0

        ar = report.annual_return
        mdd = report.max_drawdown
        ar_pct = ar * 100 if abs(ar) < 5 else ar
        mdd_pct = mdd * 100 if abs(mdd) < 5 else mdd
        extra = ""
        if dynamics:
            extra = f", 满仓{dynamics['overall_full_pct']:.0f}%/半仓{dynamics['overall_half_pct']:.0f}%/空仓{dynamics['overall_empty_pct']:.0f}%"
        logger.info(
            f"  {exp['name']}: Sharpe={report.sharpe_ratio:.2f}, "
            f"MDD={mdd_pct:.1f}%, CAGR={ar_pct:.1f}%, "
            f"耗时={elapsed:.0f}s{extra}"
        )

    conn.close()

    # 输出报告
    report_text = format_report(all_results, baseline_result)
    print(report_text)

    # 写入文件
    output_path = Path(__file__).resolve().parent.parent / "G25_DYNAMIC_POSITION_REPORT.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("```\n")
        f.write(report_text)
        f.write("\n```\n")

    total_elapsed = time.time() - t0
    logger.info(f"\n总耗时: {total_elapsed:.0f}s ({total_elapsed / 60:.1f}分钟)")
    logger.info(f"报告已写入: {output_path}")


if __name__ == "__main__":
    main()
