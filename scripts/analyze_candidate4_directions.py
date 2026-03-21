#!/usr/bin/env python3
"""候选4方向分析: 比较3个备选方向的IC和与基线相关性。

方向A: 动量反转自适应 (momentum-reversal adaptive)
方向B: 小盘成长 (small-cap growth)
方向C: 大盘质量 (large-cap quality)

核心评估:
1. 各方向核心因子的IC
2. 与基线策略的预期相关性
3. 数据可用性
4. 实战可行性

用法:
    cd /Users/xin/Documents/quantmind-v2 && python scripts/analyze_candidate4_directions.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn


def load_forward_returns(trade_dates: list, horizon: int, conn) -> pd.DataFrame:
    """加载forward excess return（超额CSI300）。"""
    min_date = min(trade_dates)
    max_date = max(trade_dates) + timedelta(days=horizon * 3)

    prices = pd.read_sql(
        """SELECT k.code, k.trade_date,
                  k.close * COALESCE(k.adj_factor, 1) AS adj_close
           FROM klines_daily k
           WHERE k.trade_date >= %s AND k.trade_date <= %s AND k.volume > 0""",
        conn, params=(min_date, max_date),
    )
    prices = prices.pivot(index="trade_date", columns="code", values="adj_close")

    bench = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date >= %s AND trade_date <= %s""",
        conn, params=(min_date, max_date),
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
        bench_ret = bench.loc[fwd_date] / bench.loc[td] - 1 if td in bench.index and fwd_date in bench.index else 0
        excess = stock_ret - bench_ret
        excess.name = td
        results.append(excess)
    return pd.DataFrame(results) if results else pd.DataFrame()


def load_existing_factors(trade_dates: list, conn) -> dict:
    """加载基线因子值（用于相关性计算）。"""
    factors = ["turnover_mean_20", "volatility_20", "reversal_20", "ln_market_cap", "bp_ratio"]
    df = pd.read_sql(
        """SELECT code, trade_date, factor_name, zscore
           FROM factor_values
           WHERE factor_name IN %s AND trade_date IN %s""",
        conn, params=(tuple(factors), tuple(trade_dates)),
    )
    return df


def calc_ic(factor_values: pd.Series, fwd_ret: pd.Series, direction: int = 1) -> float:
    """计算单期截面IC。"""
    common = factor_values.index.intersection(fwd_ret.dropna().index)
    if len(common) < 100:
        return np.nan
    ic, _ = stats.spearmanr(factor_values[common], fwd_ret[common])
    return ic * direction if np.isfinite(ic) else np.nan


def analyze_direction_a(analysis_dates, fwd_rets, existing_df, conn):
    """方向A: 动量反转自适应。

    核心idea:
    - 低波环境用中期动量(momentum_60-120)
    - 高波环境用短期反转(reversal_5-20)
    - 自适应切换权重

    需要检验:
    1. momentum_60/120在A股的IC（可能与基线的reversal_20冲突）
    2. 波动率条件对IC的调节效果
    """
    print("\n" + "="*70)
    print("方向A: 动量反转自适应")
    print("="*70)

    # 计算60日动量 (需要从klines计算)
    print("\n  计算60日/120日动量因子...")

    # 加载价格数据
    prices = pd.read_sql(
        """SELECT code, trade_date, close * COALESCE(adj_factor, 1) AS adj_close
           FROM klines_daily
           WHERE trade_date >= '2020-07-01' AND volume > 0""",
        conn,
    )
    prices_pivot = prices.pivot(index="trade_date", columns="code", values="adj_close")

    # 计算不同窗口的动量
    momentum_60 = prices_pivot.pct_change(60)  # 60日动量
    momentum_120 = prices_pivot.pct_change(120)  # 120日动量

    # 计算市场波动率 (20日滚动std)
    market_ret = prices_pivot.mean(axis=1).pct_change()
    market_vol = market_ret.rolling(20).std()
    vol_median = market_vol.median()

    # IC分析: momentum_60
    ics_m60 = []
    ics_m120 = []
    ics_m60_lowvol = []
    ics_m60_highvol = []

    for td in fwd_rets.index:
        if td not in momentum_60.index:
            continue
        fr = fwd_rets.loc[td].dropna()

        # momentum_60 IC
        m60 = momentum_60.loc[td].dropna()
        common = m60.index.intersection(fr.index)
        if len(common) >= 100:
            ic, _ = stats.spearmanr(m60[common], fr[common])
            if np.isfinite(ic):
                ics_m60.append({"date": td, "ic": ic})
                # 按市场波动率分组
                if td in market_vol.index and not np.isnan(market_vol.loc[td]):
                    if market_vol.loc[td] <= vol_median:
                        ics_m60_lowvol.append(ic)
                    else:
                        ics_m60_highvol.append(ic)

        # momentum_120 IC
        if td in momentum_120.index:
            m120 = momentum_120.loc[td].dropna()
            common = m120.index.intersection(fr.index)
            if len(common) >= 100:
                ic, _ = stats.spearmanr(m120[common], fr[common])
                if np.isfinite(ic):
                    ics_m120.append({"date": td, "ic": ic})

    # 汇总
    if ics_m60:
        m60_ic = np.mean([x["ic"] for x in ics_m60])
        print(f"\n  momentum_60 IC均值: {m60_ic:+.4f} ({m60_ic*100:+.2f}%)")
        print(f"    低波环境IC: {np.mean(ics_m60_lowvol):+.4f}" if ics_m60_lowvol else "    低波: N/A")
        print(f"    高波环境IC: {np.mean(ics_m60_highvol):+.4f}" if ics_m60_highvol else "    高波: N/A")
    if ics_m120:
        m120_ic = np.mean([x["ic"] for x in ics_m120])
        print(f"  momentum_120 IC均值: {m120_ic:+.4f} ({m120_ic*100:+.2f}%)")

    # 与基线因子相关性
    print(f"\n  与基线reversal_20的截面相关性:")
    corrs_rev = []
    for td in analysis_dates[-20:]:
        if td not in momentum_60.index:
            continue
        m60 = momentum_60.loc[td].dropna()
        rev = existing_df[(existing_df["trade_date"] == td) & (existing_df["factor_name"] == "reversal_20")].set_index("code")["zscore"]
        common = m60.index.intersection(rev.index)
        if len(common) >= 100:
            c, _ = stats.spearmanr(m60[common].astype(float), rev[common].astype(float))
            if np.isfinite(c):
                corrs_rev.append(c)
    if corrs_rev:
        print(f"    momentum_60 vs reversal_20: {np.mean(corrs_rev):+.4f}")
        print(f"    (高正相关=与基线重叠，>0.5则无分散价值)")

    return {
        "m60_ic": np.mean([x["ic"] for x in ics_m60]) if ics_m60 else None,
        "m120_ic": np.mean([x["ic"] for x in ics_m120]) if ics_m120 else None,
        "m60_lowvol": np.mean(ics_m60_lowvol) if ics_m60_lowvol else None,
        "m60_highvol": np.mean(ics_m60_highvol) if ics_m60_highvol else None,
        "corr_reversal20": np.mean(corrs_rev) if corrs_rev else None,
    }


def analyze_direction_b(analysis_dates, fwd_rets, existing_df, conn):
    """方向B: 小盘成长。

    核心idea:
    - 小市值(bottom 30%) + 高营收增速
    - 与基线小盘价值形成成长/价值互补

    风险:
    - 小盘因子与基线ln_market_cap高度重叠
    - 成长因子(revenue_yoy)在A股IC弱（候选1验证已知）
    """
    print("\n" + "="*70)
    print("方向B: 小盘成长")
    print("="*70)

    # 从daily_basic加载市值
    print("\n  评估小盘+成长因子组合...")

    # revenue_yoy IC已知 = -0.83% (FAIL)
    print(f"  revenue_yoy IC = -0.83% (候选1已验证, FAIL)")

    # 检查小盘universe内revenue_yoy的IC
    ics_small_rev = []
    for td in fwd_rets.index:
        # 加载市值
        mv = pd.read_sql(
            """SELECT code, total_mv FROM daily_basic WHERE trade_date = %s AND total_mv > 0""",
            conn, params=(td,),
        )
        if mv.empty:
            continue
        mv = mv.set_index("code")["total_mv"]

        # 小盘: bottom 30%
        threshold = mv.quantile(0.30)
        small_caps = mv[mv <= threshold].index

        # 加载revenue_yoy
        fina = pd.read_sql(
            """WITH ranked AS (
                SELECT code, revenue_yoy,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) AS rn
                FROM financial_indicators
                WHERE actual_ann_date <= %s AND revenue_yoy IS NOT NULL
            )
            SELECT code, revenue_yoy FROM ranked WHERE rn = 1""",
            conn, params=(td,),
        )
        if fina.empty:
            continue
        fina = fina.set_index("code")["revenue_yoy"].astype(float)

        # 只看小盘内的IC
        fr = fwd_rets.loc[td].dropna()
        small_fina = fina.reindex(small_caps).dropna()
        common = small_fina.index.intersection(fr.index)
        if len(common) >= 50:
            ic, _ = stats.spearmanr(small_fina[common], fr[common])
            if np.isfinite(ic):
                ics_small_rev.append(ic)

    if ics_small_rev:
        print(f"  小盘内revenue_yoy IC: {np.mean(ics_small_rev):+.4f}")

    # 与ln_market_cap的相关性（核心问题）
    print(f"\n  与基线ln_market_cap的预期重叠:")
    print(f"    小盘成长选股 ⊂ 基线小盘选股，市值维度完全重叠")
    print(f"    唯一差异在成长因子，但revenue_yoy IC不显著")

    return {
        "small_rev_ic": np.mean(ics_small_rev) if ics_small_rev else None,
        "overlap_concern": "HIGH - 市值维度与基线重叠",
    }


def analyze_direction_c(analysis_dates, fwd_rets, existing_df, conn):
    """方向C: 大盘质量。

    核心idea:
    - 大市值(top 30%) + 高ROE + 低波动
    - 完全对冲基线的小盘暴露

    优势: 与基线相关性可能为负（真正的对冲）
    风险: A股大盘质量因子长期跑输小盘
    """
    print("\n" + "="*70)
    print("方向C: 大盘质量")
    print("="*70)

    # 在大盘universe内计算ROE和低波的IC
    ics_large_roe = []
    ics_large_vol = []
    ics_large_composite = []

    for td in fwd_rets.index:
        # 加载市值
        mv = pd.read_sql(
            """SELECT code, total_mv FROM daily_basic WHERE trade_date = %s AND total_mv > 0""",
            conn, params=(td,),
        )
        if mv.empty:
            continue
        mv = mv.set_index("code")["total_mv"]

        # 大盘: top 30%
        threshold = mv.quantile(0.70)
        large_caps = mv[mv >= threshold].index

        # ROE
        fina = pd.read_sql(
            """WITH ranked AS (
                SELECT code, roe,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY report_date DESC) AS rn
                FROM financial_indicators
                WHERE actual_ann_date <= %s AND roe IS NOT NULL
            )
            SELECT code, roe FROM ranked WHERE rn = 1""",
            conn, params=(td,),
        )
        if fina.empty:
            continue
        roe = fina.set_index("code")["roe"].astype(float)

        # 波动率 (从factor_values)
        vol = existing_df[
            (existing_df["trade_date"] == td) & (existing_df["factor_name"] == "volatility_20")
        ].set_index("code")["zscore"]

        fr = fwd_rets.loc[td].dropna()

        # 大盘内ROE IC
        large_roe = roe.reindex(large_caps).dropna()
        common = large_roe.index.intersection(fr.index)
        if len(common) >= 50:
            ic, _ = stats.spearmanr(large_roe[common], fr[common])
            if np.isfinite(ic):
                ics_large_roe.append(ic)

        # 大盘内低波IC
        large_vol = vol.reindex(large_caps).dropna()
        common = large_vol.index.intersection(fr.index)
        if len(common) >= 50:
            ic, _ = stats.spearmanr(large_vol[common], fr[common])
            if np.isfinite(ic):
                ics_large_vol.append(ic * -1)  # 低波方向取反

        # 复合因子: z(ROE) - z(vol) (在大盘内标准化)
        common_all = large_roe.index.intersection(large_vol.index).intersection(fr.index)
        if len(common_all) >= 50:
            z_roe = (large_roe[common_all] - large_roe[common_all].mean()) / large_roe[common_all].std()
            z_vol = (large_vol[common_all] - large_vol[common_all].mean()) / large_vol[common_all].std()
            composite = z_roe - z_vol  # 高ROE + 低波
            ic, _ = stats.spearmanr(composite, fr[common_all])
            if np.isfinite(ic):
                ics_large_composite.append(ic)

    print(f"\n  大盘内因子IC (top 30%市值):")
    if ics_large_roe:
        print(f"    ROE: {np.mean(ics_large_roe):+.4f} ({np.mean(ics_large_roe)*100:+.2f}%)")
    if ics_large_vol:
        print(f"    低波: {np.mean(ics_large_vol):+.4f} ({np.mean(ics_large_vol)*100:+.2f}%)")
    if ics_large_composite:
        print(f"    复合(ROE-Vol): {np.mean(ics_large_composite):+.4f} ({np.mean(ics_large_composite)*100:+.2f}%)")

    # 估算与基线的相关性方向
    print(f"\n  与基线相关性分析:")
    print(f"    基线: 小盘+低波+反转+低换手+高BP → 选的是'便宜安静的小票'")
    print(f"    方向C: 大盘+高ROE+低波 → 选的是'优质稳健的大票'")
    print(f"    市值维度完全相反 → 预期corr < 0 (真对冲)")
    print(f"    但低波维度重叠 → corr不会太负")
    print(f"    预期corr: -0.1 ~ +0.1")

    return {
        "large_roe_ic": np.mean(ics_large_roe) if ics_large_roe else None,
        "large_vol_ic": np.mean(ics_large_vol) if ics_large_vol else None,
        "large_composite_ic": np.mean(ics_large_composite) if ics_large_composite else None,
    }


def main():
    conn = _get_sync_conn()

    # 获取分析日期
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (DATE_TRUNC('month', trade_date))
                  trade_date
           FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date >= '2021-01-01' AND trade_date <= '2025-12-31'
           ORDER BY DATE_TRUNC('month', trade_date) DESC, trade_date DESC"""
    )
    analysis_dates = sorted([r[0] for r in cur.fetchall()])
    print(f"分析日期: {len(analysis_dates)}个月")

    # Forward returns
    print("计算Forward Returns (20日超额)...")
    fwd_rets = load_forward_returns(analysis_dates, horizon=20, conn=conn)
    print(f"Forward returns: {fwd_rets.shape}")

    # 加载现有因子
    existing_df = load_existing_factors(analysis_dates, conn)

    # 分析3个方向
    res_a = analyze_direction_a(analysis_dates, fwd_rets, existing_df, conn)
    res_b = analyze_direction_b(analysis_dates, fwd_rets, existing_df, conn)
    res_c = analyze_direction_c(analysis_dates, fwd_rets, existing_df, conn)

    # 综合比较
    print("\n\n" + "="*70)
    print("综合比较")
    print("="*70)
    print(f"""
  方向A (动量反转自适应):
    momentum_60 IC: {res_a.get('m60_ic', 'N/A')}
    momentum_120 IC: {res_a.get('m120_ic', 'N/A')}
    低波环境m60 IC: {res_a.get('m60_lowvol', 'N/A')}
    高波环境m60 IC: {res_a.get('m60_highvol', 'N/A')}
    vs reversal_20 corr: {res_a.get('corr_reversal20', 'N/A')}
    数据可用: 完全可用(klines_daily)
    实现难度: 中(需要波动率regime切换逻辑)

  方向B (小盘成长):
    小盘内revenue_yoy IC: {res_b.get('small_rev_ic', 'N/A')}
    重叠风险: {res_b.get('overlap_concern', 'N/A')}
    数据可用: 完全可用
    实现难度: 低

  方向C (大盘质量):
    大盘内ROE IC: {res_c.get('large_roe_ic', 'N/A')}
    大盘内低波 IC: {res_c.get('large_vol_ic', 'N/A')}
    大盘复合因子 IC: {res_c.get('large_composite_ic', 'N/A')}
    预期与基线corr: -0.1 ~ +0.1 (真对冲)
    数据可用: 完全可用
    实现难度: 低
""")

    conn.close()


if __name__ == "__main__":
    main()
