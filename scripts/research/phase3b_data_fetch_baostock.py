"""Phase 3B — BaoStock 季频财务数据拉取入库。

BaoStock提供的季频数据 (fina_indicator已覆盖部分, 本脚本拉取补充数据):
  1. profit_data     — 盈利能力 (已有fina_indicator覆盖ROE/ROA/margin, 本接口补充ROIC/EBITDA等)
  2. operation_data  — 营运能力 (应收账款周转/存货周转/总资产周转等)
  3. growth_data     — 成长能力 (营收增长/利润增长/净资产增长等)
  4. balance_data    — 资产负债 (总资产/总负债/净资产/货币资金等)
  5. cash_flow_data  — 现金流量 (经营/投资/筹资CF等)
  6. dupont_data     — 杜邦分析 (ROE分解: 利润率×周转率×杠杆)

铁律:
  - 铁律29: NaN → None (SQL NULL)
  - 铁律17: psycopg2 execute_values + ON CONFLICT DO UPDATE
  - BaoStock无频率限制, 但建议适当sleep防止IP封禁

用法:
    python scripts/research/phase3b_data_fetch_baostock.py --task operation_data
    python scripts/research/phase3b_data_fetch_baostock.py --task growth_data
    python scripts/research/phase3b_data_fetch_baostock.py --task balance_data
    python scripts/research/phase3b_data_fetch_baostock.py --task cash_flow_data
    python scripts/research/phase3b_data_fetch_baostock.py --task dupont_data
    python scripts/research/phase3b_data_fetch_baostock.py --task all
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

# ─────────���───────────────────────────────���──────────────────
# 配置
# ─────────────────────────────────────────────���──────────────
DB_DSN = "dbname=quantmind_v2 user=xin password=quantmind host=localhost"
BATCH_SIZE = 5000
REPORT_PATH = Path("cache/phase3b_fetch_baostock_report.json")
CHECKPOINT_DIR = Path("cache/phase3b_checkpoints")
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# BaoStock无频率限制, 不需sleep (实测无封禁)


def get_conn():
    return psycopg2.connect(DB_DSN)


def nan_to_none(df: pd.DataFrame) -> pd.DataFrame:
    """铁律29: NaN → None。"""
    return df.where(pd.notnull(df), other=None)


def load_checkpoint(name: str) -> set:
    path = CHECKPOINT_DIR / f"bs_{name}.json"
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()


def save_checkpoint(name: str, done_set: set) -> None:
    path = CHECKPOINT_DIR / f"bs_{name}.json"
    with open(path, "w") as f:
        json.dump(list(done_set), f)


def upsert_df(conn, table: str, df: pd.DataFrame, pk_cols: list[str],
              batch_size: int = BATCH_SIZE) -> int:
    """通用Upsert。"""
    if df.empty:
        return 0
    if pk_cols and all(c in df.columns for c in pk_cols):
        df = df.drop_duplicates(subset=pk_cols, keep="first")

    cols = list(df.columns)
    non_pk = [c for c in cols if c not in pk_cols]
    conflict_clause = ", ".join(pk_cols)
    if non_pk:
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in non_pk)
        on_conflict = f"ON CONFLICT ({conflict_clause}) DO UPDATE SET {update_clause}"
    else:
        on_conflict = f"ON CONFLICT ({conflict_clause}) DO NOTHING"

    cols_str = ", ".join(cols)
    sql = f"INSERT INTO {table} ({cols_str}) VALUES %s {on_conflict}"

    total = 0
    cur = conn.cursor()
    try:
        for i in range(0, len(df), batch_size):
            chunk = df.iloc[i:i + batch_size]
            records = [
                tuple(None if (isinstance(v, float) and np.isnan(v)) else v
                      for v in row)
                for row in chunk.itertuples(index=False)
            ]
            psycopg2.extras.execute_values(cur, sql, records)
            total += len(records)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return total


def code_db_to_bs(code: str) -> str:
    """DB格式 → BaoStock格式: 000001.SZ → sh.000001 / sz.000001"""
    num, suffix = code.split(".")
    prefix = "sh" if suffix == "SH" else "sz"
    return f"{prefix}.{num}"


def get_active_symbols(conn) -> list[str]:
    """获取活跃非BJ股票代码列表 (DB格式)。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT code FROM symbols
        WHERE code NOT LIKE '4%%' AND code NOT LIKE '8%%'
        ORDER BY code
    """)
    codes = [r[0] for r in cur.fetchall()]
    cur.close()
    print(f"[symbols] {len(codes)} codes loaded (excluding BJ)")
    return codes



# ───────────────────────��────────────────────────────────────
# DDL for new tables
# ──────────────────────────────────────────��─────────────────

OPERATION_DATA_DDL = """
CREATE TABLE IF NOT EXISTS bs_operation_data (
    code                VARCHAR(10)  NOT NULL,
    end_date            DATE         NOT NULL,
    nr_turn_ratio       NUMERIC(12,6),   -- 应收账款周转率
    nr_turn_days        NUMERIC(12,4),   -- 应收账款周转天数
    inv_turn_ratio      NUMERIC(12,6),   -- 存货周转率
    inv_turn_days       NUMERIC(12,4),   -- 存货周转天数
    ca_turn_ratio       NUMERIC(12,6),   -- 流动资产周转率
    asset_turn_ratio    NUMERIC(12,6),   -- 总资产周转率
    PRIMARY KEY (code, end_date)
);
COMMENT ON TABLE bs_operation_data IS 'BaoStock 营运能力季频数据';
"""

GROWTH_DATA_DDL = """
CREATE TABLE IF NOT EXISTS bs_growth_data (
    code                VARCHAR(10)  NOT NULL,
    end_date            DATE         NOT NULL,
    yoy_equity          NUMERIC(16,6),   -- 净资产同比增长率 (%)
    yoy_asset           NUMERIC(16,6),   -- 总资产同比增长率 (%)
    yoy_ni              NUMERIC(16,6),   -- 净利润同比增长率 (%)
    yoy_eps_basic       NUMERIC(16,6),   -- 基��每股收益同比增长率 (%)
    yoy_pni             NUMERIC(16,6),   -- 归母净利润同比��长率 (%)
    PRIMARY KEY (code, end_date)
);
COMMENT ON TABLE bs_growth_data IS 'BaoStock 成长能力季频数据';
"""

BALANCE_DATA_DDL = """
CREATE TABLE IF NOT EXISTS bs_balance_data (
    code                VARCHAR(10)  NOT NULL,
    end_date            DATE         NOT NULL,
    current_ratio       NUMERIC(16,6),   -- 流动比率
    quick_ratio         NUMERIC(16,6),   -- 速动比率
    cash_ratio          NUMERIC(16,6),   -- 现金比率
    yoy_liability       NUMERIC(16,6),   -- 总负债同比增长率 (%)
    liability_to_asset  NUMERIC(16,6),   -- 资产负债率
    asset_to_equity     NUMERIC(16,6),   -- 权益乘数
    PRIMARY KEY (code, end_date)
);
COMMENT ON TABLE bs_balance_data IS 'BaoStock 偿债能力季频数据 (比率指标, 非原始资产负债表)';
"""

CASH_FLOW_DATA_DDL = """
CREATE TABLE IF NOT EXISTS bs_cash_flow_data (
    code                VARCHAR(10)  NOT NULL,
    end_date            DATE         NOT NULL,
    ca_to_asset         NUMERIC(16,6),   -- 流动资产除以总资产
    nca_to_asset        NUMERIC(16,6),   -- 非流动资产除以总资产
    tangible_to_asset   NUMERIC(16,6),   -- 有形资产除以总资产
    ebit_to_interest    NUMERIC(16,6),   -- 已获利息倍数(EBIT/利息)
    cfo_to_or           NUMERIC(16,6),   -- 经营活动现金流净额/营业收入
    cfo_to_np           NUMERIC(16,6),   -- 经营活动现金流净额/净利润
    cfo_to_gr           NUMERIC(16,6),   -- 经营活动现金流净额/营业总收入
    PRIMARY KEY (code, end_date)
);
COMMENT ON TABLE bs_cash_flow_data IS 'BaoStock 现金流比率季频数据 (比率指标, 非原始现金流量表)';
"""

DUPONT_DATA_DDL = """
CREATE TABLE IF NOT EXISTS bs_dupont_data (
    code                VARCHAR(10)  NOT NULL,
    end_date            DATE         NOT NULL,
    dupont_roe          NUMERIC(16,8),   -- ROE (归母)
    dupont_asset_to_equity NUMERIC(16,8), -- 权益乘数 (杠杆)
    dupont_asset_turn   NUMERIC(16,8),   -- 总资产周转率
    dupont_profit_to_gp NUMERIC(16,8),   -- 归母净利润/营业总收入
    dupont_tax_burden   NUMERIC(16,8),   -- 税收负担 (净利润/利润总额)
    dupont_int_burden   NUMERIC(16,8),   -- 利息负担 (利润总额/EBIT)
    dupont_ebit_to_gp   NUMERIC(16,8),   -- EBIT/营业总收入
    PRIMARY KEY (code, end_date)
);
COMMENT ON TABLE bs_dupont_data IS 'BaoStock 杜邦分析季频数据';
"""


# ──────────────────────────────────────────────���─────────────
# 通用BaoStock季频数据拉取
# ────────────────────────────────────────────────────────────

BS_QUERY_MAP = {
    "operation_data": {
        "query_func": "query_operation_data",
        "table": "bs_operation_data",
        "ddl": OPERATION_DATA_DDL,
        "rename": {
            "NRTurnRatio": "nr_turn_ratio",
            "NRTurnDays": "nr_turn_days",
            "INVTurnRatio": "inv_turn_ratio",
            "INVTurnDays": "inv_turn_days",
            "CATurnRatio": "ca_turn_ratio",
            "AssetTurnRatio": "asset_turn_ratio",
        },
        "db_cols": ["code", "end_date", "nr_turn_ratio", "nr_turn_days",
                    "inv_turn_ratio", "inv_turn_days", "ca_turn_ratio",
                    "asset_turn_ratio"],
    },
    "growth_data": {
        "query_func": "query_growth_data",
        "table": "bs_growth_data",
        "ddl": GROWTH_DATA_DDL,
        "rename": {
            "YOYEquity": "yoy_equity",
            "YOYAsset": "yoy_asset",
            "YOYNI": "yoy_ni",
            "YOYEPSBasic": "yoy_eps_basic",
            "YOYPNI": "yoy_pni",
        },
        "db_cols": ["code", "end_date", "yoy_equity", "yoy_asset",
                    "yoy_ni", "yoy_eps_basic", "yoy_pni"],
    },
    "balance_data": {
        "query_func": "query_balance_data",
        "table": "bs_balance_data",
        "ddl": BALANCE_DATA_DDL,
        "rename": {
            "currentRatio": "current_ratio",
            "quickRatio": "quick_ratio",
            "cashRatio": "cash_ratio",
            "YOYLiability": "yoy_liability",
            "liabilityToAsset": "liability_to_asset",
            "assetToEquity": "asset_to_equity",
        },
        "db_cols": ["code", "end_date", "current_ratio", "quick_ratio",
                    "cash_ratio", "yoy_liability", "liability_to_asset",
                    "asset_to_equity"],
    },
    "cash_flow_data": {
        "query_func": "query_cash_flow_data",
        "table": "bs_cash_flow_data",
        "ddl": CASH_FLOW_DATA_DDL,
        "rename": {
            "CAToAsset": "ca_to_asset",
            "NCAToAsset": "nca_to_asset",
            "tangibleAssetToAsset": "tangible_to_asset",
            "ebitToInterest": "ebit_to_interest",
            "CFOToOR": "cfo_to_or",
            "CFOToNP": "cfo_to_np",
            "CFOToGr": "cfo_to_gr",
        },
        "db_cols": ["code", "end_date", "ca_to_asset", "nca_to_asset",
                    "tangible_to_asset", "ebit_to_interest",
                    "cfo_to_or", "cfo_to_np", "cfo_to_gr"],
    },
    "dupont_data": {
        "query_func": "query_dupont_data",
        "table": "bs_dupont_data",
        "ddl": DUPONT_DATA_DDL,
        "rename": {
            "dupontROE": "dupont_roe",
            "dupontAssetStoEquity": "dupont_asset_to_equity",
            "dupontAssetTurn": "dupont_asset_turn",
            "dupontPnitoni": "dupont_profit_to_gp",
            "dupontNitogr": "dupont_tax_burden",
            "dupontTaxBurden": "dupont_int_burden",
            "dupontIntburden": "dupont_ebit_to_gp",
            "dupontEbittogr": "dupont_ebit_to_gr",
        },
        "db_cols": ["code", "end_date", "dupont_roe",
                    "dupont_asset_to_equity", "dupont_asset_turn",
                    "dupont_profit_to_gp", "dupont_tax_burden",
                    "dupont_int_burden", "dupont_ebit_to_gp"],
    },
}


# Thread-local BaoStock sessions — login once per thread, reuse across batches
_thread_local = threading.local()


def _ensure_bs_session():
    """Ensure current thread has a logged-in BaoStock session."""
    if not getattr(_thread_local, "logged_in", False):
        import baostock as _bs
        _thread_local.bs = _bs
        lg = _bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"BaoStock login failed in thread: {lg.error_msg}")
        _thread_local.logged_in = True


def _worker_fetch_batch(batch_codes: list[str], query_func_name: str,
                        start_year: int, end_year: int) -> list[tuple[str, list]]:
    """Worker线程: 复用BaoStock session, 拉取一批stocks, 返回原始行数据。

    Returns: [(code, [row_data, ...], fields), ...]
    """
    _ensure_bs_session()
    _bs = _thread_local.bs
    query_fn = getattr(_bs, query_func_name)

    results = []
    for code in batch_codes:
        bs_code = code_db_to_bs(code)
        all_rows = []
        fields = None

        for year in range(start_year, end_year + 1):
            for quarter in range(1, 5):
                if year == end_year and quarter > 1:
                    break
                try:
                    rs = query_fn(code=bs_code, year=year, quarter=quarter)
                    if rs.error_code != "0":
                        continue
                    if fields is None:
                        fields = rs.fields
                    while rs.next():
                        all_rows.append(rs.get_row_data())
                except Exception:
                    pass

        results.append((code, all_rows, fields))

    return results


def fetch_bs_quarterly(task_name: str, symbols: list[str], conn,
                       start_year: int = 2014, end_year: int = 2026,
                       n_workers: int = 8) -> dict:
    """通用BaoStock季频数据拉取。多进程并行。"""
    config = BS_QUERY_MAP[task_name]
    table = config["table"]
    query_func_name = config["query_func"]
    rename_map = config["rename"]
    db_cols = config["db_cols"]

    # 建表
    cur = conn.cursor()
    cur.execute(config["ddl"])
    conn.commit()
    cur.close()
    print(f"[{task_name}] table {table} created/verified OK", flush=True)

    checkpoint_key = task_name
    done_set = load_checkpoint(checkpoint_key)

    remaining = [s for s in symbols if s not in done_set]
    n_quarters = (end_year - start_year) * 4 + 1
    print(f"[{task_name}] {len(remaining)} stocks to fetch "
          f"(skipping {len(done_set)} already done), "
          f"{start_year}-{end_year} ({n_quarters} quarters/stock), "
          f"{n_workers} workers", flush=True)

    if not remaining:
        return {"table": table, "total_rows": 0, "elapsed_seconds": 0,
                "failed_count": 0, "failed_codes": [], "requested": 0}

    # 分批: 每批200个stocks (线程无序列化开销, 可以更大)
    BATCH_SZ = 200
    batches = [remaining[i:i+BATCH_SZ] for i in range(0, len(remaining), BATCH_SZ)]

    total_rows = 0
    failed = []
    start_time = time.time()
    stocks_done = 0

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(
                _worker_fetch_batch, batch, query_func_name,
                start_year, end_year
            ): batch
            for batch in batches
        }

        for future in as_completed(futures):
            batch = futures[future]
            try:
                results = future.result()
            except Exception as e:
                print(f"  [ERROR] batch failed: {e}", flush=True)
                failed.extend(batch)
                stocks_done += len(batch)
                continue

            # 处理结果写DB (主线程)
            batch_rows = 0
            for code, all_rows, fields in results:
                if not all_rows or fields is None:
                    done_set.add(code)
                    continue

                try:
                    df = pd.DataFrame(all_rows, columns=fields)
                except Exception:
                    done_set.add(code)
                    failed.append(code)
                    continue

                # code格式转换
                if "code" in df.columns:
                    df["code"] = df["code"].apply(
                        lambda x: x.split(".")[1] + (".SH" if x.startswith("sh") else ".SZ")
                        if isinstance(x, str) and "." in x else x
                    )
                else:
                    df["code"] = code

                # 日期处理
                if "statDate" in df.columns:
                    df["end_date"] = pd.to_datetime(df["statDate"], errors="coerce").dt.date
                elif "pubDate" in df.columns:
                    df["end_date"] = pd.to_datetime(df["pubDate"], errors="coerce").dt.date

                df = df.rename(columns=rename_map)

                for col in db_cols:
                    if col in df.columns and col not in ("code", "end_date"):
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                df = nan_to_none(df)
                available_cols = [c for c in db_cols if c in df.columns]
                df = df[available_cols]
                df = df[df["code"].notna() & df["end_date"].notna()]
                df = df.drop_duplicates(subset=["code", "end_date"], keep="first")

                if not df.empty:
                    rows_written = upsert_df(conn, table, df,
                                             pk_cols=["code", "end_date"])
                    batch_rows += rows_written

                done_set.add(code)

            total_rows += batch_rows
            stocks_done += len(batch)

            elapsed = time.time() - start_time
            rate = stocks_done / elapsed * 60 if elapsed > 0 else 0
            eta_min = (len(remaining) - stocks_done) / max(rate, 0.1)
            print(f"  [{stocks_done}/{len(remaining)}] {total_rows} rows, "
                  f"{len(failed)} failed, {elapsed:.0f}s, {rate:.0f} stk/min, "
                  f"ETA {eta_min:.0f}min",
                  flush=True)

            # Checkpoint every batch
            save_checkpoint(checkpoint_key, done_set)

    save_checkpoint(checkpoint_key, done_set)
    elapsed = time.time() - start_time

    stats = {
        "table": table,
        "total_rows": total_rows,
        "elapsed_seconds": round(elapsed, 1),
        "failed_count": len(failed),
        "failed_codes": failed[:20],
        "requested": len(remaining),
    }
    print(f"[{task_name}] DONE: {total_rows} rows in {elapsed:.0f}s, "
          f"{len(failed)} failed", flush=True)
    return stats


def verify_bs_table(table: str, conn) -> dict:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*), MIN(end_date), MAX(end_date), COUNT(DISTINCT code) FROM {table}")
    cnt, min_d, max_d, codes = cur.fetchone()
    cur.close()
    result = {
        "total_rows": cnt,
        "min_date": str(min_d) if min_d else None,
        "max_date": str(max_d) if max_d else None,
        "distinct_codes": codes,
    }
    print(f"[{table} verify] {cnt} rows, {codes} stocks, {min_d}~{max_d}")
    return result


# ──────────────────────���────────────────��────────────────────
# 主流程
# ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 3B BaoStock季频数据拉取")
    parser.add_argument(
        "--task",
        choices=["operation_data", "growth_data", "balance_data",
                 "cash_flow_data", "dupont_data", "all"],
        default="all",
        help="要拉取的数据类型"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2014,
        help="起始年份 (默认2014, 可设2020加速)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="并行worker数 (默认8, BaoStock无频率限制)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只建表不拉取"
    )
    args = parser.parse_args()

    # BaoStock登录
    lg = bs.login()
    if lg.error_code != "0":
        print(f"BaoStock login failed: {lg.error_msg}")
        sys.exit(1)
    print("[BaoStock] login OK")

    conn = get_conn()
    symbols = get_active_symbols(conn)
    report = {
        "run_time": datetime.now().isoformat(),
        "tasks": {},
    }

    tasks_to_run = (
        ["operation_data", "growth_data", "balance_data",
         "cash_flow_data", "dupont_data"]
        if args.task == "all" else [args.task]
    )

    try:
        for task_name in tasks_to_run:
            print(f"\n{'='*60}")
            print(f"TASK: {task_name}")
            print(f"{'='*60}")

            if args.dry_run:
                config = BS_QUERY_MAP[task_name]
                cur = conn.cursor()
                cur.execute(config["ddl"])
                conn.commit()
                cur.close()
                print(f"[dry-run] {config['table']} created OK")
                report["tasks"][task_name] = {"dry_run": True}
            else:
                fetch_stats = fetch_bs_quarterly(task_name, symbols, conn,
                                                  start_year=args.start_year,
                                                  n_workers=args.workers)
                config = BS_QUERY_MAP[task_name]
                verify_stats = verify_bs_table(config["table"], conn)
                report["tasks"][task_name] = {
                    **fetch_stats,
                    "verification": verify_stats,
                }

    finally:
        conn.close()
        bs.logout()
        print("[BaoStock] main thread logout")

    # 写报告
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[report] written to {REPORT_PATH}")

    # 摘要
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for task_name, stats in report["tasks"].items():
        if isinstance(stats, dict) and "total_rows" in stats:
            v = stats.get("verification", {})
            print(f"  {task_name}: {stats['total_rows']:,} rows in {stats['elapsed_seconds']:.0f}s, "
                  f"DB total={v.get('total_rows', 'N/A')}")


if __name__ == "__main__":
    main()
