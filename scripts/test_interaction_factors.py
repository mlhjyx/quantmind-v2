"""Sprint 1.5b: 基本面x价量交互因子 IC测试。

3个交互因子:
1. quality_reversal: roe_delta x reversal_20 (被错杀的改善型公司)
2. value_quality: gross_margin_delta x bp_ratio (毛利改善+低估值)
3. momentum_quality: net_margin_delta x (-turnover_mean_20) (低关注度改善股)

Gate标准: t > 2.5, 中性化后IC显著
数据范围: 2021-01 ~ 2025-12, 月度截面IC
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

# 项目根目录
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def get_month_end_dates(conn, start: date, end: date) -> list[date]:
    """获取时间范围内的月末交易日列表。"""
    sql = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
    ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, params=(start, end))
    trade_dates = [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]

    month_ends = {}
    for td in trade_dates:
        key = (td.year, td.month)
        month_ends[key] = td  # 后覆盖前 -> 月末
    return sorted(month_ends.values())


def load_neutral_factors_for_date(conn, trade_date: date, factor_names: list[str]) -> pd.DataFrame:
    """从factor_values表加载某日的neutral_value。

    Returns:
        DataFrame: index=code, columns=factor_names
    """
    placeholders = ",".join(["%s"] * len(factor_names))
    sql = f"""
    SELECT code, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date = %s AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    """
    params = [trade_date] + factor_names
    df = pd.read_sql(sql, conn, params=params)
    if df.empty:
        return pd.DataFrame()
    return df.pivot(index="code", columns="factor_name", values="neutral_value")


def load_industry_and_mcap(conn, trade_date: date) -> pd.DataFrame:
    """加载行业分类和对数市值(用于中性化)。"""
    sql = """
    SELECT k.code,
           s.industry_sw1,
           LN(db.total_mv + 1e-8) AS ln_mcap
    FROM klines_daily k
    LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
    LEFT JOIN symbols s ON k.code = s.code
    WHERE k.trade_date = %s AND k.volume > 0 AND db.total_mv > 0
    """
    df = pd.read_sql(sql, conn, params=(trade_date,))
    return df.set_index("code")


def load_forward_excess_return(conn, trade_date: date, horizon: int = 5) -> pd.Series:
    """加载5日前瞻超额收益(vs CSI300)。"""
    from engines.factor_engine import load_forward_returns
    return load_forward_returns(trade_date, horizon=horizon, conn=conn)


def neutralize_cross_section(factor_series: pd.Series, ln_mcap: pd.Series,
                              industry: pd.Series) -> pd.Series:
    """对截面因子做行业+市值中性化(OLS残差)。"""
    from engines.factor_engine import preprocess_neutralize
    return preprocess_neutralize(factor_series, ln_mcap, industry)


def zscore_cross_section(series: pd.Series) -> pd.Series:
    """截面zscore标准化。"""
    mean = series.mean()
    std = series.std()
    if std < 1e-12:
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def calc_spearman_ic(factor_vals: pd.Series, fwd_ret: pd.Series) -> float:
    """Spearman rank IC。"""
    common = factor_vals.dropna().index.intersection(fwd_ret.dropna().index)
    if len(common) < 30:
        return np.nan
    return factor_vals.loc[common].rank().corr(fwd_ret.loc[common].rank())


def main():
    from engines.factor_engine import load_fundamental_pit_data

    from app.services.price_utils import _get_sync_conn

    conn = _get_sync_conn()

    START = date(2021, 1, 1)
    END = date(2025, 12, 31)

    logger.info("=" * 70)
    logger.info("Sprint 1.5b: 基本面 x 价量 交互因子 IC测试")
    logger.info(f"数据范围: {START} ~ {END}")
    logger.info("=" * 70)

    # 月末交易日
    month_ends = get_month_end_dates(conn, START, END)
    logger.info(f"月末交易日: {len(month_ends)}个")

    # 基线因子名(从factor_values表读neutral_value)
    baseline_factors = ["reversal_20", "bp_ratio", "turnover_mean_20"]

    # 交互因子定义: (name, fundamental_comp, price_comp, fund_sign, price_sign)
    # sign用于方向对齐: 最终交互值 = (fund * fund_sign) * (price * price_sign)
    interaction_defs = [
        ("quality_reversal",  "roe_delta",          "reversal_20",       +1, +1),
        ("value_quality",     "gross_margin_delta",  "bp_ratio",          +1, +1),
        ("momentum_quality",  "net_margin_delta",    "turnover_mean_20",  +1, -1),
    ]

    # 结果存储
    results = {name: {"raw_ics": [], "neutral_ics": []} for name, *_ in interaction_defs}

    t0 = time.time()
    for i, td in enumerate(month_ends):
        logger.info(f"\n--- [{i+1}/{len(month_ends)}] {td} ---")

        # 1. 加载基线因子 neutral_value
        factor_df = load_neutral_factors_for_date(conn, td, baseline_factors)
        if factor_df.empty:
            logger.warning(f"  {td}: 无基线因子数据, 跳过")
            continue

        # 2. 加载基本面delta因子 (PIT)
        fund_data = load_fundamental_pit_data(td, conn)

        # 3. 加载行业+市值(用于中性化)
        meta_df = load_industry_and_mcap(conn, td)
        if meta_df.empty or len(meta_df) < 100:
            logger.warning(f"  {td}: 行业/市值数据不足, 跳过")
            continue

        # 4. 加载前向超额收益
        fwd_ret = load_forward_excess_return(conn, td, horizon=5)
        if fwd_ret.empty or len(fwd_ret) < 100:
            logger.warning(f"  {td}: 前向收益不足, 跳过")
            continue

        # 5. 构造交互因子
        for name, fund_name, price_name, fund_sign, price_sign in interaction_defs:
            # 基本面分量
            fund_series = fund_data.get(fund_name)
            if fund_series is None or fund_series.empty:
                continue

            # 价量分量 (从factor_values neutral_value)
            if price_name not in factor_df.columns:
                continue
            price_series = factor_df[price_name]

            # 对齐code
            common_codes = fund_series.dropna().index.intersection(
                price_series.dropna().index
            ).intersection(
                meta_df.index
            ).intersection(
                fwd_ret.dropna().index
            )
            if len(common_codes) < 100:
                continue

            # 截面zscore标准化各分量
            fund_z = zscore_cross_section(fund_series.loc[common_codes])
            price_z = zscore_cross_section(price_series.loc[common_codes])

            # 方向对齐后相乘
            interaction_raw = (fund_z * fund_sign) * (price_z * price_sign)

            # 乘积再做zscore
            interaction_z = zscore_cross_section(interaction_raw)

            # --- 原始IC ---
            raw_ic = calc_spearman_ic(interaction_z, fwd_ret.loc[common_codes])
            results[name]["raw_ics"].append(raw_ic)

            # --- 中性化IC ---
            ln_mcap = meta_df.loc[common_codes, "ln_mcap"]
            industry = meta_df.loc[common_codes, "industry_sw1"]
            interaction_neutral = neutralize_cross_section(interaction_z, ln_mcap, industry)
            neutral_z = zscore_cross_section(interaction_neutral)
            neutral_ic = calc_spearman_ic(neutral_z, fwd_ret.loc[common_codes])
            results[name]["neutral_ics"].append(neutral_ic)

        if (i + 1) % 12 == 0:
            elapsed = time.time() - t0
            logger.info(f"  已处理 {i+1}/{len(month_ends)} 月, 耗时 {elapsed:.1f}s")

    elapsed = time.time() - t0
    conn.close()

    # ============================================================
    # 汇总结果
    # ============================================================
    logger.info("\n" + "=" * 70)
    logger.info("交互因子 IC测试结果")
    logger.info("=" * 70)

    print("\n| 因子 | N月 | 原始IC | 中性化IC | t-stat(原始) | t-stat(中性化) | p(原始) | p(中性化) | 通过Gate? |")
    print("|------|-----|--------|---------|-------------|---------------|---------|----------|----------|")

    cumulative_M = 72  # 当前FACTOR_TEST_REGISTRY累积M

    for name, fund_name, price_name, fund_sign, price_sign in interaction_defs:
        raw_ics = [x for x in results[name]["raw_ics"] if np.isfinite(x)]
        neutral_ics = [x for x in results[name]["neutral_ics"] if np.isfinite(x)]

        n_months = len(raw_ics)
        if n_months < 6:
            print(f"| {name} | {n_months} | N/A | N/A | N/A | N/A | N/A | N/A | SKIP(数据不足) |")
            continue

        raw_mean = np.mean(raw_ics)
        neutral_mean = np.mean(neutral_ics)

        # t检验: IC均值是否显著异于0
        raw_t, raw_p = sp_stats.ttest_1samp(raw_ics, 0)
        neutral_t, neutral_p = sp_stats.ttest_1samp(neutral_ics, 0)

        # Gate判定: t > 2.5 (中性化后)
        gate_pass = abs(neutral_t) > 2.5 and neutral_p < 0.05
        gate_str = "PASS" if gate_pass else "FAIL"

        print(
            f"| {name} | {n_months} | "
            f"{raw_mean:+.4f} | {neutral_mean:+.4f} | "
            f"{raw_t:+.2f} | {neutral_t:+.2f} | "
            f"{raw_p:.4f} | {neutral_p:.4f} | "
            f"{gate_str} |"
        )

        # 详细年度分解
        logger.info(f"\n  {name} 年度IC分解:")
        for year in range(2021, 2026):
            year_raw = [raw_ics[j] for j, td in enumerate(month_ends[:len(raw_ics)])
                        if td.year == year and j < len(raw_ics)]
            if year_raw:
                yr_mean = np.mean(year_raw)
                yr_std = np.std(year_raw) if len(year_raw) > 1 else 0
                direction_consistent = sum(1 for x in year_raw if x > 0) / len(year_raw)
                logger.info(f"    {year}: IC={yr_mean:+.4f} std={yr_std:.4f} "
                            f"方向一致率={direction_consistent:.0%} ({len(year_raw)}月)")

    # 与基线因子的相关性
    logger.info("\n" + "=" * 70)
    logger.info("交互因子IC时序 vs 基线因子IC时序 相关性 (后续补充)")
    logger.info("=" * 70)

    print(f"\n总耗时: {elapsed:.1f}s")
    print(f"累积测试M: {cumulative_M} -> {cumulative_M + 3} (新增3个交互因子)")
    print("\n注意: 若通过Gate, 需进一步检查与5基线因子的截面相关性(corr<0.5)和SimBroker回测。")


if __name__ == "__main__":
    main()
