#!/usr/bin/env python3
"""P0因子补全: ATR_norm / IVOL / gap_frequency — 计算+写入DB+IC测试。"""
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ACTIVE_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]


# ============================================================
# Factor Calculations (pure numpy/pandas, no IO)
# ============================================================

def calc_atr_norm(high: pd.Series, low: pd.Series, close: pd.Series,
                  prev_close: pd.Series, window: int = 20) -> pd.Series:
    """ATR_norm = ATR(window) / close。标准化真实波动幅度。

    ATR = SMA(True Range, window)
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window, min_periods=window // 2).mean()
    return atr / close.clip(lower=0.01)


def calc_ivol(stock_ret: pd.Series, market_ret: pd.Series, window: int = 20) -> pd.Series:
    """IVOL: 特质波动率 — 个股收益对市场收益回归的残差标准差。

    Ang, Hodrick, Xing, Zhang (2006)
    """
    result = pd.Series(np.nan, index=stock_ret.index)
    for i in range(window, len(stock_ret)):
        y = stock_ret.iloc[i - window:i].values
        x = market_ret.iloc[i - window:i].values
        mask = ~(np.isnan(y) | np.isnan(x))
        if mask.sum() < window // 2:
            continue
        y_c, x_c = y[mask], x[mask]
        if len(x_c) < 5:
            continue
        # OLS: y = alpha + beta*x + eps
        x_aug = np.column_stack([np.ones(len(x_c)), x_c])
        try:
            beta, _, _, _ = np.linalg.lstsq(x_aug, y_c, rcond=None)
            residuals = y_c - x_aug @ beta
            result.iloc[i] = residuals.std()
        except Exception:
            continue
    return result


def calc_gap_frequency(open_price: pd.Series, prev_close: pd.Series,
                       window: int = 20, threshold: float = 0.01) -> pd.Series:
    """gap_frequency: 过去N日中跳空频率(|open-prev_close|/prev_close > threshold的占比)。"""
    gap = ((open_price - prev_close).abs() / prev_close.clip(lower=0.01)) > threshold
    return gap.astype(float).rolling(window, min_periods=window // 2).mean()


# ============================================================
# Bulk Compute + Write to DB
# ============================================================

def compute_and_write(conn):
    """批量计算3个因子并写入factor_values。"""
    cur = conn.cursor()

    # 加载行情数据(分块避免OOM)
    logger.info("加载行情数据...")
    price_df = pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close,
                  k.adj_factor
           FROM klines_daily k
           WHERE k.trade_date >= '2020-07-01' AND k.volume > 0
           ORDER BY k.code, k.trade_date""",
        conn)
    logger.info(f"行情: {len(price_df):,}行, {price_df['code'].nunique()}股票")

    # 加载沪深300日收益(IVOL用)
    idx = pd.read_sql(
        "SELECT trade_date, close FROM index_daily WHERE index_code = '000300.SH' AND trade_date >= '2020-06-01' ORDER BY trade_date",
        conn)
    idx["trade_date"] = pd.to_datetime(idx["trade_date"])
    idx["market_ret"] = idx["close"].pct_change()
    market_ret_map = idx.set_index("trade_date")["market_ret"]

    # 前复权(IVOL需要)
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    latest_adj = price_df.groupby("code")["adj_factor"].last()
    price_df = price_df.merge(latest_adj.rename("latest_adj"), on="code")
    price_df["adj_close"] = price_df["close"] * price_df["adj_factor"] / price_df["latest_adj"]
    price_df["stock_ret"] = price_df.groupby("code")["adj_close"].pct_change()

    # 逐股计算
    all_results = []
    codes = price_df["code"].unique()
    logger.info(f"计算{len(codes)}只股票的3个因子...")

    for i, code in enumerate(codes):
        g = price_df[price_df["code"] == code].sort_values("trade_date").copy()
        if len(g) < 25:
            continue

        # ATR_norm
        atr_n = calc_atr_norm(g["high"], g["low"], g["close"], g["pre_close"], 20)

        # gap_frequency
        gap_f = calc_gap_frequency(g["open"], g["pre_close"], 20, 0.01)

        # IVOL
        mkt = market_ret_map.reindex(g["trade_date"]).values
        g_mkt = pd.Series(mkt, index=g.index)
        ivol = calc_ivol(g["stock_ret"], g_mkt, 20)

        for td, atr_v, gap_v, ivol_v in zip(g["trade_date"], atr_n, gap_f, ivol, strict=False):
            if td < pd.Timestamp("2020-07-01"):
                continue
            td_date = td.date() if hasattr(td, "date") else td
            for fname, val in [("atr_norm_20", atr_v), ("gap_frequency_20", gap_v), ("ivol_20", ivol_v)]:
                if pd.notna(val) and np.isfinite(val):
                    all_results.append((code, td_date, fname, float(val)))

        if (i + 1) % 500 == 0:
            logger.info(f"  进度: {i+1}/{len(codes)} ({(i+1)/len(codes)*100:.0f}%)")

    logger.info(f"计算完成: {len(all_results):,}条记录")

    # 写入DB(需要先做中性化 — 简化版: 先写raw_value, neutral=raw, zscore=0)
    # 正式入库应通过factor_engine的预处理管道
    logger.info("写入factor_values...")
    batch_size = 10000
    written = 0
    for start in range(0, len(all_results), batch_size):
        batch = all_results[start:start + batch_size]
        for code, td, fname, val in batch:
            try:
                cur.execute(
                    """INSERT INTO factor_values (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                       VALUES (%s, %s, %s, %s, %s, 0)
                       ON CONFLICT (code, trade_date, factor_name) DO UPDATE
                       SET raw_value = EXCLUDED.raw_value, neutral_value = EXCLUDED.neutral_value""",
                    (code, td, fname, val, val))
                written += 1
            except Exception:
                conn.rollback()
        conn.commit()
        if start % 50000 == 0:
            logger.info(f"  写入: {written:,}/{len(all_results):,}")

    logger.info(f"写入完成: {written:,}条")

    # 验证
    for fname in ["atr_norm_20", "gap_frequency_20", "ivol_20"]:
        cur.execute("SELECT COUNT(*), MIN(trade_date), MAX(trade_date), COUNT(DISTINCT code) FROM factor_values WHERE factor_name = %s", (fname,))
        r = cur.fetchone()
        logger.info(f"  {fname}: {r[0]:,}行, {r[3]}股票, {r[1]}~{r[2]}")

    return written


# ============================================================
# IC Test
# ============================================================

def run_ic_test(conn):
    """对3个新因子跑IC测试。"""
    logger.info("\n=== IC TEST ===")

    # 月末因子值
    new_factors = ["atr_norm_20", "gap_frequency_20", "ivol_20"]
    month_ends = pd.read_sql(
        "SELECT MAX(trade_date) as trade_date FROM klines_daily "
        "WHERE trade_date >= '2021-01-01' AND trade_date <= '2026-03-31' AND volume > 0 "
        "GROUP BY DATE_TRUNC('month', trade_date) ORDER BY 1", conn)
    dates = month_ends["trade_date"].tolist()

    # 月度超额收益
    prices = pd.read_sql(
        "SELECT k.code, k.trade_date, k.close FROM klines_daily k "
        "JOIN symbols s ON k.code = s.code "
        "LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
        "WHERE k.trade_date >= '2021-01-01' AND k.trade_date <= '2026-03-31' AND k.volume > 0 "
        "AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%' "
        "AND (s.list_date IS NULL OR s.list_date <= k.trade_date - INTERVAL '60 days') "
        "AND COALESCE(db.total_mv, 0) > 100000 "
        "ORDER BY k.code, k.trade_date", conn)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices["ym"] = prices["trade_date"].dt.to_period("M")
    me = prices.groupby(["code", "ym"]).last().reset_index()
    me["next_close"] = me.groupby("code")["close"].shift(-1)
    me["fwd_ret"] = me["next_close"] / me["close"] - 1

    bench = pd.read_sql(
        "SELECT trade_date, close FROM index_daily WHERE index_code = '000300.SH' "
        "AND trade_date >= '2021-01-01' ORDER BY trade_date", conn)
    bench["trade_date"] = pd.to_datetime(bench["trade_date"])
    bench["ym"] = bench["trade_date"].dt.to_period("M")
    bench_m = bench.groupby("ym")["close"].last().pct_change().rename("bench_ret")
    me = me.merge(bench_m, on="ym", how="left")
    me["excess_ret"] = me["fwd_ret"] - me["bench_ret"].fillna(0)
    me = me.dropna(subset=["excess_ret"])

    # 对每个因子计算IC
    all_test = new_factors + ACTIVE_FACTORS
    print(f"\n{'因子':<25} {'IC_mean':>8} {'IC_IR':>7} {'t-stat':>7} {'月数':>5} {'maxCorr':>8} {'corrWith':>20}")
    print("-" * 100)

    for fname in all_test:
        # 月末因子值
        fv = pd.read_sql(
            "SELECT code, trade_date, raw_value FROM factor_values "
            "WHERE factor_name = %s AND trade_date >= '2021-01-01'",
            conn, params=(fname,))
        if fv.empty:
            print(f"{fname:<25} NO DATA")
            continue
        fv["trade_date"] = pd.to_datetime(fv["trade_date"])
        fv["ym"] = fv["trade_date"].dt.to_period("M")
        fv_me = fv.sort_values("trade_date").groupby(["code", "ym"]).last().reset_index()

        merged = fv_me.merge(me[["code", "ym", "excess_ret"]], on=["code", "ym"])
        merged = merged.dropna(subset=["raw_value", "excess_ret"])

        ic_list = []
        for _ym, grp in merged.groupby("ym"):
            if len(grp) < 30:
                continue
            rho, _ = sp_stats.spearmanr(grp["raw_value"].values, grp["excess_ret"].values)
            if not np.isnan(rho):
                ic_list.append(rho)

        if not ic_list:
            print(f"{fname:<25} NO IC DATA")
            continue

        ic_mean = np.mean(ic_list)
        ic_std = np.std(ic_list)
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        t_stat = ic_mean / (ic_std / np.sqrt(len(ic_list))) if ic_std > 0 else 0

        # Correlation with Active (simplified: use raw_value cross-sectional corr on last date)
        max_corr, corr_with = 0, ""
        last_date = dates[-2] if len(dates) > 1 else dates[0]
        fv_last = pd.read_sql(
            "SELECT code, factor_name, raw_value FROM factor_values "
            "WHERE trade_date = %s AND factor_name IN %s",
            conn, params=(last_date, tuple(ACTIVE_FACTORS + [fname])))
        if not fv_last.empty:
            pivot = fv_last.pivot_table(index="code", columns="factor_name", values="raw_value")
            if fname in pivot.columns:
                for af in ACTIVE_FACTORS:
                    if af in pivot.columns:
                        valid = pivot[[fname, af]].dropna()
                        if len(valid) > 30:
                            r, _ = sp_stats.spearmanr(valid[fname], valid[af])
                            if not np.isnan(r) and abs(r) > abs(max_corr):
                                max_corr = r
                                corr_with = af

        is_new = "***" if fname in new_factors else ""
        print(f"{fname:<25} {ic_mean:>+8.4f} {ic_ir:>+7.3f} {t_stat:>+7.2f} {len(ic_list):>5} "
              f"{abs(max_corr):>+8.3f} {corr_with:>20} {is_new}")


def main():
    t0 = time.time()
    conn = _get_sync_conn()

    # Step 1: Compute + Write
    compute_and_write(conn)

    # Step 2: IC Test
    run_ic_test(conn)

    conn.close()
    elapsed = time.time() - t0
    logger.info(f"\n总耗时: {elapsed:.0f}s ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
