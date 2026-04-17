#!/usr/bin/env python3
"""盈利公告数据质量探索。

探索 earnings_announcements 表的数据质量，为SUE因子计算做准备。
回答: 字段非空率、时间覆盖、报告类型分布、公告月份集中度、重复记录等。

用法:
    python scripts/research/earnings_factor_explore.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "backend"))

import pandas as pd

from app.services.price_utils import _get_sync_conn


def main() -> None:
    conn = _get_sync_conn()

    print("\n" + "=" * 60)
    print("  盈利公告数据质量探索 (earnings_announcements)")
    print("=" * 60)

    # ── 1. 总览 ──────────────────────────────────────
    df = pd.read_sql(
        """SELECT ts_code, end_date, ann_date, f_ann_date, trade_date,
                  basic_eps, eps_q4_ago, eps_surprise, eps_surprise_pct,
                  report_type, source
           FROM earnings_announcements""",
        conn,
    )
    print(f"\n[1] 总行数: {len(df):,}")
    print(f"    时间范围(ann_date): {df['ann_date'].min()} ~ {df['ann_date'].max()}")
    print(f"    时间范围(f_ann_date): {df['f_ann_date'].min()} ~ {df['f_ann_date'].max()}")
    print(f"    时间范围(end_date): {df['end_date'].min()} ~ {df['end_date'].max()}")

    # ── 2. 字段非空率 ────────────────────────────────
    print("\n[2] 字段非空率:")
    fields = [
        "basic_eps", "eps_q4_ago", "eps_surprise", "eps_surprise_pct",
        "ann_date", "f_ann_date", "trade_date", "report_type", "source",
    ]
    for f in fields:
        non_null = df[f].notna().sum()
        pct = non_null / len(df) * 100
        print(f"    {f:<20s}: {non_null:>7,} / {len(df):,}  ({pct:.1f}%)")

    # ── 3. eps_surprise_pct 验证 ─────────────────────
    # 验证 eps_surprise_pct 是否 = eps_surprise / |eps_q4_ago|
    valid = df.dropna(subset=["basic_eps", "eps_q4_ago", "eps_surprise_pct"])
    if len(valid) > 0:
        recalc = (valid["basic_eps"] - valid["eps_q4_ago"]) / valid["eps_q4_ago"].abs()
        diff = (valid["eps_surprise_pct"] - recalc).abs()
        match_pct = (diff < 0.001).sum() / len(valid) * 100
        print("\n[3] eps_surprise_pct 验证:")
        print(f"    可验证行数: {len(valid):,}")
        print(f"    与 (basic_eps - eps_q4_ago)/|eps_q4_ago| 一致率: {match_pct:.1f}%")
        print(f"    差异中位数: {diff.median():.6f}")
    else:
        print("\n[3] eps_surprise_pct 验证: 无可验证数据")

    # ── 4. source 分布 ───────────────────────────────
    print("\n[4] source 分布:")
    src_counts = df["source"].value_counts(dropna=False)
    for src, cnt in src_counts.items():
        print(f"    {str(src):<20s}: {cnt:>7,}  ({cnt / len(df) * 100:.1f}%)")

    # ── 5. report_type 分布 ──────────────────────────
    print("\n[5] report_type 分布:")
    rt_counts = df["report_type"].value_counts(dropna=False).sort_index()
    for rt, cnt in rt_counts.items():
        print(f"    {str(rt):<6s}: {cnt:>7,}  ({cnt / len(df) * 100:.1f}%)")

    # ── 6. 公告月份分布 ──────────────────────────────
    df["ann_month"] = pd.to_datetime(df["f_ann_date"]).dt.month
    print("\n[6] 公告月份分布(f_ann_date):")
    month_counts = df["ann_month"].value_counts().sort_index()
    for m, cnt in month_counts.items():
        bar = "█" * int(cnt / month_counts.max() * 30)
        print(f"    {int(m):>2d}月: {cnt:>7,}  {bar}")

    # ── 7. 按年分布 ──────────────────────────────────
    df["ann_year"] = pd.to_datetime(df["f_ann_date"]).dt.year
    print("\n[7] 按年分布:")
    year_counts = df["ann_year"].value_counts().sort_index()
    for y, cnt in year_counts.items():
        print(f"    {int(y)}: {cnt:>7,}")

    # ── 8. 股票覆盖 ─────────────────────────────────
    n_stocks = df["ts_code"].nunique()
    avg_records = len(df) / n_stocks if n_stocks > 0 else 0
    print("\n[8] 股票覆盖:")
    print(f"    覆盖股票数: {n_stocks:,}")
    print(f"    每股平均记录数: {avg_records:.1f}")

    # ── 9. 重复记录检查 ──────────────────────────────
    dup_count = df.duplicated(subset=["ts_code", "end_date"], keep=False).sum()
    dup_unique = df.duplicated(subset=["ts_code", "end_date"], keep="first").sum()
    print("\n[9] 重复记录检查 (ts_code, end_date):")
    print(f"    重复组涉及行数: {dup_count:,}")
    print(f"    去重后可删除行数: {dup_unique:,}")
    if dup_unique > 0:
        # 展示几个重复样例
        dup_groups = df[df.duplicated(subset=["ts_code", "end_date"], keep=False)]
        sample_keys = dup_groups.groupby(["ts_code", "end_date"]).size().head(3)
        print("    样例重复(ts_code, end_date):")
        for (ts, ed), cnt in sample_keys.items():
            print(f"      {ts} / {ed}: {cnt}条")

    # ── 10. SUE可计算性评估 ───────────────────────────
    has_surprise = df["eps_surprise_pct"].notna().sum()
    has_basic = df["basic_eps"].notna().sum()
    has_q4ago = df["eps_q4_ago"].notna().sum()
    print("\n[10] SUE可计算性:")
    print(f"    eps_surprise_pct 非空: {has_surprise:,} ({has_surprise / len(df) * 100:.1f}%)")
    print(f"    basic_eps 非空: {has_basic:,}")
    print(f"    eps_q4_ago 非空: {has_q4ago:,}")
    # 每股至少4季有eps_surprise_pct的覆盖
    stock_seasons = (
        df[df["eps_surprise_pct"].notna()]
        .groupby("ts_code")
        .size()
    )
    ge4 = (stock_seasons >= 4).sum()
    ge8 = (stock_seasons >= 8).sum()
    print(f"    股票有 >=4季 surprise: {ge4:,}")
    print(f"    股票有 >=8季 surprise: {ge8:,} (可计算标准化SUE)")

    # ── 11. report_type × 年度交叉分布 ────────────────
    print("\n[11] report_type × 年度分布 (eps_surprise_pct非空):")
    valid_df = df[df["eps_surprise_pct"].notna()].copy()
    cross = pd.crosstab(valid_df["ann_year"], valid_df["report_type"])
    print(cross.to_string())

    print(f"\n{'=' * 60}")
    print("  探索完成")
    print(f"{'=' * 60}\n")

    conn.close()


if __name__ == "__main__":
    main()
