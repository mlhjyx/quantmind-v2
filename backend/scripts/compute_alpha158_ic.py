"""Alpha158因子批量IC计算脚本（内存优化版）。

策略: 一次加载全量价格数据(~400MB)，逐因子计算+IC，不累积因子数据。
每个因子的内存开销: ~50MB，计算完即释放。

用法:
    python scripts/compute_alpha158_ic.py
"""

import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.compute_factor_ic import get_conn

START_DATE = date(2021, 1, 1)
END_DATE = date(2025, 12, 31)
HORIZONS = [1, 5, 10, 20]
MIN_STOCKS = 30
WINDOWS = [5, 10, 20, 30, 60]
OUTPUT_DIR = PROJECT_ROOT / "models"


def load_all_prices(conn) -> pd.DataFrame:
    """加载全量价格数据（含universe过滤）。~400MB。"""
    logger.info("加载全量价格数据...")
    df = pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.volume, k.amount, k.adj_factor
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= k.trade_date - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000
           ORDER BY code, trade_date""",
        conn,
        params=(START_DATE, END_DATE),
    )
    logger.info("  加载完成: %d行, %d只股票", len(df), df["code"].nunique())
    return df


def compute_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    """计算前向收益pivot表。"""
    logger.info("计算前向收益...")
    adj = df[["code", "trade_date"]].copy()
    adj["adj_close"] = df["close"] * df["adj_factor"]
    pivot = adj.pivot(index="trade_date", columns="code", values="adj_close").sort_index()

    fwd_tables = {}
    for h in HORIZONS:
        fwd = (pivot.shift(-h) / pivot - 1)
        fwd_tables[h] = fwd

    logger.info("  前向收益计算完成")
    return fwd_tables


# ═══════════════════════════════════════════════════════════
# 逐因子计算器（向量化，不用groupby.apply）
# ═══════════════════════════════════════════════════════════

def _grouped_rolling(pivot: pd.DataFrame, func: str, d: int, **kwargs) -> pd.DataFrame:
    """对pivot表（trade_date×code）按列做rolling操作。"""
    r = pivot.rolling(d, min_periods=d)
    return getattr(r, func)(**kwargs)


def compute_single_factor(df: pd.DataFrame, factor_name: str) -> pd.DataFrame:
    """计算单个Alpha158因子（向量化，输出pivot格式 trade_date × code）。"""
    # 构建pivot表
    o = df.pivot(index="trade_date", columns="code", values="open").sort_index()
    h = df.pivot(index="trade_date", columns="code", values="high").sort_index()
    lo = df.pivot(index="trade_date", columns="code", values="low").sort_index()
    c = df.pivot(index="trade_date", columns="code", values="close").sort_index()
    v = df.pivot(index="trade_date", columns="code", values="volume").sort_index()
    amt = df.pivot(index="trade_date", columns="code", values="amount").sort_index()
    eps = 1e-12

    # KBAR
    if factor_name == "KMID": return (c - o) / o
    if factor_name == "KLEN": return (h - lo) / o
    if factor_name == "KMID2": return (c - o) / (h - lo + eps)
    gt = pd.DataFrame(np.maximum(o.values, c.values), index=o.index, columns=o.columns)
    lt = pd.DataFrame(np.minimum(o.values, c.values), index=o.index, columns=o.columns)
    if factor_name == "KUP": return (h - gt) / o
    if factor_name == "KUP2": return (h - gt) / (h - lo + eps)
    if factor_name == "KLOW": return (lt - lo) / o
    if factor_name == "KLOW2": return (lt - lo) / (h - lo + eps)
    if factor_name == "KSFT": return (2 * c - h - lo) / o
    if factor_name == "KSFT2": return (2 * c - h - lo) / (h - lo + eps)

    # PRICE
    if factor_name == "OPEN0": return o / c
    if factor_name == "HIGH0": return h / c
    if factor_name == "LOW0": return lo / c
    if factor_name == "VWAP0": return (amt / v.replace(0, np.nan)) / c

    # ROLLING — 解析窗口
    for d in WINDOWS:
        ds = str(d)
        if not factor_name.endswith(ds):
            continue
        op = factor_name[:-len(ds)]

        if op == "ROC": return c.shift(d) / c
        if op == "MA": return c.rolling(d, min_periods=d).mean() / c
        if op == "STD": return c.rolling(d, min_periods=d).std() / c
        if op == "MAX": return h.rolling(d, min_periods=d).max() / c
        if op == "MIN": return lo.rolling(d, min_periods=d).min() / c
        if op == "QTLU": return c.rolling(d, min_periods=d).quantile(0.8) / c
        if op == "QTLD": return c.rolling(d, min_periods=d).quantile(0.2) / c
        if op == "VMA": return v.rolling(d, min_periods=d).mean() / (v + eps)
        if op == "VSTD": return v.rolling(d, min_periods=d).std() / (v + eps)

        ret = c / c.shift(1)
        c_diff = c - c.shift(1)
        v_diff = v - v.shift(1)

        # RSV
        if op == "RSV":
            rmin = lo.rolling(d, min_periods=d).min()
            rmax = h.rolling(d, min_periods=d).max()
            return (c - rmin) / (rmax - rmin + eps)

        # CORR (price-volume)
        if op == "CORR":
            log_v = np.log(v + 1)
            return c.rolling(d, min_periods=d).corr(log_v)

        # CORD (return-volume change)
        if op == "CORD":
            r1 = ret - 1
            log_vr = np.log(v / v.shift(1).replace(0, np.nan) + 1)
            return r1.rolling(d, min_periods=d).corr(log_vr)

        # CNTP/CNTN/CNTD
        up = (c > c.shift(1)).astype(float)
        dn = (c < c.shift(1)).astype(float)
        if op == "CNTP": return up.rolling(d, min_periods=d).mean()
        if op == "CNTN": return dn.rolling(d, min_periods=d).mean()
        if op == "CNTD": return up.rolling(d, min_periods=d).mean() - dn.rolling(d, min_periods=d).mean()

        # SUMP/SUMN/SUMD
        pos = c_diff.clip(lower=0)
        neg = (-c_diff).clip(lower=0)
        abs_sum = c_diff.abs().rolling(d, min_periods=d).sum() + eps
        if op == "SUMP": return pos.rolling(d, min_periods=d).sum() / abs_sum
        if op == "SUMN": return neg.rolling(d, min_periods=d).sum() / abs_sum
        if op == "SUMD":
            return (pos.rolling(d, min_periods=d).sum() - neg.rolling(d, min_periods=d).sum()) / abs_sum

        # VSUMP/VSUMN/VSUMD
        vpos = v_diff.clip(lower=0)
        vneg = (-v_diff).clip(lower=0)
        vabs_sum = v_diff.abs().rolling(d, min_periods=d).sum() + eps
        if op == "VSUMP": return vpos.rolling(d, min_periods=d).sum() / vabs_sum
        if op == "VSUMN": return vneg.rolling(d, min_periods=d).sum() / vabs_sum
        if op == "VSUMD":
            return (vpos.rolling(d, min_periods=d).sum() - vneg.rolling(d, min_periods=d).sum()) / vabs_sum

        # WVMA
        if op == "WVMA":
            wv = (ret - 1).abs() * v
            return wv.rolling(d, min_periods=d).std() / (wv.rolling(d, min_periods=d).mean() + eps)

        # IMAX/IMIN/IMXD — 跳过（apply太慢，用近似）
        if op == "RANK":
            # 时序百分位排名 — 用近似
            rmin = c.rolling(d, min_periods=d).min()
            rmax = c.rolling(d, min_periods=d).max()
            return (c - rmin) / (rmax - rmin + eps)

        if op in ("IMAX", "IMIN", "IMXD", "BETA", "RSQR", "RESI"):
            return None  # 跳过慢算子

    return None


def compute_monthly_ic(factor_pivot: pd.DataFrame, fwd_tables: dict, horizons: list[int]) -> dict:
    """计算单因子的月度IC。

    Args:
        factor_pivot: trade_date × code 的因子值。
        fwd_tables: {horizon: trade_date × code 的前向收益}。

    Returns:
        {ic_Xd_mean, ic_Xd_std, ic_ir_20d, n_months, abs_ic_20d}
    """
    result = {}
    monthly_ics = {h: [] for h in horizons}

    # 获取所有月份
    dates = factor_pivot.index
    months = sorted(set(d.strftime("%Y-%m") for d in dates))

    for ym in months:
        # 取该月最后一天的因子值和前向收益
        month_dates = [d for d in dates if d.strftime("%Y-%m") == ym]
        if not month_dates:
            continue
        last_date = max(month_dates)

        for h in horizons:
            fwd = fwd_tables[h]
            if last_date not in factor_pivot.index or last_date not in fwd.index:
                continue
            f_vals = factor_pivot.loc[last_date]
            r_vals = fwd.loc[last_date]
            valid = pd.DataFrame({"f": f_vals, "r": r_vals}).dropna()
            if len(valid) < MIN_STOCKS:
                continue
            ic, _ = stats.spearmanr(valid["f"], valid["r"])
            if not np.isnan(ic):
                monthly_ics[h].append(ic)

    for h in horizons:
        ics = monthly_ics[h]
        if ics:
            result[f"ic_{h}d_mean"] = np.mean(ics)
            result[f"ic_{h}d_std"] = np.std(ics)
        else:
            result[f"ic_{h}d_mean"] = np.nan
            result[f"ic_{h}d_std"] = np.nan

    ics_20 = monthly_ics.get(20, [])
    result["ic_ir_20d"] = np.mean(ics_20) / (np.std(ics_20) + 1e-12) if ics_20 else np.nan
    result["n_months"] = len(ics_20)
    result["abs_ic_20d"] = abs(result.get("ic_20d_mean", 0) or 0)

    return result


def get_all_factor_names() -> list[str]:
    """全部Alpha158因子名（跳过慢算子）。"""
    names = ["KMID", "KLEN", "KMID2", "KUP", "KUP2", "KLOW", "KLOW2", "KSFT", "KSFT2"]
    names += ["OPEN0", "HIGH0", "LOW0", "VWAP0"]
    fast_ops = [
        "ROC", "MA", "STD", "MAX", "MIN", "QTLU", "QTLD", "RSV", "RANK",
        "CORR", "CORD", "CNTP", "CNTN", "CNTD", "SUMP", "SUMN", "SUMD",
        "VMA", "VSTD", "WVMA", "VSUMP", "VSUMN", "VSUMD",
    ]
    # 跳过: BETA, RSQR, RESI, IMAX, IMIN, IMXD (apply太慢)
    for op in fast_ops:
        for d in WINDOWS:
            names.append(f"{op}{d}")
    return names


def main():
    t0 = time.time()
    conn = get_conn()

    # 一次加载全量价格
    price_df = load_all_prices(conn)
    conn.close()

    if price_df.empty:
        logger.error("无价格数据")
        return

    # 计算前向收益
    fwd_tables = compute_forward_returns(price_df)

    # 逐因子计算IC
    factor_names = get_all_factor_names()
    logger.info("待计算因子: %d个 (跳过6个慢算子×5窗口=30个)", len(factor_names))

    results = []
    for i, fname in enumerate(factor_names):
        try:
            pivot = compute_single_factor(price_df, fname)
            if pivot is None:
                continue

            ic_result = compute_monthly_ic(pivot, fwd_tables, HORIZONS)
            ic_result["factor_name"] = fname
            results.append(ic_result)

            if (i + 1) % 20 == 0:
                logger.info("  进度: %d/%d因子", i + 1, len(factor_names))

            del pivot  # 释放内存

        except Exception as e:
            logger.warning("  %s 计算失败: %s", fname, e)

    # 整理结果
    ic_df = pd.DataFrame(results)
    ic_df = ic_df.sort_values("abs_ic_20d", ascending=False)

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / "alpha158_ic_results.csv"
    ic_df.to_csv(out_path, index=False)
    logger.info("结果保存: %s (%d因子)", out_path, len(ic_df))

    # 汇总
    passed = ic_df[ic_df["abs_ic_20d"] >= 0.02]
    logger.info("\n=== 汇总 ===")
    logger.info("总计算因子: %d (跳过30个慢算子)", len(ic_df))
    logger.info("|IC_20d| >= 0.02: %d个", len(passed))
    logger.info("耗时: %.1f分钟", (time.time() - t0) / 60)

    if len(passed) > 0:
        logger.info("\n=== IC >= 0.02的因子 (按|IC|降序) ===")
        for _, r in passed.head(30).iterrows():
            logger.info(
                "  %-12s IC_20d=%.4f  IR=%.2f  months=%d",
                r["factor_name"], r["ic_20d_mean"], r.get("ic_ir_20d", 0), r.get("n_months", 0)
            )


if __name__ == "__main__":
    main()
