#!/usr/bin/env python3
"""拉取Tushare股东人数(stk_holdernumber) → holder_number表。

CLAUDE.md原则2: 数据源接入前必须过checklist。
参考: docs/TUSHARE_DATA_SOURCE_CHECKLIST.md §2.11

关键规则:
  1. 必须用ann_date做PIT时间对齐（不是end_date）
  2. 更新频率不固定 — 季报/半年报/年报时披露，中间可能有临时公告
  3. 因子逻辑：股东人数下降 → 筹码集中 → 看多信号
  4. 积分要求：5000（已满足，当前8000积分）

用法:
    python scripts/pull_stk_holdernumber.py                     # 全量拉取
    python scripts/pull_stk_holdernumber.py --start 20250101    # 增量拉取
    python scripts/pull_stk_holdernumber.py --verify            # 仅验证
    python scripts/pull_stk_holdernumber.py --create-table      # 建表

预估数据量: ~12.5万行 (~5000股 × ~25条/股)
预估耗时: ~15分钟 (按stock拉取, ~5000 API calls)
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

# Tushare stk_holdernumber 字段
HOLDER_FIELDS = [
    "ts_code",      # 股票代码
    "ann_date",     # 公告日期 (YYYYMMDD)
    "end_date",     # 截止日期 (YYYYMMDD)
    "holder_num",   # 股东户数（户）
]


# ════════════════════════════════════════════════════════════
# DDL
# ════════════════════════════════════════════════════════════

CREATE_TABLE_SQL = """
-- 股东人数表 (stk_holdernumber)
-- 数据来源: Tushare stk_holdernumber (积分5000)
-- 用途: 筹码集中度因子 — 股东人数下降=筹码集中=看多
CREATE TABLE IF NOT EXISTS holder_number (
    code            VARCHAR(10) NOT NULL,
    ann_date        DATE NOT NULL,               -- 公告日期 (PIT时间对齐用此字段!)
    end_date        DATE NOT NULL,               -- 截止日期 (报告期)
    holder_num      INTEGER,                     -- 股东户数（户）
    holder_num_change DECIMAL(10,4),             -- 较上期变动比例（计算字段）
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (code, ann_date, end_date)
);

CREATE INDEX IF NOT EXISTS idx_holder_number_code_date
    ON holder_number(code, end_date);
CREATE INDEX IF NOT EXISTS idx_holder_number_ann_date
    ON holder_number(ann_date);

COMMENT ON TABLE holder_number IS '股东人数。来源: Tushare stk_holdernumber。PIT对齐用ann_date。';
COMMENT ON COLUMN holder_number.code IS '股票代码（纯数字，无后缀）';
COMMENT ON COLUMN holder_number.ann_date IS '公告日期（PIT时间对齐必须用此字段，不是end_date!）';
COMMENT ON COLUMN holder_number.end_date IS '截止日期（报告期，如2025-03-31）';
COMMENT ON COLUMN holder_number.holder_num IS '股东户数（户）';
COMMENT ON COLUMN holder_number.holder_num_change IS '较上期变动比例，(当期-上期)/上期';
"""


def create_table(conn):
    """建表。"""
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("[DDL] holder_number 表已创建")


# ════════════════════════════════════════════════════════════
# 数据拉取
# ════════════════════════════════════════════════════════════

def fetch_by_stock(ts_code: str, start_date: str = "", retry: int = 3) -> pd.DataFrame:
    """按股票拉取股东人数全部历史。

    Args:
        ts_code: Tushare格式代码 如 '000001.SZ'
        start_date: 起始公告日期 (YYYYMMDD)
        retry: 重试次数

    Returns:
        DataFrame
    """
    for attempt in range(retry):
        try:
            kwargs = {"ts_code": ts_code, "fields": ",".join(HOLDER_FIELDS)}
            if start_date:
                kwargs["start_date"] = start_date
            df = pro.stk_holdernumber(**kwargs)
            return df
        except Exception as e:
            if "每分钟" in str(e) or "Exceed" in str(e):
                # 频率限制，等更久
                wait = 15 * (attempt + 1)
                print(f"    频率限制, 等待{wait}s...")
                time.sleep(wait)
            elif attempt < retry - 1:
                wait = 5 * (attempt + 1)
                time.sleep(wait)
            else:
                print(f"    FAIL: {ts_code} - {e}")
                return pd.DataFrame()


def process_holder_df(df: pd.DataFrame, symbols_set: set) -> pd.DataFrame:
    """清洗股东人数数据。

    1. 去除代码后缀(.SZ/.SH → 纯代码)
    2. 过滤无效symbols
    3. ann_date为NULL的fallback=end_date+45天
    4. 去重: 同一(code, end_date)取ann_date最新
    5. 计算holder_num_change
    """
    if df.empty:
        return df

    # 去后缀
    df["code"] = df["ts_code"].str[:6]
    df = df[df["code"].isin(symbols_set)].copy()
    if df.empty:
        return df

    # 日期转换
    df["end_date_parsed"] = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce").dt.date
    df["ann_date_parsed"] = pd.to_datetime(df["ann_date"], format="%Y%m%d", errors="coerce").dt.date

    # ann_date为NULL的fallback: end_date + 45天（季报通常在45天内披露）
    mask = df["ann_date_parsed"].isna()
    if mask.any():
        from datetime import timedelta
        df.loc[mask, "ann_date_parsed"] = df.loc[mask, "end_date_parsed"].apply(
            lambda d: d + timedelta(days=45) if d else None
        )

    # 去重: 同一(code, end_date)取ann_date最新
    df = df.sort_values("ann_date_parsed", ascending=False)
    df = df.drop_duplicates(subset=["code", "end_date_parsed"], keep="first")

    # holder_num可能为NaN
    df["holder_num"] = pd.to_numeric(df["holder_num"], errors="coerce")
    df = df.dropna(subset=["holder_num", "end_date_parsed", "ann_date_parsed"])
    df["holder_num"] = df["holder_num"].astype(int)

    # 计算变动比例 (排序后shift)
    df = df.sort_values(["code", "end_date_parsed"])
    df["prev_holder_num"] = df.groupby("code")["holder_num"].shift(1)
    df["holder_num_change"] = (
        (df["holder_num"] - df["prev_holder_num"]) / df["prev_holder_num"]
    ).round(4)
    df.drop(columns=["prev_holder_num"], inplace=True)

    return df


def upsert_holder_number(df: pd.DataFrame, conn) -> int:
    """写入holder_number表（upsert）。"""
    if df.empty:
        return 0

    cur = conn.cursor()
    inserted = 0
    for _, row in df.iterrows():
        try:
            cur.execute(
                """INSERT INTO holder_number
                   (code, ann_date, end_date, holder_num, holder_num_change)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (code, ann_date, end_date) DO UPDATE SET
                    holder_num = EXCLUDED.holder_num,
                    holder_num_change = EXCLUDED.holder_num_change""",
                (
                    row["code"],
                    row["ann_date_parsed"],
                    row["end_date_parsed"],
                    int(row["holder_num"]),
                    float(row["holder_num_change"]) if pd.notna(row["holder_num_change"]) else None,
                ),
            )
            inserted += 1
        except Exception as e:
            print(f"    写入失败: {row['code']} {row['end_date_parsed']} - {e}")
            conn.rollback()
            continue

    conn.commit()
    return inserted


# ════════════════════════════════════════════════════════════
# 验证
# ════════════════════════════════════════════════════════════

def verify_data(conn):
    """验证数据质量。"""
    cur = conn.cursor()
    print("\n[VERIFY] 数据质量检查:")

    # 1. 总行数
    cur.execute("SELECT COUNT(*) FROM holder_number")
    total = cur.fetchone()[0]
    print(f"  总行数: {total:,}")

    # 2. 股票覆盖数
    cur.execute("SELECT COUNT(DISTINCT code) FROM holder_number")
    n_codes = cur.fetchone()[0]
    print(f"  覆盖股票: {n_codes}")

    # 3. 日期范围
    cur.execute("SELECT MIN(end_date), MAX(end_date) FROM holder_number")
    row = cur.fetchone()
    print(f"  日期范围: {row[0]} ~ {row[1]}")

    # 4. 每股票平均条数
    avg = total / n_codes if n_codes > 0 else 0
    print(f"  平均每股: {avg:.1f}条")

    # 5. holder_num NULL率
    cur.execute("SELECT COUNT(*) FROM holder_number WHERE holder_num IS NULL")
    null_cnt = cur.fetchone()[0]
    print(f"  holder_num NULL: {null_cnt} ({null_cnt/total*100:.2f}%)" if total > 0 else "  N/A")

    # 6. 变动比例异常检查（变动>100%或<-50%的记录）
    cur.execute("""
        SELECT COUNT(*) FROM holder_number
        WHERE holder_num_change IS NOT NULL
          AND (holder_num_change > 1.0 OR holder_num_change < -0.5)
    """)
    outlier = cur.fetchone()[0]
    print(f"  变动异常(>100%或<-50%): {outlier}")

    # 7. 抽样验证（茅台、平安银行、宁德时代）
    print("\n  抽样验证:")
    for code, name in [("600519", "茅台"), ("000001", "平安银行"), ("300750", "宁德时代")]:
        cur.execute("""
            SELECT end_date, holder_num, holder_num_change
            FROM holder_number
            WHERE code = %s
            ORDER BY end_date DESC LIMIT 3
        """, (code,))
        rows = cur.fetchall()
        if rows:
            for r in rows:
                chg = f"{r[2]:+.2%}" if r[2] is not None else "N/A"
                print(f"    {name}({code}): {r[0]} 股东={r[1]:,}户 变动={chg}")
        else:
            print(f"    {name}({code}): 无数据")

    print("\n[VERIFY] 完成")
    return total > 0


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="拉取Tushare股东人数数据")
    parser.add_argument("--start", default="", help="起始公告日期 (YYYYMMDD)")
    parser.add_argument("--verify", action="store_true", help="仅验证数据")
    parser.add_argument("--create-table", action="store_true", help="创建表")
    args = parser.parse_args()

    conn = _get_sync_conn()

    if args.create_table:
        create_table(conn)
        conn.close()
        return

    if args.verify:
        verify_data(conn)
        conn.close()
        return

    # ── 确认表存在 ──
    cur = conn.cursor()
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'holder_number'
        )
    """)
    if not cur.fetchone()[0]:
        print("[INIT] holder_number表不存在，先建表...")
        create_table(conn)

    # ── 加载symbols列表 ──
    symbols_df = pd.read_sql(
        "SELECT code FROM symbols WHERE list_status IN ('L', 'D', 'P')",
        conn,
    )
    symbols_set = set(symbols_df["code"].values)
    all_codes = sorted(symbols_set)
    print(f"[INIT] 共{len(all_codes)}只股票")

    # ── 构建Tushare代码映射 ──
    code_map = pd.read_sql(
        "SELECT code, exchange FROM symbols WHERE list_status IN ('L', 'D', 'P')",
        conn,
    )
    ts_code_map = {}
    for _, row in code_map.iterrows():
        suffix = ".SH" if row["exchange"] == "SSE" else ".SZ"
        ts_code_map[row["code"]] = row["code"] + suffix

    # ── 开始拉取 ──
    t0 = time.time()
    total_rows = 0
    total_inserted = 0
    consecutive_fail = 0
    batch_size = 50  # 每批处理后commit

    print(f"\n[PULL] 开始拉取股东人数 (start={args.start or '全量'})...")
    batch_df = pd.DataFrame()

    for i, code in enumerate(all_codes):
        ts_code = ts_code_map.get(code)
        if not ts_code:
            continue

        df = fetch_by_stock(ts_code, start_date=args.start)
        if df is None or df.empty:
            consecutive_fail += 1
            if consecutive_fail >= 20:
                print(f"\n[ABORT] 连续{consecutive_fail}次无数据，停止")
                break
            continue

        consecutive_fail = 0
        total_rows += len(df)
        batch_df = pd.concat([batch_df, df], ignore_index=True)

        # 每batch_size只股票处理一批
        if (i + 1) % batch_size == 0 or i == len(all_codes) - 1:
            processed = process_holder_df(batch_df, symbols_set)
            inserted = upsert_holder_number(processed, conn)
            total_inserted += inserted
            batch_df = pd.DataFrame()

            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(all_codes) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{len(all_codes)}] "
                  f"拉取={total_rows:,}行 写入={total_inserted:,}行 "
                  f"速率={rate:.1f}只/s ETA={eta/60:.1f}min")

        # Tushare频率控制: ~200次/分钟 → 每次间隔0.3s
        time.sleep(0.35)

    elapsed = time.time() - t0
    print(f"\n[DONE] 总耗时: {elapsed/60:.1f}min")
    print(f"  拉取: {total_rows:,}行")
    print(f"  写入: {total_inserted:,}行")

    # ── 验证 ──
    verify_data(conn)
    conn.close()


if __name__ == "__main__":
    main()
