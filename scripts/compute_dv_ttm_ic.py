#!/usr/bin/env python3
"""dv_ttm因子IC验证: 股息率TTM截面排名与forward excess return的Spearman IC。

- 数据源: daily_basic表的dv_ttm字段
- 每月取一次截面（月末最后交易日）
- 截面rank后计算与forward 20日超额收益的Spearman IC
- 方向: +1（高股息跑赢低股息）

用法:
    python scripts/compute_dv_ttm_ic.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from engines.config_guard import print_config_header

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn

FACTOR_NAME = "dv_ttm"
FACTOR_DIRECTION = 1  # 高股息跑赢低股息
IC_HORIZON = 20  # 20日forward excess return


def get_month_end_trade_dates(conn, start: str = "2021-01-01", end: str = "2025-12-31") -> list:
    """获取每月最后一个交易日列表。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date >= %s AND trade_date <= %s
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC""",
        (start, end),
    )
    dates = sorted([r[0] for r in cur.fetchall()])
    return dates


def load_dv_ttm_monthly(conn, trade_dates: list) -> pd.DataFrame:
    """加载月末截面的dv_ttm数据。"""
    all_data = []
    for td in trade_dates:
        df = pd.read_sql(
            """SELECT code, dv_ttm
               FROM daily_basic
               WHERE trade_date = %s AND dv_ttm IS NOT NULL""",
            conn,
            params=(td,),
        )
        if not df.empty:
            df["trade_date"] = td
            df["dv_ttm"] = df["dv_ttm"].astype(float)
            all_data.append(df)

    if all_data:
        result = pd.concat(all_data, ignore_index=True)
        print(f"  加载dv_ttm数据: {len(result):,}行, {result['trade_date'].nunique()}个月, "
              f"{result['code'].nunique():,}只股票")
        return result
    return pd.DataFrame()


def cross_section_rank_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """截面rank后zscore标准化。

    对每个trade_date截面:
    1. rank (百分位)
    2. zscore
    """
    result = []
    for td, grp in df.groupby("trade_date"):
        vals = grp[["code", "dv_ttm"]].copy()
        # 截面rank（百分位）
        vals["rank_pct"] = vals["dv_ttm"].rank(pct=True)
        # zscore
        mean_val = vals["rank_pct"].mean()
        std_val = vals["rank_pct"].std()
        if std_val > 0:
            vals["zscore"] = (vals["rank_pct"] - mean_val) / std_val
        else:
            vals["zscore"] = 0.0
        vals["trade_date"] = td
        result.append(vals)

    if result:
        return pd.concat(result, ignore_index=True)
    return pd.DataFrame()


def load_forward_returns(trade_dates: list, horizon: int, conn) -> pd.DataFrame:
    """加载forward excess return（超额CSI300）。"""
    min_date = min(trade_dates)
    max_date = max(trade_dates) + timedelta(days=horizon * 3)

    prices = pd.read_sql(
        """SELECT k.code, k.trade_date,
                  k.close * COALESCE(k.adj_factor, 1) AS adj_close
           FROM klines_daily k
           WHERE k.trade_date >= %s AND k.trade_date <= %s AND k.volume > 0""",
        conn,
        params=(min_date, max_date),
    )
    prices = prices.pivot(index="trade_date", columns="code", values="adj_close")

    bench = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date >= %s AND trade_date <= %s""",
        conn,
        params=(min_date, max_date),
    )
    bench = bench.set_index("trade_date")["close"]

    all_dates = sorted(prices.index)
    results = []
    for td in trade_dates:
        if td not in prices.index:
            continue
        future = [d for d in all_dates if d > td]
        if len(future) < horizon:
            continue
        fwd_date = future[horizon - 1]

        stock_ret = prices.loc[fwd_date] / prices.loc[td] - 1
        bench_ret = (
            bench.loc[fwd_date] / bench.loc[td] - 1
            if td in bench.index and fwd_date in bench.index
            else 0
        )
        excess = stock_ret - bench_ret
        excess.name = td
        results.append(excess)

    if results:
        return pd.DataFrame(results)
    return pd.DataFrame()


def main():
    print_config_header()
    conn = _get_sync_conn()

    # 1. 获取分析日期
    analysis_dates = get_month_end_trade_dates(conn)
    print(f"[1] 分析日期: {len(analysis_dates)}个月 ({analysis_dates[0]} ~ {analysis_dates[-1]})")

    # 2. 加载dv_ttm月末截面
    print(f"\n[2] 加载dv_ttm月末截面数据...")
    raw_df = load_dv_ttm_monthly(conn, analysis_dates)
    if raw_df.empty:
        print("ERROR: 无dv_ttm数据")
        conn.close()
        return

    # 因子分布
    print(f"\n  原始dv_ttm分布: mean={raw_df['dv_ttm'].mean():.4f}, "
          f"median={raw_df['dv_ttm'].median():.4f}, "
          f"p5={raw_df['dv_ttm'].quantile(0.05):.4f}, "
          f"p95={raw_df['dv_ttm'].quantile(0.95):.4f}, "
          f"zero_pct={100*(raw_df['dv_ttm']==0).mean():.1f}%")

    # 3. 截面rank + zscore
    print(f"\n[3] 截面rank -> zscore...")
    factor_df = cross_section_rank_zscore(raw_df)
    print(f"  处理后: {len(factor_df):,}行")

    # 4. 计算IC (用原始dv_ttm做Spearman IC，等价于rank IC)
    print(f"\n[4] 计算IC ({IC_HORIZON}日forward excess return)...")
    fwd_rets = load_forward_returns(analysis_dates, horizon=IC_HORIZON, conn=conn)
    print(f"  Forward returns: {fwd_rets.shape}")

    ics = []
    for td in fwd_rets.index:
        fv = raw_df[raw_df["trade_date"] == td].set_index("code")["dv_ttm"].dropna()
        fr = fwd_rets.loc[td].dropna()
        common = fv.index.intersection(fr.index)
        if len(common) < 50:
            continue
        ic, _ = stats.spearmanr(fv[common], fr[common])
        if np.isfinite(ic):
            ics.append({"date": td, "ic": ic})

    if not ics:
        print("ERROR: 无有效IC")
        conn.close()
        return

    ic_df = pd.DataFrame(ics)
    ic_vals = ic_df["ic"].values * FACTOR_DIRECTION

    print(f"\n{'='*60}")
    print(f"  {FACTOR_NAME} IC统计 (方向={FACTOR_DIRECTION}, {IC_HORIZON}日超额)")
    print(f"{'='*60}")
    print(f"  IC均值:  {np.mean(ic_vals):+.4f}")
    print(f"  IC标准差: {np.std(ic_vals):.4f}")
    print(f"  IC_IR:   {np.mean(ic_vals)/np.std(ic_vals):+.3f}" if np.std(ic_vals) > 0 else "  IC_IR:   N/A")
    print(f"  命中率:  {np.mean(ic_vals > 0):.1%}")
    print(f"  有效月数: {len(ics)}")

    # 5. 年度IC分解
    print(f"\n[5] 年度IC分解:")
    ic_df["year"] = pd.to_datetime(ic_df["date"]).dt.year
    print(f"  {'年份':>6} {'IC均值':>8} {'IC_IR':>7} {'命中率':>6} {'月数':>4}")
    print(f"  {'-'*35}")
    for year, grp in ic_df.groupby("year"):
        vals = grp["ic"].values * FACTOR_DIRECTION
        ir = np.mean(vals) / np.std(vals) if np.std(vals) > 0 else 0
        print(f"  {year:>6} {np.mean(vals):>+.4f} {ir:>+.3f} {np.mean(vals>0):>5.0%} {len(vals):>4}")

    # 6. 与现有5因子的截面相关性
    print(f"\n[6] 与现有5因子的截面相关性 (最近20个月平均)...")
    existing_factors = [
        "turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"
    ]
    sample_dates = sorted(analysis_dates)[-20:]
    existing_df = pd.read_sql(
        """SELECT code, trade_date, factor_name, zscore
           FROM factor_values
           WHERE factor_name IN %s
             AND trade_date IN %s""",
        conn,
        params=(tuple(existing_factors), tuple(sample_dates)),
    )

    if not existing_df.empty:
        corrs_by_factor = {ef: [] for ef in existing_factors}
        for td in sample_dates:
            fv = raw_df[raw_df["trade_date"] == td].set_index("code")["dv_ttm"].dropna()
            for ef in existing_factors:
                ev = existing_df[
                    (existing_df["trade_date"] == td) & (existing_df["factor_name"] == ef)
                ].set_index("code")["zscore"]
                common = fv.index.intersection(ev.index)
                if len(common) >= 100:
                    c, _ = stats.spearmanr(fv[common].astype(float), ev[common].astype(float))
                    if np.isfinite(c):
                        corrs_by_factor[ef].append(c)

        print(f"  {'因子':>20} {'平均相关性':>10} {'样本月数':>8}")
        print(f"  {'-'*40}")
        max_abs_corr = 0
        for ef in existing_factors:
            if corrs_by_factor[ef]:
                avg_corr = np.mean(corrs_by_factor[ef])
                max_abs_corr = max(max_abs_corr, abs(avg_corr))
                flag = " *** HIGH" if abs(avg_corr) > 0.5 else ""
                print(f"  {ef:>20} {avg_corr:>+.4f} {len(corrs_by_factor[ef]):>8}{flag}")
            else:
                print(f"  {ef:>20} {'N/A':>10}")
    else:
        max_abs_corr = 0

    # 7. Gate check
    ic_mean = np.mean(ic_vals)
    corr_pass = max_abs_corr < 0.5
    ic_pass = abs(ic_mean) > 0.015
    print(f"\n{'='*60}")
    print(f"Gate Check:")
    print(f"  IC > 1.5%:       |{ic_mean:.4f}| > 0.015 = {'PASS' if ic_pass else 'FAIL'}")
    print(f"  max_corr < 0.5:  {max_abs_corr:.3f} < 0.5 = {'PASS' if corr_pass else 'FAIL'}")
    print(f"  Overall:         {'PASS' if (ic_pass and corr_pass) else 'FAIL'}")
    print(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()
