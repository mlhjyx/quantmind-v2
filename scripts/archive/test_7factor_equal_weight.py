"""7因子等权组合回测 vs 5因子基线。

测试目标：
- 7因子 = 5基线(turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio)
        + vwap_bias_1d + rsrs_raw_18
- 因子方向严格与signal_engine.py FACTOR_DIRECTION一致（铁律5）
- 对比：Sharpe/MDD/年化收益/Calmar + Paired block bootstrap p值 + 年度分解 + 成本敏感性

注意：
- vwap_bias_1d和rsrs_raw_18可能不在factor_values表中，脚本自行计算+中性化
- 信号合成逻辑与signal_engine.py一致：sign-flip neutral_value + 等权求和 + 排名Top-N
"""

import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ==============================================================
# 常量
# ==============================================================
BT_START = date(2021, 1, 1)
BT_END = date(2025, 12, 31)
TOP_N = 15
COST_ONE_WAY = 0.0015  # 单边1.5‰ (佣金+滑点+印花税摊销)
BOOTSTRAP_N = 10000
BOOTSTRAP_BLOCK = 20
SEED = 42

# ── 因子方向（来自signal_engine.py FACTOR_DIRECTION，铁律5验证） ──
# signal_engine.py:
#   turnover_mean_20: -1  (低换手好)
#   volatility_20:    -1  (低波动好)
#   reversal_20:      +1  (calc_reversal = -pct_change, 已取反, 值大=跌多=好)
#   amihud_20:        +1  (高非流动性=小盘溢价)
#   bp_ratio:         +1  (高B/P=价值股好)
# 新增:
#   vwap_bias_1d:     -1  (反转效应, 用户确认)
#   rsrs_raw_18:      -1  (反转效应, 用户确认)
FACTOR_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
    "vwap_bias_1d": -1,
    "rsrs_raw_18": -1,
}

BASELINE_FACTORS = [
    "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"
]
SEVEN_FACTORS = BASELINE_FACTORS + ["vwap_bias_1d", "rsrs_raw_18"]


def get_conn():
    return _get_sync_conn()


# ==============================================================
# 数据加载
# ==============================================================

def check_factors_in_db(conn) -> dict[str, bool]:
    """检查因子是否已在factor_values表中。"""
    sql = """
    SELECT DISTINCT factor_name FROM factor_values
    WHERE factor_name IN ('vwap_bias_1d', 'rsrs_raw_18')
    """
    df = pd.read_sql(sql, conn)
    found = set(df["factor_name"].tolist())
    return {
        "vwap_bias_1d": "vwap_bias_1d" in found,
        "rsrs_raw_18": "rsrs_raw_18" in found,
    }


def load_factor_values(conn, factor_names: list[str],
                       start_date: date, end_date: date) -> pd.DataFrame:
    """从factor_values加载neutral_value。

    Returns:
        DataFrame [trade_date, code, factor_name, neutral_value]
    """
    placeholders = ",".join(["%s"] * len(factor_names))
    sql = f"""
    SELECT trade_date, code, factor_name, neutral_value
    FROM factor_values
    WHERE trade_date BETWEEN %s AND %s
      AND factor_name IN ({placeholders})
      AND neutral_value IS NOT NULL
    ORDER BY trade_date, code
    """
    params = [start_date, end_date] + factor_names
    df = pd.read_sql(sql, conn, params=params)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    logger.info(f"因子数据({', '.join(factor_names)}): {len(df)}行, "
                f"{df['trade_date'].nunique()}天")
    return df


def load_price_data(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载复权收盘价。"""
    sql = """
    WITH latest_adj AS (
        SELECT DISTINCT ON (code)
            code, adj_factor AS latest_adj
        FROM klines_daily
        ORDER BY code, trade_date DESC
    )
    SELECT
        k.trade_date, k.code,
        k.close * k.adj_factor / la.latest_adj AS adj_close
    FROM klines_daily k
    JOIN latest_adj la ON k.code = la.code
    WHERE k.trade_date BETWEEN %s AND %s
      AND k.volume > 0
    ORDER BY k.trade_date, k.code
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    logger.info(f"行情数据: {len(df)}行, {df['trade_date'].nunique()}天, "
                f"{df['code'].nunique()}股")
    return df


def load_trade_dates(conn, start_date: date, end_date: date) -> list[date]:
    sql = """
    SELECT DISTINCT trade_date FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
    ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    return [d.date() if hasattr(d, "date") else d for d in df["trade_date"]]


def load_industry(conn) -> pd.Series:
    """加载行业分类(code -> industry_sw1)。"""
    sql = "SELECT code, industry_sw1 FROM symbols WHERE industry_sw1 IS NOT NULL AND industry_sw1 != ''"
    df = pd.read_sql(sql, conn)
    return pd.Series(df["industry_sw1"].values, index=df["code"].values)


# ==============================================================
# vwap_bias_1d / rsrs_raw_18 即时计算 + 中性化
# ==============================================================

def compute_vwap_bias_all_dates(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """计算所有日期的vwap_bias_1d。

    vwap_bias_1d = (close - VWAP) / VWAP
    VWAP = amount * 10 / volume  (千元*10/手 = 元/股)
    使用未复权价格。

    Returns:
        DataFrame [trade_date, code, raw_value]
    """
    sql = """
    SELECT trade_date, code, close, amount, volume
    FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
      AND volume > 0 AND amount > 0
    ORDER BY trade_date, code
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    vwap = df["amount"].astype(float) * 10.0 / df["volume"].astype(float)
    close = df["close"].astype(float)
    df["raw_value"] = ((close - vwap) / vwap).clip(-1.0, 1.0)

    logger.info(f"vwap_bias_1d计算完成: {len(df)}行")
    return df[["trade_date", "code", "raw_value"]].copy()


def compute_rsrs_all_dates(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """计算所有日期的rsrs_raw_18。

    rsrs_raw_18 = Cov(high, low, 18) / Var(low, 18) （OLS斜率beta）
    使用未复权价格。

    Returns:
        DataFrame [trade_date, code, raw_value]
    """
    # 需要往前多取18天数据
    lookback_start = start_date - timedelta(days=40)
    sql = """
    SELECT trade_date, code, high, low
    FROM klines_daily
    WHERE trade_date BETWEEN %s AND %s
      AND volume > 0
    ORDER BY code, trade_date
    """
    df = pd.read_sql(sql, conn, params=(lookback_start, end_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)

    logger.info(f"RSRS原始数据: {len(df)}行, 开始滚动计算...")
    t0 = time.time()

    results = []
    for code, grp in df.groupby("code"):
        grp = grp.sort_values("trade_date").reset_index(drop=True)
        highs = grp["high"].values
        lows = grp["low"].values
        dates = grp["trade_date"].values

        for i in range(len(grp)):
            if dates[i] < np.datetime64(start_date):
                continue
            # 取最近18天
            start_idx = max(0, i - 17)
            h = highs[start_idx:i + 1]
            l = lows[start_idx:i + 1]
            if len(h) < 9:  # min_periods
                continue
            var_low = np.var(l, ddof=0)
            if var_low < 1e-10:
                continue
            cov_hl = np.cov(h, l, ddof=0)[0, 1]
            rsrs = cov_hl / var_low
            results.append({
                "trade_date": dates[i] if isinstance(dates[i], date) else pd.Timestamp(dates[i]).date(),
                "code": code,
                "raw_value": rsrs,
            })

    out = pd.DataFrame(results)
    logger.info(f"rsrs_raw_18计算完成: {len(out)}行, 耗时{time.time() - t0:.1f}s")
    return out


def neutralize_cross_section(
    raw_series: pd.Series,
    ln_mcap: pd.Series,
    industry: pd.Series,
) -> pd.Series:
    """市值+行业中性化（OLS残差），然后zscore标准化。"""
    common = raw_series.index.intersection(ln_mcap.index).intersection(industry.index)
    if len(common) < 30:
        return pd.Series(dtype=float)

    raw = raw_series.loc[common]
    mcap = ln_mcap.loc[common]
    ind = industry.loc[common]

    # MAD去极值
    med = raw.median()
    mad = (raw - med).abs().median()
    if mad > 1e-10:
        raw = raw.clip(med - 5 * 1.4826 * mad, med + 5 * 1.4826 * mad)

    # 缺失值填充（中位数）
    raw = raw.fillna(raw.median())

    # 中性化：OLS回归掉ln_mcap + 行业dummy
    dummies = pd.get_dummies(ind, drop_first=True, dtype=float)
    X = pd.concat([mcap.rename("ln_mcap"), dummies], axis=1).loc[common]
    X = X.fillna(0)
    X_arr = X.values.astype(np.float64)
    y_arr = raw.values.astype(np.float64)

    # 加截距
    ones = np.ones((len(X_arr), 1))
    X_full = np.hstack([ones, X_arr])

    try:
        beta, _, _, _ = np.linalg.lstsq(X_full, y_arr, rcond=None)
        resid = y_arr - X_full @ beta
    except np.linalg.LinAlgError:
        resid = y_arr

    # zscore标准化
    std = np.std(resid, ddof=1)
    if std > 1e-10:
        resid = (resid - np.mean(resid)) / std

    return pd.Series(resid, index=common, dtype=float)


def compute_new_factors_neutralized(
    conn, start_date: date, end_date: date,
    factors_in_db: dict[str, bool],
) -> pd.DataFrame:
    """计算不在DB中的新因子，做中性化，返回与factor_values相同格式。

    Returns:
        DataFrame [trade_date, code, factor_name, neutral_value]
    """
    need_vwap = not factors_in_db.get("vwap_bias_1d", False)
    need_rsrs = not factors_in_db.get("rsrs_raw_18", False)

    if not need_vwap and not need_rsrs:
        return pd.DataFrame(columns=["trade_date", "code", "factor_name", "neutral_value"])

    raw_dfs = {}
    if need_vwap:
        logger.info("vwap_bias_1d不在DB，开始即时计算...")
        raw_dfs["vwap_bias_1d"] = compute_vwap_bias_all_dates(conn, start_date, end_date)
    if need_rsrs:
        logger.info("rsrs_raw_18不在DB，开始即时计算...")
        raw_dfs["rsrs_raw_18"] = compute_rsrs_all_dates(conn, start_date, end_date)

    # 中性化
    logger.info("加载中性化所需数据（ln_mcap + 行业）...")
    all_results = []

    for factor_name, raw_df in raw_dfs.items():
        logger.info(f"中性化 {factor_name}...")
        all_dates = sorted(raw_df["trade_date"].unique())

        for td in all_dates:
            day = raw_df[raw_df["trade_date"] == td]
            raw_series = pd.Series(
                day["raw_value"].values, index=day["code"].values, dtype=float
            )
            if len(raw_series) < 50:
                continue

            # 加载当日ln_mcap和行业
            ln_mcap, ind = _load_neutralize_data_for_date(conn, td)
            if len(ln_mcap) < 50:
                continue

            neutral = neutralize_cross_section(raw_series, ln_mcap, ind)
            if neutral.empty:
                continue

            for code, val in neutral.items():
                all_results.append({
                    "trade_date": td,
                    "code": code,
                    "factor_name": factor_name,
                    "neutral_value": val,
                })

    out = pd.DataFrame(all_results)
    logger.info(f"新因子中性化完成: {len(out)}行")
    return out


# 缓存中性化数据（避免重复查询）
_neutralize_cache: dict[date, tuple[pd.Series, pd.Series]] = {}


def _load_neutralize_data_for_date(conn, trade_date: date) -> tuple[pd.Series, pd.Series]:
    """加载截面ln_mcap和行业分类（带缓存）。"""
    if trade_date in _neutralize_cache:
        return _neutralize_cache[trade_date]

    sql = """
    SELECT d.code,
           LN(b.total_mv * 10000) AS ln_mcap,
           s.industry_sw1 AS industry
    FROM klines_daily d
    JOIN daily_basic b ON d.code = b.code AND d.trade_date = b.trade_date
    JOIN symbols s ON d.code = s.code
    WHERE d.trade_date = %s
      AND b.total_mv IS NOT NULL AND b.total_mv > 0
      AND s.industry_sw1 IS NOT NULL AND s.industry_sw1 != ''
      AND d.volume > 0
    """
    df = pd.read_sql(sql, conn, params=(trade_date,))
    ln_mcap = pd.Series(df["ln_mcap"].values, index=df["code"].values, dtype=float)
    industry = pd.Series(df["industry"].values, index=df["code"].values)
    _neutralize_cache[trade_date] = (ln_mcap, industry)
    return ln_mcap, industry


# ==============================================================
# 信号合成（与signal_engine.py SignalComposer.compose一致）
# ==============================================================

def compose_signals(
    factor_df: pd.DataFrame,
    factor_names: list[str],
    directions: dict[str, int],
    industry: pd.Series,
    top_n: int = TOP_N,
    industry_cap: float = 0.25,
) -> pd.DataFrame:
    """合成信号并选股。

    与signal_engine.py一致：
    1. pivot成宽表 (code x factor_name) 的 neutral_value
    2. 按FACTOR_DIRECTION做sign-flip
    3. 等权加和
    4. 排名Top-N (含行业约束)

    Returns:
        DataFrame [trade_date, code, score]
    """
    all_dates = sorted(factor_df["trade_date"].unique())
    results = []

    for td in all_dates:
        day = factor_df[factor_df["trade_date"] == td]

        pivot = day.pivot_table(
            index="code", columns="factor_name",
            values="neutral_value", aggfunc="first",
        )

        available = [f for f in factor_names if f in pivot.columns]
        if len(available) < len(factor_names) * 0.5:
            continue  # 因子覆盖率太低跳过

        pivot = pivot[available].copy()

        # sign-flip
        for fname in available:
            direction = directions.get(fname, 1)
            if direction == -1:
                pivot[fname] = -pivot[fname]

        # 等权求和
        weight = 1.0 / len(available)
        composite = sum(pivot[f] * weight for f in available)
        composite = composite.dropna()

        if len(composite) < top_n:
            continue

        # 排名 + 行业约束
        composite = composite.sort_values(ascending=False)
        max_per_ind = int(top_n * industry_cap)
        selected = []
        ind_count = {}

        for code in composite.index:
            if len(selected) >= top_n:
                break
            ind = industry.get(code, "其他")
            cnt = ind_count.get(ind, 0)
            if cnt >= max_per_ind:
                continue
            selected.append(code)
            ind_count[ind] = cnt + 1

        for code in selected:
            results.append({
                "trade_date": td,
                "code": code,
                "score": float(composite[code]),
            })

    out = pd.DataFrame(results)
    logger.info(f"信号合成({len(factor_names)}因子): {out['trade_date'].nunique()}天, "
                f"平均每天{len(out) / max(out['trade_date'].nunique(), 1):.0f}股")
    return out


# ==============================================================
# 月度调仓组合构建
# ==============================================================

def get_monthly_rebalance_dates(trade_dates: list[date]) -> list[date]:
    """每月最后一个交易日作为信号日。"""
    date_series = pd.Series(trade_dates)
    months = date_series.groupby(
        date_series.apply(lambda d: (d.year, d.month))
    ).last()
    return sorted(months.tolist())


def build_portfolio_returns(
    signal_df: pd.DataFrame,
    returns_pivot: pd.DataFrame,
    trade_dates: list[date],
    top_n: int = TOP_N,
    cost: float = COST_ONE_WAY,
) -> pd.DataFrame:
    """构建月度调仓Top-N等权组合日频收益。

    信号日 = 月末最后一个交易日
    执行日 = 下月第一个交易日（T+1）

    Returns:
        DataFrame [trade_date, portfolio_return]
    """
    rebal_dates = get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebal_dates if d in signal_dates]

    if not available_rebal:
        logger.warning("无可用调仓日!")
        return pd.DataFrame(columns=["trade_date", "portfolio_return"])

    logger.info(f"调仓日: {len(available_rebal)}个 "
                f"({available_rebal[0]} ~ {available_rebal[-1]})")

    daily_returns = []
    prev_holdings = set()

    for i, rebal_date in enumerate(available_rebal):
        # 选Top-N
        day_signals = signal_df[signal_df["trade_date"] == rebal_date].copy()
        day_signals = day_signals.sort_values("score", ascending=False)
        top_stocks = day_signals.head(top_n)["code"].tolist()

        if not top_stocks:
            continue

        rebal_idx = trade_dates.index(rebal_date) if rebal_date in trade_dates else None
        if rebal_idx is None:
            continue

        # 执行日 = rebal_date之后的下一个交易日
        hold_start_idx = rebal_idx + 1
        if hold_start_idx >= len(trade_dates):
            continue

        if i + 1 < len(available_rebal):
            next_rebal = available_rebal[i + 1]
            next_rebal_idx = trade_dates.index(next_rebal) if next_rebal in trade_dates else len(trade_dates) - 1
            hold_end_idx = next_rebal_idx
        else:
            hold_end_idx = len(trade_dates)

        # 换手成本
        new_holdings = set(top_stocks)
        turnover = (len(new_holdings.symmetric_difference(prev_holdings)) / (2 * top_n)
                    if prev_holdings else 1.0)
        rebal_cost = turnover * cost * 2  # 双边

        for day_idx in range(hold_start_idx, hold_end_idx):
            td = trade_dates[day_idx]
            if td not in returns_pivot.index:
                continue

            day_ret = returns_pivot.loc[td]
            stock_rets = []
            for s in top_stocks:
                if s in day_ret.index and not np.isnan(day_ret[s]):
                    stock_rets.append(day_ret[s])
            port_ret = np.mean(stock_rets) if stock_rets else 0.0

            if day_idx == hold_start_idx:
                port_ret -= rebal_cost

            daily_returns.append({"trade_date": td, "portfolio_return": port_ret})

        prev_holdings = new_holdings

    return pd.DataFrame(daily_returns)


# ==============================================================
# 绩效指标
# ==============================================================

def calc_metrics(daily_rets: np.ndarray, annual_factor: float = 252.0) -> dict:
    if len(daily_rets) == 0:
        return {}

    total_ret = np.prod(1 + daily_rets) - 1
    n_years = len(daily_rets) / annual_factor
    ann_ret = (1 + total_ret) ** (1.0 / n_years) - 1 if n_years > 0 else 0

    ann_sharpe = (np.mean(daily_rets) / np.std(daily_rets, ddof=1) * np.sqrt(annual_factor)
                  if np.std(daily_rets, ddof=1) > 0 else 0)

    cum = np.cumprod(1 + daily_rets)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum / running_max - 1
    mdd = float(np.min(drawdowns))

    calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-10 else 0

    downside = daily_rets[daily_rets < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 1e-10
    sortino = np.mean(daily_rets) / downside_std * np.sqrt(annual_factor)

    losing_streak = 0
    max_losing_streak = 0
    for r in daily_rets:
        if r < 0:
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
        else:
            losing_streak = 0

    return {
        "ann_return": ann_ret,
        "ann_sharpe": ann_sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "total_return": total_ret,
        "n_days": len(daily_rets),
        "max_losing_streak": max_losing_streak,
    }


# ==============================================================
# Paired Block Bootstrap
# ==============================================================

def paired_block_bootstrap(
    new_rets: np.ndarray,
    base_rets: np.ndarray,
    n_boot: int = BOOTSTRAP_N,
    block_size: int = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> dict:
    """Paired block bootstrap: 7因子 vs 5因子。

    H0: 7因子 Sharpe <= 5因子 Sharpe
    """
    rng = np.random.RandomState(seed)
    T = len(new_rets)
    assert len(base_rets) == T, f"长度不匹配: {T} vs {len(base_rets)}"

    d = new_rets - base_rets
    orig_diff_sharpe = (np.mean(d) / np.std(d, ddof=1) * np.sqrt(252)
                        if np.std(d, ddof=1) > 0 else 0)

    n_blocks = int(np.ceil(T / block_size))
    boot_sharpes = np.zeros(n_boot)

    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        d_boot = d[indices]
        std_boot = np.std(d_boot, ddof=1)
        if std_boot > 1e-12:
            boot_sharpes[b] = np.mean(d_boot) / std_boot * np.sqrt(252)

    p_value = np.mean(boot_sharpes <= 0)
    ci_lo = np.percentile(boot_sharpes, 2.5)
    ci_hi = np.percentile(boot_sharpes, 97.5)

    return {
        "orig_diff_sharpe": orig_diff_sharpe,
        "p_value": p_value,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "boot_mean": np.mean(boot_sharpes),
        "boot_std": np.std(boot_sharpes),
    }


def bootstrap_sharpe_ci(
    daily_rets: np.ndarray,
    n_boot: int = 10000,
    block_size: int = BOOTSTRAP_BLOCK,
    seed: int = SEED,
) -> tuple[float, float]:
    """单策略 Bootstrap Sharpe 95% CI。"""
    rng = np.random.RandomState(seed)
    T = len(daily_rets)
    n_blocks = int(np.ceil(T / block_size))
    sharpes = np.zeros(n_boot)

    for b in range(n_boot):
        starts = rng.randint(0, T - block_size + 1, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in starts])[:T]
        boot = daily_rets[indices]
        std_b = np.std(boot, ddof=1)
        if std_b > 1e-12:
            sharpes[b] = np.mean(boot) / std_b * np.sqrt(252)

    return float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))


def compute_annual_turnover(
    signal_df: pd.DataFrame,
    trade_dates: list[date],
    top_n: int = TOP_N,
) -> float:
    rebal_dates = get_monthly_rebalance_dates(trade_dates)
    signal_dates = set(signal_df["trade_date"].unique())
    available_rebal = [d for d in rebal_dates if d in signal_dates]

    turnovers = []
    prev_holdings = None

    for rebal_date in available_rebal:
        day_signals = signal_df[signal_df["trade_date"] == rebal_date].copy()
        day_signals = day_signals.sort_values("score", ascending=False)
        current = set(day_signals.head(top_n)["code"].tolist())

        if prev_holdings is not None and len(current) > 0:
            changed = len(current.symmetric_difference(prev_holdings))
            turnover = changed / (2 * top_n)
            turnovers.append(turnover)
        prev_holdings = current

    return np.mean(turnovers) * 12 if turnovers else 0.0


# ==============================================================
# Main
# ==============================================================

def main():
    t0 = time.time()

    print("=" * 80)
    print("  7因子等权组合 vs 5因子基线 对比评估")
    print("  7因子 = 5基线 + vwap_bias_1d + rsrs_raw_18")
    print("=" * 80)

    conn = get_conn()
    try:
        # ── Step 1: 检查新因子是否已在DB ──
        logger.info("Step 1: 检查因子可用性...")
        factors_in_db = check_factors_in_db(conn)
        for fn, exists in factors_in_db.items():
            logger.info(f"  {fn}: {'在DB中' if exists else '需要即时计算'}")

        # ── Step 2: 加载5基线因子 ──
        logger.info("Step 2: 加载基线因子neutral_value...")
        baseline_fv = load_factor_values(conn, BASELINE_FACTORS, BT_START, BT_END)

        # ── Step 3: 加载或计算新因子 ──
        logger.info("Step 3: 加载/计算新因子...")
        # 如果在DB中，直接加载
        db_new_factors = []
        if factors_in_db["vwap_bias_1d"]:
            db_new_factors.append("vwap_bias_1d")
        if factors_in_db["rsrs_raw_18"]:
            db_new_factors.append("rsrs_raw_18")

        new_factor_df = pd.DataFrame(
            columns=["trade_date", "code", "factor_name", "neutral_value"]
        )
        if db_new_factors:
            new_factor_df = load_factor_values(conn, db_new_factors, BT_START, BT_END)

        # 计算不在DB中的因子
        computed_df = compute_new_factors_neutralized(conn, BT_START, BT_END, factors_in_db)
        if not computed_df.empty:
            new_factor_df = pd.concat([new_factor_df, computed_df], ignore_index=True)

        # 合并全部因子数据
        all_factor_df = pd.concat([baseline_fv, new_factor_df], ignore_index=True)
        logger.info(f"全部因子数据: {len(all_factor_df)}行, "
                    f"因子={all_factor_df['factor_name'].unique().tolist()}")

        # ── Step 4: 加载行情、交易日、行业 ──
        logger.info("Step 4: 加载行情数据...")
        price_start = BT_START - timedelta(days=10)
        price_end = BT_END + timedelta(days=40)
        price_df = load_price_data(conn, price_start, price_end)
        trade_dates = load_trade_dates(conn, price_start, price_end)
        bt_trade_dates = [d for d in trade_dates if BT_START <= d <= BT_END]
        industry = load_industry(conn)

        returns_pivot = price_df.pivot(
            index="trade_date", columns="code", values="adj_close"
        ).pct_change().iloc[1:]

    finally:
        conn.close()

    # ── Step 5: 合成信号 ──
    logger.info("Step 5: 合成信号...")

    # 5因子基线
    baseline_signals = compose_signals(
        baseline_fv, BASELINE_FACTORS, FACTOR_DIRECTIONS,
        industry, TOP_N, 0.25,
    )

    # 7因子
    seven_signals = compose_signals(
        all_factor_df, SEVEN_FACTORS, FACTOR_DIRECTIONS,
        industry, TOP_N, 0.25,
    )

    # ── Step 6: 构建组合收益 ──
    logger.info("Step 6: 构建组合收益...")
    base_port = build_portfolio_returns(
        baseline_signals, returns_pivot, bt_trade_dates,
        top_n=TOP_N, cost=COST_ONE_WAY,
    )
    seven_port = build_portfolio_returns(
        seven_signals, returns_pivot, bt_trade_dates,
        top_n=TOP_N, cost=COST_ONE_WAY,
    )

    # ── Step 7: 对齐日期 ──
    logger.info("Step 7: 对齐日期...")
    base_port.set_index("trade_date", inplace=True)
    seven_port.set_index("trade_date", inplace=True)

    common_dates = base_port.index.intersection(seven_port.index).sort_values()
    logger.info(f"对齐后: {len(common_dates)}天 ({common_dates[0]} ~ {common_dates[-1]})")

    base_rets = base_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)
    seven_rets = seven_port.loc[common_dates, "portfolio_return"].values.astype(np.float64)

    # ── Step 8: 绩效指标 ──
    logger.info("Step 8: 计算绩效指标...")
    base_metrics = calc_metrics(base_rets)
    seven_metrics = calc_metrics(seven_rets)

    base_ci = bootstrap_sharpe_ci(base_rets, seed=SEED)
    seven_ci = bootstrap_sharpe_ci(seven_rets, seed=SEED + 1)

    base_turnover = compute_annual_turnover(baseline_signals, bt_trade_dates, TOP_N)
    seven_turnover = compute_annual_turnover(seven_signals, bt_trade_dates, TOP_N)

    # ── Step 9: Paired Bootstrap ──
    logger.info("Step 9: Paired Block Bootstrap (10000次)...")
    boot = paired_block_bootstrap(seven_rets, base_rets)

    # ── Step 10: 年度分解 ──
    logger.info("Step 10: 年度分解...")
    yearly_base = {}
    yearly_seven = {}
    for year in sorted(set(d.year for d in common_dates)):
        mask = np.array([d.year == year for d in common_dates])
        if mask.sum() > 0:
            yearly_base[year] = calc_metrics(base_rets[mask])
            yearly_seven[year] = calc_metrics(seven_rets[mask])

    # ── Step 11: 成本敏感性 ──
    logger.info("Step 11: 成本敏感性分析...")
    cost_multipliers = [0.5, 1.0, 1.5, 2.0]
    cost_results = {}
    for mult in cost_multipliers:
        cost = COST_ONE_WAY * mult
        bp = build_portfolio_returns(
            baseline_signals, returns_pivot, bt_trade_dates,
            top_n=TOP_N, cost=cost,
        )
        sp = build_portfolio_returns(
            seven_signals, returns_pivot, bt_trade_dates,
            top_n=TOP_N, cost=cost,
        )
        bp.set_index("trade_date", inplace=True)
        sp.set_index("trade_date", inplace=True)
        cd = bp.index.intersection(sp.index).sort_values()
        br = bp.loc[cd, "portfolio_return"].values.astype(np.float64)
        sr = sp.loc[cd, "portfolio_return"].values.astype(np.float64)
        cost_results[mult] = {
            "base": calc_metrics(br),
            "seven": calc_metrics(sr),
        }

    # ==============================================================
    # 输出报告
    # ==============================================================
    elapsed = time.time() - t0

    print("\n")
    print("=" * 80)
    print("  7因子等权 vs 5因子基线 评估报告")
    print(f"  评估期间: {common_dates[0]} ~ {common_dates[-1]} ({len(common_dates)} 交易日)")
    print(f"  Top-{TOP_N} 等权 月度调仓 单边成本{COST_ONE_WAY * 1000:.1f}bps")
    print("  行业约束: 单行业<=25% (简化版: 无整手约束)")
    print("=" * 80)

    # --- 核心指标对比 ---
    print(f"\n{'':=^80}")
    print(f" {'核心指标对比':^74} ")
    print(f"{'':=^80}")
    print(f"{'指标':<25} {'5因子基线':>20} {'7因子等权':>20}")
    print("-" * 65)
    print(f"{'年化收益率':<25} {base_metrics['ann_return']:>19.2%} {seven_metrics['ann_return']:>19.2%}")
    print(f"{'年化Sharpe':<25} {base_metrics['ann_sharpe']:>20.3f} {seven_metrics['ann_sharpe']:>20.3f}")
    print(f"{'最大回撤(MDD)':<25} {base_metrics['mdd']:>19.2%} {seven_metrics['mdd']:>19.2%}")
    print(f"{'Calmar Ratio':<25} {base_metrics['calmar']:>20.3f} {seven_metrics['calmar']:>20.3f}")
    print(f"{'Sortino Ratio':<25} {base_metrics['sortino']:>20.3f} {seven_metrics['sortino']:>20.3f}")
    print(f"{'总收益率':<25} {base_metrics['total_return']:>19.2%} {seven_metrics['total_return']:>19.2%}")
    print(f"{'年化换手率':<25} {base_turnover * 100:>19.1f}% {seven_turnover * 100:>19.1f}%")
    print(f"{'最大连续亏损天数':<25} {base_metrics['max_losing_streak']:>20d} {seven_metrics['max_losing_streak']:>20d}")

    # --- Bootstrap Sharpe CI ---
    print(f"\n{'':=^80}")
    print(f" {'Bootstrap Sharpe 95% CI':^74} ")
    print(f"{'':=^80}")
    print(f"5因子基线:  Sharpe = {base_metrics['ann_sharpe']:.3f}  "
          f"[{base_ci[0]:.3f}, {base_ci[1]:.3f}]")
    print(f"7因子等权:  Sharpe = {seven_metrics['ann_sharpe']:.3f}  "
          f"[{seven_ci[0]:.3f}, {seven_ci[1]:.3f}]")

    # --- Paired Bootstrap ---
    print(f"\n{'':=^80}")
    print(f" {'Paired Block Bootstrap (block=20, n=10000)':^74} ")
    print(f"{'':=^80}")
    print(f"差异Sharpe (7F - 5F):     {boot['orig_diff_sharpe']:.3f}")
    print(f"Bootstrap 95% CI:         [{boot['ci_lo']:.3f}, {boot['ci_hi']:.3f}]")
    print(f"p-value (H0: 7F <= 5F):   {boot['p_value']:.4f}")
    print(f"Bootstrap mean/std:        {boot['boot_mean']:.3f} / {boot['boot_std']:.3f}")

    sig = "SIGNIFICANT (p < 0.05)" if boot["p_value"] < 0.05 else "NOT SIGNIFICANT (p >= 0.05)"
    print(f"\n>>> 结论: {sig}")

    # --- 年度分解 ---
    print(f"\n{'':=^80}")
    print(f" {'年度分解':^74} ")
    print(f"{'':=^80}")
    print(f"{'年度':<8} {'5F Sharpe':>12} {'7F Sharpe':>12} {'5F 收益':>12} {'7F 收益':>12} {'5F MDD':>12} {'7F MDD':>12}")
    print("-" * 80)
    for year in sorted(yearly_base.keys()):
        bm = yearly_base[year]
        sm = yearly_seven[year]
        worst_mark_b = " <--" if bm["ann_sharpe"] == min(m["ann_sharpe"] for m in yearly_base.values()) else ""
        worst_mark_s = " <--" if sm["ann_sharpe"] == min(m["ann_sharpe"] for m in yearly_seven.values()) else ""
        print(f"{year:<8} {bm['ann_sharpe']:>12.3f} {sm['ann_sharpe']:>12.3f} "
              f"{bm['ann_return']:>11.2%} {sm['ann_return']:>11.2%} "
              f"{bm['mdd']:>11.2%} {sm['mdd']:>11.2%}"
              f"{worst_mark_b}{worst_mark_s}")

    # --- 成本敏感性 ---
    print(f"\n{'':=^80}")
    print(f" {'成本敏感性分析':^74} ")
    print(f"{'':=^80}")
    print(f"{'成本倍数':<12} {'5F Sharpe':>12} {'7F Sharpe':>12} {'5F 收益':>12} {'7F 收益':>12} {'5F MDD':>12} {'7F MDD':>12}")
    print("-" * 80)
    for mult in cost_multipliers:
        bm = cost_results[mult]["base"]
        sm = cost_results[mult]["seven"]
        print(f"{mult:.1f}x{'':<8} {bm['ann_sharpe']:>12.3f} {sm['ann_sharpe']:>12.3f} "
              f"{bm['ann_return']:>11.2%} {sm['ann_return']:>11.2%} "
              f"{bm['mdd']:>11.2%} {sm['mdd']:>11.2%}")

    # --- 判定建议 ---
    print(f"\n{'':=^80}")
    print(f" {'判定建议':^74} ")
    print(f"{'':=^80}")
    sharpe_diff = seven_metrics["ann_sharpe"] - base_metrics["ann_sharpe"]
    mdd_diff = seven_metrics["mdd"] - base_metrics["mdd"]  # mdd is negative, more negative = worse

    if boot["p_value"] < 0.05 and sharpe_diff > 0:
        verdict = "JUSTIFIED - 7因子显著优于5因子(p<0.05)"
    elif sharpe_diff > 0 and boot["p_value"] < 0.10:
        verdict = "MARGINAL - 7因子略优但不显著(0.05<=p<0.10)"
    elif sharpe_diff > 0:
        verdict = "NOT JUSTIFIED - 增量不显著(p>=0.10)"
    else:
        verdict = "NOT JUSTIFIED - 7因子表现不如5因子"

    print(f"Sharpe差异: {sharpe_diff:+.3f}")
    print(f"MDD变化:    {mdd_diff:+.2%} ({'更差' if mdd_diff < 0 else '改善'})")
    print(f"p-value:    {boot['p_value']:.4f}")
    print(f"判定:       {verdict}")

    # 参考铁律: 等权因子数上限5-6因子局部最优
    print("\n注意: CLAUDE.md技术决策表记载'5-6因子局部最优,更多反而差'(Sprint 1.3b)")
    print("      7因子结果需要与该历史经验对比。")

    print(f"\n耗时: {elapsed:.1f}s")
    print("=" * 80)


if __name__ == "__main__":
    main()
