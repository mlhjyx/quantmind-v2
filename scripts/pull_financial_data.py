#!/usr/bin/env python3
"""拉取Tushare财务指标数据(fina_indicator) → financial_indicators表。

CLAUDE.md原则2: 数据源接入前必须过checklist。
关键规则:
  1. 必须用ann_date做PIT时间对齐（不是end_date）
  2. 同一end_date可能多条（预披露/修正/正式），取ann_date最新
  3. 百分比字段已×100（roe=15.23 表示 15.23%，直接存）
  4. 季度频率，一年最多4条

用法:
    python scripts/pull_financial_data.py                    # 全量拉取2019-2026
    python scripts/pull_financial_data.py --start 20250101   # 增量
    python scripts/pull_financial_data.py --verify           # 仅验证
"""

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd
import tushare as ts
from app.config import settings
from app.services.price_utils import _get_sync_conn

pro = ts.pro_api(settings.TUSHARE_TOKEN)


FINA_FIELDS = [
    "ts_code", "ann_date", "end_date",
    "roe", "roe_dt", "roa",
    "grossprofit_margin", "netprofit_margin",
    "or_yoy", "netprofit_yoy", "basic_eps_yoy",  # or_yoy=营收同比（非revenue_yoy!）
    "eps", "bps",
    "current_ratio", "quick_ratio",
    "debt_to_assets",
]


def fetch_fina_by_stock(ts_code: str, retry: int = 3) -> pd.DataFrame:
    """按股票拉取fina_indicator全部历史。

    Args:
        ts_code: 股票代码 如 '000001.SZ'
        retry: 重试次数

    Returns:
        DataFrame
    """
    for attempt in range(retry):
        try:
            df = pro.fina_indicator(
                ts_code=ts_code,
                fields=FINA_FIELDS,
            )
            return df
        except Exception as e:
            if attempt < retry - 1:
                wait = 5 * (attempt + 1)
                time.sleep(wait)
            else:
                return pd.DataFrame()


def process_fina_df(df: pd.DataFrame, symbols_set: set) -> pd.DataFrame:
    """清洗财务数据。

    1. 去除代码后缀(.SZ/.SH → 纯代码)
    2. 过滤无效symbols
    3. 去重: 同一(code, end_date)取ann_date最新
    4. ann_date为NULL时fallback=end_date+90天
    """
    if df.empty:
        return df

    # 去后缀
    df["code"] = df["ts_code"].str[:6]
    df = df[df["code"].isin(symbols_set)].copy()

    if df.empty:
        return df

    # 日期转换
    df["report_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d").dt.date
    df["actual_ann_date"] = pd.to_datetime(df["ann_date"], format="%Y%m%d", errors="coerce").dt.date

    # ann_date为NULL的fallback: report_date + 90天
    mask = df["actual_ann_date"].isna()
    if mask.any():
        from datetime import timedelta
        df.loc[mask, "actual_ann_date"] = df.loc[mask, "report_date"].apply(
            lambda d: d + timedelta(days=90) if d else None
        )

    # 去重: 同一(code, end_date)取ann_date最新（最终版）
    df = df.sort_values("actual_ann_date", ascending=False)
    df = df.drop_duplicates(subset=["code", "report_date"], keep="first")

    # 重命名Tushare字段 → DDL字段
    rename_map = {
        "grossprofit_margin": "gross_profit_margin",
        "netprofit_margin": "net_profit_margin",
        "or_yoy": "revenue_yoy",       # Tushare字段名 or_yoy → DDL字段 revenue_yoy
        "netprofit_yoy": "net_profit_yoy",
        "debt_to_assets": "debt_to_asset",
    }
    df = df.rename(columns=rename_map)

    # 选择最终列
    cols = [
        "code", "report_date", "actual_ann_date",
        "roe", "roe_dt", "roa",
        "gross_profit_margin", "net_profit_margin",
        "revenue_yoy", "net_profit_yoy", "basic_eps_yoy",
        "eps", "bps",
        "current_ratio", "quick_ratio", "debt_to_asset",
    ]
    return df[[c for c in cols if c in df.columns]]


def upsert_financial(df: pd.DataFrame, conn) -> int:
    """批量upsert到financial_indicators。"""
    if df.empty:
        return 0

    cur = conn.cursor()
    cols = [
        "code", "report_date", "actual_ann_date",
        "roe", "roe_dt", "roa",
        "gross_profit_margin", "net_profit_margin",
        "revenue_yoy", "net_profit_yoy", "basic_eps_yoy",
        "eps", "bps",
        "current_ratio", "quick_ratio", "debt_to_asset",
    ]

    # 构建upsert SQL
    placeholders = ", ".join(["%s"] * len(cols))
    col_str = ", ".join(cols)
    update_str = ", ".join(
        f"{c}=EXCLUDED.{c}" for c in cols if c not in ("code", "report_date")
    )

    sql = f"""INSERT INTO financial_indicators ({col_str})
              VALUES ({placeholders})
              ON CONFLICT (code, report_date) DO UPDATE SET {update_str}"""

    count = 0
    for _, row in df.iterrows():
        values = []
        for c in cols:
            v = row.get(c)
            if pd.isna(v):
                values.append(None)
            else:
                values.append(v)
        try:
            cur.execute(sql, values)
            count += 1
        except Exception as e:
            conn.rollback()
            print(f"  ⚠ upsert失败: {row.get('code')} {row.get('report_date')}: {e}")
            continue

    conn.commit()
    return count


def verify_data(conn):
    """验证财务数据质量。"""
    cur = conn.cursor()

    print("\n=== 财务数据验证 ===")

    # 总行数
    cur.execute("SELECT COUNT(*) FROM financial_indicators")
    total = cur.fetchone()[0]
    print(f"  总行数: {total:,}")

    # 日期范围
    cur.execute("SELECT MIN(report_date), MAX(report_date) FROM financial_indicators")
    r = cur.fetchone()
    print(f"  报告期范围: {r[0]} ~ {r[1]}")

    # 覆盖股票数
    cur.execute("SELECT COUNT(DISTINCT code) FROM financial_indicators")
    print(f"  覆盖股票: {cur.fetchone()[0]}")

    # ann_date NULL率
    cur.execute("""SELECT COUNT(*) FILTER(WHERE actual_ann_date IS NULL)::float / COUNT(*)
                   FROM financial_indicators""")
    print(f"  ann_date NULL率: {cur.fetchone()[0]:.2%}")

    # ROE范围
    cur.execute("""SELECT report_date, MIN(roe), MAX(roe), AVG(roe), COUNT(*)
                   FROM financial_indicators
                   WHERE report_date >= '2023-01-01'
                   GROUP BY report_date ORDER BY report_date DESC LIMIT 4""")
    print("\n  最近ROE统计:")
    for r in cur.fetchall():
        roe_min = float(r[1]) if r[1] else 0
        roe_max = float(r[2]) if r[2] else 0
        roe_avg = float(r[3]) if r[3] else 0
        print(f"    {r[0]}: min={roe_min:.1f}% max={roe_max:.1f}% avg={roe_avg:.1f}% n={r[4]}")

    # PIT验证: ann_date应晚于report_date
    cur.execute("""SELECT COUNT(*) FROM financial_indicators
                   WHERE actual_ann_date < report_date""")
    bad_pit = cur.fetchone()[0]
    if bad_pit > 0:
        print(f"  ⚠ ann_date < report_date: {bad_pit}行 (需检查)")
    else:
        print(f"  ✓ PIT时序正确")

    # 重复检测
    cur.execute("""SELECT code, report_date, COUNT(*) FROM financial_indicators
                   GROUP BY code, report_date HAVING COUNT(*) > 1 LIMIT 5""")
    dups = cur.fetchall()
    if dups:
        print(f"  ⚠ 发现{len(dups)}组重复")
    else:
        print(f"  ✓ 无重复")


def main():
    parser = argparse.ArgumentParser(description="拉取Tushare财务指标数据")
    parser.add_argument("--verify", action="store_true", help="仅验证")
    parser.add_argument("--offset", type=int, default=0, help="从第N只股票开始(断点续传)")
    args = parser.parse_args()

    conn = _get_sync_conn()

    if args.verify:
        verify_data(conn)
        conn.close()
        return

    # 获取symbols列表（带后缀用于Tushare API）
    cur = conn.cursor()
    cur.execute("""SELECT code,
                   CASE WHEN code LIKE '6%' OR code LIKE '9%' THEN code || '.SH'
                        ELSE code || '.SZ' END AS ts_code
                   FROM symbols ORDER BY code""")
    stocks = cur.fetchall()
    symbols_set = {r[0] for r in stocks}
    print(f"股票总数: {len(stocks)}只, 从第{args.offset}只开始")

    total_rows = 0
    fail_count = 0
    t_start = time.time()

    for i, (code, ts_code) in enumerate(stocks):
        if i < args.offset:
            continue

        if (i + 1) % 100 == 0 or i == args.offset:
            elapsed = time.time() - t_start
            eta = elapsed / max(i - args.offset + 1, 1) * (len(stocks) - i)
            print(f"[{i+1}/{len(stocks)}] {ts_code}... "
                  f"(写入{total_rows:,}行, 失败{fail_count}, "
                  f"ETA {eta/60:.0f}min)", flush=True)

        df = fetch_fina_by_stock(ts_code)
        if df.empty:
            fail_count += 1
            time.sleep(0.3)
            continue

        df_clean = process_fina_df(df, symbols_set)
        n = upsert_financial(df_clean, conn)
        total_rows += n

        # Tushare限流: 200次/分钟 → 0.3s/次
        time.sleep(0.32)

        # 连续失败保护
        if fail_count > 50:
            print(f"\n⚠ 连续失败过多({fail_count}), 停止。可用 --offset {i} 续传")
            break

    print(f"\n✅ 完成: 共写入 {total_rows:,} 行, 失败 {fail_count} 只")
    print(f"   耗时: {(time.time()-t_start)/60:.1f}分钟")
    verify_data(conn)
    conn.close()


if __name__ == "__main__":
    main()
