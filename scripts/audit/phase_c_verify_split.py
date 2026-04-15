#!/usr/bin/env python3
"""Phase C — verify factor_engine.py split against frozen baseline.

用法:
    python scripts/audit/phase_c_verify_split.py             # 全部 8 因子, 全部行对比
    python scripts/audit/phase_c_verify_split.py --sample 5  # 随机 5 个交易日子集 (快速 smoke)
    python scripts/audit/phase_c_verify_split.py --factor bp_ratio  # 单因子

验证逻辑:
    1. 读取 cache/phase_c_baseline/factor_values_{factor}_frozen.parquet (C0 冻结)
    2. 从 DB factor_values 表重新查询同一 (factor, date_range)
    3. 对齐 (code, trade_date, factor_name) 后对比:
       max_diff_raw     = max(abs(raw_value_db - raw_value_frozen))
       max_diff_neutral = max(abs(neutral_value_db - neutral_value_frozen))
       count_null_mismatch = SUM(raw_db.isna() ^ raw_frozen.isna())
    4. 三项必须全 0 才算 PASS

C1 的验证语义:
    C1 只搬家纯计算 + preprocess, 未触碰 DB 写入路径, 也未触碰 compute_daily_factors 的
    核心编排. 因此 DB 中 factor_values 表在 C1 前后**完全不变**, 从 DB 重新查询 vs
    C0 冻结的 parquet 必须 max_diff=0. 这是 C1 milestone 的金标验证.

C2/C3 的验证语义:
    C2 (load_* → factor_repository) 后, 理论上 DB 值仍然不变 (repository 仅搬家 SQL).
    C3 (compute_batch_factors → DataPipeline.ingest) 完成后, 小范围重跑 compute_batch
    并对比入库行数 + sample rows (本脚本可扩展为 --recompute 模式).

铁律 15: 回测结果必须可复现 — 本脚本是 factor_engine.py 拆分的 "可复现" 验证.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BASELINE_DIR = ROOT / "cache" / "phase_c_baseline"

FREEZE_FACTORS: list[str] = [
    "turnover_mean_20",
    "volatility_20",
    "bp_ratio",
    "dv_ttm",
    "amihud_20",
    "reversal_20",
    "maxret_20",
    "ln_market_cap",
]

DATE_START = date(2014, 1, 1)
DATE_END = date(2026, 4, 14)


def _load_frozen(factor_name: str) -> pd.DataFrame:
    """加载某因子的 C0 冻结 parquet."""
    path = BASELINE_DIR / f"factor_values_{factor_name}_frozen.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"冻结 baseline 不存在: {path}\n"
            f"请先运行 python scripts/audit/phase_c_freeze_baseline.py"
        )
    return pd.read_parquet(path)


def _load_db(conn, factor_name: str, sample_dates: list[date] | None = None) -> pd.DataFrame:
    """从 DB 重新查询某因子. sample_dates 非 None 时限制日期子集."""
    if sample_dates is None:
        sql = """
            SELECT code, trade_date, factor_name, raw_value, neutral_value, zscore
            FROM factor_values
            WHERE factor_name = %s
              AND trade_date BETWEEN %s AND %s
            ORDER BY code, trade_date
        """
        return pd.read_sql(sql, conn, params=(factor_name, DATE_START, DATE_END))
    else:
        dates_tuple = tuple(sample_dates)
        sql = """
            SELECT code, trade_date, factor_name, raw_value, neutral_value, zscore
            FROM factor_values
            WHERE factor_name = %s
              AND trade_date IN %s
            ORDER BY code, trade_date
        """
        return pd.read_sql(sql, conn, params=(factor_name, dates_tuple))


def _compare(db_df: pd.DataFrame, frozen_df: pd.DataFrame) -> dict:
    """对齐两份 DataFrame, 返回 diff 统计."""
    key_cols = ["code", "trade_date", "factor_name"]
    # frozen 可能是子集 (sample 模式), 以 frozen 为主键 join
    merged = frozen_df.merge(
        db_df,
        on=key_cols,
        how="inner",
        suffixes=("_frozen", "_db"),
        validate="one_to_one",
    )

    n = len(merged)
    if n == 0:
        return {
            "rows_compared": 0,
            "max_diff_raw": None,
            "max_diff_neutral": None,
            "null_mismatch_raw": None,
            "null_mismatch_neutral": None,
            "pass": False,
            "reason": "0 rows after merge (alignment failed)",
        }

    # null mask 对比 (NaN XOR)
    raw_null_db = merged["raw_value_db"].isna()
    raw_null_frozen = merged["raw_value_frozen"].isna()
    neu_null_db = merged["neutral_value_db"].isna()
    neu_null_frozen = merged["neutral_value_frozen"].isna()
    null_mismatch_raw = int((raw_null_db ^ raw_null_frozen).sum())
    null_mismatch_neutral = int((neu_null_db ^ neu_null_frozen).sum())

    # 非 NaN 部分的数值 diff
    both_raw = (~raw_null_db) & (~raw_null_frozen)
    both_neu = (~neu_null_db) & (~neu_null_frozen)

    max_diff_raw = (
        float(
            np.abs(
                merged.loc[both_raw, "raw_value_db"].astype(float)
                - merged.loc[both_raw, "raw_value_frozen"].astype(float)
            ).max()
        )
        if both_raw.any()
        else 0.0
    )
    max_diff_neutral = (
        float(
            np.abs(
                merged.loc[both_neu, "neutral_value_db"].astype(float)
                - merged.loc[both_neu, "neutral_value_frozen"].astype(float)
            ).max()
        )
        if both_neu.any()
        else 0.0
    )

    passed = (
        max_diff_raw == 0.0
        and max_diff_neutral == 0.0
        and null_mismatch_raw == 0
        and null_mismatch_neutral == 0
    )

    return {
        "rows_compared": n,
        "max_diff_raw": max_diff_raw,
        "max_diff_neutral": max_diff_neutral,
        "null_mismatch_raw": null_mismatch_raw,
        "null_mismatch_neutral": null_mismatch_neutral,
        "pass": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase C split verification")
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="仅对比 N 个随机 trade_date (0=全量)",
    )
    parser.add_argument(
        "--factor",
        type=str,
        default=None,
        help="仅验证单因子 (省略则全 8 个)",
    )
    args = parser.parse_args()

    factors = [args.factor] if args.factor else FREEZE_FACTORS
    for f in factors:
        if f not in FREEZE_FACTORS:
            print(f"❌ 未知因子: {f}. 可选: {FREEZE_FACTORS}", file=sys.stderr)
            return 2

    from app.services.db import get_sync_conn  # noqa: E402

    print(f"[Phase C Verify] 对比 {len(factors)} 因子 vs C0 冻结 baseline")
    print(f"  baseline: {BASELINE_DIR.relative_to(ROOT)}")
    print(f"  mode: {'sample=' + str(args.sample) if args.sample else 'full'}")
    print()

    conn = get_sync_conn()
    all_pass = True
    any_compared = False
    try:
        sample_dates: list[date] | None = None
        if args.sample > 0:
            # 随机采样 trade_date (需要先从 DB 拿全日期)
            first = factors[0]
            frozen = _load_frozen(first)
            unique_dates = sorted(frozen["trade_date"].unique())
            if len(unique_dates) > args.sample:
                rng = np.random.default_rng(42)  # 固定种子
                idx = rng.choice(len(unique_dates), args.sample, replace=False)
                sample_dates = sorted([unique_dates[i] for i in idx])
                print(f"  sampled dates: {[str(d) for d in sample_dates]}")
                print()

        for factor in factors:
            t0 = time.time()
            frozen_df = _load_frozen(factor)
            db_df = _load_db(conn, factor, sample_dates)

            # frozen 也限制到 sample_dates (如果 sample 模式)
            if sample_dates is not None:
                frozen_df = frozen_df[frozen_df["trade_date"].isin(sample_dates)].reset_index(
                    drop=True
                )

            result = _compare(db_df, frozen_df)
            dur = time.time() - t0
            any_compared = any_compared or result["rows_compared"] > 0

            mark = "✓" if result["pass"] else "✗"
            print(
                f"  {mark} {factor:<22} rows={result['rows_compared']:>10,}  "
                f"max_diff_raw={result['max_diff_raw']}  "
                f"max_diff_neutral={result['max_diff_neutral']}  "
                f"null_mismatch_raw={result['null_mismatch_raw']}  "
                f"null_mismatch_neutral={result['null_mismatch_neutral']}  "
                f"{dur:.1f}s"
            )
            if not result["pass"]:
                all_pass = False
    finally:
        conn.close()

    print()
    if not any_compared:
        print("⚠ 无对比结果, 可能 baseline 为空或 sample 区间无交集")
        return 1
    if all_pass:
        print("✅ Phase C split 验证通过: 全部因子 max_diff=0 (铁律 15)")
        return 0
    else:
        print("❌ Phase C split 验证失败: 至少一个因子 max_diff≠0 — 请回滚到上一 milestone")
        return 1


if __name__ == "__main__":
    sys.exit(main())
