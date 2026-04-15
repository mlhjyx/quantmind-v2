"""业绩预告因子IC快筛 — 3个forecast因子。

因子设计（Team Lead提供）:
1. forecast_surprise_type: 预告方向(+1正面/-1负面/0无预告)
2. forecast_magnitude: 预告净利变动幅度中值 (p_change_max+min)/2/100
3. forecast_recency: 距最近预告公告天数（越小越好）

数据源: Tushare forecast接口（业绩预告, 5000积分, 我们8000）
PIT对齐: forecast.ann_date <= trade_date, 每只股票取ann_date最新

全样本IC检验: 2020-2025全部月末截面(60+), 5日前瞻Spearman IC
中性化验证: 市值+行业中性化后IC并列 (LL-014)
"""

import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

(project_root / "models").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            project_root / "models" / "test_forecast_factors.log", mode="w"
        ),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# 因子配置
# ============================================================

# 预告类型 -> 方向分数
FORECAST_TYPE_MAP = {
    "预增": 1,
    "扭亏": 1,
    "续盈": 1,
    "略增": 1,
    "预减": -1,
    "首亏": -1,
    "续亏": -1,
    "略减": -1,
    "不确定": 0,
    "其他": 0,
}

FACTOR_NAMES = ["forecast_surprise_type", "forecast_magnitude", "forecast_recency"]
FACTOR_DIRECTION = {
    "forecast_surprise_type": 1,   # 正面=好
    "forecast_magnitude": 1,       # 大幅预增=好
    "forecast_recency": -1,        # 天数越少=越新=越好
}


# ============================================================
# Step 1: 从Tushare拉取forecast数据
# ============================================================

def fetch_forecast_from_tushare(
    start_date: str = "20200101",
    end_date: str = "20250101",
) -> pd.DataFrame:
    """从Tushare拉取业绩预告数据（按ann_date逐日拉取）。

    Args:
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD

    Returns:
        DataFrame [ts_code, ann_date, end_date, type, p_change_min, p_change_max,
                   net_profit_min, net_profit_max]
    """
    import os
    import tushare as ts

    _token = os.environ.get("TUSHARE_TOKEN", "")
    if not _token:
        raise RuntimeError("TUSHARE_TOKEN 环境变量未设置")
    pro = ts.pro_api(_token)

    logger.info(f"从Tushare拉取forecast数据: {start_date} ~ {end_date}")

    all_dfs = []
    current = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    total_rows = 0
    api_calls = 0

    while current <= end:
        ann = current.strftime("%Y%m%d")
        try:
            df = pro.forecast(
                ann_date=ann,
                fields="ts_code,ann_date,end_date,type,p_change_min,p_change_max,"
                       "net_profit_min,net_profit_max",
            )
            if df is not None and len(df) > 0:
                all_dfs.append(df)
                total_rows += len(df)
            api_calls += 1

            # Rate limit: ~200 calls/min for 5000pt API
            if api_calls % 100 == 0:
                logger.info(f"  已拉取 {api_calls} 天, {total_rows} 行 (当前: {ann})")
            time.sleep(0.35)  # ~170 calls/min, safe margin
        except Exception as e:
            if "每分钟" in str(e) or "频率" in str(e):
                logger.warning(f"  Rate limit hit at {ann}, sleeping 60s...")
                time.sleep(60)
                continue  # retry same date
            # Other errors (weekends etc) just skip
            pass

        current += timedelta(days=1)

    if not all_dfs:
        logger.error("未拉取到任何forecast数据!")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)

    # 去重: 同一(ts_code, ann_date, end_date, type)取第一条
    before = len(result)
    result = result.drop_duplicates(
        subset=["ts_code", "ann_date", "end_date", "type"], keep="first"
    )
    logger.info(
        f"Forecast数据拉取完成: {api_calls}天API调用, "
        f"{before}行 -> 去重后{len(result)}行, "
        f"{result['ts_code'].nunique()}只股票"
    )

    return result


def load_or_fetch_forecast(cache_path: Path) -> pd.DataFrame:
    """优先从Parquet缓存加载，否则从Tushare拉取并缓存。"""
    csv_path = cache_path.with_suffix(".csv")
    if csv_path.exists():
        logger.info(f"从CSV缓存加载forecast数据: {csv_path}")
        df = pd.read_csv(csv_path, dtype={"ann_date": str, "end_date": str})
        logger.info(f"缓存: {len(df)}行, {df['ts_code'].nunique()}只股票")
        return df
    if cache_path.exists():
        logger.info(f"从Parquet缓存加载forecast数据: {cache_path}")
        df = pd.read_parquet(cache_path)
        logger.info(f"缓存: {len(df)}行, {df['ts_code'].nunique()}只股票")
        return df

    df = fetch_forecast_from_tushare("20200101", "20250101")
    if not df.empty:
        csv_path = cache_path.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        logger.info(f"已缓存到: {csv_path}")
    return df


# ============================================================
# Step 2: PIT因子计算
# ============================================================

def load_forecast_pit_data(
    trade_date: date,
    forecast_df: pd.DataFrame,
) -> dict[str, pd.Series]:
    """计算截至trade_date的3个forecast因子（PIT对齐）。

    PIT规则: ann_date <= trade_date, 每只股票取ann_date最新的预告。

    Args:
        trade_date: 交易日
        forecast_df: 全量forecast DataFrame (已预处理好 ann_date为date)

    Returns:
        dict[factor_name -> pd.Series(index=code, value=factor_value)]
    """
    # 确保trade_date与ann_date类型一致
    td = pd.Timestamp(trade_date)

    # PIT过滤: ann_date <= trade_date
    pit = forecast_df[forecast_df["ann_date"] <= td].copy()

    if pit.empty:
        return {name: pd.Series(dtype=float) for name in FACTOR_NAMES}

    # 每只股票取ann_date最新的预告（最近一次预告）
    pit = pit.sort_values("ann_date", ascending=False)
    latest = pit.groupby("code").first().reset_index()

    # 因子1: forecast_surprise_type
    surprise_type = latest["type"].map(FORECAST_TYPE_MAP).fillna(0).astype(float)
    factor_surprise = pd.Series(
        surprise_type.values, index=latest["code"].values, name="forecast_surprise_type"
    )

    # 因子2: forecast_magnitude (中值变动幅度)
    magnitude = (latest["p_change_max"].fillna(0) + latest["p_change_min"].fillna(0)) / 2 / 100
    # Clip to [-3, 5]
    magnitude = magnitude.clip(-3.0, 5.0)
    factor_magnitude = pd.Series(
        magnitude.values, index=latest["code"].values, name="forecast_magnitude"
    )

    # 因子3: forecast_recency (距最近预告天数)
    recency_days = (td - latest["ann_date"]).dt.days.astype(float)
    recency_days = recency_days.clip(0, 365)
    factor_recency = pd.Series(
        recency_days.values, index=latest["code"].values, name="forecast_recency"
    )

    return {
        "forecast_surprise_type": factor_surprise,
        "forecast_magnitude": factor_magnitude,
        "forecast_recency": factor_recency,
    }


# ============================================================
# Step 3: IC快筛
# ============================================================

def load_neutralize_data(trade_date: date, conn) -> tuple[pd.Series, pd.Series]:
    """加载截面的ln_mcap和行业分类（用于中性化）。

    Args:
        trade_date: 交易日
        conn: 数据库连接

    Returns:
        (ln_mcap Series indexed by code, industry Series indexed by code)
    """
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
    """对因子做市值+行业中性化（OLS回归取残差）。

    复用factor_engine.preprocess_neutralize的逻辑。
    """
    common = factor_series.index.intersection(ln_mcap.index).intersection(industry.index)
    if len(common) < 30:
        return pd.Series(dtype=float)

    y = factor_series.loc[common].values
    mcap_col = ln_mcap.loc[common].values.reshape(-1, 1)
    ind_dummies = pd.get_dummies(industry.loc[common], drop_first=True).values

    X = np.column_stack([np.ones(len(y)), mcap_col, ind_dummies])

    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        residual = y - X @ beta
        return pd.Series(residual, index=common)
    except np.linalg.LinAlgError:
        return pd.Series(dtype=float)


def ic_screening(forecast_df: pd.DataFrame, conn) -> dict[str, dict]:
    """全样本月末截面IC快筛（2020-2025） + 中性化验证。

    对3个forecast因子在60+个月末交易日计算截面Spearman IC。
    同时计算原始IC和中性化后IC。
    前瞻收益: 5日超额收益(vs沪深300)。
    """
    logger.info("=" * 70)
    logger.info("全样本IC检验: 3个forecast因子 x 2020-2025月末 + 中性化")
    logger.info("=" * 70)

    # 获取2020-2025年交易日
    sql_dates = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN '2020-01-01' AND '2025-12-31'
    ORDER BY trade_date
    """
    dates_df = pd.read_sql(sql_dates, conn)
    trade_dates = [d.date() if hasattr(d, "date") else d
                   for d in dates_df["trade_date"]]

    # 月末交易日（按年-月分组取最大日期）
    month_end_dates = {}
    for td in trade_dates:
        key = (td.year, td.month)
        month_end_dates[key] = td
    month_ends = sorted(month_end_dates.values())
    logger.info(f"月末交易日: {len(month_ends)}个 ({month_ends[0]} ~ {month_ends[-1]})")

    # 前瞻5日超额收益 (2020-2025)
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
        WHERE k1.trade_date BETWEEN '2020-01-01' AND '2025-12-31'
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
          AND i1.trade_date BETWEEN '2020-01-01' AND '2025-12-31'
    )
    SELECT s.code, s.trade_date,
           s.stock_return_5 - i.index_return_5 AS excess_return_5
    FROM stock_ret s
    JOIN index_ret i ON s.trade_date = i.trade_date
    WHERE s.stock_return_5 IS NOT NULL AND i.index_return_5 IS NOT NULL
      AND ABS(s.stock_return_5) < 5.0
    """
    logger.info("加载2020-2025年5日前瞻超额收益（耗时较长）...")
    ret_df = pd.read_sql(sql_ret, conn)
    ret_df["trade_date"] = pd.to_datetime(ret_df["trade_date"]).dt.date
    logger.info(f"前瞻收益: {len(ret_df)}行, {ret_df['code'].nunique()}股")

    # 每个月末计算3个因子的原始IC和中性化IC
    results: dict[str, dict] = {
        name: {
            "monthly_ics": [],
            "monthly_ics_neutral": [],
            "frozen_months": 0,
            "coverage": [],
        }
        for name in FACTOR_NAMES
    }

    for idx, td in enumerate(month_ends):
        if idx % 12 == 0:
            logger.info(f"  处理 {td} ({idx+1}/{len(month_ends)})...")
        factor_data = load_forecast_pit_data(td, forecast_df)

        day_ret = ret_df[ret_df["trade_date"] == td].set_index("code")["excess_return_5"]

        # 加载中性化数据
        ln_mcap, industry = load_neutralize_data(td, conn)

        for fname in FACTOR_NAMES:
            fvals = factor_data.get(fname, pd.Series(dtype=float))

            if fvals.empty:
                results[fname]["monthly_ics"].append(np.nan)
                results[fname]["monthly_ics_neutral"].append(np.nan)
                results[fname]["frozen_months"] += 1
                results[fname]["coverage"].append(0)
                continue

            common = fvals.index.intersection(day_ret.index)
            results[fname]["coverage"].append(len(common))

            if len(common) < 30:
                results[fname]["monthly_ics"].append(np.nan)
                results[fname]["monthly_ics_neutral"].append(np.nan)
                results[fname]["frozen_months"] += 1
                continue

            f = fvals.loc[common]
            r = day_ret.loc[common]

            if f.std() < 1e-10:
                results[fname]["monthly_ics"].append(np.nan)
                results[fname]["monthly_ics_neutral"].append(np.nan)
                results[fname]["frozen_months"] += 1
                continue

            # 原始IC
            ic_raw = sp_stats.spearmanr(f, r).statistic
            if np.isnan(ic_raw):
                ic_raw = np.nan
            results[fname]["monthly_ics"].append(ic_raw)

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

    # 汇总
    n_months = len(month_ends)
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"全样本IC结果: 3个forecast因子 (2020-2025, {n_months}个月末截面)")
    logger.info("=" * 70)

    print("\n")
    print("=" * 110)
    print(f"全样本IC结果: 3个forecast因子 (2020-2025, {n_months}个月末, 5日前瞻超额)")
    print("=" * 110)

    header = (
        f"{'Factor':<28} | {'RawIC':>7} | {'NeutIC':>7} | "
        f"{'RawIR':>7} | {'NeutIR':>7} | "
        f"{'Raw-t':>7} | {'Neut-t':>7} | {'N':>4} | {'Status':>10}"
    )
    print(header)
    print("-" * len(header))
    logger.info(header)
    logger.info("-" * len(header))

    for fname in FACTOR_NAMES:
        r = results[fname]
        ics_raw = np.array(r["monthly_ics"], dtype=float)
        ics_neutral = np.array(r["monthly_ics_neutral"], dtype=float)

        # 只用非NaN的月份
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

        # 判定: 中性化后t-stat是否达标
        raw_pass = abs(r["t_stat"]) >= 2.0
        neutral_pass = abs(r["t_stat_neutral"]) >= 2.0
        if neutral_pass:
            status = "PASS"
        elif raw_pass and not neutral_pass:
            status = "FAIL(neut)"
        else:
            status = "FAIL"

        line = (
            f"  {fname:<26} | {r['mean_ic']:>7.4f} | {r['mean_ic_neutral']:>7.4f} | "
            f"{r['icir']:>7.3f} | {r['icir_neutral']:>7.3f} | "
            f"{r['t_stat']:>7.2f} | {r['t_stat_neutral']:>7.2f} | {n_raw:>4} | {status:>10}"
        )
        print(line)
        logger.info(line)

    # 方向调整后
    print(f"\n{'方向调整后IC (direction × mean_ic)':=^70}")
    for fname in FACTOR_NAMES:
        r = results[fname]
        d = FACTOR_DIRECTION[fname]
        sign = "+" if d == 1 else "-"
        raw_adj = r["mean_ic"] * d
        neut_adj = r["mean_ic_neutral"] * d
        print(f"  {fname:<28}: dir={sign:>2}  raw_adj={raw_adj:>8.4f}  neut_adj={neut_adj:>8.4f}")

    # 年度分解
    print(f"\n{'年度IC分解 (原始 / 中性化)':=^70}")
    year_ics: dict[int, dict[str, list]] = {}
    for i, td in enumerate(month_ends):
        yr = td.year
        if yr not in year_ics:
            year_ics[yr] = {fname: {"raw": [], "neut": []} for fname in FACTOR_NAMES}
        for fname in FACTOR_NAMES:
            raw_v = results[fname]["monthly_ics"][i]
            neut_v = results[fname]["monthly_ics_neutral"][i]
            if not np.isnan(raw_v):
                year_ics[yr][fname]["raw"].append(raw_v)
            if not np.isnan(neut_v):
                year_ics[yr][fname]["neut"].append(neut_v)

    header_yr = f"{'Year':<6} |"
    for fname in FACTOR_NAMES:
        short = fname[:10]
        header_yr += f" {short+'_raw':>12} | {short+'_neut':>12} |"
    print(header_yr)
    print("-" * len(header_yr))
    for yr in sorted(year_ics.keys()):
        line_yr = f"  {yr:<4} |"
        for fname in FACTOR_NAMES:
            raw_list = year_ics[yr][fname]["raw"]
            neut_list = year_ics[yr][fname]["neut"]
            raw_mean = np.mean(raw_list) if raw_list else 0.0
            neut_mean = np.mean(neut_list) if neut_list else 0.0
            line_yr += f" {raw_mean:>12.4f} | {neut_mean:>12.4f} |"
        print(line_yr)

    print("\n" + "=" * 110)

    return results


# ============================================================
# Main
# ============================================================

def main():
    import psycopg2

    t_start = time.time()

    cache_path = project_root / "models" / "forecast_cache.parquet"
    forecast_df = load_or_fetch_forecast(cache_path)

    if forecast_df.empty:
        logger.error("无forecast数据，退出")
        return

    # 预处理: ts_code -> code, ann_date -> date
    forecast_df["code"] = forecast_df["ts_code"].str.replace(r"\.(SH|SZ|BJ)", "", regex=True)
    forecast_df["ann_date"] = pd.to_datetime(forecast_df["ann_date"])

    # 去重: 同一(code, end_date)取ann_date最新
    forecast_df = forecast_df.sort_values("ann_date", ascending=False)
    forecast_df = forecast_df.drop_duplicates(subset=["code", "end_date"], keep="first")
    logger.info(
        f"预处理后: {len(forecast_df)}行, {forecast_df['code'].nunique()}股, "
        f"ann_date范围: {forecast_df['ann_date'].min()} ~ {forecast_df['ann_date'].max()}"
    )

    # 数据质量检查
    logger.info("数据质量:")
    logger.info(f"  type分布:\n{forecast_df['type'].value_counts().to_string()}")
    logger.info(f"  p_change_min缺失率: {forecast_df['p_change_min'].isna().mean():.1%}")
    logger.info(f"  p_change_max缺失率: {forecast_df['p_change_max'].isna().mean():.1%}")

    # IC快筛
    conn = psycopg2.connect(
        dbname="quantmind_v2",
        user="xin",
        password="quantmind",
        host="localhost",
    )

    try:
        results = ic_screening(forecast_df, conn)

        # 最终判定
        print("\n" + "=" * 70)
        print("最终判定 (硬性标准: 中性化后 |t-stat| >= 2.0)")
        print("=" * 70)
        pass_factors = []
        for fname in FACTOR_NAMES:
            r = results[fname]
            raw_t = abs(r["t_stat"])
            neut_t = abs(r["t_stat_neutral"])
            raw_ic = abs(r["mean_ic"])
            neut_ic = abs(r["mean_ic_neutral"])
            verdict = "PASS" if neut_t >= 2.0 else "FAIL"
            if verdict == "PASS":
                pass_factors.append(fname)
            print(
                f"  {fname:<28}: raw|IC|={raw_ic:.4f} t={raw_t:.2f}  "
                f"neut|IC|={neut_ic:.4f} t={neut_t:.2f} -> {verdict}"
            )

        if pass_factors:
            print(f"\n  >>> {len(pass_factors)}个因子通过中性化t-stat>=2.0: {pass_factors}")
        else:
            print("\n  >>> 全部FAIL: 中性化后t-stat均<2.0")
            print("  >>> 结论: forecast方向关闭证据充分")

        print("=" * 70)

        total = time.time() - t_start
        logger.info(f"\n总耗时: {total:.1f}s ({total/60:.1f}min)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
