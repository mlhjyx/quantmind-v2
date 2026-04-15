#!/usr/bin/env python3
"""Phase C C0 — 冻结 factor_values 金标快照 (F31 split 前基线).

铁律 15 要求: 任何回测结果必须可复现. Phase C 拆分 factor_engine.py (2049 行) 时,
每个 milestone (C1/C2/C3) 完成后必须通过 `phase_c_verify_split.py` 对比 8 因子 ×
12 年的 raw_value / neutral_value 与本脚本冻结的 parquet, 断言 max_diff = 0.

冻结范围 (prep 文档 §金标快照策略):
    CORE 4 (当前 PT WF OOS Sharpe=0.8659): turnover_mean_20, volatility_20, bp_ratio, dv_ttm
    PASS 4 (广覆盖, 方向不同): amihud_20, reversal_20, maxret_20, ln_market_cap
    日期区间: 2014-01-01 → 2026-04-14

注意: DB 中对数市值的 factor_name 是 "ln_market_cap" (见 PHASE0_CORE_FACTORS lambda key),
prep 文档简写 "ln_mcap" 只是助记符.

输出:
    cache/phase_c_baseline/factor_values_{factor_name}_frozen.parquet  (每因子一份)
    cache/phase_c_baseline/freeze_manifest.json                       (元数据 + 行数 + sha256)

用法:
    python scripts/audit/phase_c_freeze_baseline.py            # 正常冻结 (一次性)
    python scripts/audit/phase_c_freeze_baseline.py --dry-run  # 仅打印计划不写盘

依赖: backend/app/services/db.get_sync_conn
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

# Path setup
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402

BASELINE_DIR = ROOT / "cache" / "phase_c_baseline"

FREEZE_FACTORS: list[str] = [
    # CORE 4 (当前 PT 活跃, pt_live.yaml, WF OOS Sharpe=0.8659)
    "turnover_mean_20",
    "volatility_20",
    "bp_ratio",
    "dv_ttm",
    # PASS 4 (广覆盖, 方向分布均衡, 覆盖动量/流动性/规模)
    "amihud_20",
    "reversal_20",
    "maxret_20",
    "ln_market_cap",
]

DATE_START = date(2014, 1, 1)
DATE_END = date(2026, 4, 14)


def _file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _freeze_factor(conn, factor_name: str, out_path: Path, dry_run: bool) -> dict:
    """拉取单个因子 [DATE_START, DATE_END] 的全部行, 写 parquet."""
    sql = """
        SELECT code, trade_date, factor_name, raw_value, neutral_value, zscore
        FROM factor_values
        WHERE factor_name = %s
          AND trade_date BETWEEN %s AND %s
        ORDER BY code, trade_date
    """
    t0 = time.time()
    df = pd.read_sql(sql, conn, params=(factor_name, DATE_START, DATE_END))
    load_sec = time.time() - t0

    info = {
        "factor_name": factor_name,
        "rows": int(len(df)),
        "codes": int(df["code"].nunique()) if not df.empty else 0,
        "dates": int(df["trade_date"].nunique()) if not df.empty else 0,
        "date_min": str(df["trade_date"].min()) if not df.empty else None,
        "date_max": str(df["trade_date"].max()) if not df.empty else None,
        "raw_null_pct": float(df["raw_value"].isna().mean()) if not df.empty else 0.0,
        "neutral_null_pct": float(df["neutral_value"].isna().mean()) if not df.empty else 0.0,
        "load_sec": round(load_sec, 2),
        "parquet_path": str(out_path.relative_to(ROOT)),
    }

    if df.empty:
        print(f"  ⚠ {factor_name}: 0 行 (DB 中无此因子, 跳过 parquet)")
        info["status"] = "empty"
        return info

    if dry_run:
        print(
            f"  [dry-run] {factor_name}: {info['rows']:>10,} rows  "
            f"{info['codes']:>5} stocks  {info['dates']:>5} dates  "
            f"raw_null={info['raw_null_pct']:.2%}  load={info['load_sec']}s"
        )
        info["status"] = "dry_run"
        return info

    t1 = time.time()
    df.to_parquet(out_path, compression="snappy", index=False)
    write_sec = time.time() - t1

    size_mb = out_path.stat().st_size / (1024 * 1024)
    info["parquet_mb"] = round(size_mb, 2)
    info["write_sec"] = round(write_sec, 2)
    info["sha256"] = _file_sha256(out_path)
    info["status"] = "frozen"

    print(
        f"  ✓ {factor_name}: {info['rows']:>10,} rows  "
        f"{info['codes']:>5} stocks  {info['dates']:>5} dates  "
        f"{size_mb:>6.1f} MB  "
        f"raw_null={info['raw_null_pct']:.2%}  "
        f"load={info['load_sec']}s write={info['write_sec']}s"
    )
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase C C0 — freeze factor_values baseline")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划不写 parquet")
    args = parser.parse_args()

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    print("[Phase C C0] 冻结 factor_values 金标快照")
    print(f"  范围: {len(FREEZE_FACTORS)} 因子 × [{DATE_START} .. {DATE_END}]")
    print(f"  输出: {BASELINE_DIR.relative_to(ROOT)}")
    print(f"  模式: {'dry-run (不写盘)' if args.dry_run else '正常冻结'}")
    print()

    from app.services.db import get_sync_conn  # noqa: E402

    conn = get_sync_conn()
    results: list[dict] = []
    try:
        t_all = time.time()
        for factor in FREEZE_FACTORS:
            out_path = BASELINE_DIR / f"factor_values_{factor}_frozen.parquet"
            info = _freeze_factor(conn, factor, out_path, args.dry_run)
            results.append(info)
        total_sec = time.time() - t_all
    finally:
        conn.close()

    total_rows = sum(r["rows"] for r in results)
    total_mb = sum(r.get("parquet_mb", 0.0) for r in results)

    print()
    print(
        f"[Phase C C0] 完成: {len(results)} 因子, {total_rows:,} 行, "
        f"{total_mb:.1f} MB, 总耗时 {total_sec:.1f}s"
    )

    # 写 manifest (不在 dry-run 模式)
    if not args.dry_run:
        manifest = {
            "version": 1,
            "phase": "C0",
            "purpose": "factor_engine.py F31 split baseline (prep: docs/audit/PHASE_C_F31_PREP.md)",
            "frozen_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "git_head": _git_head(),
            "date_range": [str(DATE_START), str(DATE_END)],
            "factors": FREEZE_FACTORS,
            "total_rows": total_rows,
            "total_mb": round(total_mb, 2),
            "entries": results,
        }
        manifest_path = BASELINE_DIR / "freeze_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[Manifest] {manifest_path.relative_to(ROOT)}")

    return 0


def _git_head() -> str:
    """Best-effort git HEAD capture (non-fatal if git missing)."""
    try:
        import subprocess

        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
