"""MVP 2.1c Sub3 dual-write 对齐监控 — 新老 klines_daily 路径每日盘后一致性检查.

Wave 2 2.1c Sub3 启动前置硬门:
  1. 连续 5 交易日 dual-write 新老 100% 对齐 (行数 + 关键列无差)
  2. regression_test --years 5 max_diff=0 × 3 次
  3. 任一 fail 重置窗口

本脚本: 硬门 #1 自动化. 每日盘后 (or 任意时点) 跑一次:
  - 读 klines_daily DB (老 fetcher 入库, prod)
  - 调 TushareDataSource (新路径, 内存 only 不入库)
  - 对比 12 关键列, 写报告 + 追踪 state

用法:
    # 默认 today
    python scripts/dual_write_check.py

    # 指定日期
    python scripts/dual_write_check.py --date 2026-04-21

    # 回溯窗口
    python scripts/dual_write_check.py --backfill 2026-04-20 2026-04-25

    # 只看 state
    python scripts/dual_write_check.py --status

输出:
  - docs/reports/dual_write/<date>.md  — 每日对齐详情 (Markdown 表格)
  - cache/dual_write_state.json        — 5 日窗口进度 (机器可读)
  - exit 0 PASS, 1 FAIL, 2 ERROR (如 TUSHARE_TOKEN 缺失)

铁律: 10 基础设施改动后全链路验证 / 17 数据入库唯一管道 / 36 precondition 核对
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "backend"))

from app.data_fetcher.data_loader import get_sync_conn  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("dual_write_check")

STATE_FILE = PROJECT_ROOT / "cache" / "dual_write_state.json"
REPORT_DIR = PROJECT_ROOT / "docs" / "reports" / "dual_write"
FLOAT_TOLERANCE = 1e-6

# DataPipeline 入库后 DB 侧列 vs TushareDataSource RAW 列的对比对 (post-rename, post-unit)
_COMPARE_COLS = [
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_change",
    "volume",
    "amount",
    "adj_factor",
    "up_limit",
    "down_limit",
]


def load_old_path(conn, trade_date: date) -> pd.DataFrame:
    """读 klines_daily prod DB (老 fetcher 入库)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT code, trade_date, open, high, low, close, pre_close,
               change, pct_change, volume, amount,
               adj_factor, up_limit, down_limit
          FROM klines_daily
         WHERE trade_date = %s
        """,
        (trade_date,),
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    cur.close()
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def load_new_path(trade_date: date) -> pd.DataFrame:
    """TushareDataSource 新路径 (不入库, 只拉到内存).

    模拟 DataPipeline.ingest 的 rename + 单位转换, 让结果与 DB 形态可比.
    """
    # 延迟 import 避免 TUSHARE_TOKEN 缺失时模块级崩溃
    from app.data_fetcher.tushare_api import TushareAPI
    from backend.platform.data.sources.tushare_source import (
        KLINES_DAILY_DATA_CONTRACT,
        TushareDataSource,
    )

    client = TushareAPI()
    src = TushareDataSource(client=client, end=trade_date)
    df = src.fetch(KLINES_DAILY_DATA_CONTRACT, since=trade_date)
    if df.empty:
        return df
    # 模拟 DataPipeline 的 rename (contracts.py KLINES_DAILY.rename_map)
    df = df.rename(columns={"ts_code": "code", "vol": "volume", "pct_chg": "pct_change"})
    # 单位转换: amount 千元→元 (DataPipeline conversion_factor)
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000.0
    # trade_date 归一到 date
    if "trade_date" in df.columns:
        # Tushare 返回 'YYYYMMDD' str 或 Timestamp
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="mixed").dt.date
    return df


def compare(old: pd.DataFrame, new: pd.DataFrame) -> dict:
    """对比两路径. 返回 dict 报告."""
    report: dict = {
        "old_rows": len(old),
        "new_rows": len(new),
        "row_count_match": len(old) == len(new),
    }
    if old.empty or new.empty:
        report["status"] = "ERROR"
        report["error"] = "one_side_empty"
        return report

    oi = old.set_index(["code", "trade_date"]).sort_index()
    ni = new.set_index(["code", "trade_date"]).sort_index()
    old_keys = set(oi.index)
    new_keys = set(ni.index)
    report["codes_only_in_old"] = len(old_keys - new_keys)
    report["codes_only_in_new"] = len(new_keys - old_keys)
    common = sorted(old_keys & new_keys)
    report["codes_common"] = len(common)

    if not common:
        report["status"] = "ERROR"
        report["error"] = "no_common_pk"
        return report

    o = oi.loc[common]
    n = ni.loc[common]

    col_reports: dict = {}
    all_match = True
    for col in _COMPARE_COLS:
        if col not in o.columns or col not in n.columns:
            col_reports[col] = {"status": "missing_in_either", "match": False}
            all_match = False
            continue
        ov = pd.to_numeric(o[col], errors="coerce")
        nv = pd.to_numeric(n[col], errors="coerce")
        both_nan = ov.isna() & nv.isna()
        only_old_nan = ov.isna() & ~nv.isna()
        only_new_nan = ~ov.isna() & nv.isna()
        diff = (ov - nv).abs()
        mismatch_mask = (diff > FLOAT_TOLERANCE) & ~both_nan
        mismatch = (
            int(mismatch_mask.sum())
            + int(only_old_nan.sum())
            + int(only_new_nan.sum())
        )
        max_diff = float(diff[~both_nan].max()) if (~both_nan).any() else 0.0
        col_match = mismatch == 0
        if not col_match:
            all_match = False
        col_reports[col] = {
            "mismatch_count": mismatch,
            "max_diff": max_diff,
            "only_old_nan": int(only_old_nan.sum()),
            "only_new_nan": int(only_new_nan.sum()),
            "match": col_match,
        }

    report["columns"] = col_reports
    report["all_columns_match"] = all_match
    report["status"] = (
        "PASS"
        if (
            report["row_count_match"]
            and all_match
            and report["codes_only_in_old"] == 0
            and report["codes_only_in_new"] == 0
        )
        else "FAIL"
    )
    return report


def save_state(trade_date: date, report: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    state[trade_date.isoformat()] = {
        "status": report.get("status"),
        "old_rows": report.get("old_rows"),
        "new_rows": report.get("new_rows"),
        "row_count_match": report.get("row_count_match"),
        "codes_only_in_old": report.get("codes_only_in_old"),
        "codes_only_in_new": report.get("codes_only_in_new"),
        "checked_at": datetime.now().isoformat(),
    }
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def save_report(trade_date: date, report: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md = REPORT_DIR / f"{trade_date.isoformat()}.md"
    lines = [
        f"# Dual-write consistency check — {trade_date.isoformat()}",
        "",
        f"**Status**: `{report.get('status', 'ERROR')}`  ",
        f"**Checked at**: {datetime.now().isoformat()}",
        "",
        "## Row counts",
        "",
        f"- old (DB klines_daily): {report.get('old_rows', 0)}",
        f"- new (TushareDataSource): {report.get('new_rows', 0)}",
        f"- row_count_match: {report.get('row_count_match')}",
        f"- codes_only_in_old: {report.get('codes_only_in_old', 'N/A')}",
        f"- codes_only_in_new: {report.get('codes_only_in_new', 'N/A')}",
        f"- codes_common: {report.get('codes_common', 'N/A')}",
        "",
    ]
    if report.get("error"):
        lines += ["## Error", "", f"`{report['error']}`", ""]
    if report.get("columns"):
        lines += [
            "## Column comparison",
            "",
            "| col | mismatch | max_diff | only_old_nan | only_new_nan | match |",
            "| --- | ---: | ---: | ---: | ---: | :---: |",
        ]
        for col, cr in report["columns"].items():
            if cr.get("status") == "missing_in_either":
                lines.append(f"| {col} | - | - | - | - | ❌ missing |")
                continue
            mark = "✅" if cr.get("match") else "❌"
            lines.append(
                f"| {col} | {cr['mismatch_count']} | {cr['max_diff']:.6g} | "
                f"{cr['only_old_nan']} | {cr['only_new_nan']} | {mark} |"
            )
        lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def print_state() -> int:
    if not STATE_FILE.exists():
        print("dual_write_state.json 尚未生成 (本窗口首跑)")
        return 0
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    print(f"Dual-write 窗口进度 (state: {STATE_FILE}):")
    pass_count = 0
    for d in sorted(state.keys()):
        v = state[d]
        mark = "✅" if v.get("status") == "PASS" else "❌"
        if v.get("status") == "PASS":
            pass_count += 1
        print(
            f"  {d} {mark} {v.get('status'):5} "
            f"old={v.get('old_rows')} new={v.get('new_rows')} "
            f"checked={v.get('checked_at', '-')[:19]}"
        )
    print(f"\n窗口合格天数: {pass_count} / 5 (MVP 2.1c Sub3 启动硬门之一)")
    return 0 if pass_count >= 5 else 1


def check_one(trade_date: date) -> dict:
    if not os.environ.get("TUSHARE_TOKEN"):
        return {"status": "ERROR", "error": "TUSHARE_TOKEN not set"}
    conn = get_sync_conn()
    try:
        old = load_old_path(conn, trade_date)
        if old.empty:
            return {
                "status": "ERROR",
                "error": f"old path empty for {trade_date} (老 fetcher 未跑?)",
            }
        new = load_new_path(trade_date)
        report = compare(old, new)
        save_state(trade_date, report)
        md = save_report(trade_date, report)
        logger.info(
            "report: %s  status=%s  old=%d new=%d",
            md,
            report.get("status"),
            report.get("old_rows", 0),
            report.get("new_rows", 0),
        )
        return report
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", type=str, default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument(
        "--backfill",
        nargs=2,
        metavar=("START", "END"),
        help="回溯窗口: YYYY-MM-DD YYYY-MM-DD (inclusive)",
    )
    ap.add_argument(
        "--status",
        action="store_true",
        help="只打印 state 文件进度, 不跑 check",
    )
    args = ap.parse_args()

    if args.status:
        return print_state()

    if args.backfill:
        s = datetime.strptime(args.backfill[0], "%Y-%m-%d").date()
        e = datetime.strptime(args.backfill[1], "%Y-%m-%d").date()
        fails = 0
        d = s
        while d <= e:
            r = check_one(d)
            mark = "✅" if r.get("status") == "PASS" else "❌"
            print(
                f"{d} {mark} {r.get('status'):5} "
                f"old={r.get('old_rows', 0)} new={r.get('new_rows', 0)} "
                f"match={r.get('all_columns_match', '-')}"
            )
            if r.get("status") != "PASS":
                fails += 1
            d += timedelta(days=1)
        return 0 if fails == 0 else 1

    td = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    r = check_one(td)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    status = r.get("status")
    return 0 if status == "PASS" else (2 if status == "ERROR" else 1)


if __name__ == "__main__":
    sys.exit(main())
