#!/usr/bin/env python3
"""拉取Tushare资产负债表(balancesheet) -> balance_sheet表。

CLAUDE.md原则2: 数据源接入前必须过checklist。
关键规则:
  1. 必须用f_ann_date做PIT时间对齐（不是end_date，不是ann_date）
  2. 同一end_date可能多条（预披露/修正/正式），取f_ann_date最新
  3. 金额字段单位=元（Tushare原始单位，直接存）
  4. report_type=1 为合并报表（默认只拉合并报表）
  5. 季度频率，一年最多4条

用法:
    python scripts/pull_balancesheet.py                    # 全量拉取
    python scripts/pull_balancesheet.py --offset 100       # 从第100只开始(断点续传)
    python scripts/pull_balancesheet.py --verify           # 仅验证
"""

import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd
import tushare as ts

from app.config import settings
from app.services.price_utils import _get_sync_conn

pro = ts.pro_api(settings.TUSHARE_TOKEN)


# 拉取的字段列表（与DDL对应）
BS_FIELDS = [
    "ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "comp_type",
    # 资产端
    "money_cap", "trad_asset", "notes_receiv", "accounts_receiv",
    "oth_receiv", "prepayment", "inventories", "total_cur_assets",
    "fix_assets", "cip", "intan_assets", "goodwill", "lt_eqt_invest",
    "defer_tax_assets", "total_nca", "total_assets",
    # 负债端
    "st_borr", "notes_payable", "acct_payable", "adv_receipts",
    "payroll_payable", "taxes_payable", "total_cur_liab",
    "lt_borr", "bond_payable", "total_ncl", "total_liab",
    # 所有者权益
    "total_share", "cap_rese", "surplus_rese", "undistr_porfit",
    "minority_int", "total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int",
    "total_liab_hldr_eqy",
    # 新准则补充
    "accounts_receiv_bill", "contract_assets", "contract_liab",
    "use_right_assets", "lease_liab",
    "update_flag",
]

# DDL列（不含code, report_date，这两个从ts_code/end_date转换）
DB_COLS = [
    "code", "report_date", "actual_ann_date", "report_type", "comp_type",
    "money_cap", "trad_asset", "notes_receiv", "accounts_receiv",
    "oth_receiv", "prepayment", "inventories", "total_cur_assets",
    "fix_assets", "cip", "intan_assets", "goodwill", "lt_eqt_invest",
    "defer_tax_assets", "total_nca", "total_assets",
    "st_borr", "notes_payable", "acct_payable", "adv_receipts",
    "payroll_payable", "taxes_payable", "total_cur_liab",
    "lt_borr", "bond_payable", "total_ncl", "total_liab",
    "total_share", "cap_rese", "surplus_rese", "undistr_porfit",
    "minority_int", "total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int",
    "total_liab_hldr_eqy",
    "accounts_receiv_bill", "contract_assets", "contract_liab",
    "use_right_assets", "lease_liab",
    "update_flag",
]


def fetch_bs_by_stock(ts_code: str, retry: int = 3) -> pd.DataFrame:
    """按股票拉取balancesheet全部历史（合并报表）。

    Args:
        ts_code: 股票代码 如 '000001.SZ'
        retry: 重试次数

    Returns:
        DataFrame
    """
    for attempt in range(retry):
        try:
            df = pro.balancesheet(
                ts_code=ts_code,
                report_type="1",  # 合并报表
                fields=",".join(BS_FIELDS),
            )
            return df
        except Exception as e:
            if attempt < retry - 1:
                wait = 5 * (attempt + 1)
                print(f"  重试 {ts_code} (attempt {attempt+1}): {e}")
                time.sleep(wait)
            else:
                print(f"  失败 {ts_code}: {e}")
                return pd.DataFrame()


def process_bs_df(df: pd.DataFrame, symbols_set: set) -> pd.DataFrame:
    """清洗资产负债表数据。

    1. 去除代码后缀(.SZ/.SH -> 纯代码)
    2. 过滤无效symbols
    3. 日期转换
    4. PIT: f_ann_date为NULL时fallback=end_date+90天
    5. 去重: 同一(code, end_date)取f_ann_date最新
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

    # PIT: 优先用f_ann_date，fallback到ann_date，最后fallback到end_date+90天
    df["actual_ann_date"] = pd.to_datetime(
        df["f_ann_date"], format="%Y%m%d", errors="coerce"
    ).dt.date
    ann_fallback = pd.to_datetime(
        df["ann_date"], format="%Y%m%d", errors="coerce"
    ).dt.date
    mask_null = df["actual_ann_date"].isna()
    df.loc[mask_null, "actual_ann_date"] = ann_fallback[mask_null]

    # 仍为NULL的用report_date+90天
    mask_still_null = df["actual_ann_date"].isna()
    if mask_still_null.any():
        df.loc[mask_still_null, "actual_ann_date"] = df.loc[
            mask_still_null, "report_date"
        ].apply(lambda d: d + timedelta(days=90) if d else None)

    # 去重: 同一(code, end_date)取actual_ann_date最新（最终版）
    df = df.sort_values("actual_ann_date", ascending=False)
    df = df.drop_duplicates(subset=["code", "report_date"], keep="first")

    # 选择最终列
    return df[[c for c in DB_COLS if c in df.columns]]


def upsert_balancesheet(df: pd.DataFrame, conn) -> int:
    """批量upsert到balance_sheet。"""
    if df.empty:
        return 0

    cur = conn.cursor()
    placeholders = ", ".join(["%s"] * len(DB_COLS))
    col_str = ", ".join(DB_COLS)
    update_str = ", ".join(
        f"{c}=EXCLUDED.{c}" for c in DB_COLS if c not in ("code", "report_date")
    )

    sql = f"""INSERT INTO balance_sheet ({col_str})
              VALUES ({placeholders})
              ON CONFLICT (code, report_date) DO UPDATE SET {update_str}"""

    count = 0
    for _, row in df.iterrows():
        values = []
        for c in DB_COLS:
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
            print(f"  upsert失败: {row.get('code')} {row.get('report_date')}: {e}")
            continue

    conn.commit()
    return count


def verify_data(conn):
    """验证资产负债表数据质量。"""
    cur = conn.cursor()

    print("\n=== 资产负债表数据验证 ===")

    # 总行数
    cur.execute("SELECT COUNT(*) FROM balance_sheet")
    total = cur.fetchone()[0]
    print(f"  总行数: {total:,}")

    if total == 0:
        print("  (表为空，跳过验证)")
        return

    # 日期范围
    cur.execute("SELECT MIN(report_date), MAX(report_date) FROM balance_sheet")
    r = cur.fetchone()
    print(f"  报告期范围: {r[0]} ~ {r[1]}")

    # 覆盖股票数
    cur.execute("SELECT COUNT(DISTINCT code) FROM balance_sheet")
    print(f"  覆盖股票: {cur.fetchone()[0]}")

    # ann_date NULL率
    cur.execute("""SELECT COUNT(*) FILTER(WHERE actual_ann_date IS NULL)::float
                   / NULLIF(COUNT(*), 0)
                   FROM balance_sheet""")
    r = cur.fetchone()[0]
    print(f"  ann_date NULL率: {r:.2%}" if r else "  ann_date NULL率: N/A")

    # total_assets非空率
    cur.execute("""SELECT COUNT(*) FILTER(WHERE total_assets IS NOT NULL)::float
                   / NULLIF(COUNT(*), 0)
                   FROM balance_sheet""")
    r = cur.fetchone()[0]
    print(f"  total_assets非空率: {r:.2%}" if r else "  total_assets非空率: N/A")

    # total_assets范围抽样
    cur.execute("""SELECT report_date, MIN(total_assets), MAX(total_assets),
                          AVG(total_assets), COUNT(*)
                   FROM balance_sheet
                   WHERE report_date >= '2023-01-01' AND total_assets IS NOT NULL
                   GROUP BY report_date ORDER BY report_date DESC LIMIT 4""")
    rows = cur.fetchall()
    if rows:
        print("\n  最近total_assets统计:")
        for r in rows:
            print(f"    {r[0]}: min={float(r[1])/1e8:.1f}亿 "
                  f"max={float(r[2])/1e8:.0f}亿 "
                  f"avg={float(r[3])/1e8:.1f}亿 n={r[4]}")

    # PIT验证: ann_date应晚于report_date
    cur.execute("""SELECT COUNT(*) FROM balance_sheet
                   WHERE actual_ann_date < report_date""")
    bad_pit = cur.fetchone()[0]
    if bad_pit > 0:
        print(f"  ann_date < report_date: {bad_pit}行 (需检查)")
    else:
        print("  PIT时序正确")

    # 重复检测
    cur.execute("""SELECT code, report_date, COUNT(*) FROM balance_sheet
                   GROUP BY code, report_date HAVING COUNT(*) > 1 LIMIT 5""")
    dups = cur.fetchall()
    if dups:
        print(f"  发现{len(dups)}组重复")
    else:
        print("  无重复")


def main():
    parser = argparse.ArgumentParser(description="拉取Tushare资产负债表数据")
    parser.add_argument("--verify", action="store_true", help="仅验证")
    parser.add_argument("--offset", type=int, default=0,
                        help="从第N只股票开始(断点续传)")
    args = parser.parse_args()

    conn = _get_sync_conn()

    if args.verify:
        verify_data(conn)
        conn.close()
        return

    # 获取symbols列表
    cur = conn.cursor()
    cur.execute("""SELECT code,
                   CASE WHEN code LIKE '6%%' OR code LIKE '9%%' THEN code || '.SH'
                        ELSE code || '.SZ' END AS ts_code
                   FROM symbols ORDER BY code""")
    stocks = cur.fetchall()
    symbols_set = {r[0] for r in stocks}
    print(f"股票总数: {len(stocks)}只, 从第{args.offset}只开始")

    total_rows = 0
    fail_count = 0
    consecutive_fail = 0
    t_start = time.time()

    for i, (_code, ts_code) in enumerate(stocks):
        if i < args.offset:
            continue

        if (i + 1) % 100 == 0 or i == args.offset:
            elapsed = time.time() - t_start
            done = max(i - args.offset + 1, 1)
            eta = elapsed / done * (len(stocks) - i)
            print(f"[{i+1}/{len(stocks)}] {ts_code}... "
                  f"(写入{total_rows:,}行, 失败{fail_count}, "
                  f"ETA {eta/60:.0f}min)", flush=True)

        df = fetch_bs_by_stock(ts_code)
        if df.empty:
            fail_count += 1
            consecutive_fail += 1
            time.sleep(0.3)
        else:
            consecutive_fail = 0
            df_clean = process_bs_df(df, symbols_set)
            n = upsert_balancesheet(df_clean, conn)
            total_rows += n

        # Tushare限流: ~200次/分钟 -> 0.32s/次
        time.sleep(0.32)

        # 连续失败保护
        if consecutive_fail > 50:
            print(f"\n连续失败过多({consecutive_fail}), 停止。可用 --offset {i} 续传")
            break

    print(f"\n完成: 共写入 {total_rows:,} 行, 失败 {fail_count} 只")
    print(f"   耗时: {(time.time()-t_start)/60:.1f}分钟")
    verify_data(conn)
    conn.close()


if __name__ == "__main__":
    main()
