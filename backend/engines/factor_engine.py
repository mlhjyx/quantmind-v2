"""因子计算引擎 — Phase 0 规则版因子管道。

流程: 读取行情 → 计算原始因子值 → 预处理(MAD→fill→neutralize→zscore) → 批量写入

严格遵守 CLAUDE.md 因子计算规则:
1. 预处理顺序不可调换: MAD去极值 → 缺失值填充 → 中性化 → 标准化
2. 按日期批量写入(单事务)
3. IC使用超额收益(vs CSI300)
"""

import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# Phase 0 因子定义 (6 core → Week 6 扩展到 18)
# ============================================================

def calc_momentum(close_adj: pd.Series, window: int) -> pd.Series:
    """动量因子: N日收益率。

    Args:
        close_adj: 前复权收盘价, MultiIndex=(code, trade_date) 或按code分组后的Series
        window: 回看窗口(5/10/20)

    Returns:
        pd.Series: 动量值
    """
    return close_adj.pct_change(window)


def calc_reversal(close_adj: pd.Series, window: int) -> pd.Series:
    """反转因子: -1 × N日收益率（取反，近期跌多的排前面）。"""
    return -close_adj.pct_change(window)


def calc_volatility(close_adj: pd.Series, window: int) -> pd.Series:
    """波动率因子: N日收益率的滚动标准差。"""
    returns = close_adj.pct_change(1)
    return returns.rolling(window, min_periods=max(window // 2, 5)).std()


def calc_volume_std(volume: pd.Series, window: int) -> pd.Series:
    """成交量波动率: N日volume的滚动标准差。"""
    return volume.rolling(window, min_periods=max(window // 2, 5)).std()


def calc_turnover_mean(turnover_rate: pd.Series, window: int) -> pd.Series:
    """换手率均值: N日turnover_rate的滚动均值。"""
    return turnover_rate.rolling(window, min_periods=max(window // 2, 5)).mean()


def calc_turnover_std(turnover_rate: pd.Series, window: int) -> pd.Series:
    """换手率波动: N日turnover_rate的滚动标准差。"""
    return turnover_rate.rolling(window, min_periods=max(window // 2, 5)).std()


def calc_amihud(
    close_adj: pd.Series, volume: pd.Series, amount: pd.Series, window: int
) -> pd.Series:
    """Amihud非流动性因子: mean(|return| / amount)。

    注意: amount单位是千元, 不影响截面排序。
    """
    ret = close_adj.pct_change(1).abs()
    illiq = ret / (amount + 1e-12)
    return illiq.rolling(window, min_periods=max(window // 2, 5)).mean()


def calc_ln_mcap(total_mv: pd.Series) -> pd.Series:
    """对数市值: ln(total_mv)。total_mv单位万元。"""
    return np.log(total_mv + 1e-12)


def calc_bp_ratio(pb: pd.Series) -> pd.Series:
    """账面市值比: 1/pb。pb=0时返回NaN。"""
    return 1.0 / pb.replace(0, np.nan)


def calc_ep_ratio(pe: pd.Series) -> pd.Series:
    """盈利收益率: 1/pe_ttm。pe_ttm=0时返回NaN。"""
    return 1.0 / pe.replace(0, np.nan)


def calc_pv_corr(close_adj: pd.Series, volume: pd.Series, window: int) -> pd.Series:
    """价量相关性: N日close与volume的滚动相关系数。"""
    return close_adj.rolling(window, min_periods=max(window // 2, 5)).corr(volume)


def calc_hl_range(
    high_adj: pd.Series, low_adj: pd.Series, window: int
) -> pd.Series:
    """振幅因子: N日平均(high-low)/low。"""
    daily_range = (high_adj - low_adj) / (low_adj + 1e-12)
    return daily_range.rolling(window, min_periods=max(window // 2, 5)).mean()


def calc_price_level(close: pd.Series) -> pd.Series:
    """价格水平因子: -ln(close)。用原始close（非复权），反映价格分层偏好。"""
    return -np.log(close.clip(lower=1e-12))


def calc_relative_volume(volume: pd.Series, window: int) -> pd.Series:
    """相对成交量: volume_today / mean(volume, Nd)。"""
    vol_ma = volume.rolling(window, min_periods=max(window // 2, 5)).mean()
    return volume / (vol_ma + 1e-12)


def calc_turnover_surge_ratio(turnover_rate: pd.Series) -> pd.Series:
    """换手率突增比: mean(turnover_rate, 5d) / mean(turnover_rate, 20d)。"""
    ma5 = turnover_rate.rolling(5, min_periods=3).mean()
    ma20 = turnover_rate.rolling(20, min_periods=10).mean()
    return ma5 / (ma20 + 1e-12)


# ============================================================
# 因子注册表
# ============================================================

# Phase 0 Week 3: 6 core factors
PHASE0_CORE_FACTORS = {
    "momentum_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 20)
    ),
    "volatility_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_volatility(x, 20)
    ),
    "turnover_mean_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_mean(x, 20)
    ),
    "amihud_20": lambda df: df.groupby("code").apply(
        lambda g: calc_amihud(g["adj_close"], g["volume"], g["amount"], 20)
    ).droplevel(0),
    "ln_market_cap": lambda df: calc_ln_mcap(df["total_mv"]),
    "bp_ratio": lambda df: calc_bp_ratio(df["pb"]),
}

# Phase 0 Week 6: 扩展到 18 factors
PHASE0_FULL_FACTORS = {
    **PHASE0_CORE_FACTORS,
    "momentum_5": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 5)
    ),
    "momentum_10": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 10)
    ),
    "reversal_5": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 5)
    ),
    "reversal_10": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 10)
    ),
    "reversal_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 20)
    ),
    "volatility_60": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_volatility(x, 60)
    ),
    "volume_std_20": lambda df: df.groupby("code")["volume"].transform(
        lambda x: calc_volume_std(x, 20)
    ),
    "turnover_std_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_std(x, 20)
    ),
    "ep_ratio": lambda df: calc_ep_ratio(df["pe_ttm"]),
    "price_volume_corr_20": lambda df: df.groupby("code").apply(
        lambda g: calc_pv_corr(g["adj_close"], g["volume"].astype(float), 20)
    ).droplevel(0),
    "high_low_range_20": lambda df: df.groupby("code").apply(
        lambda g: calc_hl_range(g["adj_high"], g["adj_low"], 20)
    ).droplevel(0),
    # northbound_pct: Phase 1 (需要额外数据源 AKShare)
    # ---- v1.2 新增因子 ----
    "price_level_factor": lambda df: df.groupby("code")["close"].transform(
        lambda x: calc_price_level(x)
    ),
    "relative_volume_20": lambda df: df.groupby("code")["volume"].transform(
        lambda x: calc_relative_volume(x.astype(float), 60)
    ),
    "dv_ttm": lambda df: df["dv_ttm"],  # daily_basic直接取值
    "turnover_surge_ratio": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_surge_ratio(x)
    ),
}


# ============================================================
# 预处理管道 (CLAUDE.md 强制顺序: MAD → fill → neutralize → zscore)
# ============================================================

def preprocess_mad(series: pd.Series, n_mad: float = 5.0) -> pd.Series:
    """Step 1: MAD去极值。

    将超出 median ± n_mad × MAD 的值截断到边界。

    Args:
        series: 单因子截面值 (一个trade_date的全部股票)
        n_mad: MAD倍数, 默认5倍

    Returns:
        去极值后的Series
    """
    median = series.median()
    mad = (series - median).abs().median()
    if mad < 1e-12:
        return series
    upper = median + n_mad * mad
    lower = median - n_mad * mad
    return series.clip(lower=lower, upper=upper)


def preprocess_fill(
    series: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """Step 2: 缺失值填充。

    先用行业中位数填充, 再用0填充剩余。

    Args:
        series: 单因子截面值
        industry: 对应的行业分类

    Returns:
        填充后的Series (无NaN)
    """
    # 行业中位数填充
    industry_median = series.groupby(industry).transform("median")
    filled = series.fillna(industry_median)
    # 剩余NaN用0填充
    filled = filled.fillna(0.0)
    return filled


def preprocess_neutralize(
    series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """Step 3: 中性化 — 回归掉市值 + 行业。

    对 factor = alpha + beta1 × ln_mcap + sum(beta_i × industry_dummy) + residual
    返回 residual。

    Args:
        series: 单因子截面值 (已去极值+填充)
        ln_mcap: 对数市值
        industry: 行业分类

    Returns:
        中性化后的残差
    """
    valid_mask = series.notna() & ln_mcap.notna() & industry.notna()
    if valid_mask.sum() < 30:
        logger.warning("中性化样本不足30，跳过中性化")
        return series

    y = series[valid_mask].values
    # 构建X: [ln_mcap, industry_dummies]
    mcap_col = ln_mcap[valid_mask].values.reshape(-1, 1)
    ind_dummies = pd.get_dummies(industry[valid_mask], drop_first=True).values

    X = np.column_stack([np.ones(len(y)), mcap_col, ind_dummies])

    try:
        # OLS: beta = (X'X)^-1 X'y
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        residual = y - X @ beta

        result = series.copy()
        result[valid_mask] = residual
        result[~valid_mask] = np.nan
        return result
    except np.linalg.LinAlgError:
        logger.warning("中性化回归失败(矩阵奇异)，返回原值")
        return series


def preprocess_zscore(series: pd.Series) -> pd.Series:
    """Step 4: zscore标准化。

    (x - mean) / std, 标准差为0时返回全0。
    """
    mean = series.mean()
    std = series.std()
    if std < 1e-12:
        return pd.Series(0.0, index=series.index)
    return (series - mean) / std


def preprocess_pipeline(
    factor_series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """完整预处理管道。

    返回 (raw_value, neutral_value)。
    neutral_value = 经过MAD→fill→neutralize→zscore全部4步处理后的值。

    Args:
        factor_series: 原始因子截面值
        ln_mcap: 对数市值
        industry: 行业分类

    Returns:
        (raw_value, neutral_value) 两个Series
    """
    raw = factor_series.copy()

    # Step 1: MAD去极值
    step1 = preprocess_mad(raw)
    # Step 2: 缺失值填充
    step2 = preprocess_fill(step1, industry)
    # Step 3: 中性化
    step3 = preprocess_neutralize(step2, ln_mcap, industry)
    # Step 4: zscore
    step4 = preprocess_zscore(step3)

    return raw, step4


# ============================================================
# IC计算
# ============================================================

def calc_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    method: str = "spearman",
) -> float:
    """计算单日单因子的IC (Information Coefficient)。

    Args:
        factor_values: 因子截面值 (index=code)
        forward_returns: 前向超额收益 (index=code)
        method: 'spearman'(rank IC) 或 'pearson'

    Returns:
        IC值 (float)
    """
    # 对齐index
    common = factor_values.dropna().index.intersection(forward_returns.dropna().index)
    if len(common) < 30:
        return np.nan

    f = factor_values.loc[common]
    r = forward_returns.loc[common]

    if method == "spearman":
        return f.rank().corr(r.rank())
    else:
        return f.corr(r)


# ============================================================
# 数据加载 (读取行情 + daily_basic, 计算adj_close)
# ============================================================

def load_daily_data(
    trade_date: date,
    lookback_days: int = 120,
    conn=None,
) -> pd.DataFrame:
    """加载因子计算所需的每日数据。

    合并 klines_daily + daily_basic, 计算前复权价格。

    Args:
        trade_date: 计算日期
        lookback_days: 回看天数(用于滚动计算)
        conn: psycopg2连接

    Returns:
        DataFrame with columns: code, trade_date, open, high, low, close,
        volume, amount, adj_factor, adj_close, adj_high, adj_low,
        turnover_rate, total_mv, pb, pe_ttm, industry_sw1
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        )
        SELECT
            k.code,
            k.trade_date,
            k.open, k.high, k.low, k.close,
            k.volume, k.amount,
            k.adj_factor,
            k.close * k.adj_factor / la.latest_adj_factor AS adj_close,
            k.high  * k.adj_factor / la.latest_adj_factor AS adj_high,
            k.low   * k.adj_factor / la.latest_adj_factor AS adj_low,
            db.turnover_rate,
            db.total_mv,
            db.pb,
            db.pe_ttm,
            db.dv_ttm,
            s.industry_sw1
        FROM klines_daily k
        JOIN latest_adj la ON k.code = la.code
        LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
        LEFT JOIN symbols s ON k.code = s.code
        WHERE k.trade_date BETWEEN
            (SELECT DISTINCT trade_date FROM klines_daily
             WHERE trade_date <= %s
             ORDER BY trade_date DESC
             OFFSET %s LIMIT 1)
            AND %s
          AND k.adj_factor IS NOT NULL
          AND k.volume > 0
        ORDER BY k.code, k.trade_date
        """
        df = pd.read_sql(sql, conn, params=(trade_date, lookback_days, trade_date))
        return df
    finally:
        if close_conn:
            conn.close()


def load_forward_returns(
    trade_date: date,
    horizon: int = 5,
    conn=None,
) -> pd.Series:
    """加载前向超额收益(vs CSI300)。

    Args:
        trade_date: 基准日期
        horizon: 前看天数(1/5/10/20)
        conn: psycopg2连接

    Returns:
        pd.Series indexed by code, values = excess return
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        # 先找到N个交易日后的日期
        future_date_df = pd.read_sql(
            """SELECT DISTINCT trade_date FROM klines_daily
               WHERE trade_date > %s ORDER BY trade_date LIMIT %s""",
            conn, params=(trade_date, horizon),
        )
        if future_date_df.empty:
            return pd.Series(dtype=float)
        future_date = future_date_df.iloc[-1]["trade_date"]

        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        ),
        base AS (
            SELECT k.code,
                   k.close * k.adj_factor / la.latest_adj_factor AS adj_close
            FROM klines_daily k
            JOIN latest_adj la ON k.code = la.code
            WHERE k.trade_date = %s AND k.adj_factor IS NOT NULL
        ),
        future AS (
            SELECT k.code,
                   k.close * k.adj_factor / la.latest_adj_factor AS adj_close
            FROM klines_daily k
            JOIN latest_adj la ON k.code = la.code
            WHERE k.trade_date = %s AND k.adj_factor IS NOT NULL
        )
        SELECT
            b.code,
            (f.adj_close / NULLIF(b.adj_close, 0) - 1)
            - (
                (SELECT close FROM index_daily
                 WHERE index_code = '000300.SH' AND trade_date = %s)
                / NULLIF(
                    (SELECT close FROM index_daily
                     WHERE index_code = '000300.SH' AND trade_date = %s), 0)
                - 1
              ) AS excess_return
        FROM base b
        JOIN future f ON b.code = f.code
        """
        df = pd.read_sql(
            sql, conn,
            params=(trade_date, future_date, future_date, trade_date),
        )
        return df.set_index("code")["excess_return"]
    finally:
        if close_conn:
            conn.close()


# ============================================================
# 因子写入
# ============================================================

def save_daily_factors(
    trade_date: date,
    factor_df: pd.DataFrame,
    conn=None,
) -> int:
    """按日期批量写入因子值(单事务)。

    CLAUDE.md强制要求: 一次事务写入当日全部股票×全部因子。

    Args:
        trade_date: 交易日期
        factor_df: DataFrame with columns [code, factor_name, raw_value, neutral_value, zscore]
        conn: psycopg2连接

    Returns:
        写入行数
    """
    from psycopg2.extras import execute_values
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    def _safe_float(val):
        """将NaN/inf转为None（PostgreSQL NUMERIC不支持inf）。"""
        if pd.isna(val):
            return None
        v = float(val)
        if not np.isfinite(v):
            return None
        return v

    try:
        rows = []
        for _, row in factor_df.iterrows():
            rows.append((
                row["code"],
                trade_date,
                row["factor_name"],
                _safe_float(row.get("raw_value")),
                _safe_float(row.get("neutral_value")),
                _safe_float(row.get("zscore")),
            ))

        with conn.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO factor_values (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                   VALUES %s
                   ON CONFLICT (code, trade_date, factor_name)
                   DO UPDATE SET raw_value = EXCLUDED.raw_value,
                                 neutral_value = EXCLUDED.neutral_value,
                                 zscore = EXCLUDED.zscore""",
                rows,
                page_size=5000,
            )
        conn.commit()
        logger.info(f"[{trade_date}] 写入因子 {len(rows)} 行")
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()


# ============================================================
# 主流程: 单日因子计算
# ============================================================

def compute_daily_factors(
    trade_date: date,
    factor_set: str = "core",
    conn=None,
) -> pd.DataFrame:
    """计算单日全部因子。

    Args:
        trade_date: 交易日期
        factor_set: 'core'(6因子) 或 'full'(18因子)
        conn: 可选连接

    Returns:
        DataFrame [code, factor_name, raw_value, neutral_value, zscore]
    """
    factors = PHASE0_CORE_FACTORS if factor_set == "core" else PHASE0_FULL_FACTORS

    # 1. 加载数据
    logger.info(f"[{trade_date}] 加载行情数据...")
    df = load_daily_data(trade_date, lookback_days=120, conn=conn)

    if df.empty:
        logger.warning(f"[{trade_date}] 无数据，跳过")
        return pd.DataFrame()

    # 取当日截面
    today_mask = df["trade_date"] == trade_date
    if today_mask.sum() == 0:
        logger.warning(f"[{trade_date}] 当日无数据，跳过")
        return pd.DataFrame()

    today_codes = df.loc[today_mask, "code"].values
    today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
    today_industry.index = today_codes
    today_ln_mcap = df.loc[today_mask, "total_mv"].apply(lambda x: np.log(x + 1e-12))
    today_ln_mcap.index = today_codes

    # 2. 计算每个因子
    all_results = []

    for factor_name, calc_fn in factors.items():
        try:
            logger.debug(f"[{trade_date}] 计算因子: {factor_name}")

            # 计算原始值
            raw_series = calc_fn(df)

            # 取当日截面
            raw_today = raw_series[today_mask].copy()
            raw_today.index = today_codes

            # 预处理
            raw_val, neutral_val = preprocess_pipeline(
                raw_today, today_ln_mcap, today_industry
            )

            # 组装结果
            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)
                all_results.append({
                    "code": code,
                    "factor_name": factor_name,
                    "raw_value": rv,
                    "neutral_value": nv,
                    "zscore": nv,  # neutral_value已经是zscore
                })
        except Exception as e:
            logger.error(f"[{trade_date}] 因子 {factor_name} 计算失败: {e}")
            continue

    result_df = pd.DataFrame(all_results)
    logger.info(
        f"[{trade_date}] 计算完成: {len(factors)}因子 × {len(today_codes)}股 = {len(result_df)}行"
    )
    return result_df


# ============================================================
# 批量计算: 一次加载全量数据, 逐日计算+写入
# ============================================================

def load_bulk_data(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """批量加载行情数据(含前复权价格)。

    一次性加载 [start_date-120天, end_date] 的全部数据，
    避免逐日加载的重复IO。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        conn: psycopg2连接

    Returns:
        DataFrame sorted by (code, trade_date)
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        ),
        lookback_start AS (
            SELECT COALESCE(
                (SELECT DISTINCT trade_date FROM klines_daily
                 WHERE trade_date <= %s
                 ORDER BY trade_date DESC
                 OFFSET 120 LIMIT 1),
                (SELECT MIN(trade_date) FROM klines_daily)
            ) AS trade_date
        )
        SELECT
            k.code,
            k.trade_date,
            k.open, k.high, k.low, k.close,
            k.volume, k.amount,
            k.adj_factor,
            k.close * k.adj_factor / la.latest_adj_factor AS adj_close,
            k.high  * k.adj_factor / la.latest_adj_factor AS adj_high,
            k.low   * k.adj_factor / la.latest_adj_factor AS adj_low,
            db.turnover_rate,
            db.total_mv,
            db.pb,
            db.pe_ttm,
            db.dv_ttm,
            s.industry_sw1
        FROM klines_daily k
        JOIN latest_adj la ON k.code = la.code
        LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
        LEFT JOIN symbols s ON k.code = s.code
        WHERE k.trade_date BETWEEN (SELECT trade_date FROM lookback_start) AND %s
          AND k.adj_factor IS NOT NULL
          AND k.volume > 0
        ORDER BY k.code, k.trade_date
        """
        logger.info(f"批量加载数据: {start_date} → {end_date} (+120天回看)")
        df = pd.read_sql(sql, conn, params=(start_date, end_date))
        logger.info(f"数据加载完成: {len(df)}行, {df['code'].nunique()}股, "
                     f"{df['trade_date'].nunique()}天")
        return df
    finally:
        if close_conn:
            conn.close()


def compute_batch_factors(
    start_date: date,
    end_date: date,
    factor_set: str = "core",
    conn=None,
    write: bool = True,
) -> dict:
    """批量计算因子并逐日写入。

    高效模式: 一次加载全量数据 → 计算滚动因子 → 逐日预处理+写入。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        factor_set: 'core' 或 'full'
        conn: 可选连接
        write: 是否写入数据库

    Returns:
        dict with stats (total_rows, elapsed, etc.)
    """
    import time
    from psycopg2.extras import execute_values
    from app.services.price_utils import _get_sync_conn

    factors = PHASE0_CORE_FACTORS if factor_set == "core" else PHASE0_FULL_FACTORS
    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    t0 = time.time()

    # 1. 一次性加载全量数据
    df = load_bulk_data(start_date, end_date, conn=conn)
    if df.empty:
        return {"total_rows": 0, "elapsed": 0, "dates": 0,
                "load_time": 0, "calc_time": 0, "total_time": 0}

    t_load = time.time() - t0

    # 2. 一次性计算所有因子的滚动值
    logger.info(f"计算 {len(factors)} 个因子的滚动值...")
    factor_raw = {}
    for fname, calc_fn in factors.items():
        try:
            factor_raw[fname] = calc_fn(df)
        except Exception as e:
            logger.error(f"因子 {fname} 计算失败: {e}")

    t_calc = time.time() - t0 - t_load

    # 3. 获取计算范围内的交易日
    all_dates = sorted(df.loc[
        (df["trade_date"] >= start_date) &
        (df["trade_date"] <= end_date),
        "trade_date"
    ].unique())

    logger.info(f"逐日预处理+写入: {len(all_dates)}个交易日")

    total_rows = 0
    for i, td in enumerate(all_dates):
        td_date = td.date() if hasattr(td, "date") else td

        # 取当日截面
        today_mask = df["trade_date"] == td
        if today_mask.sum() == 0:
            continue

        today_codes = df.loc[today_mask, "code"].values
        today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
        today_industry.index = today_codes
        today_ln_mcap = df.loc[today_mask, "total_mv"].apply(
            lambda x: np.log(x + 1e-12)
        )
        today_ln_mcap.index = today_codes

        # 逐因子预处理
        day_rows = []
        for fname in factor_raw:
            raw_today = factor_raw[fname][today_mask].copy()
            raw_today.index = today_codes

            raw_val, neutral_val = preprocess_pipeline(
                raw_today, today_ln_mcap, today_industry
            )

            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)

                def _safe(v):
                    if pd.isna(v):
                        return None
                    fv = float(v)
                    return None if not np.isfinite(fv) else fv

                day_rows.append((
                    code, td_date, fname,
                    _safe(rv), _safe(nv), _safe(nv),
                ))

        # 写入当日所有因子(单事务)
        if write and day_rows:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """INSERT INTO factor_values
                       (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                       VALUES %s
                       ON CONFLICT (code, trade_date, factor_name)
                       DO UPDATE SET raw_value = EXCLUDED.raw_value,
                                     neutral_value = EXCLUDED.neutral_value,
                                     zscore = EXCLUDED.zscore""",
                    day_rows,
                    page_size=5000,
                )
            conn.commit()

        total_rows += len(day_rows)
        if (i + 1) % 50 == 0 or i == 0 or i == len(all_dates) - 1:
            elapsed = time.time() - t0
            logger.info(
                f"  [{i+1}/{len(all_dates)}] {td_date} | "
                f"{len(day_rows)}行 | 累计{total_rows}行 | "
                f"{elapsed:.0f}s"
            )

    elapsed = time.time() - t0
    stats = {
        "total_rows": total_rows,
        "dates": len(all_dates),
        "load_time": round(t_load, 1),
        "calc_time": round(t_calc, 1),
        "total_time": round(elapsed, 1),
    }
    logger.info(
        f"批量因子计算完成: {stats['dates']}天, {total_rows}行, "
        f"加载{t_load:.0f}s + 计算{t_calc:.0f}s + 总计{elapsed:.0f}s"
    )
    return stats
