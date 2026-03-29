#!/usr/bin/env python3
"""7因子 vs 5因子 SimBroker回测对比。

Sprint 1.6 Task #1 (ML Agent)
新因子候选: vwap_bias_1d (t=-3.53, IC=-0.0349) + rsrs_raw_18 (t=-4.35, IC=-0.0301)
两者方向均为 -1（反转方向），尚未写入factor_values表。

策略:
- 5F基线: turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio
- 7F候选: 基线5因子 + vwap_bias_1d + rsrs_raw_18

输出:
- Sharpe (含bootstrap 95% CI)
- MDD
- 年度分解 (每年Sharpe/收益/MDD)
- Paired bootstrap p-value (7F vs 5F)
- 成本敏感性 (0.5x/1x/1.5x/2x)
- 换手率对比
"""

import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "backend"))
sys.path.insert(0, str(project_root / "scripts"))

import numpy as np
import pandas as pd
from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.metrics import (
    TRADING_DAYS_PER_YEAR,
    bootstrap_sharpe_ci,
    calc_annual_breakdown,
    calc_max_drawdown,
    calc_sharpe,
)
from engines.signal_engine import (
    FACTOR_DIRECTION,
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalConfig,
    get_rebalance_dates,
)

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────

START_DATE = date(2021, 1, 1)
END_DATE = date(2025, 12, 31)
INITIAL_CAPITAL = 1_000_000.0

FACTORS_5 = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
FACTORS_7 = FACTORS_5 + ["vwap_bias_1d", "rsrs_raw_18"]

# 新因子方向: IC为负 → direction=-1 (因子值越小越好，即偏离/rsrs越负越看多)
EXTRA_DIRECTIONS = {
    "vwap_bias_1d": -1,
    "rsrs_raw_18": -1,
}


# ─────────────────────────────────────────────
# 数据加载
# ─────────────────────────────────────────────

def load_factor_values_for_date(trade_date: date, conn) -> pd.DataFrame:
    """加载单日5基线因子的neutral_value。"""
    return pd.read_sql(
        """SELECT code, factor_name, neutral_value
           FROM factor_values
           WHERE trade_date = %s
             AND factor_name IN (
               'turnover_mean_20','volatility_20','reversal_20',
               'amihud_20','bp_ratio'
             )""",
        conn,
        params=(trade_date,),
    )


def load_universe(trade_date: date, conn) -> set[str]:
    """Universe过滤（排除ST/新股/停牌/低流动性）。"""
    df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000
        """,
        conn,
        params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def load_price_data(start_date: date, end_date: date, conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount,
                  k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db
             ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s
             AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn,
        params=(start_date, end_date),
    )


def load_benchmark(start_date: date, end_date: date, conn) -> pd.DataFrame:
    return pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(start_date, end_date),
    )


def load_industry(conn) -> pd.Series:
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
        conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


# ─────────────────────────────────────────────
# 新因子计算 (inline, 不依赖factor_values表)
# ─────────────────────────────────────────────

def calc_vwap_bias_cross_section(trade_date: date, conn) -> pd.Series:
    """截面vwap_bias_1d = (close - VWAP) / VWAP。
    VWAP = amount(千元)*10 / volume(手) = 元/股
    中性化用neutralize_inline。
    """
    df = pd.read_sql(
        """SELECT code, close, amount, volume
           FROM klines_daily
           WHERE trade_date = %s AND volume > 0 AND amount > 0""",
        conn,
        params=(trade_date,),
    )
    if df.empty:
        return pd.Series(dtype=float, name="vwap_bias_1d")

    vwap = df["amount"].astype(float) * 10.0 / df["volume"].astype(float)
    bias = (df["close"].astype(float) - vwap) / vwap
    bias = bias.clip(-1.0, 1.0)
    return pd.Series(bias.values, index=df["code"].values, name="vwap_bias_1d")


def calc_rsrs_cross_section(trade_date: date, conn) -> pd.Series:
    """截面rsrs_raw_18 = Cov(high,low,18) / Var(low,18)。
    min_periods=9。
    """
    sql = f"""
    WITH date_window AS (
        SELECT DISTINCT trade_date FROM klines_daily
        WHERE trade_date <= '{trade_date}'
        ORDER BY trade_date DESC
        LIMIT 18
    )
    SELECT k.code, k.trade_date, k.high, k.low
    FROM klines_daily k
    WHERE k.trade_date IN (SELECT trade_date FROM date_window)
      AND k.volume > 0
    ORDER BY k.code, k.trade_date
    """
    df = pd.read_sql(sql, conn)
    if df.empty:
        return pd.Series(dtype=float, name="rsrs_raw_18")

    results = {}
    for code, grp in df.groupby("code"):
        if len(grp) < 9:
            continue
        high = grp["high"].astype(float).values
        low = grp["low"].astype(float).values
        var_low = np.var(low, ddof=0)
        if var_low < 1e-10:
            continue
        cov_hl = np.cov(high, low, ddof=0)[0, 1]
        results[code] = cov_hl / var_low

    return pd.Series(results, name="rsrs_raw_18", dtype=float)


def mad_winsorize(s: pd.Series, n_mad: float = 5.0) -> pd.Series:
    """MAD去极值（CLAUDE.md规定预处理第1步）。"""
    median = s.median()
    mad = (s - median).abs().median()
    if mad < 1e-10:
        return s
    upper = median + n_mad * 1.4826 * mad
    lower = median - n_mad * 1.4826 * mad
    return s.clip(lower, upper)


def neutralize_series(
    factor_series: pd.Series,
    trade_date: date,
    conn,
) -> pd.Series:
    """MAD去极值 → 缺失值填充 → 市值+行业中性化（CLAUDE.md规定顺序）。"""
    # Step 1: MAD去极值
    factor_series = mad_winsorize(factor_series)
    # Step 2: 缺失值填充
    factor_series = factor_series.fillna(factor_series.median())
    sql = f"""
    SELECT d.code,
           LN(b.total_mv * 10000) AS ln_mcap,
           s.industry_sw1 AS industry
    FROM klines_daily d
    JOIN daily_basic b ON d.code = b.code AND d.trade_date = b.trade_date
    JOIN symbols s ON d.code = s.code
    WHERE d.trade_date = '{trade_date}'
      AND b.total_mv IS NOT NULL AND b.total_mv > 0
      AND s.industry_sw1 IS NOT NULL AND s.industry_sw1 != ''
      AND d.volume > 0
    """
    meta = pd.read_sql(sql, conn)
    if meta.empty:
        return factor_series

    ln_mcap = pd.Series(meta["ln_mcap"].values, index=meta["code"].values, dtype=float)
    industry = pd.Series(meta["industry"].values, index=meta["code"].values)

    common = factor_series.index.intersection(ln_mcap.index).intersection(industry.index)
    if len(common) < 30:
        return factor_series

    y = factor_series.loc[common].values.astype(float)
    mcap_col = ln_mcap.loc[common].values.reshape(-1, 1)
    ind_dummies = pd.get_dummies(industry.loc[common], drop_first=True).values

    X = np.column_stack([np.ones(len(y)), mcap_col, ind_dummies])
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        residual = y - X @ beta
        return pd.Series(residual, index=common, name=factor_series.name)
    except np.linalg.LinAlgError:
        return factor_series


def zscore_series(s: pd.Series) -> pd.Series:
    """截面zscore标准化。"""
    std = s.std()
    if std < 1e-10:
        return s * 0.0
    return (s - s.mean()) / std


# ─────────────────────────────────────────────
# 信号合成 (自定义，支持注入计算因子)
# ─────────────────────────────────────────────

def build_scores(
    factor_df: pd.DataFrame,
    extra_factors: dict[str, pd.Series],
    factor_names: list[str],
    universe: set[str],
) -> pd.Series:
    """合成等权composite score。

    factor_df: 来自factor_values表的long格式 (code, factor_name, neutral_value)
    extra_factors: {factor_name: pd.Series(index=code)} — 已中性化+zscore的额外因子
    factor_names: 要用的因子列表
    universe: 可选universe过滤
    """
    # 从DB数据pivot
    pivot = factor_df.pivot_table(
        index="code",
        columns="factor_name",
        values="neutral_value",
        aggfunc="first",
    )

    # 注入额外因子
    for fname, series in extra_factors.items():
        pivot[fname] = series

    # Universe过滤
    if universe:
        pivot = pivot[pivot.index.isin(universe)]

    available = [f for f in factor_names if f in pivot.columns]
    if not available:
        return pd.Series(dtype=float)

    pivot = pivot[available].copy()

    # 方向调整 (合并默认方向 + 额外因子方向)
    combined_directions = dict(FACTOR_DIRECTION)
    combined_directions.update(EXTRA_DIRECTIONS)

    for fname in available:
        direction = combined_directions.get(fname, 1)
        if direction == -1:
            pivot[fname] = -pivot[fname]

    # 等权合成
    composite = pivot[available].mean(axis=1)

    return composite.sort_values(ascending=False)


# ─────────────────────────────────────────────
# 回测主函数
# ─────────────────────────────────────────────

def run_backtest_for_factors(
    factor_names: list[str],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    industry: pd.Series,
    rebalance_dates: list[date],
    conn,
    slippage_bps: float = 10.0,
    label: str = "",
) -> tuple:
    """运行单次回测，返回 (BacktestResult, target_portfolios)。"""
    sig_config = SignalConfig(
        factor_names=factor_names,
        top_n=PAPER_TRADING_CONFIG.top_n,       # 15
        rebalance_freq=PAPER_TRADING_CONFIG.rebalance_freq,  # monthly
        industry_cap=PAPER_TRADING_CONFIG.industry_cap,     # 0.25
    )
    bt_config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        top_n=sig_config.top_n,
        rebalance_freq=sig_config.rebalance_freq,
        slippage_bps=slippage_bps,
    )

    builder = PortfolioBuilder(sig_config)
    target_portfolios = {}
    prev_weights = {}

    use_extra = any(f in ["vwap_bias_1d", "rsrs_raw_18"] for f in factor_names)

    logger.info(f"[{label}] 生成信号 ({len(rebalance_dates)} 调仓日)...")
    for i, rd in enumerate(rebalance_dates):
        fv = load_factor_values_for_date(rd, conn)
        if fv.empty:
            logger.warning(f"[{label}][{rd}] 无基线因子数据, 跳过")
            continue

        universe = load_universe(rd, conn)

        extra_factors = {}
        if use_extra:
            if "vwap_bias_1d" in factor_names:
                vwap_raw = calc_vwap_bias_cross_section(rd, conn)
                vwap_neutral = neutralize_series(vwap_raw, rd, conn)
                extra_factors["vwap_bias_1d"] = zscore_series(vwap_neutral)

            if "rsrs_raw_18" in factor_names:
                rsrs_raw = calc_rsrs_cross_section(rd, conn)
                rsrs_neutral = neutralize_series(rsrs_raw, rd, conn)
                extra_factors["rsrs_raw_18"] = zscore_series(rsrs_neutral)

        scores = build_scores(fv, extra_factors, factor_names, universe)
        if scores.empty:
            continue

        target = builder.build(scores, industry, prev_weights)
        if target:
            target_portfolios[rd] = target
            prev_weights = target

        if (i + 1) % 12 == 0:
            logger.info(f"[{label}]   [{i+1}/{len(rebalance_dates)}] {rd}: {len(target)}只")

    logger.info(f"[{label}] 信号生成完成: {len(target_portfolios)} 个调仓日")

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    return result, target_portfolios


# ─────────────────────────────────────────────
# 统计分析
# ─────────────────────────────────────────────

def paired_bootstrap_pvalue(
    returns_a: pd.Series,
    returns_b: pd.Series,
    n_bootstrap: int = 5000,
    seed: int = 42,
) -> tuple[float, float]:
    """Paired bootstrap p-value: H0 = Sharpe(B) - Sharpe(A) <= 0。

    单侧检验(B是否显著优于A)。返回 (p_value, obs_diff)。
    """
    common_idx = returns_a.index.intersection(returns_b.index)
    ra = returns_a.loc[common_idx].values
    rb = returns_b.loc[common_idx].values

    obs_diff = calc_sharpe(pd.Series(rb)) - calc_sharpe(pd.Series(ra))

    rng = np.random.RandomState(seed)
    diffs = []
    n = len(ra)
    for _ in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        sa = calc_sharpe(pd.Series(ra[idx]))
        sb = calc_sharpe(pd.Series(rb[idx]))
        diffs.append(sb - sa)

    diffs = np.array(diffs)
    # p-value: 观测差在bootstrap分布中的位置
    p_two_sided = float(np.mean(np.abs(diffs) >= abs(obs_diff)))
    return p_two_sided, obs_diff


def cost_sensitivity_sharpe(returns: pd.Series, base_slippage_bps: float) -> dict:
    """成本敏感性分析。

    通过调整日收益率来模拟不同成本倍数。
    近似方法: 每个调仓日的交易成本约为 2*slippage*avg_turnover。
    简化: 直接在Sharpe计算上展示，实际成本调整需要重跑回测。
    """
    # 注: 精确成本敏感性需重跑回测。这里返回Sharpe点估计。
    return calc_sharpe(returns)


def annual_turnover_from_result(result) -> float:
    """从BacktestResult计算年化换手率。"""
    if result.turnover_series.empty:
        return 0.0
    # 月度换手率 × 12 ≈ 年化换手率
    avg_monthly = result.turnover_series.mean()
    return avg_monthly * 12


# ─────────────────────────────────────────────
# 报告输出
# ─────────────────────────────────────────────

def print_comparison_report(
    result_5f,
    result_7f,
    label_5f: str = "5F基线",
    label_7f: str = "7F候选",
) -> None:
    r5 = result_5f.daily_returns
    r7 = result_7f.daily_returns
    n5 = result_5f.daily_nav
    n7 = result_7f.daily_nav
    bn5 = result_5f.benchmark_nav
    bn7 = result_7f.benchmark_nav

    # ── 核心指标 ──
    sharpe_5, ci5_lo, ci5_hi = bootstrap_sharpe_ci(r5, n_bootstrap=2000)
    sharpe_7, ci7_lo, ci7_hi = bootstrap_sharpe_ci(r7, n_bootstrap=2000)
    mdd_5 = calc_max_drawdown(n5)
    mdd_7 = calc_max_drawdown(n7)
    ann_ret_5 = float((n5.iloc[-1] / n5.iloc[0]) ** (TRADING_DAYS_PER_YEAR / len(n5)) - 1)
    ann_ret_7 = float((n7.iloc[-1] / n7.iloc[0]) ** (TRADING_DAYS_PER_YEAR / len(n7)) - 1)
    turn_5 = annual_turnover_from_result(result_5f)
    turn_7 = annual_turnover_from_result(result_7f)

    # ── Paired bootstrap p-value ──
    p_val, obs_diff = paired_bootstrap_pvalue(r5, r7, n_bootstrap=5000)

    print("\n")
    print("=" * 80)
    print("  7因子 vs 5因子 SimBroker回测对比")
    print(f"  周期: {START_DATE} ~ {END_DATE}  |  初始资金: {INITIAL_CAPITAL:,.0f}")
    print(f"  配置: Top{PAPER_TRADING_CONFIG.top_n} + 月度 + 行业25%上限")
    print("=" * 80)

    print(f"\n{'指标':<28} {label_5f:>16} {label_7f:>16}  {'差值':>10}")
    print("-" * 72)
    print(f"  {'年化收益':<26} {ann_ret_5:>15.2%} {ann_ret_7:>15.2%}  {ann_ret_7-ann_ret_5:>+9.2%}")
    print(f"  {'Sharpe':<26} {sharpe_5:>15.3f} {sharpe_7:>15.3f}  {sharpe_7-sharpe_5:>+9.3f}")
    print(f"    Bootstrap 95% CI         [{ci5_lo:.3f}, {ci5_hi:.3f}]   [{ci7_lo:.3f}, {ci7_hi:.3f}]")
    mdd_flag = " ⚠" if mdd_7 < mdd_5 else ""
    print(f"  {'最大回撤 (MDD)':<26} {mdd_5:>15.2%} {mdd_7:>15.2%}  {mdd_7-mdd_5:>+9.2%}{mdd_flag}")
    print(f"  {'年化换手率':<26} {turn_5:>15.1%} {turn_7:>15.1%}  {turn_7-turn_5:>+9.1%}")
    print()
    print(f"  Paired Bootstrap p-value (双侧): {p_val:.4f}")
    print(f"  观测Sharpe差值 (7F - 5F): {obs_diff:+.4f}")
    if p_val < 0.05:
        print(f"  ** 结论: 7F vs 5F 差异显著 (p={p_val:.4f} < 0.05)")
    elif p_val < 0.10:
        print(f"  * 结论: 7F vs 5F 差异边缘显著 (p={p_val:.4f} < 0.10)")
    else:
        print(f"  结论: 7F vs 5F 无显著差异 (p={p_val:.4f} >= 0.10) — 铁律7: 不上线")

    # ── 年度分解 ──
    print(f"\n{'年度分解':=^72}")
    breakdown_5 = calc_annual_breakdown(n5, bn5)
    breakdown_7 = calc_annual_breakdown(n7, bn7)

    # 合并展示 (DataFrame indexed by year)
    all_years = sorted(set(breakdown_5.index.tolist()) | set(breakdown_7.index.tolist()))
    print(f"  {'年份':<6} | {'5F收益':>8} {'5F Sharpe':>10} {'5F MDD':>8} |"
          f" {'7F收益':>8} {'7F Sharpe':>10} {'7F MDD':>8}")
    print("  " + "-" * 66)

    # calc_annual_breakdown returns DataFrame indexed by year with columns: return, sharpe, mdd
    # 'return' is percent already (×100), mdd is also percent (×100)
    for yr in all_years:
        r5_row = breakdown_5.loc[yr] if yr in breakdown_5.index else None
        r7_row = breakdown_7.loc[yr] if yr in breakdown_7.index else None
        r5_str = (f"{r5_row['return']/100:>8.2%} {r5_row['sharpe']:>10.3f} {r5_row['mdd']/100:>8.2%}"
                  if r5_row is not None else f"{'N/A':>8} {'N/A':>10} {'N/A':>8}")
        r7_str = (f"{r7_row['return']/100:>8.2%} {r7_row['sharpe']:>10.3f} {r7_row['mdd']/100:>8.2%}"
                  if r7_row is not None else f"{'N/A':>8} {'N/A':>10} {'N/A':>8}")
        print(f"  {yr:<6} | {r5_str} | {r7_str}")

    # ── 成本敏感性 ──
    print(f"\n{'成本敏感性 (Sharpe)':=^72}")
    print("  注: 精确成本敏感性需重跑回测。以下为近似估计（基于日收益率调整）")
    print(f"  成本倍数  |  {label_5f} Sharpe  |  {label_7f} Sharpe")
    print("  " + "-" * 50)
    # 近似: 年换手率 × 单边成本(bps) × 倍数 → 年度收益率调整
    base_cost_per_year_5 = turn_5 * 10 / 10000   # 万1 单边
    base_cost_per_year_7 = turn_7 * 10 / 10000

    for mult in [0.5, 1.0, 1.5, 2.0]:
        # 在日收益率上模拟额外成本
        extra_5 = (mult - 1.0) * base_cost_per_year_5 / TRADING_DAYS_PER_YEAR
        extra_7 = (mult - 1.0) * base_cost_per_year_7 / TRADING_DAYS_PER_YEAR
        adj_r5 = r5 - extra_5
        adj_r7 = r7 - extra_7
        s5 = calc_sharpe(adj_r5)
        s7 = calc_sharpe(adj_r7)
        flag5 = " ⚠" if s5 < 0.5 else ""
        flag7 = " ⚠" if s7 < 0.5 else ""
        print(f"  {mult:.1f}x       | {s5:>16.3f}{flag5}  | {s7:>16.3f}{flag7}")

    print(f"\n{'=' * 80}\n")


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

def main():
    t_start = time.time()
    conn = _get_sync_conn()

    try:
        logger.info("加载基础数据...")
        industry = load_industry(conn)
        price_data = load_price_data(START_DATE, END_DATE, conn)
        benchmark_data = load_benchmark(START_DATE, END_DATE, conn)
        logger.info(f"价格数据: {len(price_data)}行, 基准: {len(benchmark_data)}行")

        # 调仓日历（月度）
        rebalance_dates = get_rebalance_dates(
            START_DATE, END_DATE, freq="monthly", conn=conn
        )
        logger.info(f"调仓日: {len(rebalance_dates)}个")

        # ── 5因子基线 ──
        logger.info("\n>>> 运行5因子基线回测...")
        result_5f, _ = run_backtest_for_factors(
            FACTORS_5, price_data, benchmark_data, industry,
            rebalance_dates, conn, label="5F"
        )

        # ── 7因子候选 ──
        logger.info("\n>>> 运行7因子候选回测 (含vwap+rsrs)...")
        result_7f, _ = run_backtest_for_factors(
            FACTORS_7, price_data, benchmark_data, industry,
            rebalance_dates, conn, label="7F"
        )

        # ── 输出报告 ──
        print_comparison_report(result_5f, result_7f)

        elapsed = time.time() - t_start
        logger.info(f"总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
