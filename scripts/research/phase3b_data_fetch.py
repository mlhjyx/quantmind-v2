"""Phase 3B — 新数据源拉取入库。

数据源优先级:
  1. fina_indicator  (新建表, 按股票循环拉取全历史)
  2. moneyflow_daily (已有完整数据 2014-2026, 跳过)
  3. margin_detail   (新建表, 按日期循环拉取 2014-2026)
  4. stk_factor      (与daily_basic完全重复, 跳过)
  5. stk_holdernumber (补全, 表已存在82K行/550股, 需扩至全A)
  6. forecast        (业绩预告, 按股票拉取全历史)
  7. express         (业绩快报, 按股票拉取全历史)
  8. top_list        (龙虎榜, 按日期拉取 2014-2026)

铁律:
  - 铁律29: NaN → None (SQL NULL), 禁止写float NaN到DB
  - 铁律17: 新表无现成Contract, 使用 psycopg2 execute_values + ON CONFLICT DO UPDATE
  - 批量: 每批5000行
  - 单位: fina_indicator字段均为百分比(%)/比率(无量纲), 直接存储, 无需转换
  - margin_detail字段: rzye/rqye等单位为元(Tushare原始), 直接存储

用法:
    python scripts/research/phase3b_data_fetch.py --task fina_indicator
    python scripts/research/phase3b_data_fetch.py --task margin_detail
    python scripts/research/phase3b_data_fetch.py --task forecast
    python scripts/research/phase3b_data_fetch.py --task express
    python scripts/research/phase3b_data_fetch.py --task top_list
    python scripts/research/phase3b_data_fetch.py --task all
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import tushare as ts

# ────────────────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────────────────
TUSHARE_TOKEN = "ecc9cc7ad4c50a5f06b8cc168d01b5830374c544c99a0c18a526dd23"
DB_DSN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"
BATCH_SIZE = 5000
REPORT_PATH = Path("cache/phase3b_fetch_report.json")
CHECKPOINT_DIR = Path("cache/phase3b_checkpoints")
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# Tushare频率限制: fina_indicator/margin_detail → 每分钟200次 (积分2000)
# 安全间隔: 0.35秒/次 (约170次/分钟)
SLEEP_PER_REQUEST = 0.35  # seconds
# 按日期拉取的接口 (margin_detail) 数据量大，间隔稍长
SLEEP_PER_DATE_REQUEST = 0.4  # seconds


# ────────────────────────────────────────────────────────────
# 工具函数
# ────────────────────────────────────────────────────────────

def get_pro() -> Any:
    """获取Tushare Pro API实例。"""
    return ts.pro_api(TUSHARE_TOKEN)


def get_conn() -> psycopg2.extensions.connection:
    """获取DB连接。"""
    return psycopg2.connect(DB_DSN)


def nan_to_none(df: pd.DataFrame) -> pd.DataFrame:
    """铁律29: 将所有float NaN转为None (SQL NULL)。

    pd.DataFrame.where(pd.notnull(df), None) 方法会保留object列中的None，
    但对数值列将NaN转为None。
    """
    return df.where(pd.notnull(df), other=None)


def load_checkpoint(name: str) -> set:
    """加载断点续传检查点。返回已处理的key集合。"""
    path = CHECKPOINT_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()


def save_checkpoint(name: str, done_set: set) -> None:
    """保存检查点。"""
    path = CHECKPOINT_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(list(done_set), f)


def upsert_df(conn, table: str, df: pd.DataFrame, pk_cols: list[str],
              batch_size: int = BATCH_SIZE) -> int:
    """通用Upsert: ON CONFLICT (pk_cols) DO UPDATE SET non-pk columns。

    返回upsert行数。
    """
    if df.empty:
        return 0

    # 安全去重: 同一批次内重复PK会触发 CardinalityViolation
    if pk_cols and all(c in df.columns for c in pk_cols):
        df = df.drop_duplicates(subset=pk_cols, keep="first")

    cols = list(df.columns)
    non_pk = [c for c in cols if c not in pk_cols]

    # 构造 ON CONFLICT ... DO UPDATE SET 子句
    conflict_clause = ", ".join(pk_cols)
    if non_pk:
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_pk)
        on_conflict = f"ON CONFLICT ({conflict_clause}) DO UPDATE SET {update_clause}"
    else:
        on_conflict = f"ON CONFLICT ({conflict_clause}) DO NOTHING"

    cols_str = ", ".join(cols)
    sql = f"INSERT INTO {table} ({cols_str}) VALUES %s {on_conflict}"

    total_upserted = 0
    cur = conn.cursor()
    try:
        for i in range(0, len(df), batch_size):
            chunk = df.iloc[i:i + batch_size]
            # 铁律29: 确保所有NaN已被转为None
            records = [
                tuple(None if (isinstance(v, float) and np.isnan(v)) else v
                      for v in row)
                for row in chunk.itertuples(index=False)
            ]
            psycopg2.extras.execute_values(cur, sql, records)
            total_upserted += len(records)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    return total_upserted


# ────────────────────────────────────────────────────────────
# 1. fina_indicator — 季频财务指标
# ────────────────────────────────────────────────────────────

FINA_INDICATOR_DDL = """
CREATE TABLE IF NOT EXISTS fina_indicator (
    code            VARCHAR(10)     NOT NULL,
    end_date        DATE            NOT NULL,
    ann_date        DATE,
    roe             NUMERIC(16,6),   -- 净资产收益率 (%)
    roe_dt          NUMERIC(16,6),   -- 稀释ROE (%)
    roa             NUMERIC(16,6),   -- 总资产净利率 (%)
    grossprofit_margin  NUMERIC(16,6), -- 毛利率 (%)
    netprofit_margin    NUMERIC(16,6), -- 净利率 (%)
    debt_to_assets  NUMERIC(16,6),   -- 资产负债率 (%)
    current_ratio   NUMERIC(16,6),   -- 流动比率 (无量纲)
    quick_ratio     NUMERIC(16,6),   -- 速动比率 (无量纲)
    dt_netprofit_yoy NUMERIC(16,6),  -- 扣非净利润同比增长率 (%)
    basic_eps_yoy   NUMERIC(16,6),   -- EPS同比增长率 (%)
    update_flag     VARCHAR(2),       -- 更新标志
    PRIMARY KEY (code, end_date)
);
COMMENT ON COLUMN fina_indicator.roe IS '净资产收益率, 单位: %';
COMMENT ON COLUMN fina_indicator.roa IS '总资产净利率, 单位: %';
COMMENT ON COLUMN fina_indicator.grossprofit_margin IS '毛利率, 单位: %';
COMMENT ON COLUMN fina_indicator.netprofit_margin IS '净利率, 单位: %';
COMMENT ON COLUMN fina_indicator.debt_to_assets IS '资产负债率, 单位: %';
"""

# Tushare fina_indicator实际返回的字段 (经测试验证, op_income_yoy不可用)
FINA_FIELDS = (
    "ts_code,ann_date,end_date,"
    "roe,roe_dt,roa,"
    "grossprofit_margin,netprofit_margin,"
    "debt_to_assets,current_ratio,quick_ratio,"
    "dt_netprofit_yoy,basic_eps_yoy,update_flag"
)

FINA_RENAME = {"ts_code": "code"}

FINA_DB_COLS = [
    "code", "end_date", "ann_date",
    "roe", "roe_dt", "roa",
    "grossprofit_margin", "netprofit_margin",
    "debt_to_assets", "current_ratio", "quick_ratio",
    "dt_netprofit_yoy", "basic_eps_yoy", "update_flag",
]


def create_fina_indicator_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(FINA_INDICATOR_DDL)
    conn.commit()
    cur.close()
    print("[fina_indicator] table created/verified OK")


def fetch_fina_indicator(symbols: list[str], conn) -> dict:
    """按股票循环拉取全历史fina_indicator。

    Returns:
        结果统计字典
    """
    pro = get_pro()
    checkpoint_key = "fina_indicator_done"
    done_set = load_checkpoint(checkpoint_key)

    total_rows = 0
    failed = []
    start_time = time.time()
    request_count = 0

    remaining = [s for s in symbols if s not in done_set]
    print(f"[fina_indicator] {len(remaining)} stocks to fetch "
          f"(skipping {len(done_set)} already done)")

    for idx, code in enumerate(remaining):
        if idx > 0 and idx % 100 == 0:
            elapsed = time.time() - start_time
            rate = request_count / elapsed * 60
            print(f"  [{idx}/{len(remaining)}] {total_rows} rows fetched, "
                  f"{rate:.0f} req/min, {len(failed)} failed")
            save_checkpoint(checkpoint_key, done_set)

        # 重试3次
        df = None
        for attempt in range(3):
            try:
                time.sleep(SLEEP_PER_REQUEST)
                df = pro.fina_indicator(ts_code=code, fields=FINA_FIELDS)
                request_count += 1
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [FAIL] {code}: {e}")
                    failed.append(code)
                    df = None
                else:
                    time.sleep(2.0)  # 限速后等待

        if df is None or df.empty:
            done_set.add(code)
            continue

        # rename ts_code → code
        df = df.rename(columns=FINA_RENAME)

        # 转换日期字段 YYYYMMDD → datetime.date
        for date_col in ["ann_date", "end_date"]:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(
                    df[date_col], format="%Y%m%d", errors="coerce"
                ).dt.date

        # 铁律29: object列转numeric, NaN → None
        for col in ["roa", "current_ratio", "quick_ratio", "grossprofit_margin"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = nan_to_none(df)

        # 只保留DB目标列 (过滤Tushare可能多返回的列)
        available_cols = [c for c in FINA_DB_COLS if c in df.columns]
        df = df[available_cols]

        # 过滤掉end_date为None的行 (PK不能为NULL)
        df = df[df["end_date"].notna() & df["code"].notna()]

        # PIT去重: 同一(code, end_date)保留ann_date最新的一行
        # Tushare有时对同一报告期返回多条不同update_flag的记录
        if "ann_date" in df.columns:
            df = df.sort_values("ann_date", ascending=False, na_position="last")
        df = df.drop_duplicates(subset=["code", "end_date"], keep="first")

        if not df.empty:
            rows_written = upsert_df(conn, "fina_indicator", df,
                                     pk_cols=["code", "end_date"])
            total_rows += rows_written

        done_set.add(code)

    # 最终保存检查点
    save_checkpoint(checkpoint_key, done_set)
    elapsed = time.time() - start_time

    stats = {
        "table": "fina_indicator",
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "failed_count": len(failed),
        "failed_codes": failed[:20],  # 只记录前20
        "requested": len(remaining),
        "skipped_checkpoint": len(done_set) - len(remaining),
    }
    print(f"[fina_indicator] DONE: {total_rows} rows in {elapsed:.0f}s, "
          f"{len(failed)} failed")
    return stats


def verify_fina_indicator(conn) -> dict:
    """拉取后验证SQL。"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(end_date), MAX(end_date), COUNT(DISTINCT code) FROM fina_indicator")
    cnt, min_d, max_d, codes = cur.fetchone()

    cur.execute("SELECT COUNT(*) FROM fina_indicator WHERE end_date IS NULL OR code IS NULL")
    null_pk = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM fina_indicator
        WHERE roe IS NULL AND roa IS NULL AND grossprofit_margin IS NULL
    """)
    all_null = cur.fetchone()[0]

    # 缺失率估算: 期望每只股票约50行 (12年×4季度)
    expected_rows = codes * 50 if codes else 0
    missing_pct = max(0, (expected_rows - cnt) / max(expected_rows, 1) * 100)

    cur.close()
    result = {
        "total_rows": cnt,
        "min_date": str(min_d) if min_d else None,
        "max_date": str(max_d) if max_d else None,
        "distinct_codes": codes,
        "null_pk_rows": null_pk,  # 应为0
        "all_metric_null_rows": all_null,
        "estimated_missing_pct": round(missing_pct, 2),
    }
    print(f"[fina_indicator verify] {cnt} rows, {codes} stocks, "
          f"{min_d}~{max_d}, null_pk={null_pk}, "
          f"all_null={all_null}, est_missing={missing_pct:.1f}%")
    return result


# ────────────────────────────────────────────────────────────
# 2. margin_detail — 融资融券明细 (新表, 按日期拉取)
# ────────────────────────────────────────────────────────────

MARGIN_DETAIL_DDL = """
CREATE TABLE IF NOT EXISTS margin_detail (
    code            VARCHAR(10)     NOT NULL,
    trade_date      DATE            NOT NULL,
    rzye            NUMERIC(20,2),  -- 融资余额 (元)
    rqye            NUMERIC(20,2),  -- 融券余额 (元)
    rzmre           NUMERIC(20,2),  -- 融资买入额 (元)
    rqyl            NUMERIC(20,2),  -- 融券余量 (股)
    rzche           NUMERIC(20,2),  -- 融资偿还额 (元)
    rqchl           NUMERIC(20,2),  -- 融券偿还量 (股)
    rqmcl           NUMERIC(20,2),  -- 融券卖出量 (股)
    rzrqye          NUMERIC(20,2),  -- 融资融券余额 (元)
    PRIMARY KEY (code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_margin_detail_date ON margin_detail (trade_date);
COMMENT ON TABLE margin_detail IS '个股融资融券明细, 来源Tushare margin_detail';
COMMENT ON COLUMN margin_detail.rzye IS '融资余额, 单位: 元';
COMMENT ON COLUMN margin_detail.rqye IS '融券余额, 单位: 元';
COMMENT ON COLUMN margin_detail.rzmre IS '融资买入额, 单位: 元';
COMMENT ON COLUMN margin_detail.rzrqye IS '融资融券余额, 单位: 元';
"""

MARGIN_RENAME = {"ts_code": "code"}

MARGIN_DB_COLS = [
    "code", "trade_date",
    "rzye", "rqye", "rzmre", "rqyl", "rzche", "rqchl", "rqmcl", "rzrqye",
]


def create_margin_detail_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(MARGIN_DETAIL_DDL)
    conn.commit()
    cur.close()
    print("[margin_detail] table created/verified OK")


def get_missing_margin_dates(conn, start_date: str = "20140102",
                             end_date: str = "20260410") -> list[str]:
    """返回margin_detail中缺失的交易日列表 (YYYYMMDD格式)。"""
    cur = conn.cursor()
    # 获取已有日期
    cur.execute("SELECT DISTINCT trade_date FROM margin_detail ORDER BY trade_date")
    existing = {r[0].strftime("%Y%m%d") for r in cur.fetchall()}

    # 获取trading_calendar中的交易日 (DB从2015起，2014需特殊处理)
    cur.execute("""
        SELECT trade_date FROM trading_calendar
        WHERE is_trading_day = TRUE
          AND trade_date BETWEEN %s AND %s
        ORDER BY trade_date
    """, (start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:],
          end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:]))
    all_trade_dates = {r[0].strftime("%Y%m%d") for r in cur.fetchall()}
    cur.close()

    # 2014年trading_calendar可能不完整，追加已知2014交易日
    # 使用klines_daily的日期作为2014年交易日参考
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT trade_date FROM klines_daily
        WHERE trade_date BETWEEN '2014-01-01' AND '2014-12-31'
        ORDER BY trade_date
    """)
    for r in cur.fetchall():
        all_trade_dates.add(r[0].strftime("%Y%m%d"))
    cur.close()

    missing = sorted(all_trade_dates - existing)
    return missing


def fetch_margin_detail(conn) -> dict:
    """按日期循环拉取margin_detail。"""
    pro = get_pro()
    checkpoint_key = "margin_detail_done"
    done_set = load_checkpoint(checkpoint_key)

    missing_dates = get_missing_margin_dates(conn)
    remaining = [d for d in missing_dates if d not in done_set]
    print(f"[margin_detail] {len(remaining)} dates to fetch "
          f"(skipping {len(done_set)} already done)")

    total_rows = 0
    failed_dates = []
    start_time = time.time()

    for idx, trade_date in enumerate(remaining):
        if idx > 0 and idx % 50 == 0:
            elapsed = time.time() - start_time
            rate = (idx + 1) / elapsed * 60
            print(f"  [{idx}/{len(remaining)}] date={trade_date}, "
                  f"{total_rows} rows, {rate:.0f} dates/min, "
                  f"{len(failed_dates)} failed")
            save_checkpoint(checkpoint_key, done_set)

        df = None
        for attempt in range(3):
            try:
                time.sleep(SLEEP_PER_DATE_REQUEST)
                df = pro.margin_detail(trade_date=trade_date)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [FAIL] {trade_date}: {e}")
                    failed_dates.append(trade_date)
                    df = None
                else:
                    time.sleep(3.0)

        if df is None or df.empty:
            done_set.add(trade_date)
            continue

        # rename ts_code → code
        df = df.rename(columns=MARGIN_RENAME)

        # 转换 trade_date YYYYMMDD → date
        if df["trade_date"].dtype == object:
            df["trade_date"] = pd.to_datetime(
                df["trade_date"], format="%Y%m%d", errors="coerce"
            ).dt.date

        # 铁律29: NaN → None
        df = nan_to_none(df)

        # 只保留目标列
        available_cols = [c for c in MARGIN_DB_COLS if c in df.columns]
        df = df[available_cols]

        # 过滤null PK
        df = df[df["code"].notna() & df["trade_date"].notna()]

        if not df.empty:
            rows_written = upsert_df(conn, "margin_detail", df,
                                     pk_cols=["code", "trade_date"])
            total_rows += rows_written

        done_set.add(trade_date)

    save_checkpoint(checkpoint_key, done_set)
    elapsed = time.time() - start_time

    stats = {
        "table": "margin_detail",
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "failed_dates": failed_dates[:20],
        "failed_count": len(failed_dates),
        "dates_requested": len(remaining),
    }
    print(f"[margin_detail] DONE: {total_rows} rows in {elapsed:.0f}s, "
          f"{len(failed_dates)} failed dates")
    return stats


def verify_margin_detail(conn) -> dict:
    """验证margin_detail。"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(trade_date), MAX(trade_date), COUNT(DISTINCT code) FROM margin_detail")
    cnt, min_d, max_d, codes = cur.fetchone()

    cur.execute("SELECT COUNT(*) FROM margin_detail WHERE rzye IS NULL AND rqye IS NULL")
    all_null = cur.fetchone()[0]
    cur.close()

    result = {
        "total_rows": cnt,
        "min_date": str(min_d) if min_d else None,
        "max_date": str(max_d) if max_d else None,
        "distinct_codes": codes,
        "all_metric_null_rows": all_null,
    }
    print(f"[margin_detail verify] {cnt} rows, {codes} stocks, {min_d}~{max_d}, "
          f"all_null={all_null}")
    return result


# ────────────────────────────────────────────────────────────
# 3. forecast — 业绩预告 (按股票拉取全历史)
# ────────────────────────────────────────────────────────────

FORECAST_DDL = """
CREATE TABLE IF NOT EXISTS forecast (
    code            VARCHAR(10)     NOT NULL,
    end_date        DATE            NOT NULL,
    ann_date        DATE,
    type            VARCHAR(10),     -- 预告类型: 预增/预减/扭亏/首亏/续盈/续亏/略增/略减
    p_change_min    NUMERIC(16,4),   -- 预告净利润变动幅度下限 (%)
    p_change_max    NUMERIC(16,4),   -- 预告净利润变动幅度上限 (%)
    net_profit_min  NUMERIC(20,4),   -- 预告净利润下限 (万元)
    net_profit_max  NUMERIC(20,4),   -- 预告净利润上限 (万元)
    last_parent_net NUMERIC(20,4),   -- 上年同期归母净利润 (万元)
    first_ann_date  DATE,            -- 首次公告日
    summary         TEXT,            -- 业绩预告摘要
    change_reason   TEXT,            -- 业绩变动原因
    PRIMARY KEY (code, end_date)
);
CREATE INDEX IF NOT EXISTS idx_forecast_ann_date ON forecast (ann_date);
COMMENT ON TABLE forecast IS '业绩预告, 来源Tushare forecast';
COMMENT ON COLUMN forecast.p_change_min IS '预告净利润变动幅度下限, 单位: %';
COMMENT ON COLUMN forecast.net_profit_min IS '预告净利润下限, 单位: 万元';
"""

FORECAST_FIELDS = (
    "ts_code,ann_date,end_date,type,"
    "p_change_min,p_change_max,net_profit_min,net_profit_max,"
    "last_parent_net,first_ann_date,summary,change_reason"
)

FORECAST_RENAME = {"ts_code": "code"}

FORECAST_DB_COLS = [
    "code", "end_date", "ann_date", "type",
    "p_change_min", "p_change_max", "net_profit_min", "net_profit_max",
    "last_parent_net", "first_ann_date", "summary", "change_reason",
]


def create_forecast_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(FORECAST_DDL)
    conn.commit()
    cur.close()
    print("[forecast] table created/verified OK")


def fetch_forecast(symbols: list[str], conn) -> dict:
    """按股票循环拉取全历史forecast。"""
    pro = get_pro()
    checkpoint_key = "forecast_done"
    done_set = load_checkpoint(checkpoint_key)

    total_rows = 0
    failed = []
    start_time = time.time()
    request_count = 0

    remaining = [s for s in symbols if s not in done_set]
    print(f"[forecast] {len(remaining)} stocks to fetch "
          f"(skipping {len(done_set)} already done)")

    for idx, code in enumerate(remaining):
        if idx > 0 and idx % 100 == 0:
            elapsed = time.time() - start_time
            rate = request_count / elapsed * 60 if elapsed > 0 else 0
            print(f"  [{idx}/{len(remaining)}] {total_rows} rows fetched, "
                  f"{rate:.0f} req/min, {len(failed)} failed")
            save_checkpoint(checkpoint_key, done_set)

        df = None
        for attempt in range(3):
            try:
                time.sleep(SLEEP_PER_REQUEST)
                df = pro.forecast(ts_code=code, fields=FORECAST_FIELDS)
                request_count += 1
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [FAIL] {code}: {e}")
                    failed.append(code)
                    df = None
                else:
                    time.sleep(2.0)

        if df is None or df.empty:
            done_set.add(code)
            continue

        df = df.rename(columns=FORECAST_RENAME)

        for date_col in ["ann_date", "end_date", "first_ann_date"]:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(
                    df[date_col], format="%Y%m%d", errors="coerce"
                ).dt.date

        df = nan_to_none(df)
        available_cols = [c for c in FORECAST_DB_COLS if c in df.columns]
        df = df[available_cols]
        df = df[df["end_date"].notna() & df["code"].notna()]

        # 同一(code, end_date)保留ann_date最新
        if "ann_date" in df.columns:
            df = df.sort_values("ann_date", ascending=False, na_position="last")
        df = df.drop_duplicates(subset=["code", "end_date"], keep="first")

        if not df.empty:
            rows_written = upsert_df(conn, "forecast", df,
                                     pk_cols=["code", "end_date"])
            total_rows += rows_written

        done_set.add(code)

    save_checkpoint(checkpoint_key, done_set)
    elapsed = time.time() - start_time

    stats = {
        "table": "forecast",
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "failed_count": len(failed),
        "failed_codes": failed[:20],
        "requested": len(remaining),
    }
    print(f"[forecast] DONE: {total_rows} rows in {elapsed:.0f}s, "
          f"{len(failed)} failed")
    return stats


def verify_forecast(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(end_date), MAX(end_date), COUNT(DISTINCT code) FROM forecast")
    cnt, min_d, max_d, codes = cur.fetchone()
    cur.close()
    result = {
        "total_rows": cnt,
        "min_date": str(min_d) if min_d else None,
        "max_date": str(max_d) if max_d else None,
        "distinct_codes": codes,
    }
    print(f"[forecast verify] {cnt} rows, {codes} stocks, {min_d}~{max_d}")
    return result


# ────────────────────────────────────────────────────────────
# 4. express — 业绩快报 (按股票拉取全历史)
# ────────────────────────────────────────────────────────────

EXPRESS_DDL = """
CREATE TABLE IF NOT EXISTS express (
    code            VARCHAR(10)     NOT NULL,
    end_date        DATE            NOT NULL,
    ann_date        DATE,
    revenue         NUMERIC(20,4),   -- 营业收入 (万元)
    operate_profit  NUMERIC(20,4),   -- 营业利润 (万元)
    total_profit    NUMERIC(20,4),   -- 利润总额 (万元)
    n_income        NUMERIC(20,4),   -- 净利润 (万元)
    total_assets    NUMERIC(20,4),   -- 总资产 (万元)
    diluted_eps     NUMERIC(12,6),   -- 稀释每股收益 (元)
    diluted_roe     NUMERIC(12,6),   -- 稀释ROE (%)
    yoy_net_profit  NUMERIC(20,4),   -- 去年同期净利润增长率 (%)
    bps             NUMERIC(12,6),   -- 每股净资产 (元)
    yoy_sales       NUMERIC(20,4),   -- 同比营业收入增长率 (%)
    yoy_op          NUMERIC(20,4),   -- 同比营业利润增长率 (%)
    yoy_tp          NUMERIC(20,4),   -- 同比利润总额增长率 (%)
    yoy_dedu_np     NUMERIC(20,4),   -- 同比扣非净利润增长率 (%)
    yoy_eps         NUMERIC(20,4),   -- 同比每股收益增长率 (%)
    yoy_roe         NUMERIC(20,4),   -- 同比ROE增长率 (%)
    perf_summary    TEXT,            -- 业绩简要说明
    is_audit        INTEGER,         -- 是否审计 0否1是
    PRIMARY KEY (code, end_date)
);
CREATE INDEX IF NOT EXISTS idx_express_ann_date ON express (ann_date);
COMMENT ON TABLE express IS '业绩快报, 来源Tushare express';
COMMENT ON COLUMN express.revenue IS '营业收入, 单位: 万元';
COMMENT ON COLUMN express.n_income IS '净利润, 单位: 万元';
"""

EXPRESS_FIELDS = (
    "ts_code,ann_date,end_date,revenue,operate_profit,total_profit,"
    "n_income,total_assets,diluted_eps,diluted_roe,"
    "yoy_net_profit,bps,yoy_sales,yoy_op,yoy_tp,"
    "yoy_dedu_np,yoy_eps,yoy_roe,perf_summary,is_audit"
)

EXPRESS_RENAME = {"ts_code": "code"}

EXPRESS_DB_COLS = [
    "code", "end_date", "ann_date", "revenue", "operate_profit",
    "total_profit", "n_income", "total_assets",
    "diluted_eps", "diluted_roe", "yoy_net_profit", "bps",
    "yoy_sales", "yoy_op", "yoy_tp", "yoy_dedu_np",
    "yoy_eps", "yoy_roe", "perf_summary", "is_audit",
]


def create_express_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(EXPRESS_DDL)
    conn.commit()
    cur.close()
    print("[express] table created/verified OK")


def fetch_express(symbols: list[str], conn) -> dict:
    """按股票循环拉取全历史express。"""
    pro = get_pro()
    checkpoint_key = "express_done"
    done_set = load_checkpoint(checkpoint_key)

    total_rows = 0
    failed = []
    start_time = time.time()
    request_count = 0

    remaining = [s for s in symbols if s not in done_set]
    print(f"[express] {len(remaining)} stocks to fetch "
          f"(skipping {len(done_set)} already done)")

    for idx, code in enumerate(remaining):
        if idx > 0 and idx % 100 == 0:
            elapsed = time.time() - start_time
            rate = request_count / elapsed * 60 if elapsed > 0 else 0
            print(f"  [{idx}/{len(remaining)}] {total_rows} rows fetched, "
                  f"{rate:.0f} req/min, {len(failed)} failed")
            save_checkpoint(checkpoint_key, done_set)

        df = None
        for attempt in range(3):
            try:
                time.sleep(SLEEP_PER_REQUEST)
                df = pro.express(ts_code=code, fields=EXPRESS_FIELDS)
                request_count += 1
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [FAIL] {code}: {e}")
                    failed.append(code)
                    df = None
                else:
                    time.sleep(2.0)

        if df is None or df.empty:
            done_set.add(code)
            continue

        df = df.rename(columns=EXPRESS_RENAME)

        for date_col in ["ann_date", "end_date"]:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(
                    df[date_col], format="%Y%m%d", errors="coerce"
                ).dt.date

        df = nan_to_none(df)
        available_cols = [c for c in EXPRESS_DB_COLS if c in df.columns]
        df = df[available_cols]
        df = df[df["end_date"].notna() & df["code"].notna()]

        if "ann_date" in df.columns:
            df = df.sort_values("ann_date", ascending=False, na_position="last")
        df = df.drop_duplicates(subset=["code", "end_date"], keep="first")

        if not df.empty:
            rows_written = upsert_df(conn, "express", df,
                                     pk_cols=["code", "end_date"])
            total_rows += rows_written

        done_set.add(code)

    save_checkpoint(checkpoint_key, done_set)
    elapsed = time.time() - start_time

    stats = {
        "table": "express",
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "failed_count": len(failed),
        "failed_codes": failed[:20],
        "requested": len(remaining),
    }
    print(f"[express] DONE: {total_rows} rows in {elapsed:.0f}s, "
          f"{len(failed)} failed")
    return stats


def verify_express(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(end_date), MAX(end_date), COUNT(DISTINCT code) FROM express")
    cnt, min_d, max_d, codes = cur.fetchone()
    cur.close()
    result = {
        "total_rows": cnt,
        "min_date": str(min_d) if min_d else None,
        "max_date": str(max_d) if max_d else None,
        "distinct_codes": codes,
    }
    print(f"[express verify] {cnt} rows, {codes} stocks, {min_d}~{max_d}")
    return result


# ────────────────────────────────────────────────────────────
# 5. top_list — 龙虎榜 (按日期拉取)
# ────────────────────────────────────────────────────────────

TOP_LIST_DDL = """
CREATE TABLE IF NOT EXISTS top_list (
    code            VARCHAR(10)     NOT NULL,
    trade_date      DATE            NOT NULL,
    name            VARCHAR(20),
    close           NUMERIC(12,4),
    pct_change      NUMERIC(12,6),
    turnover_rate   NUMERIC(12,6),
    amount          NUMERIC(20,4),   -- 总成交额 (万元)
    l_sell          NUMERIC(20,4),   -- 龙虎榜卖出额 (万元)
    l_buy           NUMERIC(20,4),   -- 龙虎榜买入额 (万元)
    l_amount        NUMERIC(20,4),   -- 龙虎榜成交额 (万元)
    net_amount      NUMERIC(20,4),   -- 龙虎榜净买入额 (万元)
    net_rate        NUMERIC(12,6),   -- 龙虎榜净买额占比 (%)
    amount_rate     NUMERIC(12,6),   -- 龙虎榜成交额占比 (%)
    float_values    NUMERIC(20,4),   -- 当日流通市值 (万元)
    reason          TEXT,            -- 上榜原因
    PRIMARY KEY (code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_top_list_date ON top_list (trade_date);
COMMENT ON TABLE top_list IS '龙虎榜明细, 来源Tushare top_list';
COMMENT ON COLUMN top_list.amount IS '总成交额, 单位: 万元';
COMMENT ON COLUMN top_list.net_amount IS '龙虎榜净买入额, 单位: 万元';
"""

TOP_LIST_RENAME = {"ts_code": "code"}

TOP_LIST_DB_COLS = [
    "code", "trade_date", "name", "close", "pct_change", "turnover_rate",
    "amount", "l_sell", "l_buy", "l_amount", "net_amount",
    "net_rate", "amount_rate", "float_values", "reason",
]


def create_top_list_table(conn) -> None:
    cur = conn.cursor()
    cur.execute(TOP_LIST_DDL)
    conn.commit()
    cur.close()
    print("[top_list] table created/verified OK")


def get_missing_top_list_dates(conn, start_date: str = "20140102",
                               end_date: str = "20260410") -> list[str]:
    """返回top_list中缺失的交易日列表。"""
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT trade_date FROM top_list ORDER BY trade_date")
    existing = {r[0].strftime("%Y%m%d") for r in cur.fetchall()}

    # 使用klines_daily的日期作为交易日参考 (覆盖2014-2026)
    cur.execute("""
        SELECT DISTINCT trade_date FROM klines_daily
        WHERE trade_date BETWEEN %s AND %s
        ORDER BY trade_date
    """, (start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:],
          end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:]))
    all_trade_dates = {r[0].strftime("%Y%m%d") for r in cur.fetchall()}
    cur.close()

    missing = sorted(all_trade_dates - existing)
    return missing


def fetch_top_list(conn) -> dict:
    """按日期循环拉取top_list。"""
    pro = get_pro()
    checkpoint_key = "top_list_done"
    done_set = load_checkpoint(checkpoint_key)

    missing_dates = get_missing_top_list_dates(conn)
    remaining = [d for d in missing_dates if d not in done_set]
    print(f"[top_list] {len(remaining)} dates to fetch "
          f"(skipping {len(done_set)} already done)")

    total_rows = 0
    failed_dates = []
    start_time = time.time()

    for idx, trade_date in enumerate(remaining):
        if idx > 0 and idx % 50 == 0:
            elapsed = time.time() - start_time
            rate = (idx + 1) / elapsed * 60 if elapsed > 0 else 0
            print(f"  [{idx}/{len(remaining)}] date={trade_date}, "
                  f"{total_rows} rows, {rate:.0f} dates/min, "
                  f"{len(failed_dates)} failed")
            save_checkpoint(checkpoint_key, done_set)

        df = None
        for attempt in range(3):
            try:
                time.sleep(SLEEP_PER_DATE_REQUEST)
                df = pro.top_list(trade_date=trade_date)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [FAIL] {trade_date}: {e}")
                    failed_dates.append(trade_date)
                    df = None
                else:
                    time.sleep(3.0)

        if df is None or df.empty:
            done_set.add(trade_date)
            continue

        df = df.rename(columns=TOP_LIST_RENAME)

        if df["trade_date"].dtype == object:
            df["trade_date"] = pd.to_datetime(
                df["trade_date"], format="%Y%m%d", errors="coerce"
            ).dt.date

        df = nan_to_none(df)
        available_cols = [c for c in TOP_LIST_DB_COLS if c in df.columns]
        df = df[available_cols]
        df = df[df["code"].notna() & df["trade_date"].notna()]

        # 同一(code, trade_date)可能有多条记录(不同原因), 聚合保留净买入最大的
        if not df.empty and len(df) > df[["code", "trade_date"]].drop_duplicates().shape[0]:
            # 按净买入额降序, 保留最大的一条
            df = df.sort_values("net_amount", ascending=False, na_position="last")
            df = df.drop_duplicates(subset=["code", "trade_date"], keep="first")

        if not df.empty:
            rows_written = upsert_df(conn, "top_list", df,
                                     pk_cols=["code", "trade_date"])
            total_rows += rows_written

        done_set.add(trade_date)

    save_checkpoint(checkpoint_key, done_set)
    elapsed = time.time() - start_time

    stats = {
        "table": "top_list",
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "failed_dates": failed_dates[:20],
        "failed_count": len(failed_dates),
        "dates_requested": len(remaining),
    }
    print(f"[top_list] DONE: {total_rows} rows in {elapsed:.0f}s, "
          f"{len(failed_dates)} failed dates")
    return stats


def verify_top_list(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(trade_date), MAX(trade_date), COUNT(DISTINCT code) FROM top_list")
    cnt, min_d, max_d, codes = cur.fetchone()
    cur.close()
    result = {
        "total_rows": cnt,
        "min_date": str(min_d) if min_d else None,
        "max_date": str(max_d) if max_d else None,
        "distinct_codes": codes,
    }
    print(f"[top_list verify] {cnt} rows, {codes} stocks, {min_d}~{max_d}")
    return result


# ────────────────────────────────────────────────────────────
# 6. stk_holdernumber — 股东户数 (补全, 表已存在82K行/550股)
# ────────────────────────────────────────────────────────────

HOLDERNUMBER_DB_COLS = ["code", "ann_date", "end_date", "holder_num", "holder_num_change"]
HOLDERNUMBER_RENAME = {"ts_code": "code"}


def fetch_holdernumber(symbols: list[str], conn) -> dict:
    """按股票循环补全stk_holdernumber (holder_number表已存在)。"""
    pro = get_pro()
    checkpoint_key = "holdernumber_done"
    done_set = load_checkpoint(checkpoint_key)

    total_rows = 0
    failed = []
    start_time = time.time()
    request_count = 0

    remaining = [s for s in symbols if s not in done_set]
    print(f"[holdernumber] {len(remaining)} stocks to fetch "
          f"(skipping {len(done_set)} already done)")

    for idx, code in enumerate(remaining):
        if idx > 0 and idx % 100 == 0:
            elapsed = time.time() - start_time
            rate = request_count / elapsed * 60 if elapsed > 0 else 0
            print(f"  [{idx}/{len(remaining)}] {total_rows} rows fetched, "
                  f"{rate:.0f} req/min, {len(failed)} failed")
            save_checkpoint(checkpoint_key, done_set)

        df = None
        for attempt in range(3):
            try:
                time.sleep(SLEEP_PER_REQUEST)
                df = pro.stk_holdernumber(ts_code=code)
                request_count += 1
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [FAIL] {code}: {e}")
                    failed.append(code)
                    df = None
                else:
                    time.sleep(2.0)

        if df is None or df.empty:
            done_set.add(code)
            continue

        df = df.rename(columns=HOLDERNUMBER_RENAME)

        for date_col in ["ann_date", "end_date"]:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(
                    df[date_col], format="%Y%m%d", errors="coerce"
                ).dt.date

        df = nan_to_none(df)
        available_cols = [c for c in HOLDERNUMBER_DB_COLS if c in df.columns]
        df = df[available_cols]
        df = df[df["code"].notna() & df["ann_date"].notna() & df["end_date"].notna()]
        df = df.drop_duplicates(subset=["code", "ann_date", "end_date"], keep="first")

        if not df.empty:
            rows_written = upsert_df(conn, "holder_number", df,
                                     pk_cols=["code", "ann_date", "end_date"])
            total_rows += rows_written

        done_set.add(code)

    save_checkpoint(checkpoint_key, done_set)
    elapsed = time.time() - start_time

    stats = {
        "table": "holder_number",
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "failed_count": len(failed),
        "failed_codes": failed[:20],
        "requested": len(remaining),
    }
    print(f"[holdernumber] DONE: {total_rows} rows in {elapsed:.0f}s, "
          f"{len(failed)} failed")
    return stats


def verify_holdernumber(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), MIN(end_date), MAX(end_date), COUNT(DISTINCT code) FROM holder_number")
    cnt, min_d, max_d, codes = cur.fetchone()
    cur.close()
    result = {
        "total_rows": cnt,
        "min_date": str(min_d) if min_d else None,
        "max_date": str(max_d) if max_d else None,
        "distinct_codes": codes,
    }
    print(f"[holdernumber verify] {cnt} rows, {codes} stocks, {min_d}~{max_d}")
    return result


# ────────────────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────────────────

def get_active_symbols(conn) -> list[str]:
    """获取活跃非BJ股票代码列表。"""
    cur = conn.cursor()
    # 排除北交所(4开头 8开头), 包含已退市(历史数据需要)
    cur.execute("""
        SELECT code FROM symbols
        WHERE code NOT LIKE '4%%'
          AND code NOT LIKE '8%%'
        ORDER BY code
    """)
    codes = [r[0] for r in cur.fetchall()]
    cur.close()
    print(f"[symbols] {len(codes)} codes loaded (excluding BJ)")
    return codes


def main():
    parser = argparse.ArgumentParser(description="Phase 3B 新数据源拉取入库")
    parser.add_argument(
        "--task",
        choices=["fina_indicator", "margin_detail", "forecast", "express",
                 "top_list", "holdernumber", "all"],
        default="all",
        help="要执行的任务"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只建表和验证，不拉取数据"
    )
    args = parser.parse_args()

    conn = get_conn()
    report = {
        "run_time": datetime.now().isoformat(),
        "tasks": {},
        "data_quality_issues": [],
        "skipped": [],
    }

    try:
        # moneyflow_daily: 已有完整数据, 跳过
        report["skipped"].append({
            "table": "moneyflow_daily",
            "reason": "already complete: 11,386,118 rows, 2014-01-02~2026-04-10"
        })

        # holder_number: 已有82K行历史数据, 属于低优先级
        report["skipped"].append({
            "table": "holder_number",
            "reason": "already has 82,286 rows from 1994-2026, low priority"
        })

        # stk_factor: 与daily_basic完全重复(11.6M行, 18列全覆盖), 跳过
        report["skipped"].append({
            "table": "stk_factor",
            "reason": "redundant with daily_basic (11,615,969 rows, all 18 cols overlap)"
        })

        symbols = None  # lazy load

        # ── Task 1: fina_indicator ────────────────────────────
        if args.task in ("fina_indicator", "all"):
            print("\n" + "="*60)
            print("TASK 1: fina_indicator")
            print("="*60)
            create_fina_indicator_table(conn)

            if not args.dry_run:
                if symbols is None:
                    symbols = get_active_symbols(conn)
                fetch_stats = fetch_fina_indicator(symbols, conn)
                verify_stats = verify_fina_indicator(conn)
                report["tasks"]["fina_indicator"] = {
                    **fetch_stats,
                    "verification": verify_stats,
                }
                if verify_stats["null_pk_rows"] > 0:
                    report["data_quality_issues"].append(
                        f"fina_indicator: {verify_stats['null_pk_rows']} rows with NULL PK"
                    )
                if fetch_stats["failed_count"] > 0:
                    report["data_quality_issues"].append(
                        f"fina_indicator: {fetch_stats['failed_count']} stocks failed to fetch"
                    )
            else:
                print("[dry-run] fina_indicator table created, skipping fetch")
                report["tasks"]["fina_indicator"] = {"dry_run": True}

        # ── Task 2: margin_detail ─────────────────────────────
        if args.task in ("margin_detail", "all"):
            print("\n" + "="*60)
            print("TASK 2: margin_detail")
            print("="*60)
            create_margin_detail_table(conn)

            if not args.dry_run:
                fetch_stats = fetch_margin_detail(conn)
                verify_stats = verify_margin_detail(conn)
                report["tasks"]["margin_detail"] = {
                    **fetch_stats,
                    "verification": verify_stats,
                }
                if fetch_stats["failed_count"] > 0:
                    report["data_quality_issues"].append(
                        f"margin_detail: {fetch_stats['failed_count']} dates failed to fetch"
                    )
            else:
                print("[dry-run] margin_detail table created, skipping fetch")
                report["tasks"]["margin_detail"] = {"dry_run": True}

        # ── Task 3: forecast ──────────────────────────────────
        if args.task in ("forecast", "all"):
            print("\n" + "="*60)
            print("TASK 3: forecast (业绩预告)")
            print("="*60)
            create_forecast_table(conn)

            if not args.dry_run:
                if symbols is None:
                    symbols = get_active_symbols(conn)
                fetch_stats = fetch_forecast(symbols, conn)
                verify_stats = verify_forecast(conn)
                report["tasks"]["forecast"] = {
                    **fetch_stats,
                    "verification": verify_stats,
                }
                if fetch_stats["failed_count"] > 0:
                    report["data_quality_issues"].append(
                        f"forecast: {fetch_stats['failed_count']} stocks failed to fetch"
                    )
            else:
                print("[dry-run] forecast table created, skipping fetch")
                report["tasks"]["forecast"] = {"dry_run": True}

        # ── Task 4: express ───────────────────────────────────
        if args.task in ("express", "all"):
            print("\n" + "="*60)
            print("TASK 4: express (业绩快报)")
            print("="*60)
            create_express_table(conn)

            if not args.dry_run:
                if symbols is None:
                    symbols = get_active_symbols(conn)
                fetch_stats = fetch_express(symbols, conn)
                verify_stats = verify_express(conn)
                report["tasks"]["express"] = {
                    **fetch_stats,
                    "verification": verify_stats,
                }
                if fetch_stats["failed_count"] > 0:
                    report["data_quality_issues"].append(
                        f"express: {fetch_stats['failed_count']} stocks failed to fetch"
                    )
            else:
                print("[dry-run] express table created, skipping fetch")
                report["tasks"]["express"] = {"dry_run": True}

        # ── Task 5: top_list ──────────────────────────────────
        if args.task in ("top_list", "all"):
            print("\n" + "="*60)
            print("TASK 5: top_list (龙虎榜)")
            print("="*60)
            create_top_list_table(conn)

            if not args.dry_run:
                fetch_stats = fetch_top_list(conn)
                verify_stats = verify_top_list(conn)
                report["tasks"]["top_list"] = {
                    **fetch_stats,
                    "verification": verify_stats,
                }
                if fetch_stats["failed_count"] > 0:
                    report["data_quality_issues"].append(
                        f"top_list: {fetch_stats['failed_count']} dates failed to fetch"
                    )
            else:
                print("[dry-run] top_list table created, skipping fetch")
                report["tasks"]["top_list"] = {"dry_run": True}

        # ── Task 6: holdernumber (补全) ───────────────────────
        if args.task in ("holdernumber", "all"):
            print("\n" + "="*60)
            print("TASK 6: holdernumber (股东户数补全)")
            print("="*60)
            # 表已存在, 不需要DDL

            if not args.dry_run:
                if symbols is None:
                    symbols = get_active_symbols(conn)
                fetch_stats = fetch_holdernumber(symbols, conn)
                verify_stats = verify_holdernumber(conn)
                report["tasks"]["holdernumber"] = {
                    **fetch_stats,
                    "verification": verify_stats,
                }
                if fetch_stats["failed_count"] > 0:
                    report["data_quality_issues"].append(
                        f"holdernumber: {fetch_stats['failed_count']} stocks failed to fetch"
                    )
            else:
                print("[dry-run] holdernumber table already exists, skipping fetch")
                report["tasks"]["holdernumber"] = {"dry_run": True}

    finally:
        conn.close()

    # ── 写报告 ────────────────────────────────────────────────
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[report] written to {REPORT_PATH}")

    # 打印摘要
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for task_name, stats in report["tasks"].items():
        if isinstance(stats, dict) and "total_rows" in stats:
            v = stats.get("verification", {})
            print(f"  {task_name}:")
            print(f"    rows_fetched  = {stats['total_rows']:,}")
            print(f"    elapsed       = {stats['elapsed_seconds']:.0f}s")
            print(f"    failed        = {stats['failed_count']}")
            if v:
                print(f"    db_total_rows = {v.get('total_rows', 'N/A'):,}")
                print(f"    date_range    = {v.get('min_date')} ~ {v.get('max_date')}")
                print(f"    distinct_codes= {v.get('distinct_codes', 'N/A')}")

    if report["data_quality_issues"]:
        print("\n[DATA QUALITY ISSUES]")
        for issue in report["data_quality_issues"]:
            print(f"  P1: {issue}")
    else:
        print("\n[DATA QUALITY] No issues detected.")

    for skip in report["skipped"]:
        print(f"\n[SKIPPED] {skip['table']}: {skip['reason']}")


if __name__ == "__main__":
    main()
