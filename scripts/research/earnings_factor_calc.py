#!/usr/bin/env python3
"""盈利公告因子(SUE) — 计算 + EVENT IC评估 + 入库 + 报告。

经济机制: 盈利惊喜(YoY) → PEAD漂移 → 正SUE=超预期=看多
因子类型: EVENT（非RANKING截面），用模板6 PEAD事件驱动回测
方向: +1（SUE > 0 = 正漂移）

产出:
  - cache/earnings_sue.parquet: SUE因子值 (ann信号)
  - factor_ic_history: EVENT IC入库（铁律11）
  - 终端研究报告

用法:
    python scripts/research/earnings_factor_calc.py
    python scripts/research/earnings_factor_calc.py --dry-run   # 不入库
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import numpy as np
import pandas as pd
import psycopg2.extras
from scipy import stats

from app.services.price_utils import _get_sync_conn

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"

# ── 配置 ─────────────────────────────────────────────
HOLD_DAYS = [5, 7, 10, 15, 20]
MIN_SEASONS = 4          # 标准化最低季度数
SUE_CLIP = 5.0           # 极值截断
MIN_EVENTS_FOR_IC = 50   # IC计算最低事件数
FACTOR_DIRECTION = 1     # +1: 正surprise = 看多

# IC slot映射备注（decay_level字段VARCHAR(10)，存"event"标识）
# 完整映射: ic_1d=7d, ic_5d=5d, ic_10d=10d, ic_20d=20d, ic_abs_1d=15d
IC_SLOT_NOTE = "event"  # decay_level标识EVENT类型IC


# ═══════════════════════════════════════════════════════
# Step A: SUE计算
# ═══════════════════════════════════════════════════════
def compute_sue(conn) -> pd.DataFrame:
    """计算标准化盈利意外(SUE)。

    SUE = eps_surprise_pct / std(该股过去8季eps_surprise_pct)
    PIT: 用trade_date (f_ann_date后第一个交易日)
    去重: 同一(ts_code, end_date)取f_ann_date最早的（首次披露）

    Returns:
        DataFrame[ts_code, end_date, trade_date, report_type, sue, eps_surprise_pct]
    """
    print("\n[Step A] 计算SUE...")

    df = pd.read_sql(
        """SELECT ts_code, end_date, f_ann_date, trade_date,
                  eps_surprise_pct, report_type
           FROM earnings_announcements
           WHERE eps_surprise_pct IS NOT NULL
             AND trade_date IS NOT NULL
           ORDER BY ts_code, end_date, f_ann_date""",
        conn,
    )
    print(f"  原始行数(eps_surprise_pct非空): {len(df):,}")

    # 去重: 同一(ts_code, end_date)取f_ann_date最早的（首次披露信息冲击）
    df = df.sort_values(["ts_code", "end_date", "f_ann_date"])
    df = df.drop_duplicates(subset=["ts_code", "end_date"], keep="first")
    print(f"  去重后: {len(df):,}")

    # 按股票+时间排序，计算滚动标准差（过去8季）
    df = df.sort_values(["ts_code", "end_date"]).reset_index(drop=True)

    sue_values = []
    for ts_code, grp in df.groupby("ts_code"):
        grp = grp.sort_values("end_date").reset_index(drop=True)
        vals = grp["eps_surprise_pct"].values

        for i in range(len(grp)):
            # 过去8季（不含当前）的surprise标准差
            lookback = vals[max(0, i - 8) : i]
            if len(lookback) < MIN_SEASONS:
                sue_values.append(np.nan)
                continue
            std_val = np.std(lookback, ddof=1)
            if std_val < 1e-8:  # 标准差太小，跳过
                sue_values.append(np.nan)
                continue
            sue = vals[i] / std_val
            sue_values.append(np.clip(sue, -SUE_CLIP, SUE_CLIP))

    df["sue"] = sue_values
    valid = df.dropna(subset=["sue"]).copy()
    print(f"  有效SUE: {len(valid):,} (需>=4季历史)")
    print(f"  SUE分布: mean={valid['sue'].mean():.3f}, std={valid['sue'].std():.3f}, "
          f"min={valid['sue'].min():.2f}, max={valid['sue'].max():.2f}")

    # report_type分布
    rt_counts = valid["report_type"].value_counts().sort_index()
    for rt, cnt in rt_counts.items():
        print(f"    {rt}: {cnt:,}")

    return valid[["ts_code", "end_date", "trade_date", "report_type", "sue", "eps_surprise_pct"]]


# ═══════════════════════════════════════════════════════
# Step B: Forward Return（EVENT per-event）
# ═══════════════════════════════════════════════════════
def compute_event_forward_returns(
    sue_df: pd.DataFrame, conn
) -> pd.DataFrame:
    """计算每个事件的T+1到T+h复权收益。

    T = trade_date (f_ann_date后第一个交易日)
    Entry = adj_close[T+1]（A股T+1制度）
    Exit = adj_close[T+h]
    forward_return = Exit / Entry - 1

    停牌处理: T+1停牌则用复牌后首日; 连续停牌>hold_days则剔除
    """
    print("\n[Step B] 计算EVENT forward returns...")

    # 获取所有需要的trade_date范围
    min_date = sue_df["trade_date"].min()
    max_date = sue_df["trade_date"].max()
    max_hold = max(HOLD_DAYS)

    # 加载复权价格（限时间范围，避免OOM）
    prices = pd.read_sql(
        """SELECT code, trade_date,
                  close * COALESCE(adj_factor, 1) AS adj_close
           FROM klines_daily
           WHERE trade_date >= %s
             AND trade_date <= %s + INTERVAL '%s days'
             AND volume > 0""",
        conn,
        params=(min_date, max_date, max_hold + 30),
    )
    print(f"  价格数据: {len(prices):,}行, {prices['code'].nunique()}只股票")

    # 构建交易日序列
    trading_dates = sorted(prices["trade_date"].unique())
    td_index = {d: i for i, d in enumerate(trading_dates)}

    # 按股票构建价格查找表
    price_lookup: dict[tuple, float] = {}
    for _, row in prices.iterrows():
        price_lookup[(row["code"], row["trade_date"])] = row["adj_close"]

    # ts_code → code 转换: earnings用 000001.SZ, klines_daily用 000001
    # 检测格式差异并建立映射
    sample_codes = prices["code"].head(3).tolist()
    sue_sample = sue_df["ts_code"].head(3).tolist()
    print(f"  klines_daily code样例: {sample_codes}")
    print(f"  earnings ts_code样例: {sue_sample}")

    # 判断是否需要去后缀
    needs_strip = any("." in str(c) for c in sue_sample) and not any("." in str(c) for c in sample_codes)
    if needs_strip:
        print("  代码格式转换: ts_code去后缀(.SZ/.SH/.BJ)")

    results = []
    skipped_no_price = 0
    skipped_suspended = 0

    for _, event in sue_df.iterrows():
        code = event["ts_code"]
        if needs_strip:
            code = code.split(".")[0]  # 000001.SZ → 000001
        t_date = event["trade_date"]

        if t_date not in td_index:
            skipped_no_price += 1
            continue

        t_idx = td_index[t_date]

        # T+1 entry price (A股T+1制度)
        entry_idx = t_idx + 1
        if entry_idx >= len(trading_dates):
            skipped_no_price += 1
            continue

        entry_date = trading_dates[entry_idx]
        entry_price = price_lookup.get((code, entry_date))

        # 如果T+1停牌，找复牌后首日（最多再看5天）
        if entry_price is None:
            found = False
            for offset in range(2, 7):
                alt_idx = t_idx + offset
                if alt_idx >= len(trading_dates):
                    break
                alt_date = trading_dates[alt_idx]
                alt_price = price_lookup.get((code, alt_date))
                if alt_price is not None:
                    entry_date = alt_date
                    entry_price = alt_price
                    entry_idx = alt_idx
                    found = True
                    break
            if not found:
                skipped_suspended += 1
                continue

        row_data = {
            "ts_code": code,
            "end_date": event["end_date"],
            "trade_date": t_date,
            "report_type": event["report_type"],
            "sue": event["sue"],
        }

        for h in HOLD_DAYS:
            exit_idx = entry_idx + h - 1  # h trading days from entry
            if exit_idx >= len(trading_dates):
                row_data[f"fwd_{h}d"] = np.nan
                continue
            exit_date = trading_dates[exit_idx]
            exit_price = price_lookup.get((code, exit_date))
            if exit_price is None:
                row_data[f"fwd_{h}d"] = np.nan
            else:
                row_data[f"fwd_{h}d"] = exit_price / entry_price - 1

        results.append(row_data)

    result_df = pd.DataFrame(results)
    print(f"  有效事件: {len(result_df):,}")
    print(f"  跳过(无价格): {skipped_no_price}, 跳过(停牌): {skipped_suspended}")

    return result_df


# ═══════════════════════════════════════════════════════
# Step C: EVENT IC计算
# ═══════════════════════════════════════════════════════
def compute_event_ic(
    event_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算EVENT IC: spearman_corr(SUE, forward_return) 按report_type分组。

    Returns:
        (ic_summary, yearly_breakdown)
        ic_summary: report_type × hold_days 的 IC/t-stat 矩阵
        yearly_breakdown: Q1的年度IC分解
    """
    print("\n[Step C] 计算EVENT IC...")

    report_types = ["Q1", "H1", "Q3", "Y", "ALL"]
    ic_records = []

    for rt in report_types:
        if rt == "ALL":
            subset = event_df
        else:
            subset = event_df[event_df["report_type"] == rt]

        row = {"report_type": rt, "N": len(subset)}
        for h in HOLD_DAYS:
            col = f"fwd_{h}d"
            valid = subset[["sue", col]].dropna()
            n = len(valid)

            if n < MIN_EVENTS_FOR_IC:
                row[f"ic_{h}d"] = np.nan
                row[f"t_{h}d"] = np.nan
                row[f"n_{h}d"] = n
                continue

            ic_val, p_val = stats.spearmanr(valid["sue"], valid[col])
            ic_val = float(ic_val) if np.isfinite(ic_val) else np.nan

            # t-stat = IC * sqrt(N) / sqrt(1 - IC^2)
            if ic_val is not None and not np.isnan(ic_val) and abs(ic_val) < 1.0:
                t_stat = ic_val * np.sqrt(n) / np.sqrt(1 - ic_val ** 2)
            else:
                t_stat = np.nan

            row[f"ic_{h}d"] = ic_val
            row[f"t_{h}d"] = t_stat
            row[f"n_{h}d"] = n

        ic_records.append(row)

    ic_summary = pd.DataFrame(ic_records)

    # ── 年度分解（所有report_type都做） ───────────────
    event_df = event_df.copy()
    event_df["year"] = pd.to_datetime(event_df["trade_date"]).dt.year

    yearly_records = []
    for rt in ["Q1", "H1", "Q3", "Y"]:
        subset = event_df[event_df["report_type"] == rt]
        for year, ygrp in subset.groupby("year"):
            for h in HOLD_DAYS:
                col = f"fwd_{h}d"
                valid = ygrp[["sue", col]].dropna()
                n = len(valid)
                if n < 30:
                    ic_val = np.nan
                    t_stat = np.nan
                else:
                    ic_val, _ = stats.spearmanr(valid["sue"], valid[col])
                    ic_val = float(ic_val) if np.isfinite(ic_val) else np.nan
                    if ic_val is not None and not np.isnan(ic_val) and abs(ic_val) < 1.0:
                        t_stat = ic_val * np.sqrt(n) / np.sqrt(1 - ic_val ** 2)
                    else:
                        t_stat = np.nan

                yearly_records.append({
                    "report_type": rt,
                    "year": int(year),
                    "hold_days": h,
                    "ic": ic_val,
                    "t_stat": t_stat,
                    "n": n,
                })

    yearly_df = pd.DataFrame(yearly_records)
    return ic_summary, yearly_df


# ═══════════════════════════════════════════════════════
# Step D: IC入库
# ═══════════════════════════════════════════════════════
def upsert_event_ic(
    conn, ic_summary: pd.DataFrame, dry_run: bool = False
) -> int:
    """将EVENT IC写入factor_ic_history（铁律11）。

    适配策略:
      factor_name = "sue_{report_type}" (如 sue_q1)
      trade_date = 分析截止日（今天）
      IC slot映射: ic_1d=7d, ic_5d=5d, ic_10d=10d, ic_20d=20d, ic_abs_1d=15d
      decay_level = IC_SLOT_NOTE（备注slot映射关系）
    """
    print("\n[Step D] IC入库 factor_ic_history...")

    today = date.today()
    rows = []

    for _, r in ic_summary.iterrows():
        rt = r["report_type"]
        if rt == "ALL":
            factor_name = "sue_all"
        else:
            factor_name = f"sue_{rt.lower()}"

        rows.append((
            factor_name,
            today,
            _safe_float(r.get("ic_7d")),    # ic_1d slot → 7d
            _safe_float(r.get("ic_5d")),     # ic_5d slot → 5d
            _safe_float(r.get("ic_10d")),    # ic_10d slot → 10d
            _safe_float(r.get("ic_20d")),    # ic_20d slot → 20d
            _safe_float(r.get("ic_15d")),    # ic_abs_1d slot → 15d
            None,                             # ic_abs_5d
            None,                             # ic_ma20
            None,                             # ic_ma60
            IC_SLOT_NOTE,                     # decay_level → 备注
        ))

    if dry_run:
        print(f"  [DRY RUN] 跳过入库，共 {len(rows)} 行")
        for row in rows:
            print(f"    {row[0]}: 7d={row[2]}, 5d={row[3]}, 10d={row[4]}, 20d={row[5]}, 15d={row[6]}")
        return 0

    upsert_sql = """
        INSERT INTO factor_ic_history
            (factor_name, trade_date, ic_1d, ic_5d, ic_10d, ic_20d,
             ic_abs_1d, ic_abs_5d, ic_ma20, ic_ma60, decay_level)
        VALUES %s
        ON CONFLICT (factor_name, trade_date) DO UPDATE SET
            ic_1d       = EXCLUDED.ic_1d,
            ic_5d       = EXCLUDED.ic_5d,
            ic_10d      = EXCLUDED.ic_10d,
            ic_20d      = EXCLUDED.ic_20d,
            ic_abs_1d   = EXCLUDED.ic_abs_1d,
            ic_abs_5d   = EXCLUDED.ic_abs_5d,
            ic_ma20     = EXCLUDED.ic_ma20,
            ic_ma60     = EXCLUDED.ic_ma60,
            decay_level = EXCLUDED.decay_level
    """

    cur = conn.cursor()
    psycopg2.extras.execute_values(cur, upsert_sql, rows, page_size=100)
    conn.commit()
    print(f"  写入 {len(rows)} 行到 factor_ic_history")
    return len(rows)


def _safe_float(val) -> float | None:
    """安全转换float，NaN/None→None。"""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════
# Step E: 终端报告
# ═══════════════════════════════════════════════════════
def print_report(
    sue_df: pd.DataFrame,
    event_df: pd.DataFrame,
    ic_summary: pd.DataFrame,
    yearly_df: pd.DataFrame,
) -> None:
    """输出完整研究报告。"""

    print("\n")
    print("═" * 60)
    print("  盈利公告因子(SUE)研究报告")
    print("═" * 60)

    # ── 数据概况 ──
    print("\n数据概况:")
    print(f"  总事件数(SUE有效): {len(sue_df):,}")
    print(f"  覆盖股票: {sue_df['ts_code'].nunique():,}只")
    td = sue_df["trade_date"]
    print(f"  时间范围: {td.min()} ~ {td.max()}")

    print("\n因子计算:")
    print("  方法: 方案B (YoY同比: eps_surprise_pct / rolling_8q_std)")
    print(f"  有效SUE事件: {len(event_df):,} (含forward return)")
    print("  方向: +1 (正surprise → 正漂移)")

    # ── IC结果表 ──
    print("\nIC结果（按报告类型 × 持有期）:")
    header = f"  {'报告类型':^10s}"
    for h in HOLD_DAYS:
        header += f" │ {h:>2d}d IC{'':>5s}"
    print(header)
    print(f"  {'─' * 10}" + "─┼─" + "─┼─".join(["─" * 13] * len(HOLD_DAYS)))

    for _, row in ic_summary.iterrows():
        rt = row["report_type"]
        line = f"  {rt:^10s}"
        for h in HOLD_DAYS:
            ic_val = row.get(f"ic_{h}d")
            t_val = row.get(f"t_{h}d")
            n_val = row.get(f"n_{h}d", 0)

            if ic_val is not None and not np.isnan(ic_val):
                star = "★" if (t_val is not None and not np.isnan(t_val) and abs(t_val) > 2.0) else " "
                line += f" │ {ic_val:+.4f}({t_val:+.1f}){star}"
            else:
                line += f" │ {'N/A':>13s}"
        line += f"  N={int(n_val)}"
        print(line)

    print("\n  ★ = |t| > 2.0 (统计显著)")

    # ── 年度分解（所有report_type, 7d hold） ──
    for rt in ["Q1", "H1", "Q3", "Y"]:
        rt_yearly = yearly_df[(yearly_df["report_type"] == rt) & (yearly_df["hold_days"] == 7)]
        if rt_yearly.empty:
            continue
        print(f"\n年度分解 ({rt}, 7d持有):")
        for _, yr in rt_yearly.sort_values("year").iterrows():
            y = int(yr["year"])
            ic = yr["ic"]
            n = int(yr["n"])
            t = yr["t_stat"]
            if np.isnan(ic):
                print(f"  {y}: IC=N/A (N={n})")
            else:
                warn = " ⚠️N<50" if n < 50 else ""
                star = " ★" if (not np.isnan(t) and abs(t) > 2.0) else ""
                print(f"  {y}: IC={ic:+.4f} (t={t:+.1f}, N={n}){star}{warn}")

    # ── 自动结论 ──
    print("\n结论:")

    sig_combos = []
    for _, row in ic_summary.iterrows():
        rt = row["report_type"]
        for h in HOLD_DAYS:
            ic_val = row.get(f"ic_{h}d")
            t_val = row.get(f"t_{h}d")
            if (
                ic_val is not None
                and not np.isnan(ic_val)
                and t_val is not None
                and not np.isnan(t_val)
            ):
                if ic_val > 0 and t_val > 2.0:
                    sig_combos.append((rt, h, ic_val, t_val))

    if sig_combos:
        print("  显著正IC组合 (IC>0, t>2.0):")
        for rt, h, ic, t in sorted(sig_combos, key=lambda x: -x[3]):
            print(f"    {rt} × {h}d: IC={ic:+.4f}, t={t:+.1f}")
    else:
        print("  无显著正IC组合 (所有report_type × hold_days)")

    # 与4/5结论对比
    q1_7d = ic_summary[ic_summary["report_type"] == "Q1"]
    if not q1_7d.empty:
        q1_ic = q1_7d.iloc[0].get("ic_7d")
        q1_t = q1_7d.iloc[0].get("t_7d")
        if q1_ic is not None and not np.isnan(q1_ic):
            direction = "正" if q1_ic > 0 else "负"
            sig = "显著" if (q1_t is not None and not np.isnan(q1_t) and abs(q1_t) > 2.0) else "不显著"
            print(f"\n  4/5结论验证: Q1 × 7d IC={q1_ic:+.4f} (t={q1_t:+.1f}), {direction}方向, {sig}")
            print(f"  4/5初步结论(Q1唯一正方向): {'确认' if q1_ic > 0 else '修正'}")

    neg_combos = []
    for _, row in ic_summary.iterrows():
        rt = row["report_type"]
        if rt == "ALL":
            continue
        for h in HOLD_DAYS:
            ic_val = row.get(f"ic_{h}d")
            t_val = row.get(f"t_{h}d")
            if (
                ic_val is not None
                and not np.isnan(ic_val)
                and t_val is not None
                and not np.isnan(t_val)
                and ic_val < 0
                and t_val < -2.0
            ):
                neg_combos.append((rt, h, ic_val, t_val))

    if neg_combos:
        print("\n  显著负IC组合（利空出尽/反转效应）:")
        for rt, h, ic, t in sorted(neg_combos, key=lambda x: x[3]):
            print(f"    {rt} × {h}d: IC={ic:+.4f}, t={t:+.1f}")

    print(f"\n{'═' * 60}\n")


# ═══════════════════════════════════════════════════════
# Step F: Q3 SUE中性化验证（独立alpha检验）
# ═══════════════════════════════════════════════════════
def check_q3_neutralized_ic(event_df: pd.DataFrame, conn) -> None:
    """验证Q3 SUE反转是否独立于小盘效应。

    对Q3事件样本做WLS中性化(行业+市值)后重新算IC。
    raw IC=-0.125 vs neutral IC → 判断alpha独立性。
    """
    print("\n" + "=" * 60)
    print("  [Step F] Q3 SUE中性化验证 — 独立alpha检验")
    print("=" * 60)

    q3 = event_df[event_df["report_type"] == "Q3"].copy()
    if q3.empty:
        print("  Q3事件为空，跳过")
        return

    # 需要ts_code去后缀匹配klines_daily的code格式
    q3["code"] = q3["ts_code"].str.split(".").str[0]

    # 加载市值和行业数据
    # 用trade_date(信号日)当天的市值
    min_date = q3["trade_date"].min()
    max_date = q3["trade_date"].max()

    mktcap = pd.read_sql(
        """SELECT code, trade_date, total_mv
           FROM daily_basic
           WHERE trade_date >= %s AND trade_date <= %s
             AND total_mv > 0""",
        conn,
        params=(min_date, max_date),
    )
    print(f"  市值数据: {len(mktcap):,}行")

    industry = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE is_active = true",
        conn,
    )
    print(f"  行业数据: {len(industry):,}只股票")

    # merge 市值 (用trade_date匹配)
    q3 = q3.merge(
        mktcap, left_on=["code", "trade_date"], right_on=["code", "trade_date"], how="left",
    )
    q3 = q3.merge(industry, on="code", how="left")

    valid = q3.dropna(subset=["sue", "total_mv", "industry_sw1"])
    print(f"  Q3有效样本(含市值+行业): {len(valid):,} / {len(q3):,}")

    if len(valid) < 100:
        print("  有效样本不足100，跳过中性化")
        return

    # WLS中性化: 复用factor_engine的preprocess_neutralize
    valid["ln_mv"] = np.log(valid["total_mv"])

    from engines.factor_engine import preprocess_neutralize

    # 按trade_date分组做截面中性化
    neutral_sue = []
    for td, grp in valid.groupby("trade_date"):
        if len(grp) < 30:
            continue
        sue_series = pd.Series(grp["sue"].values, index=grp.index)
        ln_mcap = pd.Series(grp["ln_mv"].values, index=grp.index)
        ind = pd.Series(grp["industry_sw1"].values, index=grp.index)
        residual = preprocess_neutralize(sue_series, ln_mcap, ind)
        for idx, val in residual.items():
            neutral_sue.append({"idx": idx, "sue_neutral": val})

    if not neutral_sue:
        print("  中性化结果为空")
        return

    neutral_df = pd.DataFrame(neutral_sue).set_index("idx")
    valid = valid.copy()
    valid["sue_neutral"] = neutral_df["sue_neutral"]
    valid = valid.dropna(subset=["sue_neutral"])
    print(f"  中性化后有效: {len(valid):,}")

    # 用中性化后的SUE重新算IC
    print("\n  Q3 IC对比 (raw vs neutral):")
    print(f"  {'hold':>6s}  {'raw IC':>10s}  {'raw t':>8s}  {'neut IC':>10s}  {'neut t':>8s}  {'衰减%':>8s}  {'判定':>10s}")
    print(f"  {'─' * 6}  {'─' * 10}  {'─' * 8}  {'─' * 10}  {'─' * 8}  {'─' * 8}  {'─' * 10}")

    for h in HOLD_DAYS:
        col = f"fwd_{h}d"
        v_raw = valid[["sue", col]].dropna()
        v_neut = valid[["sue_neutral", col]].dropna()

        if len(v_raw) < 50 or len(v_neut) < 50:
            print(f"  {h:>4d}d  {'N/A':>10s}  {'N/A':>8s}  {'N/A':>10s}  {'N/A':>8s}")
            continue

        ic_raw, _ = stats.spearmanr(v_raw["sue"], v_raw[col])
        t_raw = ic_raw * np.sqrt(len(v_raw)) / np.sqrt(1 - ic_raw ** 2)

        ic_neut, _ = stats.spearmanr(v_neut["sue_neutral"], v_neut[col])
        t_neut = ic_neut * np.sqrt(len(v_neut)) / np.sqrt(1 - ic_neut ** 2)

        # 衰减百分比
        if abs(ic_raw) > 1e-6:
            decay_pct = (1 - abs(ic_neut) / abs(ic_raw)) * 100
        else:
            decay_pct = 0

        # 判定
        if abs(ic_neut) >= 0.08:
            verdict = "✅独立alpha"
        elif abs(ic_neut) >= 0.05:
            verdict = "⚠️部分独立"
        else:
            verdict = "❌小盘暴露"

        print(
            f"  {h:>4d}d  {ic_raw:>+10.4f}  {t_raw:>+8.1f}  "
            f"{ic_neut:>+10.4f}  {t_neut:>+8.1f}  {decay_pct:>7.1f}%  {verdict}"
        )

    print()


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(description="盈利公告因子(SUE)计算+IC评估")
    parser.add_argument("--dry-run", action="store_true", help="不入库，只计算和展示")
    args = parser.parse_args()

    conn = _get_sync_conn()

    # Step A: SUE计算
    sue_df = compute_sue(conn)

    # 保存Parquet
    CACHE_DIR.mkdir(exist_ok=True)
    parquet_path = CACHE_DIR / "earnings_sue.parquet"
    sue_df.to_parquet(parquet_path, index=False)
    print(f"\n  SUE保存: {parquet_path} ({len(sue_df):,}行)")

    # Step B: Forward Return
    event_df = compute_event_forward_returns(sue_df, conn)

    # Step C: EVENT IC
    ic_summary, yearly_df = compute_event_ic(event_df)

    # Step D: IC入库
    upsert_event_ic(conn, ic_summary, dry_run=args.dry_run)

    # Step E: 报告
    print_report(sue_df, event_df, ic_summary, yearly_df)

    # Step F: Q3中性化验证
    check_q3_neutralized_ic(event_df, conn)

    conn.close()


if __name__ == "__main__":
    main()
