#!/usr/bin/env python3
"""方案7: 基本面动量因子(3季度移动平均ROE变化) IC快筛。

小样本快筛: 2024年12个月末, 100只股票样本。
通过标准: IC > 2% 且方向正确(正IC)。

用法:
    cd D:/quantmind-v2
    python scripts/screen_roe_momentum_3q.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd
from engines.financial_factors import calc_roe_momentum_3q, load_financial_pit
from scipy import stats

from app.services.price_utils import _get_sync_conn


def get_monthly_trade_dates(conn, year: int = 2024) -> list[date]:
    """获取指定年份每月最后一个交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE is_trading_day = true
             AND trade_date >= %s AND trade_date <= %s
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC""",
        (date(year, 1, 1), date(year, 12, 31)),
    )
    dates = sorted([row[0] for row in cur.fetchall()])
    cur.close()
    return dates


def sample_stocks(conn, n: int = 100) -> list[str]:
    """随机采样n只股票(有财务数据且活跃)。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT code FROM financial_indicators
           WHERE actual_ann_date >= '2023-01-01'
           ORDER BY code
           LIMIT %s""",
        (n,),
    )
    codes = [row[0] for row in cur.fetchall()]
    cur.close()
    return codes


def load_forward_returns(
    trade_dates: list[date], codes: list[str], horizon: int, conn
) -> dict[date, pd.Series]:
    """加载forward excess return (vs CSI300)。"""
    min_date = min(trade_dates)
    max_date = max(trade_dates) + timedelta(days=horizon * 3)

    # 使用参数化查询避免SQL注入
    placeholders = ",".join(["%s"] * len(codes))

    prices = pd.read_sql(
        f"""SELECT k.code, k.trade_date,
                  k.close * COALESCE(k.adj_factor, 1) AS adj_close
           FROM klines_daily k
           WHERE k.trade_date >= %s AND k.trade_date <= %s
             AND k.volume > 0
             AND k.code IN ({placeholders})""",
        conn,
        params=(min_date, max_date, *codes),
    )
    prices_pivot = prices.pivot(index="trade_date", columns="code", values="adj_close")

    bench = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date >= %s AND trade_date <= %s""",
        conn,
        params=(min_date, max_date),
    )
    bench = bench.set_index("trade_date")["close"]

    all_dates = sorted(prices_pivot.index)
    fwd_returns: dict[date, pd.Series] = {}

    for td in trade_dates:
        if td not in prices_pivot.index:
            continue
        future = [d for d in all_dates if d > td]
        if len(future) < horizon:
            continue
        fwd_date = future[horizon - 1]

        stock_ret = prices_pivot.loc[fwd_date] / prices_pivot.loc[td] - 1
        bench_ret = (
            bench.loc[fwd_date] / bench.loc[td] - 1
            if td in bench.index and fwd_date in bench.index
            else 0
        )
        fwd_returns[td] = stock_ret - bench_ret

    return fwd_returns


def main():
    conn = _get_sync_conn()

    # 1. 获取月末日期
    trade_dates = get_monthly_trade_dates(conn, 2024)
    print(f"分析日期: {len(trade_dates)}个月末 ({trade_dates[0]} ~ {trade_dates[-1]})")

    # 2. 采样股票
    codes = sample_stocks(conn, 100)
    print(f"样本股票: {len(codes)}只")

    # 3. 加载forward returns (20日)
    print("加载forward returns...")
    fwd_returns = load_forward_returns(trade_dates, codes, 20, conn)
    print(f"  有效日期: {len(fwd_returns)}个")

    # 4. 逐月计算因子 + IC
    print("\n逐月计算 roe_momentum_3q 因子...")
    ics = []
    n_stocks_per_date = []

    for td in trade_dates:
        if td not in fwd_returns:
            print(f"  {td}: 无forward return, 跳过")
            continue

        fina_df = load_financial_pit(td, conn)
        if fina_df.empty:
            print(f"  {td}: 无PIT数据, 跳过")
            continue

        # 过滤到样本股票
        fina_df = fina_df[fina_df["code"].isin(codes)]

        factor_vals = calc_roe_momentum_3q(fina_df)
        fr = fwd_returns[td]

        # 交集
        common = factor_vals.index.intersection(fr.dropna().index)
        n_common = len(common)
        n_stocks_per_date.append(n_common)

        if n_common < 30:
            print(f"  {td}: 样本{n_common}<30, 跳过")
            continue

        ic, pval = stats.spearmanr(factor_vals[common], fr[common])
        if np.isfinite(ic):
            ics.append({"date": td, "ic": ic, "pval": pval, "n": n_common})
            print(f"  {td}: IC={ic:+.4f} (p={pval:.3f}, n={n_common})")

    conn.close()

    # 5. 汇总统计
    if not ics:
        print("\n*** FAIL: 无有效IC数据 ***")
        return

    ic_df = pd.DataFrame(ics)
    ic_vals = ic_df["ic"].values
    ic_mean = float(np.mean(ic_vals))
    ic_std = float(np.std(ic_vals))
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    hit_rate = float(np.mean(ic_vals > 0))

    print("\n" + "=" * 60)
    print("roe_momentum_3q IC快筛结果 (2024, 小样本)")
    print("=" * 60)
    print(f"  有效月数:   {len(ics)}")
    print(f"  平均样本:   {np.mean(n_stocks_per_date):.0f}只")
    print(f"  IC mean:    {ic_mean:+.4f} ({ic_mean*100:+.2f}%)")
    print(f"  IC std:     {ic_std:.4f}")
    print(f"  ICIR:       {ic_ir:.3f}")
    print(f"  Hit rate:   {hit_rate:.1%}")
    print(f"  t-stat:     {ic_mean / (ic_std / np.sqrt(len(ics))):.3f}" if ic_std > 0 else "  t-stat:     N/A")

    # 6. 判定
    print("\n--- 判定 ---")
    if ic_mean > 0.02:
        print(f"  PASS: IC={ic_mean*100:.2f}% > 2%, 方向正确(正)")
        print("  → 建议进入F1 fold LightGBM测试")
    elif ic_mean > 0.01:
        print(f"  MARGINAL: IC={ic_mean*100:.2f}%, 在1-2%之间")
        print("  → 可考虑扩大样本全量验证")
    else:
        print(f"  FAIL: IC={ic_mean*100:.2f}% < 1%")
        print("  → 不进入LightGBM测试")


if __name__ == "__main__":
    main()
