"""VWAP偏离 + RSRS因子 IC测试。

因子设计（factor审批）:
1. vwap_bias_1d: (close - VWAP) / VWAP, VWAP = amount*10/volume
   - close未复权, amount千元, volume手 → VWAP元/股
   - 预期IC方向: 待实测（反转-1或趋势+1）

2. rsrs_raw_18: Cov(high,low,18) / Var(low,18)
   - high/low未复权, min_periods=9
   - 预期IC方向: +1

全样本IC检验: 2020-07~2025-12月末截面, 5日前瞻Spearman IC
中性化验证: 市值+行业中性化后IC并列 (LL-014)
与5基线因子截面相关性矩阵
年度分解IC
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            project_root / "models" / "test_vwap_rsrs.log", mode="w"
        ),
    ],
)
logger = logging.getLogger(__name__)

FACTOR_NAMES = ["vwap_bias_1d", "rsrs_raw_18"]

BASELINE_FACTORS = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"
]


# ============================================================
# 因子计算
# ============================================================

def calc_vwap_bias(df: pd.DataFrame) -> pd.Series:
    """计算单截面的vwap_bias_1d。

    vwap_bias_1d = (close - VWAP) / VWAP
    VWAP = amount * 10 / volume  (千元*10/手 = 元/股)

    Args:
        df: DataFrame with columns [code, close, amount, volume]

    Returns:
        Series indexed by code
    """
    # 过滤无效数据
    valid = df[(df["volume"] > 0) & (df["amount"] > 0)].copy()
    if valid.empty:
        return pd.Series(dtype=float)

    vwap = valid["amount"].astype(float) * 10.0 / valid["volume"].astype(float)
    close = valid["close"].astype(float)
    bias = (close - vwap) / vwap

    # clip极端值
    bias = bias.clip(-1.0, 1.0)

    return pd.Series(bias.values, index=valid["code"].values, name="vwap_bias_1d")


def calc_rsrs_raw(panel: pd.DataFrame, code: str) -> float:
    """计算单只股票的rsrs_raw_18。

    rsrs_raw_18 = Cov(high, low, 18) / Var(low, 18)
    即OLS回归 high ~ low 的斜率 beta。

    Args:
        panel: 该股票最近18天的DataFrame [high, low]

    Returns:
        rsrs值（float），数据不足返回NaN
    """
    if len(panel) < 9:  # min_periods=9
        return np.nan

    high = panel["high"].astype(float).values
    low = panel["low"].astype(float).values

    var_low = np.var(low, ddof=0)
    if var_low < 1e-10:
        return np.nan

    cov_hl = np.cov(high, low, ddof=0)[0, 1]
    return cov_hl / var_low


def calc_rsrs_cross_section(
    trade_date: date,
    conn,
) -> pd.Series:
    """计算截面所有股票的rsrs_raw_18。

    需要往前取18个交易日的high/low数据。

    Args:
        trade_date: 截面日期
        conn: 数据库连接

    Returns:
        Series indexed by code
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
        return pd.Series(dtype=float)

    results = {}
    for code, grp in df.groupby("code"):
        results[code] = calc_rsrs_raw(grp, code)

    s = pd.Series(results, name="rsrs_raw_18", dtype=float)
    return s.dropna()


# ============================================================
# 中性化
# ============================================================

def load_neutralize_data(trade_date: date, conn) -> tuple[pd.Series, pd.Series]:
    """加载截面ln_mcap和行业分类。"""
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
    df = pd.read_sql(sql, conn)
    ln_mcap = pd.Series(df["ln_mcap"].values, index=df["code"].values, dtype=float)
    industry = pd.Series(df["industry"].values, index=df["code"].values)
    return ln_mcap, industry


def neutralize_factor(
    factor_series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """市值+行业中性化（OLS残差）。"""
    common = factor_series.index.intersection(ln_mcap.index).intersection(industry.index)
    if len(common) < 30:
        return pd.Series(dtype=float)

    y = factor_series.loc[common].values.astype(float)
    mcap_col = ln_mcap.loc[common].values.reshape(-1, 1)
    ind_dummies = pd.get_dummies(industry.loc[common], drop_first=True).values

    X = np.column_stack([np.ones(len(y)), mcap_col, ind_dummies])

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        residual = y - X @ beta
        return pd.Series(residual, index=common)
    except np.linalg.LinAlgError:
        return pd.Series(dtype=float)


# ============================================================
# IC测试
# ============================================================

def ic_test(conn) -> dict[str, dict]:
    """全样本IC测试 + 中性化 + 基线相关性。"""

    logger.info("=" * 70)
    logger.info("VWAP偏离 + RSRS因子 全样本IC测试")
    logger.info("=" * 70)

    # 1. 获取2020-07~2025-12月末交易日
    sql_dates = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN '2020-07-01' AND '2025-12-31'
    ORDER BY trade_date
    """
    dates_df = pd.read_sql(sql_dates, conn)
    trade_dates = [d.date() if hasattr(d, "date") else d
                   for d in dates_df["trade_date"]]

    month_end_dates = {}
    for td in trade_dates:
        key = (td.year, td.month)
        month_end_dates[key] = td
    month_ends = sorted(month_end_dates.values())
    logger.info(f"月末交易日: {len(month_ends)}个 ({month_ends[0]} ~ {month_ends[-1]})")

    # 2. 前瞻5日超额收益
    sql_ret = """
    WITH latest_adj AS (
        SELECT DISTINCT ON (code) code, adj_factor AS latest_adj_factor
        FROM klines_daily ORDER BY code, trade_date DESC
    ),
    stock_ret AS (
        SELECT k1.code, k1.trade_date,
               k2.close * k2.adj_factor / la.latest_adj_factor
               / NULLIF(k1.close * k1.adj_factor / la.latest_adj_factor, 0) - 1
                   AS stock_return_5
        FROM klines_daily k1
        JOIN latest_adj la ON k1.code = la.code
        JOIN LATERAL (
            SELECT code, close, adj_factor
            FROM klines_daily k2
            WHERE k2.code = k1.code AND k2.trade_date > k1.trade_date
            ORDER BY k2.trade_date OFFSET 4 LIMIT 1
        ) k2 ON TRUE
        WHERE k1.trade_date BETWEEN '2020-07-01' AND '2025-12-31'
          AND k1.adj_factor IS NOT NULL AND k1.volume > 0
    ),
    index_ret AS (
        SELECT i1.trade_date,
               i2.close / NULLIF(i1.close, 0) - 1 AS index_return_5
        FROM index_daily i1
        JOIN LATERAL (
            SELECT close FROM index_daily i2
            WHERE i2.index_code = '000300.SH'
              AND i2.trade_date > i1.trade_date
            ORDER BY i2.trade_date OFFSET 4 LIMIT 1
        ) i2 ON TRUE
        WHERE i1.index_code = '000300.SH'
          AND i1.trade_date BETWEEN '2020-07-01' AND '2025-12-31'
    )
    SELECT s.code, s.trade_date,
           s.stock_return_5 - i.index_return_5 AS excess_return_5
    FROM stock_ret s
    JOIN index_ret i ON s.trade_date = i.trade_date
    WHERE s.stock_return_5 IS NOT NULL AND i.index_return_5 IS NOT NULL
      AND ABS(s.stock_return_5) < 5.0
    """
    logger.info("加载2020-07~2025-12 5日前瞻超额收益...")
    ret_df = pd.read_sql(sql_ret, conn)
    ret_df["trade_date"] = pd.to_datetime(ret_df["trade_date"]).dt.date
    logger.info(f"前瞻收益: {len(ret_df)}行, {ret_df['code'].nunique()}股")

    # 3. 每月末计算因子IC
    results: dict[str, dict] = {
        name: {
            "monthly_ics": [],
            "monthly_ics_neutral": [],
            "coverage": [],
        }
        for name in FACTOR_NAMES
    }

    # 基线因子相关性收集
    corr_data: dict[str, list] = {
        f"{fn}_vs_{bf}": [] for fn in FACTOR_NAMES for bf in BASELINE_FACTORS
    }

    for idx, td in enumerate(month_ends):
        if idx % 6 == 0:
            logger.info(f"  处理 {td} ({idx+1}/{len(month_ends)})...")

        day_ret = ret_df[ret_df["trade_date"] == td].set_index("code")["excess_return_5"]

        # 中性化数据
        ln_mcap, industry = load_neutralize_data(td, conn)

        # --- vwap_bias_1d ---
        sql_vwap = f"""
        SELECT code, close, amount, volume
        FROM klines_daily
        WHERE trade_date = '{td}' AND volume > 0
        """
        vwap_df = pd.read_sql(sql_vwap, conn)
        vwap_vals = calc_vwap_bias(vwap_df)

        # --- rsrs_raw_18 ---
        rsrs_vals = calc_rsrs_cross_section(td, conn)

        factor_data = {
            "vwap_bias_1d": vwap_vals,
            "rsrs_raw_18": rsrs_vals,
        }

        # --- 基线因子 (从factor_values表) ---
        sql_baseline = f"""
        SELECT code, factor_name, raw_value FROM factor_values
        WHERE trade_date = '{td}'
          AND factor_name IN ('turnover_mean_20','volatility_20','reversal_20','amihud_20','bp_ratio')
        """
        baseline_df = pd.read_sql(sql_baseline, conn)
        baseline_series = {}
        for bf in BASELINE_FACTORS:
            bfdata = baseline_df[baseline_df["factor_name"] == bf]
            if not bfdata.empty:
                baseline_series[bf] = pd.Series(
                    bfdata["raw_value"].values, index=bfdata["code"].values, dtype=float
                )

        for fname in FACTOR_NAMES:
            fvals = factor_data.get(fname, pd.Series(dtype=float))

            if fvals.empty:
                results[fname]["monthly_ics"].append(np.nan)
                results[fname]["monthly_ics_neutral"].append(np.nan)
                results[fname]["coverage"].append(0)
                continue

            common = fvals.index.intersection(day_ret.index)
            results[fname]["coverage"].append(len(common))

            if len(common) < 30:
                results[fname]["monthly_ics"].append(np.nan)
                results[fname]["monthly_ics_neutral"].append(np.nan)
                continue

            f = fvals.loc[common]
            r = day_ret.loc[common]

            if f.std() < 1e-10:
                results[fname]["monthly_ics"].append(np.nan)
                results[fname]["monthly_ics_neutral"].append(np.nan)
                continue

            # 原始IC
            ic_raw = sp_stats.spearmanr(f, r).statistic
            results[fname]["monthly_ics"].append(ic_raw if not np.isnan(ic_raw) else np.nan)

            # 中性化IC
            f_neutral = neutralize_factor(f, ln_mcap, industry)
            if f_neutral.empty or f_neutral.std() < 1e-10:
                results[fname]["monthly_ics_neutral"].append(np.nan)
            else:
                common_n = f_neutral.index.intersection(r.index)
                if len(common_n) < 30:
                    results[fname]["monthly_ics_neutral"].append(np.nan)
                else:
                    ic_n = sp_stats.spearmanr(f_neutral.loc[common_n], r.loc[common_n]).statistic
                    results[fname]["monthly_ics_neutral"].append(
                        ic_n if not np.isnan(ic_n) else np.nan
                    )

            # 与基线因子截面相关性 (Spearman rank corr on factor values)
            for bf in BASELINE_FACTORS:
                key = f"{fname}_vs_{bf}"
                if bf in baseline_series:
                    bf_s = baseline_series[bf]
                    common_bf = fvals.index.intersection(bf_s.index)
                    if len(common_bf) >= 30:
                        rho = sp_stats.spearmanr(
                            fvals.loc[common_bf], bf_s.loc[common_bf]
                        ).statistic
                        corr_data[key].append(rho if not np.isnan(rho) else np.nan)
                    else:
                        corr_data[key].append(np.nan)
                else:
                    corr_data[key].append(np.nan)

    # ============================================================
    # 输出结果
    # ============================================================

    n_months = len(month_ends)
    print("\n")
    print("=" * 110)
    print(f"VWAP偏离 + RSRS因子 IC结果 (2020-07~2025-12, {n_months}个月末, 5日前瞻超额)")
    print("=" * 110)

    header = (
        f"{'Factor':<20} | {'RawIC':>7} | {'NeutIC':>7} | "
        f"{'RawIR':>7} | {'NeutIR':>7} | "
        f"{'Raw-t':>7} | {'Neut-t':>7} | {'N':>4} | {'AvgCov':>7} | {'Status':>10}"
    )
    print(header)
    print("-" * len(header))

    for fname in FACTOR_NAMES:
        r = results[fname]
        ics_raw = np.array(r["monthly_ics"], dtype=float)
        ics_neutral = np.array(r["monthly_ics_neutral"], dtype=float)

        valid_raw = ics_raw[~np.isnan(ics_raw)]
        valid_neutral = ics_neutral[~np.isnan(ics_neutral)]

        n_raw = len(valid_raw)
        n_neutral = len(valid_neutral)

        r["mean_ic"] = float(np.mean(valid_raw)) if n_raw > 0 else 0.0
        r["std_ic"] = float(np.std(valid_raw, ddof=1)) if n_raw > 1 else 0.0
        r["icir"] = r["mean_ic"] / r["std_ic"] if r["std_ic"] > 1e-8 else 0.0
        r["t_stat"] = r["mean_ic"] / (r["std_ic"] / np.sqrt(n_raw)) if r["std_ic"] > 1e-8 and n_raw > 1 else 0.0

        r["mean_ic_neutral"] = float(np.mean(valid_neutral)) if n_neutral > 0 else 0.0
        r["std_ic_neutral"] = float(np.std(valid_neutral, ddof=1)) if n_neutral > 1 else 0.0
        r["icir_neutral"] = r["mean_ic_neutral"] / r["std_ic_neutral"] if r["std_ic_neutral"] > 1e-8 else 0.0
        r["t_stat_neutral"] = r["mean_ic_neutral"] / (r["std_ic_neutral"] / np.sqrt(n_neutral)) if r["std_ic_neutral"] > 1e-8 and n_neutral > 1 else 0.0

        avg_cov = np.mean(r["coverage"]) if r["coverage"] else 0

        # 判定
        raw_pass = abs(r["t_stat"]) >= 2.0
        neutral_pass = abs(r["t_stat_neutral"]) >= 2.0
        if neutral_pass and abs(r["mean_ic_neutral"]) >= 0.02:
            status = "PASS"
        elif neutral_pass:
            status = "WEAK-PASS"
        elif raw_pass and not neutral_pass:
            status = "FAIL(neut)"
        else:
            status = "FAIL"

        line = (
            f"  {fname:<18} | {r['mean_ic']:>7.4f} | {r['mean_ic_neutral']:>7.4f} | "
            f"{r['icir']:>7.3f} | {r['icir_neutral']:>7.3f} | "
            f"{r['t_stat']:>7.2f} | {r['t_stat_neutral']:>7.2f} | {n_raw:>4} | {avg_cov:>7.0f} | {status:>10}"
        )
        print(line)
        logger.info(line)

    # --- 年度分解 ---
    print(f"\n{'年度IC分解 (原始 / 中性化)':=^70}")
    year_ics: dict[int, dict[str, dict[str, list]]] = {}
    for i, td in enumerate(month_ends):
        yr = td.year
        if yr not in year_ics:
            year_ics[yr] = {fn: {"raw": [], "neut": []} for fn in FACTOR_NAMES}
        for fn in FACTOR_NAMES:
            raw_v = results[fn]["monthly_ics"][i]
            neut_v = results[fn]["monthly_ics_neutral"][i]
            if not np.isnan(raw_v):
                year_ics[yr][fn]["raw"].append(raw_v)
            if not np.isnan(neut_v):
                year_ics[yr][fn]["neut"].append(neut_v)

    header_yr = f"{'Year':<6} |"
    for fn in FACTOR_NAMES:
        short = fn[:14]
        header_yr += f" {short+'_raw':>16} | {short+'_neut':>16} |"
    print(header_yr)
    print("-" * len(header_yr))
    for yr in sorted(year_ics.keys()):
        line_yr = f"  {yr:<4} |"
        for fn in FACTOR_NAMES:
            raw_list = year_ics[yr][fn]["raw"]
            neut_list = year_ics[yr][fn]["neut"]
            raw_mean = np.mean(raw_list) if raw_list else 0.0
            neut_mean = np.mean(neut_list) if neut_list else 0.0
            line_yr += f" {raw_mean:>16.4f} | {neut_mean:>16.4f} |"
        print(line_yr)

    # --- 与5基线因子截面相关性 ---
    print(f"\n{'与5基线因子截面Spearman相关性 (月度均值)':=^70}")
    header_corr = f"{'':>20} |"
    for bf in BASELINE_FACTORS:
        header_corr += f" {bf[:14]:>14} |"
    print(header_corr)
    print("-" * len(header_corr))
    for fn in FACTOR_NAMES:
        line_corr = f"  {fn:<18} |"
        for bf in BASELINE_FACTORS:
            key = f"{fn}_vs_{bf}"
            vals = [v for v in corr_data[key] if not np.isnan(v)]
            mean_corr = np.mean(vals) if vals else 0.0
            line_corr += f" {mean_corr:>14.4f} |"
        print(line_corr)

    # --- 最终判定 ---
    print(f"\n{'=' * 70}")
    print("最终判定 (硬性: 中性化后 |t| >= 2.0 + |IC| >= 2%)")
    print("=" * 70)
    for fname in FACTOR_NAMES:
        r = results[fname]
        raw_t = abs(r["t_stat"])
        neut_t = abs(r["t_stat_neutral"])
        raw_ic = abs(r["mean_ic"])
        neut_ic = abs(r["mean_ic_neutral"])
        # 最大相关性
        max_corr = 0.0
        for bf in BASELINE_FACTORS:
            key = f"{fname}_vs_{bf}"
            vals = [v for v in corr_data[key] if not np.isnan(v)]
            if vals:
                max_corr = max(max_corr, abs(np.mean(vals)))

        print(
            f"  {fname:<20}: raw|IC|={raw_ic:.4f} t={raw_t:.2f}  "
            f"neut|IC|={neut_ic:.4f} t={neut_t:.2f}  "
            f"max_corr={max_corr:.3f}"
        )

    print("=" * 70)

    return results


def main():
    import psycopg2

    t_start = time.time()

    conn = psycopg2.connect(
        dbname="quantmind_v2",
        user="xin",
        password="quantmind",
        host="localhost",
    )

    try:
        results = ic_test(conn)
    finally:
        conn.close()

    total = time.time() - t_start
    logger.info(f"\n总耗时: {total:.1f}s ({total/60:.1f}min)")


if __name__ == "__main__":
    main()
