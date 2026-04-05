#!/usr/bin/env python3
"""P0因子快速补全 — 批量计算+COPY写入(比逐行INSERT快100倍)。

用法: python scripts/research_p0_factors_fast.py [atr|ivol|gap|all]
默认: all (顺序执行3个因子)
并行: 3个终端分别跑 atr / ivol / gap
"""
import logging, os, sys, time, io
from datetime import datetime
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


def load_price_data(conn):
    """加载行情(含前复权)。"""
    logger.info("加载行情...")
    df = pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close, k.adj_factor
           FROM klines_daily k WHERE k.trade_date >= '2020-06-01' AND k.volume > 0
           ORDER BY k.code, k.trade_date""", conn)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    # 前复权
    latest_adj = df.groupby("code")["adj_factor"].last()
    df = df.merge(latest_adj.rename("la"), on="code")
    df["adj_close"] = df["close"] * df["adj_factor"] / df["la"]
    df["stock_ret"] = df.groupby("code")["adj_close"].pct_change()
    logger.info(f"行情: {len(df):,}行, {df['code'].nunique()}只")
    return df


def load_market_ret(conn):
    """沪深300日收益。"""
    idx = pd.read_sql(
        "SELECT trade_date, close FROM index_daily WHERE index_code = '000300.SH' AND trade_date >= '2020-06-01' ORDER BY trade_date", conn)
    idx["trade_date"] = pd.to_datetime(idx["trade_date"])
    idx["market_ret"] = idx["close"].pct_change()
    return idx.set_index("trade_date")["market_ret"]


def calc_atr_norm_batch(pdf):
    """ATR_norm = ATR(20)/close 批量计算。"""
    results = []
    for code, g in pdf.groupby("code"):
        g = g.sort_values("trade_date")
        if len(g) < 22:
            continue
        tr1 = g["high"] - g["low"]
        tr2 = (g["high"] - g["pre_close"]).abs()
        tr3 = (g["low"] - g["pre_close"]).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(20, min_periods=10).mean()
        val = atr / g["close"].clip(lower=0.01)
        for td, v in zip(g["trade_date"], val):
            if td >= pd.Timestamp("2020-07-01") and pd.notna(v) and np.isfinite(v):
                results.append((code, td.date(), "atr_norm_20", float(v)))
    return results


def calc_gap_freq_batch(pdf):
    """gap_frequency = 跳空频率 批量计算。"""
    results = []
    for code, g in pdf.groupby("code"):
        g = g.sort_values("trade_date")
        if len(g) < 22:
            continue
        gap = ((g["open"] - g["pre_close"]).abs() / g["pre_close"].clip(lower=0.01)) > 0.01
        val = gap.astype(float).rolling(20, min_periods=10).mean()
        for td, v in zip(g["trade_date"], val):
            if td >= pd.Timestamp("2020-07-01") and pd.notna(v) and np.isfinite(v):
                results.append((code, td.date(), "gap_frequency_20", float(v)))
    return results


def calc_ivol_batch(pdf, market_ret):
    """IVOL = 特质波动率(OLS残差std) 批量计算。"""
    results = []
    mkt_map = market_ret.to_dict()
    for code, g in pdf.groupby("code"):
        g = g.sort_values("trade_date")
        if len(g) < 25:
            continue
        rets = g["stock_ret"].values
        dates = g["trade_date"].values
        mkts = np.array([mkt_map.get(pd.Timestamp(d), np.nan) for d in dates])

        for i in range(20, len(rets)):
            y = rets[i-20:i]
            x = mkts[i-20:i]
            mask = ~(np.isnan(y) | np.isnan(x))
            if mask.sum() < 10:
                continue
            yc, xc = y[mask], x[mask]
            # Fast OLS
            xm = xc - xc.mean()
            ym = yc - yc.mean()
            beta = np.dot(xm, ym) / (np.dot(xm, xm) + 1e-12)
            alpha = yc.mean() - beta * xc.mean()
            resid = yc - alpha - beta * xc
            ivol = resid.std()

            td = pd.Timestamp(dates[i])
            if td >= pd.Timestamp("2020-07-01") and np.isfinite(ivol):
                results.append((code, td.date(), "ivol_20", float(ivol)))
    return results


def batch_write(conn, records, factor_name):
    """用COPY协议快速写入(比INSERT快100倍)。"""
    if not records:
        return 0

    cur = conn.cursor()
    # 先删除旧数据
    cur.execute("DELETE FROM factor_values WHERE factor_name = %s", (factor_name,))
    old_count = cur.rowcount
    conn.commit()
    logger.info(f"  删除旧{factor_name}: {old_count}行")

    # 用StringIO + COPY FROM
    buf = io.StringIO()
    for code, td, fname, val in records:
        # COPY格式: code\ttrade_date\tfactor_name\traw_value\tneutral_value\tzscore
        buf.write(f"{code}\t{td}\t{fname}\t{val}\t{val}\t0\n")
    buf.seek(0)

    cur.copy_from(buf, "factor_values",
                  columns=("code", "trade_date", "factor_name", "raw_value", "neutral_value", "zscore"))
    conn.commit()

    # 验证
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(trade_date), MAX(trade_date) FROM factor_values WHERE factor_name = %s", (factor_name,))
    r = cur.fetchone()
    logger.info(f"  写入{factor_name}: {r[0]:,}行, {r[1]}只, {r[2]}~{r[3]}")
    return r[0]


def run_ic_test(conn, factor_name):
    """快速IC测试。"""
    logger.info(f"\n=== IC TEST: {factor_name} ===")
    # 月末因子值
    fv = pd.read_sql(
        "SELECT code, trade_date, raw_value FROM factor_values "
        "WHERE factor_name = %s AND trade_date >= '2021-01-01'", conn, params=(factor_name,))
    if fv.empty:
        print(f"  {factor_name}: NO DATA")
        return

    fv["trade_date"] = pd.to_datetime(fv["trade_date"])
    fv["ym"] = fv["trade_date"].dt.to_period("M")
    fv_me = fv.sort_values("trade_date").groupby(["code", "ym"]).last().reset_index()

    # 月度超额收益(aligned universe)
    prices = pd.read_sql(
        """SELECT k.code, k.trade_date, k.close FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date >= '2021-01-01' AND k.trade_date <= '2026-03-31' AND k.volume > 0
           AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%'
           AND (s.list_date IS NULL OR s.list_date <= k.trade_date - INTERVAL '60 days')
           AND COALESCE(db.total_mv, 0) > 100000
           ORDER BY k.code, k.trade_date""", conn)
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices["ym"] = prices["trade_date"].dt.to_period("M")
    me = prices.groupby(["code", "ym"]).last().reset_index()
    me["next_close"] = me.groupby("code")["close"].shift(-1)
    me["fwd_ret"] = me["next_close"] / me["close"] - 1

    bench = pd.read_sql(
        "SELECT trade_date, close FROM index_daily WHERE index_code = '000300.SH' AND trade_date >= '2021-01-01' ORDER BY trade_date", conn)
    bench["trade_date"] = pd.to_datetime(bench["trade_date"])
    bench["ym"] = bench["trade_date"].dt.to_period("M")
    bench_m = bench.groupby("ym")["close"].last().pct_change()
    me = me.merge(bench_m.rename("bench_ret"), on="ym", how="left")
    me["excess_ret"] = me["fwd_ret"] - me["bench_ret"].fillna(0)
    me = me.dropna(subset=["excess_ret"])

    merged = fv_me.merge(me[["code", "ym", "excess_ret"]], on=["code", "ym"])
    merged = merged.dropna(subset=["raw_value", "excess_ret"])

    ic_list = []
    yearly = {}
    for ym, grp in merged.groupby("ym"):
        if len(grp) < 30:
            continue
        rho, _ = sp_stats.spearmanr(grp["raw_value"].values, grp["excess_ret"].values)
        if not np.isnan(rho):
            ic_list.append(rho)
            yr = ym.year
            if yr not in yearly:
                yearly[yr] = []
            yearly[yr].append(rho)

    if not ic_list:
        print(f"  {factor_name}: no valid IC months")
        return

    ic_mean = np.mean(ic_list)
    ic_std = np.std(ic_list)
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_list))) if ic_std > 0 else 0

    print(f"  {factor_name:20s} IC={ic_mean:+.4f}  IR={ic_ir:+.3f}  t={t_stat:+.2f}  months={len(ic_list)}")
    for yr in sorted(yearly.keys()):
        print(f"    {yr}: IC={np.mean(yearly[yr]):+.4f} ({len(yearly[yr])}m)")

    # Correlation with Active factors
    last_date = merged["ym"].max()
    active = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    fv_all = pd.read_sql(
        "SELECT code, factor_name, raw_value FROM factor_values "
        "WHERE trade_date = (SELECT MAX(trade_date) FROM factor_values WHERE factor_name = %s) "
        "AND factor_name IN %s",
        conn, params=(factor_name, tuple(active + [factor_name])))
    if not fv_all.empty:
        pivot = fv_all.pivot_table(index="code", columns="factor_name", values="raw_value")
        if factor_name in pivot.columns:
            print(f"  Correlations with Active:")
            for af in active:
                if af in pivot.columns:
                    valid = pivot[[factor_name, af]].dropna()
                    if len(valid) > 30:
                        r, _ = sp_stats.spearmanr(valid[factor_name], valid[af])
                        print(f"    vs {af:25s}: {r:+.3f}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    t0 = time.time()
    conn = _get_sync_conn()
    pdf = load_price_data(conn)
    market_ret = load_market_ret(conn)

    if mode in ("atr", "all"):
        logger.info("\n=== ATR_NORM_20 ===")
        t1 = time.time()
        records = calc_atr_norm_batch(pdf)
        logger.info(f"  计算完成: {len(records):,}条, {time.time()-t1:.0f}s")
        batch_write(conn, records, "atr_norm_20")
        run_ic_test(conn, "atr_norm_20")

    if mode in ("gap", "all"):
        logger.info("\n=== GAP_FREQUENCY_20 ===")
        t1 = time.time()
        records = calc_gap_freq_batch(pdf)
        logger.info(f"  计算完成: {len(records):,}条, {time.time()-t1:.0f}s")
        batch_write(conn, records, "gap_frequency_20")
        run_ic_test(conn, "gap_frequency_20")

    if mode in ("ivol", "all"):
        logger.info("\n=== IVOL_20 ===")
        t1 = time.time()
        records = calc_ivol_batch(pdf, market_ret)
        logger.info(f"  计算完成: {len(records):,}条, {time.time()-t1:.0f}s")
        batch_write(conn, records, "ivol_20")
        run_ic_test(conn, "ivol_20")

    conn.close()
    elapsed = time.time() - t0
    logger.info(f"\n总耗时: {elapsed:.0f}s ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
