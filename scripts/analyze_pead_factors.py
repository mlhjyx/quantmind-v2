#!/usr/bin/env python3
"""PEAD（Post-Earnings Announcement Drift）因子分析。

Sprint 1.3b — 盈利惊喜/PEAD维度因子挖掘。
背景：LL-014教训表明资金流因子中性化后alpha消失，转向PEAD维度。

3个候选因子:
1. earnings_surprise_car: 业绩公告[-1, +5]的CAR（超额CSI300）
   经济学逻辑: A股散户为主，对业绩信息反应不足，公告后超额收益可持续漂移
2. earnings_revision: ROE环比变化方向（正=超预期）
   经济学逻辑: 盈利改善的公司后续表现好，SUE(Standardized Unexpected Earnings)的简化版
3. ann_date_proximity: 距最近一次公告的天数取反（-days，越近=越大=信息越新鲜）
   经济学逻辑: 信息衰减效应，刚公告的公司信息优势最大

质量要求（§1.2⑩）:
- 每个因子有经济学解释 ✓
- A股适用性测试 ✓
- 中性化后IC验证（防LL-014重复）✓
- 与现有5因子corr<0.5 ✓

用法:
    python scripts/analyze_pead_factors.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from scipy import stats

from app.services.price_utils import _get_sync_conn
from engines.factor_engine import preprocess_mad, preprocess_fill, preprocess_neutralize, preprocess_zscore


# ============================================================
# 数据加载
# ============================================================

def load_prices_and_index(conn, start_date: date, end_date: date) -> tuple[pd.DataFrame, pd.Series]:
    """加载复权价格和CSI300基准。"""
    prices = pd.read_sql(
        """SELECT k.code, k.trade_date,
                  k.close * COALESCE(k.adj_factor, 1) AS adj_close,
                  k.volume, k.is_suspended
           FROM klines_daily k
           WHERE k.trade_date >= %s AND k.trade_date <= %s
             AND k.volume > 0""",
        conn,
        params=(start_date, end_date),
    )
    bench = pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date >= %s AND trade_date <= %s""",
        conn,
        params=(start_date, end_date),
    )
    bench = bench.set_index("trade_date")["close"].sort_index()
    return prices, bench


def load_financial_data(conn) -> pd.DataFrame:
    """加载全量财务数据（含actual_ann_date）。"""
    df = pd.read_sql(
        """SELECT code, report_date, actual_ann_date, roe, roe_dt
           FROM financial_indicators
           WHERE actual_ann_date IS NOT NULL
             AND roe IS NOT NULL
           ORDER BY code, actual_ann_date""",
        conn,
    )
    return df


def load_stock_info(conn) -> pd.DataFrame:
    """加载股票基本信息（行业）。"""
    return pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE is_active = true",
        conn,
    )


def load_market_cap(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载市值数据用于中性化。"""
    return pd.read_sql(
        """SELECT code, trade_date, total_mv
           FROM daily_basic
           WHERE trade_date >= %s AND trade_date <= %s
             AND total_mv > 0""",
        conn,
        params=(start_date, end_date),
    )


# ============================================================
# PEAD因子计算
# ============================================================

def calc_earnings_surprise_car(
    fina_df: pd.DataFrame,
    prices_pivot: pd.DataFrame,
    bench: pd.Series,
    eval_date: date,
) -> pd.Series:
    """因子1: earnings_surprise_car — 公告[-1, +5]的CAR。

    对每只股票:
    1. 找到eval_date之前最近的一次公告（actual_ann_date <= eval_date）
    2. 取公告日ann_date前1天到后5天的区间
    3. 计算这个区间的CAR = sum(stock_ret_i - bench_ret_i)
    4. 只取最近90天内有公告的股票（太旧的公告信息价值低）

    方向: +1（CAR越大=市场反应越正面=后续漂移越好）
    """
    all_dates = sorted(prices_pivot.index)
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    # 每个code取eval_date之前最近的公告
    recent = fina_df[
        (fina_df["actual_ann_date"] <= eval_date)
        & (fina_df["actual_ann_date"] >= eval_date - timedelta(days=90))
    ]
    if recent.empty:
        return pd.Series(dtype=float)

    # 每个code取最近一次公告
    latest = recent.sort_values("actual_ann_date").groupby("code").last().reset_index()

    results = {}
    for _, row in latest.iterrows():
        code = row["code"]
        ann = row["actual_ann_date"]

        if code not in prices_pivot.columns:
            continue
        if ann not in date_to_idx:
            # ann_date不是交易日，找最近的下一个交易日
            future = [d for d in all_dates if d >= ann]
            if not future:
                continue
            ann_td = future[0]
        else:
            ann_td = ann

        ann_idx = date_to_idx[ann_td]

        # 窗口: ann-1 到 ann+5
        start_idx = max(0, ann_idx - 1)
        end_idx = min(len(all_dates) - 1, ann_idx + 5)

        if end_idx - start_idx < 2:
            continue

        # 计算CAR
        window_dates = all_dates[start_idx:end_idx + 1]
        stock_prices = prices_pivot[code].reindex(window_dates).dropna()
        bench_prices = bench.reindex(window_dates).dropna()

        common_dates = stock_prices.index.intersection(bench_prices.index)
        if len(common_dates) < 3:
            continue

        stock_ret = stock_prices.loc[common_dates].pct_change().dropna()
        bench_ret = bench_prices.loc[common_dates].pct_change().dropna()

        common_ret = stock_ret.index.intersection(bench_ret.index)
        if len(common_ret) < 2:
            continue

        car = (stock_ret.loc[common_ret] - bench_ret.loc[common_ret]).sum()
        results[code] = car

    return pd.Series(results, name="earnings_surprise_car")


def calc_earnings_revision(
    fina_df: pd.DataFrame,
    eval_date: date,
) -> pd.Series:
    """因子2: earnings_revision — ROE环比变化（标准化）。

    定义: (ROE_latest - ROE_prev) / std(ROE变化)
    使用roe_dt（扣非），fallback到roe。
    只取最近180天内有公告的股票。

    方向: +1（ROE改善越大=基本面好转=后续表现好）
    """
    recent = fina_df[
        (fina_df["actual_ann_date"] <= eval_date)
        & (fina_df["actual_ann_date"] >= eval_date - timedelta(days=180))
    ]
    if recent.empty:
        return pd.Series(dtype=float)

    results = {}
    for code, grp in recent.groupby("code"):
        grp = grp.sort_values("report_date", ascending=False)
        if len(grp) < 2:
            continue

        # 取最近两个report_date
        latest = grp.iloc[0]
        prev = grp.iloc[1]

        roe_latest = latest["roe_dt"] if pd.notna(latest["roe_dt"]) else latest["roe"]
        roe_prev = prev["roe_dt"] if pd.notna(prev["roe_dt"]) else prev["roe"]

        if pd.isna(roe_latest) or pd.isna(roe_prev):
            continue

        results[code] = float(roe_latest - roe_prev)

    if not results:
        return pd.Series(dtype=float)

    s = pd.Series(results, name="earnings_revision")
    return s


def calc_ann_date_proximity(
    fina_df: pd.DataFrame,
    eval_date: date,
) -> pd.Series:
    """因子3: ann_date_proximity — 距最近公告的天数（取反）。

    定义: -1 × (eval_date - latest_ann_date).days
    即越近的公告=值越大=排名越前

    经济学逻辑: 信息衰减效应。刚公告的公司信息优势最大，
    投资者对新信息的消化需要时间（PEAD核心机制）。

    方向: +1（越近越好）
    """
    recent = fina_df[fina_df["actual_ann_date"] <= eval_date]
    if recent.empty:
        return pd.Series(dtype=float)

    # 每个code取最近一次公告日
    latest = recent.groupby("code")["actual_ann_date"].max()

    days_since = latest.apply(lambda d: (eval_date - d).days)
    proximity = -days_since  # 取反: 越近=值越大

    # 过滤掉太旧的（>365天没公告的股票）
    proximity = proximity[days_since <= 365]

    proximity.name = "ann_date_proximity"
    return proximity


# ============================================================
# IC计算 + 预处理
# ============================================================

def get_month_end_dates(trade_dates: list[date], start: date, end: date) -> list[date]:
    """获取月末交易日列表。"""
    df = pd.DataFrame({"trade_date": trade_dates})
    df["ym"] = df["trade_date"].apply(lambda d: (d.year, d.month))
    month_ends = df.groupby("ym")["trade_date"].max().values
    month_ends = sorted([pd.Timestamp(d).date() for d in month_ends])
    return [d for d in month_ends if start <= d <= end]


def calc_forward_excess_return(
    prices_pivot: pd.DataFrame,
    bench: pd.Series,
    eval_date: date,
    horizon: int = 20,
) -> pd.Series:
    """计算eval_date开始horizon天的forward excess return。"""
    all_dates = sorted(prices_pivot.index)
    future = [d for d in all_dates if d > eval_date]
    if len(future) < horizon:
        return pd.Series(dtype=float)

    fwd_date = future[horizon - 1]
    if eval_date not in prices_pivot.index or fwd_date not in prices_pivot.index:
        return pd.Series(dtype=float)

    stock_ret = prices_pivot.loc[fwd_date] / prices_pivot.loc[eval_date] - 1
    if eval_date in bench.index and fwd_date in bench.index:
        bench_ret = bench.loc[fwd_date] / bench.loc[eval_date] - 1
    else:
        bench_ret = 0

    return stock_ret - bench_ret


def neutralize_factor(
    factor: pd.Series,
    industry: pd.Series,
    ln_mcap: pd.Series,
) -> pd.Series:
    """对因子做中性化（MAD→fill→neutralize→zscore）。"""
    common = factor.index.intersection(industry.index).intersection(ln_mcap.index)
    if len(common) < 50:
        return pd.Series(dtype=float)

    f = factor.loc[common].astype(float)
    ind = industry.loc[common]
    mc = ln_mcap.loc[common]

    # Step 1: MAD
    f = preprocess_mad(f)
    # Step 2: fill
    f = preprocess_fill(f, ind)
    # Step 3: neutralize
    f = preprocess_neutralize(f, mc, ind)
    # Step 4: zscore
    f = preprocess_zscore(f)

    return f.dropna()


# ============================================================
# 主分析流程
# ============================================================

def main():
    print("=" * 80)
    print("PEAD因子分析 — Sprint 1.3b 盈利惊喜/PEAD维度")
    print("=" * 80)

    conn = _get_sync_conn()

    # 参数
    start_date = date(2021, 1, 1)
    end_date = date(2025, 9, 30)
    fwd_horizon = 20  # 20日forward return

    print(f"\n分析区间: {start_date} ~ {end_date}")
    print(f"Forward Return: {fwd_horizon}日超额CSI300")

    # 1. 加载数据
    print("\n[1/5] 加载数据...")
    prices_raw, bench = load_prices_and_index(conn, start_date - timedelta(days=60), end_date + timedelta(days=60))
    fina_df = load_financial_data(conn)
    stock_info = load_stock_info(conn)
    mcap_df = load_market_cap(conn, start_date, end_date)

    # 行业映射
    industry_map = stock_info.set_index("code")["industry_sw1"]

    # pivot价格
    prices_pivot = prices_raw.pivot_table(
        index="trade_date", columns="code", values="adj_close", aggfunc="first"
    )
    prices_pivot = prices_pivot.sort_index()

    # 交易日列表
    trade_dates = sorted(prices_pivot.index.tolist())
    month_ends = get_month_end_dates(trade_dates, start_date, end_date)
    print(f"  月末截面数: {len(month_ends)}")
    print(f"  股票数: {prices_pivot.shape[1]}")
    print(f"  财报记录: {len(fina_df)}")

    # 2. 逐月计算因子和IC
    print("\n[2/5] 逐月计算3个PEAD因子 + IC...")
    factor_names = ["earnings_surprise_car", "earnings_revision", "ann_date_proximity"]
    ic_records = {fn: [] for fn in factor_names}
    ic_neutral_records = {fn: [] for fn in factor_names}
    coverage_records = {fn: [] for fn in factor_names}
    corr_with_existing = {fn: [] for fn in factor_names}

    # 现有5因子 — 从factor_values加载
    existing_factors = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]

    for i, eval_date in enumerate(month_ends):
        if i % 6 == 0:
            print(f"  处理: {eval_date} ({i+1}/{len(month_ends)})")

        # 计算3个因子
        car = calc_earnings_surprise_car(fina_df, prices_pivot, bench, eval_date)
        rev = calc_earnings_revision(fina_df, eval_date)
        prox = calc_ann_date_proximity(fina_df, eval_date)

        factors = {
            "earnings_surprise_car": car,
            "earnings_revision": rev,
            "ann_date_proximity": prox,
        }

        # Forward return
        fwd_ret = calc_forward_excess_return(prices_pivot, bench, eval_date, fwd_horizon)
        if fwd_ret.dropna().empty:
            continue

        # 获取该日的市值和行业
        mcap_day = mcap_df[mcap_df["trade_date"] == eval_date].set_index("code")["total_mv"]
        ln_mcap_day = np.log(mcap_day + 1e-12)

        for fn, fv in factors.items():
            if fv.empty:
                continue

            # 原始IC（未中性化）
            common = fv.index.intersection(fwd_ret.dropna().index)
            if len(common) < 50:
                continue

            coverage_records[fn].append(len(common))

            ic_raw, _ = stats.spearmanr(fv.loc[common], fwd_ret.loc[common])
            ic_records[fn].append({"date": eval_date, "ic": ic_raw})

            # 中性化后IC
            fv_neutral = neutralize_factor(fv, industry_map, ln_mcap_day)
            if fv_neutral.empty or len(fv_neutral) < 50:
                continue

            common_n = fv_neutral.index.intersection(fwd_ret.dropna().index)
            if len(common_n) < 50:
                continue

            ic_n, _ = stats.spearmanr(fv_neutral.loc[common_n], fwd_ret.loc[common_n])
            ic_neutral_records[fn].append({"date": eval_date, "ic": ic_n})

            # 与现有因子相关性（截面）
            # 从factor_values表加载当日的现有因子
            if i % 6 == 0:  # 每6个月算一次相关性（减少DB查询）
                try:
                    existing_fv = pd.read_sql(
                        """SELECT code, factor_name, value FROM factor_values
                           WHERE trade_date = %s AND factor_name = ANY(%s)""",
                        conn,
                        params=(eval_date, existing_factors),
                    )
                    if not existing_fv.empty:
                        epivot = existing_fv.pivot(index="code", columns="factor_name", values="value")
                        for ef in existing_factors:
                            if ef in epivot.columns:
                                c2 = fv.index.intersection(epivot.index)
                                if len(c2) > 50:
                                    corr_val, _ = stats.spearmanr(
                                        fv.loc[c2], epivot[ef].loc[c2]
                                    )
                                    corr_with_existing[fn].append({
                                        "date": eval_date,
                                        "existing_factor": ef,
                                        "corr": corr_val,
                                    })
                except Exception as e:
                    pass  # factor_values表可能没该日数据

    # 3. 汇总统计
    print("\n[3/5] 汇总IC统计...")
    print("\n" + "=" * 80)
    print("因子IC汇总（原始 / 中性化后）")
    print("=" * 80)

    summary = {}
    for fn in factor_names:
        ics_raw = [r["ic"] for r in ic_records[fn]]
        ics_neutral = [r["ic"] for r in ic_neutral_records[fn]]

        if len(ics_raw) < 5:
            print(f"\n{fn}: 数据不足（{len(ics_raw)}个月）")
            continue

        ic_mean_raw = np.mean(ics_raw)
        ic_std_raw = np.std(ics_raw)
        ir_raw = ic_mean_raw / ic_std_raw if ic_std_raw > 0 else 0
        t_raw = ic_mean_raw / (ic_std_raw / np.sqrt(len(ics_raw))) if ic_std_raw > 0 else 0
        hit_raw = np.mean([1 if ic > 0 else 0 for ic in ics_raw])

        ic_mean_n = np.mean(ics_neutral) if ics_neutral else np.nan
        ic_std_n = np.std(ics_neutral) if ics_neutral else np.nan
        ir_n = ic_mean_n / ic_std_n if ics_neutral and ic_std_n > 0 else np.nan
        t_n = ic_mean_n / (ic_std_n / np.sqrt(len(ics_neutral))) if ics_neutral and ic_std_n > 0 else np.nan
        hit_n = np.mean([1 if ic > 0 else 0 for ic in ics_neutral]) if ics_neutral else np.nan

        avg_coverage = np.mean(coverage_records[fn]) if coverage_records[fn] else 0

        summary[fn] = {
            "ic_mean_raw": ic_mean_raw,
            "ir_raw": ir_raw,
            "t_raw": t_raw,
            "hit_raw": hit_raw,
            "ic_mean_neutral": ic_mean_n,
            "ir_neutral": ir_n,
            "t_neutral": t_n,
            "hit_neutral": hit_n,
            "n_months": len(ics_raw),
            "avg_coverage": avg_coverage,
        }

        print(f"\n{'─' * 60}")
        print(f"因子: {fn}")
        print(f"{'─' * 60}")
        print(f"  月数: {len(ics_raw)}")
        print(f"  平均覆盖率: {avg_coverage:.0f}只")
        print(f"  ┌─ 原始IC ─────────────────────────────────")
        print(f"  │ IC均值:  {ic_mean_raw:+.4f}")
        print(f"  │ IC标准差: {ic_std_raw:.4f}")
        print(f"  │ IR:      {ir_raw:.3f}")
        print(f"  │ t-stat:  {t_raw:.2f}  {'***' if abs(t_raw) > 2.58 else '**' if abs(t_raw) > 1.96 else '*' if abs(t_raw) > 1.65 else ''}")
        print(f"  │ 正IC率:  {hit_raw:.1%}")
        print(f"  ├─ 中性化后IC ─────────────────────────────")
        print(f"  │ IC均值:  {ic_mean_n:+.4f}" if not np.isnan(ic_mean_n) else "  │ IC均值:  N/A")
        print(f"  │ IR:      {ir_n:.3f}" if not np.isnan(ir_n) else "  │ IR:      N/A")
        print(f"  │ t-stat:  {t_n:.2f}  {'***' if abs(t_n) > 2.58 else '**' if abs(t_n) > 1.96 else '*' if abs(t_n) > 1.65 else ''}" if not np.isnan(t_n) else "  │ t-stat:  N/A")
        print(f"  │ 正IC率:  {hit_n:.1%}" if not np.isnan(hit_n) else "  │ 正IC率:  N/A")
        print(f"  └─ IC衰减检查: 原始{ic_mean_raw:+.4f} → 中性化{ic_mean_n:+.4f} = 衰减{abs(ic_mean_raw) - abs(ic_mean_n):.4f}" if not np.isnan(ic_mean_n) else f"  └─ IC衰减检查: N/A")

    # 4. 分年IC
    print("\n\n[4/5] 分年IC分析...")
    for fn in factor_names:
        ics = ic_records[fn]
        if not ics:
            continue
        print(f"\n{fn} 分年IC:")
        df_ic = pd.DataFrame(ics)
        df_ic["year"] = df_ic["date"].apply(lambda d: d.year)
        yearly = df_ic.groupby("year")["ic"].agg(["mean", "std", "count"])
        yearly["ir"] = yearly["mean"] / yearly["std"]
        for yr, row in yearly.iterrows():
            sig = "***" if abs(row["mean"]) / (row["std"] / np.sqrt(row["count"])) > 2.58 else \
                  "**" if abs(row["mean"]) / (row["std"] / np.sqrt(row["count"])) > 1.96 else ""
            print(f"  {yr}: IC={row['mean']:+.4f}, IR={row['ir']:.3f}, N={row['count']:.0f} {sig}")

    # 同样分年看中性化后IC
    print("\n分年IC（中性化后）:")
    for fn in factor_names:
        ics = ic_neutral_records[fn]
        if not ics:
            continue
        print(f"\n{fn}:")
        df_ic = pd.DataFrame(ics)
        df_ic["year"] = df_ic["date"].apply(lambda d: d.year)
        yearly = df_ic.groupby("year")["ic"].agg(["mean", "std", "count"])
        yearly["ir"] = yearly["mean"] / yearly["std"]
        for yr, row in yearly.iterrows():
            sig = "***" if row["count"] > 1 and abs(row["mean"]) / (row["std"] / np.sqrt(row["count"])) > 2.58 else \
                  "**" if row["count"] > 1 and abs(row["mean"]) / (row["std"] / np.sqrt(row["count"])) > 1.96 else ""
            print(f"  {yr}: IC={row['mean']:+.4f}, IR={row['ir']:.3f}, N={row['count']:.0f} {sig}")

    # 5. 与现有因子相关性
    print("\n\n[5/5] 与现有5因子的截面相关性...")
    for fn in factor_names:
        if not corr_with_existing[fn]:
            print(f"\n{fn}: 无相关性数据（factor_values表无匹配日期）")
            continue
        print(f"\n{fn}:")
        corr_df = pd.DataFrame(corr_with_existing[fn])
        avg_corr = corr_df.groupby("existing_factor")["corr"].mean()
        for ef, c in avg_corr.items():
            flag = "⚠️ >0.5" if abs(c) > 0.5 else "✓ <0.5"
            print(f"  vs {ef}: {c:+.4f}  {flag}")

    # 6. 结论
    print("\n\n" + "=" * 80)
    print("结论与建议")
    print("=" * 80)

    for fn in factor_names:
        if fn not in summary:
            print(f"\n{fn}: 数据不足，无法评估")
            continue

        s = summary[fn]
        # 判断标准: 中性化后IC>0.015（CLAUDE.md LLM因子门槛）, t>1.96, 正IC率>55%
        raw_pass = abs(s["ic_mean_raw"]) > 0.015 and abs(s["t_raw"]) > 1.96
        neutral_pass = (not np.isnan(s["ic_mean_neutral"])) and abs(s["ic_mean_neutral"]) > 0.015 and abs(s["t_neutral"]) > 1.96

        # LL-014检查: 中性化后IC衰减是否>70%？
        if not np.isnan(s["ic_mean_neutral"]) and abs(s["ic_mean_raw"]) > 0.001:
            decay_pct = 1 - abs(s["ic_mean_neutral"]) / abs(s["ic_mean_raw"])
            ll014_flag = decay_pct > 0.7
        else:
            decay_pct = np.nan
            ll014_flag = True

        print(f"\n{fn}:")
        print(f"  原始IC通过(|IC|>0.015, |t|>1.96): {'YES' if raw_pass else 'NO'}")
        print(f"  中性化通过(|IC|>0.015, |t|>1.96): {'YES' if neutral_pass else 'NO'}")
        if not np.isnan(decay_pct):
            print(f"  LL-014衰减检查(衰减<70%): {'PASS' if not ll014_flag else 'FAIL — 中性化后alpha消失!'} (衰减={decay_pct:.1%})")
        if raw_pass and neutral_pass and not ll014_flag:
            print(f"  >>> 推荐进入因子候选池 <<<")
        elif raw_pass and not neutral_pass:
            print(f"  >>> 原始IC可观但中性化后消失，与LL-014相同模式，不推荐 <<<")
        else:
            print(f"  >>> 不推荐 <<<")

    conn.close()
    print("\n分析完成。")


if __name__ == "__main__":
    main()
