"""Alpha158因子库 — 从Qlib Alpha158翻译的pandas实现。

来源: https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py
结构: 9 KBAR + 4 PRICE + 145 ROLLING(29算子×5窗口) = 158因子

用法:
    from engines.alpha158_factors import compute_all_alpha158
    result_df = compute_all_alpha158(price_df)
    # price_df需要: code, trade_date, open, high, low, close, volume, amount
    # result_df: code, trade_date, factor_name, value

注意:
- 所有因子按股票分组(groupby code)计算时序特征
- vwap用 amount/volume 近似
- rolling计算前min_periods=窗口大小（避免不完整窗口）
- Slope/Rsquare/Resi用numpy polyfit近似
"""

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

WINDOWS = [5, 10, 20, 30, 60]


def _vwap(df: pd.DataFrame) -> pd.Series:
    """近似VWAP = amount / volume。"""
    vol = df["volume"].replace(0, np.nan)
    return df["amount"] / vol


def _slope(s: pd.Series, d: int) -> pd.Series:
    """滚动线性回归斜率。"""
    def _fit(x):
        if len(x) < d or x.isna().any():
            return np.nan
        y = x.values
        t = np.arange(len(y), dtype=float)
        coeffs = np.polyfit(t, y, 1)
        return coeffs[0]
    return s.rolling(d, min_periods=d).apply(_fit, raw=False)


def _rsquare(s: pd.Series, d: int) -> pd.Series:
    """滚动R²。"""
    def _fit(x):
        if len(x) < d or x.isna().any():
            return np.nan
        y = x.values
        t = np.arange(len(y), dtype=float)
        coeffs = np.polyfit(t, y, 1)
        pred = np.polyval(coeffs, t)
        ss_res = np.sum((y - pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        return 1 - ss_res / (ss_tot + 1e-12)
    return s.rolling(d, min_periods=d).apply(_fit, raw=False)


def _resi(s: pd.Series, d: int) -> pd.Series:
    """滚动回归残差（最后一个点）。"""
    def _fit(x):
        if len(x) < d or x.isna().any():
            return np.nan
        y = x.values
        t = np.arange(len(y), dtype=float)
        coeffs = np.polyfit(t, y, 1)
        return y[-1] - np.polyval(coeffs, t[-1])
    return s.rolling(d, min_periods=d).apply(_fit, raw=False)


def _idxmax(s: pd.Series, d: int) -> pd.Series:
    """滚动窗口内最大值距今天数。"""
    return s.rolling(d, min_periods=d).apply(lambda x: d - 1 - np.argmax(x), raw=True)


def _idxmin(s: pd.Series, d: int) -> pd.Series:
    """滚动窗口内最小值距今天数。"""
    return s.rolling(d, min_periods=d).apply(lambda x: d - 1 - np.argmin(x), raw=True)


def _ts_rank(s: pd.Series, d: int) -> pd.Series:
    """时序百分位排名。"""
    def _rank_pct(x):
        if len(x) < d:
            return np.nan
        return (x.values < x.values[-1]).sum() / (d - 1) if d > 1 else 0.5
    return s.rolling(d, min_periods=d).apply(_rank_pct, raw=False)


# ═══════════════════════════════════════════════════════════
# KBAR因子 (9个)
# ═══════════════════════════════════════════════════════════

def compute_kbar(df: pd.DataFrame) -> dict[str, pd.Series]:
    """K线形态因子。"""
    o, h, lo, c = df["open"], df["high"], df["low"], df["close"]
    hl = h - lo + 1e-12
    gt = pd.concat([o, c], axis=1).max(axis=1)  # Greater(open, close)
    lt = pd.concat([o, c], axis=1).min(axis=1)   # Less(open, close)
    return {
        "KMID": (c - o) / o,
        "KLEN": (h - lo) / o,
        "KMID2": (c - o) / hl,
        "KUP": (h - gt) / o,
        "KUP2": (h - gt) / hl,
        "KLOW": (lt - lo) / o,
        "KLOW2": (lt - lo) / hl,
        "KSFT": (2 * c - h - lo) / o,
        "KSFT2": (2 * c - h - lo) / hl,
    }


# ═══════════════════════════════════════════════════════════
# PRICE因子 (4个)
# ═══════════════════════════════════════════════════════════

def compute_price(df: pd.DataFrame) -> dict[str, pd.Series]:
    """价格归一化因子。"""
    c = df["close"]
    return {
        "OPEN0": df["open"] / c,
        "HIGH0": df["high"] / c,
        "LOW0": df["low"] / c,
        "VWAP0": _vwap(df) / c,
    }


# ═══════════════════════════════════════════════════════════
# ROLLING因子 (29算子 × 5窗口 = 145个)
# ═══════════════════════════════════════════════════════════

def compute_rolling(df: pd.DataFrame) -> dict[str, pd.Series]:
    """全部滚动因子，按股票分组计算。"""
    c = df["close"]
    h = df["high"]
    lo = df["low"]
    v = df["volume"]
    eps = 1e-12

    # 预计算常用中间量
    ret = c / c.shift(1)  # 日收益比
    log_v = np.log(v + 1)
    abs_ret = (ret - 1).abs()
    c_diff = c - c.shift(1)
    v_diff = v - v.shift(1)

    factors = {}

    for d in WINDOWS:
        ds = str(d)

        # ROC
        factors[f"ROC{ds}"] = c.shift(d) / c

        # MA
        factors[f"MA{ds}"] = c.rolling(d, min_periods=d).mean() / c

        # STD
        factors[f"STD{ds}"] = c.rolling(d, min_periods=d).std() / c

        # BETA (slope)
        factors[f"BETA{ds}"] = _slope(c, d) / c

        # RSQR
        factors[f"RSQR{ds}"] = _rsquare(c, d)

        # RESI
        factors[f"RESI{ds}"] = _resi(c, d) / c

        # MAX
        factors[f"MAX{ds}"] = h.rolling(d, min_periods=d).max() / c

        # MIN
        factors[f"MIN{ds}"] = lo.rolling(d, min_periods=d).min() / c

        # QTLU (80th percentile)
        factors[f"QTLU{ds}"] = c.rolling(d, min_periods=d).quantile(0.8) / c

        # QTLD (20th percentile)
        factors[f"QTLD{ds}"] = c.rolling(d, min_periods=d).quantile(0.2) / c

        # RANK (time-series percentile rank)
        factors[f"RANK{ds}"] = _ts_rank(c, d)

        # RSV (raw stochastic value)
        roll_min_lo = lo.rolling(d, min_periods=d).min()
        roll_max_hi = h.rolling(d, min_periods=d).max()
        factors[f"RSV{ds}"] = (c - roll_min_lo) / (roll_max_hi - roll_min_lo + eps)

        # IMAX, IMIN, IMXD
        factors[f"IMAX{ds}"] = _idxmax(h, d) / d
        factors[f"IMIN{ds}"] = _idxmin(lo, d) / d
        factors[f"IMXD{ds}"] = factors[f"IMAX{ds}"] - factors[f"IMIN{ds}"]

        # CORR (price-volume)
        factors[f"CORR{ds}"] = c.rolling(d, min_periods=d).corr(log_v)

        # CORD (return-volume change)
        log_v_ret = np.log(v / v.shift(1) + 1)
        factors[f"CORD{ds}"] = (ret - 1).rolling(d, min_periods=d).corr(log_v_ret)

        # CNTP, CNTN, CNTD
        up = (c > c.shift(1)).astype(float)
        dn = (c < c.shift(1)).astype(float)
        factors[f"CNTP{ds}"] = up.rolling(d, min_periods=d).mean()
        factors[f"CNTN{ds}"] = dn.rolling(d, min_periods=d).mean()
        factors[f"CNTD{ds}"] = factors[f"CNTP{ds}"] - factors[f"CNTN{ds}"]

        # SUMP, SUMN, SUMD
        pos_chg = c_diff.clip(lower=0)
        neg_chg = (-c_diff).clip(lower=0)
        abs_chg_sum = c_diff.abs().rolling(d, min_periods=d).sum() + eps
        factors[f"SUMP{ds}"] = pos_chg.rolling(d, min_periods=d).sum() / abs_chg_sum
        factors[f"SUMN{ds}"] = neg_chg.rolling(d, min_periods=d).sum() / abs_chg_sum
        factors[f"SUMD{ds}"] = factors[f"SUMP{ds}"] - factors[f"SUMN{ds}"]

        # VMA, VSTD
        factors[f"VMA{ds}"] = v.rolling(d, min_periods=d).mean() / (v + eps)
        factors[f"VSTD{ds}"] = v.rolling(d, min_periods=d).std() / (v + eps)

        # WVMA
        wv = abs_ret * v
        factors[f"WVMA{ds}"] = wv.rolling(d, min_periods=d).std() / (wv.rolling(d, min_periods=d).mean() + eps)

        # VSUMP, VSUMN, VSUMD
        pos_v = v_diff.clip(lower=0)
        neg_v = (-v_diff).clip(lower=0)
        abs_v_sum = v_diff.abs().rolling(d, min_periods=d).sum() + eps
        factors[f"VSUMP{ds}"] = pos_v.rolling(d, min_periods=d).sum() / abs_v_sum
        factors[f"VSUMN{ds}"] = neg_v.rolling(d, min_periods=d).sum() / abs_v_sum
        factors[f"VSUMD{ds}"] = factors[f"VSUMP{ds}"] - factors[f"VSUMN{ds}"]

    return factors


# ═══════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════

def compute_all_alpha158(
    price_df: pd.DataFrame,
    skip_slow: bool = False,
) -> pd.DataFrame:
    """计算全部Alpha158因子。

    Args:
        price_df: 包含 code, trade_date, open, high, low, close, volume, amount 的DataFrame。
        skip_slow: 跳过计算慢的因子（Slope/Rsquare/Resi）。

    Returns:
        长表 DataFrame: code, trade_date, factor_name, value。
    """
    required = {"code", "trade_date", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(price_df.columns)
    if missing:
        raise ValueError(f"缺少字段: {missing}")

    logger.info("[Alpha158] 开始计算, %d只股票, %d行", price_df["code"].nunique(), len(price_df))

    all_results = []

    for code, gdf in price_df.groupby("code"):
        gdf = gdf.sort_values("trade_date").reset_index(drop=True)

        # KBAR
        kbar = compute_kbar(gdf)
        # PRICE
        price = compute_price(gdf)
        # ROLLING
        rolling = compute_rolling(gdf)

        # 合并
        all_factors = {**kbar, **price, **rolling}

        # 转为长表
        for fname, series in all_factors.items():
            vals = series.values
            dates = gdf["trade_date"].values
            mask = ~np.isnan(vals.astype(float))
            if mask.sum() == 0:
                continue
            sub = pd.DataFrame({
                "code": code,
                "trade_date": dates[mask],
                "factor_name": fname,
                "value": vals[mask],
            })
            all_results.append(sub)

    if not all_results:
        return pd.DataFrame(columns=["code", "trade_date", "factor_name", "value"])

    result = pd.concat(all_results, ignore_index=True)
    logger.info("[Alpha158] 计算完成: %d行, %d因子", len(result), result["factor_name"].nunique())
    return result


# 因子名称列表（用于批量IC计算）
def get_alpha158_names() -> list[str]:
    """返回全部158个因子名称。"""
    names = []
    # KBAR
    names.extend(["KMID", "KLEN", "KMID2", "KUP", "KUP2", "KLOW", "KLOW2", "KSFT", "KSFT2"])
    # PRICE
    names.extend(["OPEN0", "HIGH0", "LOW0", "VWAP0"])
    # ROLLING
    ops = [
        "ROC", "MA", "STD", "BETA", "RSQR", "RESI", "MAX", "MIN",
        "QTLU", "QTLD", "RANK", "RSV", "IMAX", "IMIN", "IMXD",
        "CORR", "CORD", "CNTP", "CNTN", "CNTD", "SUMP", "SUMN", "SUMD",
        "VMA", "VSTD", "WVMA", "VSUMP", "VSUMN", "VSUMD",
    ]
    for op in ops:
        for d in WINDOWS:
            names.append(f"{op}{d}")
    return names
