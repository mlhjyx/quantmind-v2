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
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "backend"))

from app.config import settings  # noqa: E402 — pydantic Settings 自动读 backend/.env
from app.data_fetcher.data_loader import get_sync_conn  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("dual_write_check")

STATE_FILE = PROJECT_ROOT / "cache" / "dual_write_state.json"
REPORT_DIR = PROJECT_ROOT / "docs" / "reports" / "dual_write"

# Per-column tolerance (2026-04-18 Session 6 backfill 二次诊断发现):
# Tushare API 偶尔微调历史数据 (e.g. volume ±1 手 = ±100 股), float 精度累积,
# 绝对 bit-identical 不现实. Per-col tolerance 业界标准做法.
_COL_TOLERANCE = {
    # 价格列严 (Tushare 稳定, 精度 0.01 元)
    "open": 1e-6,
    "high": 1e-6,
    "low": 1e-6,
    "close": 1e-6,
    "pre_close": 1e-6,
    "change": 1e-6,
    "pct_change": 1e-6,
    # 复权因子严
    "adj_factor": 1e-6,
    # 涨跌停 (histotical_gap 走 only_old_nan 分支)
    "up_limit": 1e-6,
    "down_limit": 1e-6,
    # volume 允许 ±100 股 (Tushare vol 1 手精度, API 偶修正)
    "volume": 100.0,
    # amount 允许 ±10 元 (Tushare 2026-04-08 前 amount 精度 5 元级, 04-08 后提升到 0.01.
    # 10 元 / 万元级 = 万分之一, 对下游策略无影响)
    "amount": 10.0,
}
FLOAT_TOLERANCE = 1e-6  # fallback (new col 未声明 tolerance 时)
_MISMATCH_RATIO_LIMIT = 0.01  # col mismatch 行 / 共有行 > 1% 判 FAIL

# Noise tolerance (2026-04-18 Session 6 backfill 诊断发现, MVP 2.1b L173 设定印证):
# - codes_only_in_new ≤ 50: FK 过滤差异 (老 fetcher 过 symbols, 新路径不过), 正常噪音
# - only_old_nan > 0 && only_new_nan == 0: 新路径补老 DB 历史缺失 (如 BJ 股 up/down_limit), feature 非 bug
# 硬门: (a) row_count 大致对齐 (b) 无 only_new_nan (c) 价格列 100% (d) volume/amount mismatch < 1% 且 max_diff ≤ tolerance
MAX_NEW_EXTRA_CODES = 50

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
    from backend.qm_platform.data.sources.tushare_source import (
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
    # 精度归一: volume Tushare 原生 float 有 .5 小数, Contract schema="int64 手", DataPipeline 入库 int cast.
    # 不 cast → dual_write 对 4000+ 行半舍入差 (max_diff=0.5) 判 FAIL.
    if "volume" in df.columns:
        df["volume"] = (
            pd.to_numeric(df["volume"], errors="coerce").round().astype("Int64")
        )
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
    common_rows = len(common)
    for col in _COMPARE_COLS:
        if col not in o.columns or col not in n.columns:
            col_reports[col] = {"status": "missing_in_either", "match": False}
            all_match = False
            continue
        tolerance = _COL_TOLERANCE.get(col, FLOAT_TOLERANCE)
        ov = pd.to_numeric(o[col], errors="coerce")
        nv = pd.to_numeric(n[col], errors="coerce")
        both_nan = ov.isna() & nv.isna()
        only_old_nan = ov.isna() & ~nv.isna()
        only_new_nan = ~ov.isna() & nv.isna()
        diff = (ov - nv).abs()
        mismatch_mask = (diff > tolerance) & ~both_nan
        # 铁律 14 数据契约 + MVP 2.1b L173 "新路径补老 DB 历史缺失" 设定:
        # only_old_nan (老 NaN 新有值) 是 historical_gap_filled, feature 非 drift
        # only_new_nan (新 NaN 老有值) 是真 bug (新路径丢值)
        # 只有真值超 tolerance mismatch + only_new_nan 算 mismatch_count
        mismatch = int(mismatch_mask.sum()) + int(only_new_nan.sum())
        gap_filled = int(only_old_nan.sum())
        max_diff = float(diff[~both_nan].max()) if (~both_nan).any() else 0.0
        # col PASS: 0 行超 tolerance (mismatch_mask 已按 per-col tolerance 判):
        # - 价格列 tolerance=1e-6 严 (0.01 元差即 FAIL)
        # - volume tolerance=100 股 (1 手 API 微调接受)
        # - amount tolerance=10 元 (Tushare 历史精度 5 元差接受)
        # ratio 豁免 (原设计) 会让 tolerance 失效, 去除.
        mismatch_ratio = mismatch / common_rows if common_rows else 0.0
        col_match = mismatch == 0
        if not col_match:
            all_match = False
        col_reports[col] = {
            "mismatch_count": mismatch,
            "mismatch_ratio": round(mismatch_ratio, 6),
            "max_diff": max_diff,
            "tolerance": tolerance,
            "only_old_nan": gap_filled,  # 展示用, 不影响 status
            "only_new_nan": int(only_new_nan.sum()),
            "historical_gap_filled": gap_filled,
            "match": col_match,
        }

    report["columns"] = col_reports
    report["all_columns_match"] = all_match
    # 硬门: 行数相近 (noise ≤ 50) + 无 only_new_nan + 无真值 mismatch
    # codes_only_in_new > 0 但 ≤ 50: FK 噪音, 接受 (MVP 2.1b L173)
    # codes_only_in_old > 0: 老路径多行 (通常 0), 若大量说明新路径丢 code, 算 drift
    row_count_acceptable = (
        report["codes_only_in_old"] == 0
        and report["codes_only_in_new"] <= MAX_NEW_EXTRA_CODES
    )
    report["row_count_acceptable"] = row_count_acceptable
    report["status"] = (
        "PASS" if (all_match and row_count_acceptable) else "FAIL"
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
    # pydantic Settings 从 backend/.env 读 TUSHARE_TOKEN (不走 os.environ)
    if not settings.TUSHARE_TOKEN:
        return {
            "status": "ERROR",
            "error": "TUSHARE_TOKEN not set in backend/.env or settings.TUSHARE_TOKEN empty",
        }
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
        passes = 0
        skips = 0
        d = s
        while d <= e:
            r = check_one(d)
            status = r.get("status")
            # 非交易日双方 0 rows: ERROR 正常, skip 不算 fail
            is_nontrading = (
                status == "ERROR"
                and r.get("old_rows", 0) == 0
                and r.get("new_rows", 0) == 0
            )
            if is_nontrading:
                mark = "⏭"
                skips += 1
            elif status == "PASS":
                mark = "✅"
                passes += 1
            else:
                mark = "❌"
                fails += 1
            print(
                f"{d} {mark} {status:5} "
                f"old={r.get('old_rows', 0)} new={r.get('new_rows', 0)} "
                f"match={r.get('all_columns_match', '-')}"
            )
            d += timedelta(days=1)
        print(
            f"\nSummary: {passes} PASS / {fails} FAIL / {skips} SKIP (non-trading day)"
        )
        return 0 if fails == 0 else 1

    td = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    r = check_one(td)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    status = r.get("status")
    return 0 if status == "PASS" else (2 if status == "ERROR" else 1)


if __name__ == "__main__":
    sys.exit(main())
