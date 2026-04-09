#!/usr/bin/env python3
"""Step 6-D Part 2: Fama-French 3-Factor 归因.

对 5 因子等权策略的 12 年日收益率序列做 FF3 时序回归:
  R_p - R_f = alpha + b_mkt*(R_m - R_f) + b_smb*SMB + b_hml*HML + epsilon

使用 HAC (Newey-West) 标准误, lag=5。

FF3 因子自建:
  - Universe: 跟策略一致 (排除 BJ/ST/停牌/新股), 所有 A股主板/创业板/科创板
  - SMB: 小盘 (市值下 50%) - 大盘 (市值上 50%), 等权, 日再平衡
  - HML: 高 B/P (上 30%) - 低 B/P (下 30%), 等权, 日再平衡
  - MKT: 全 A 市值加权收益 - RF
  - RF: 常数 2.5% 年化 (A股学术研究常用, 约等于 SHIBOR 3M 长期均值)

输入: cache/baseline/yearly_chain_nav.parquet (Part 1 产出的 12 年 chain NAV)
输出:
  cache/baseline/ff3_factors.parquet    — FF3 因子日序列
  cache/baseline/ff3_attribution.json   — 全样本 + 分期 + 逐年回归结果

用法:
    python scripts/research/ff3_attribution.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.WARNING)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "baseline"

# 学术惯例: A股 RF ≈ 2.5% 年化 (近似 SHIBOR 3M 长期均值 / 10年期国债长期均值)
RF_ANNUAL = 0.025
RF_DAILY = RF_ANNUAL / 244


# ============================================================
# Step A: 构建 FF3 因子
# ============================================================


def build_ff3_factors(
    start_date: date, end_date: date, conn
) -> pd.DataFrame:
    """从 DB 构建 A股 FF3 因子日序列。

    SMB 和 HML 使用 daily reblancing + equal weight 简化版 (非 Fama 6-portfolio),
    符合 "市值下 50% - 上 50%" 的直接 SMB proxy。
    """
    print("[FF3] 加载 12 年 universe 日收益率 + 市值 + pb...")
    t0 = time.time()

    # 一次性加载所有需要的数据
    sql = """
    SELECT k.code, k.trade_date,
           k.close, k.pre_close, k.volume,
           k.adj_factor,
           db.total_mv, db.pb,
           COALESCE(ss.is_st, false) AS is_st,
           COALESCE(ss.is_suspended, false) AS is_suspended,
           COALESCE(ss.is_new_stock, false) AS is_new_stock,
           ss.board
    FROM klines_daily k
    LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
    LEFT JOIN stock_status_daily ss ON k.code = ss.code AND k.trade_date = ss.trade_date
    WHERE k.trade_date BETWEEN %s AND %s
      AND k.volume > 0
      AND k.pre_close IS NOT NULL AND k.pre_close > 0
      AND db.total_mv IS NOT NULL AND db.total_mv > 0
    """
    df = pd.read_sql(sql, conn, params=(start_date, end_date))
    print(f"  加载 {len(df):,} 行, {time.time() - t0:.1f}s")

    # Universe filter (跟策略一致)
    before = len(df)
    df = df[
        (~df["is_st"])
        & (~df["is_suspended"])
        & (~df["is_new_stock"])
        & (df["board"].fillna("") != "bse")
    ].copy()
    print(f"  过滤后 {len(df):,} 行 (去掉 {before - len(df):,})")

    # 日复权收益率 (simple = close/pre_close - 1, pre_close 已是前一日的复权收盘)
    df["ret"] = df["close"] / df["pre_close"] - 1
    # 剔除异常收益 (>50% or <-50% = 数据错误)
    df = df[(df["ret"] > -0.5) & (df["ret"] < 0.5)].copy()

    # 按日对股票分组构建 SMB/HML/MKT
    print("[FF3] 每日构建 SMB/HML/MKT...")
    factors_list = []
    grouped = df.groupby("trade_date")
    total_days = len(grouped)

    for i, (trade_date, day_df) in enumerate(grouped):
        if len(day_df) < 50:
            continue

        # 市值加权 MKT: 全 A 市值加权收益
        mv_sum = day_df["total_mv"].sum()
        mkt_ret = (day_df["ret"] * day_df["total_mv"] / mv_sum).sum()

        # SMB: 市值中位数分大小
        mv_median = day_df["total_mv"].median()
        small = day_df[day_df["total_mv"] <= mv_median]
        large = day_df[day_df["total_mv"] > mv_median]
        if len(small) < 20 or len(large) < 20:
            continue
        smb = float(small["ret"].mean() - large["ret"].mean())

        # HML: B/P = 1/pb, 高 30% - 低 30%
        day_valid_pb = day_df[day_df["pb"].notna() & (day_df["pb"] > 0)].copy()
        if len(day_valid_pb) < 60:
            continue
        day_valid_pb["bp"] = 1.0 / day_valid_pb["pb"]
        q_low = day_valid_pb["bp"].quantile(0.30)
        q_high = day_valid_pb["bp"].quantile(0.70)
        high_bp = day_valid_pb[day_valid_pb["bp"] >= q_high]
        low_bp = day_valid_pb[day_valid_pb["bp"] <= q_low]
        if len(high_bp) < 20 or len(low_bp) < 20:
            continue
        hml = float(high_bp["ret"].mean() - low_bp["ret"].mean())

        factors_list.append({
            "trade_date": trade_date,
            "MKT_RF": float(mkt_ret) - RF_DAILY,
            "SMB": smb,
            "HML": hml,
            "RF": RF_DAILY,
            "n_stocks": len(day_df),
        })

        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{total_days} 天 ({(i + 1) / total_days * 100:.0f}%)")

    ff3 = pd.DataFrame(factors_list).sort_values("trade_date").reset_index(drop=True)
    print(f"  构建 FF3 完成: {len(ff3)} 天")

    return ff3


# ============================================================
# Step B: 时序回归 (HAC)
# ============================================================


def run_hac_regression(
    strategy_ret: pd.Series, ff3: pd.DataFrame, label: str = "full"
) -> dict:
    """单次 HAC 回归。

    Args:
        strategy_ret: 策略日收益率 Series (index=trade_date)
        ff3: FF3 因子 DataFrame (trade_date, MKT_RF, SMB, HML, RF)
        label: 标签 (用于打印)

    Returns:
        dict with alpha, alpha_t, mkt_beta, smb_beta, hml_beta, r2
    """
    # 合并对齐
    df = pd.DataFrame({"ret": strategy_ret}).reset_index()
    df.columns = ["trade_date", "ret"]
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    ff3_ = ff3.copy()
    ff3_["trade_date"] = pd.to_datetime(ff3_["trade_date"]).dt.date
    merged = df.merge(ff3_, on="trade_date", how="inner")

    if len(merged) < 30:
        return {
            "label": label,
            "n_days": len(merged),
            "error": "insufficient data",
        }

    y = merged["ret"].values - merged["RF"].values  # 策略超额收益
    X = merged[["MKT_RF", "SMB", "HML"]].values
    X = sm.add_constant(X)  # 加常数项 (alpha)

    # OLS with Newey-West HAC standard errors (lag=5)
    model = sm.OLS(y, X)
    result = model.fit(cov_type="HAC", cov_kwds={"maxlags": 5})

    alpha_daily = float(result.params[0])
    alpha_annual = alpha_daily * 244
    alpha_t = float(result.tvalues[0])
    alpha_p = float(result.pvalues[0])
    mkt_beta = float(result.params[1])
    mkt_t = float(result.tvalues[1])
    smb_beta = float(result.params[2])
    smb_t = float(result.tvalues[2])
    hml_beta = float(result.params[3])
    hml_t = float(result.tvalues[3])
    r2 = float(result.rsquared)
    r2_adj = float(result.rsquared_adj)

    return {
        "label": label,
        "n_days": int(len(merged)),
        "date_start": str(merged["trade_date"].min()),
        "date_end": str(merged["trade_date"].max()),
        "alpha_daily": round(alpha_daily, 6),
        "alpha_annual": round(alpha_annual, 4),
        "alpha_t": round(alpha_t, 4),
        "alpha_p": round(alpha_p, 6),
        "alpha_significant_5pct": alpha_p < 0.05,
        "alpha_significant_1pct": alpha_p < 0.01,
        "mkt_beta": round(mkt_beta, 4),
        "mkt_t": round(mkt_t, 4),
        "smb_beta": round(smb_beta, 4),
        "smb_t": round(smb_t, 4),
        "hml_beta": round(hml_beta, 4),
        "hml_t": round(hml_t, 4),
        "r2": round(r2, 4),
        "r2_adj": round(r2_adj, 4),
    }


# ============================================================
# Main
# ============================================================


def main():
    # Step 1: 加载策略 NAV (12 年 chain)
    nav_path = BASELINE_DIR / "yearly_chain_nav.parquet"
    if not nav_path.exists():
        print(f"ERROR: {nav_path} 不存在. 请先跑 scripts/yearly_breakdown_backtest.py")
        sys.exit(1)

    print(f"[Load] 策略 chain NAV: {nav_path}")
    nav_df = pd.read_parquet(nav_path)
    nav_df["trade_date"] = pd.to_datetime(nav_df["trade_date"]).dt.date
    strategy_nav = pd.Series(
        nav_df["nav"].values, index=pd.Index(nav_df["trade_date"], name="trade_date")
    )
    strategy_ret = strategy_nav.pct_change().dropna()
    print(f"  NAV days: {len(strategy_nav)}, Returns days: {len(strategy_ret)}")
    print(f"  Range: {strategy_ret.index.min()}..{strategy_ret.index.max()}")

    # Step 2: 构建/加载 FF3 因子
    ff3_path = BASELINE_DIR / "ff3_factors.parquet"
    if ff3_path.exists():
        print(f"\n[Load] FF3 cached: {ff3_path}")
        ff3 = pd.read_parquet(ff3_path)
        ff3["trade_date"] = pd.to_datetime(ff3["trade_date"]).dt.date
        print(f"  {len(ff3)} 天, {ff3['trade_date'].min()}..{ff3['trade_date'].max()}")
    else:
        print("\n[Build] FF3 因子 (从 DB 构建)...")
        conn = get_sync_conn()
        try:
            ff3 = build_ff3_factors(
                start_date=strategy_ret.index.min(),
                end_date=strategy_ret.index.max(),
                conn=conn,
            )
        finally:
            conn.close()
        ff3.to_parquet(ff3_path, index=False)
        print(f"  Saved: {ff3_path}")

    # FF3 sanity check
    print("\n[FF3 Stats]")
    print(f"  MKT_RF: mean={ff3['MKT_RF'].mean() * 244:.2%}/yr, "
          f"std={ff3['MKT_RF'].std() * np.sqrt(244):.2%}/yr")
    print(f"  SMB:    mean={ff3['SMB'].mean() * 244:.2%}/yr, "
          f"std={ff3['SMB'].std() * np.sqrt(244):.2%}/yr")
    print(f"  HML:    mean={ff3['HML'].mean() * 244:.2%}/yr, "
          f"std={ff3['HML'].std() * np.sqrt(244):.2%}/yr")

    # Step 3: 分期回归
    print("\n[Regression] HAC (Newey-West lag=5)...")

    results = {}

    # 全样本
    results["full_12yr"] = run_hac_regression(
        strategy_ret, ff3, label="2014-2026 full"
    )

    # 2014-2020 (WF 盲区)
    mask_pre = (strategy_ret.index >= date(2014, 1, 1)) & (
        strategy_ret.index <= date(2020, 12, 31)
    )
    results["pre_wf_2014_2020"] = run_hac_regression(
        strategy_ret[mask_pre], ff3, label="2014-2020 (pre-WF blind spot)"
    )

    # 2021-2026 (WF 覆盖)
    mask_wf = strategy_ret.index >= date(2021, 1, 1)
    results["wf_2021_2026"] = run_hac_regression(
        strategy_ret[mask_wf], ff3, label="2021-2026 (WF covered)"
    )

    # 逐年
    yearly = []
    for year in range(2014, 2027):
        mask = (strategy_ret.index >= date(year, 1, 1)) & (
            strategy_ret.index <= date(year, 12, 31)
        )
        sr = strategy_ret[mask]
        if len(sr) < 30:
            continue
        r = run_hac_regression(sr, ff3, label=f"{year}")
        r["year"] = year
        yearly.append(r)
    results["yearly"] = yearly

    # Step 4: 保存
    output = {
        "config": {
            "rf_annual": RF_ANNUAL,
            "hac_lag": 5,
            "universe": "exclude BJ/ST/suspended/new_stock",
            "factor_construction": {
                "smb": "mv_median split, equal-weight, daily rebal",
                "hml": "bp(=1/pb) 30%/70% split, equal-weight, daily rebal",
                "mkt": "全A 市值加权 - RF",
            },
            "ff3_days": len(ff3),
            "strategy_days": len(strategy_ret),
        },
        "full_12yr": results["full_12yr"],
        "pre_wf_2014_2020": results["pre_wf_2014_2020"],
        "wf_2021_2026": results["wf_2021_2026"],
        "yearly": results["yearly"],
    }

    out_path = BASELINE_DIR / "ff3_attribution.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n[Save] {out_path}")

    # Step 5: 打印报告
    print("\n" + "=" * 100)
    print("  Fama-French 3-Factor 归因 — 策略 (5 因子等权 Top-20 monthly)")
    print("=" * 100)

    def print_row(r):
        sig = (
            "***" if r.get("alpha_significant_1pct")
            else "**" if r.get("alpha_significant_5pct")
            else ""
        )
        print(
            f"  {r['label']:<32}  "
            f"Alpha={r['alpha_annual']:+7.2%}{sig:>4} "
            f"(t={r['alpha_t']:+6.2f})  "
            f"MKT={r['mkt_beta']:+5.2f}(t={r['mkt_t']:+5.2f})  "
            f"SMB={r['smb_beta']:+5.2f}(t={r['smb_t']:+5.2f})  "
            f"HML={r['hml_beta']:+5.2f}(t={r['hml_t']:+5.2f})  "
            f"R²={r['r2']:.3f}  "
            f"n={r['n_days']}"
        )

    print("\n  全期与分段:")
    print_row(results["full_12yr"])
    print_row(results["pre_wf_2014_2020"])
    print_row(results["wf_2021_2026"])

    print("\n  逐年:")
    for r in yearly:
        print_row(r)

    print("\n  *** p<0.01, ** p<0.05")
    print("=" * 100)


if __name__ == "__main__":
    main()
