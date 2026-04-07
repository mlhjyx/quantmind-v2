#!/usr/bin/env python3
"""因子全量重算(优化版) — 4层优化 + 6段并行。

优化1: 同日X矩阵复用 (pd.get_dummies只调1次/天，不是5次)
优化2: 批量WLS (预计算(Xw'Xw)^-1 Xw'，每因子只做矩阵乘法)
优化3: 批量commit (每50天commit一次)
优化4: 6年段multiprocessing并行

用法:
    python scripts/recalc_factors_fast.py                    # 全量重算2021~2026
    python scripts/recalc_factors_fast.py --workers 4        # 指定并行数
    python scripts/recalc_factors_fast.py --segment 2021     # 只跑一段
"""

import argparse
import os
import sys
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd
import psycopg2
import structlog
from engines.factor_engine import (
    PHASE0_FULL_FACTORS,
    RESERVE_FACTORS,
    load_bulk_data,
    preprocess_fill,
    preprocess_mad,
    preprocess_zscore,
)
from psycopg2.extras import execute_values

logger = structlog.get_logger("recalc_fast")

SEGMENTS = [
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
    ("2026-01-01", "2026-03-31"),
]

COMMIT_INTERVAL = 50  # 每50天commit一次


def _get_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin",
        password="quantmind", host="localhost",
    )


def _build_wls_matrix(
    ln_mcap: pd.Series, industry: pd.Series, valid_mask: pd.Series,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """构建一次X矩阵和WLS权重，当天所有因子复用。

    Returns:
        (X, W_sqrt, Xw, projection_matrix) — projection = (Xw'Xw)^-1 Xw'
        用法: beta = projection @ (y * W_sqrt) → residual = y - X @ beta
    """
    mcap_vals = ln_mcap[valid_mask].values
    mcap_col = mcap_vals.reshape(-1, 1)
    ind_dummies = pd.get_dummies(industry[valid_mask], drop_first=True).values
    X = np.column_stack([np.ones(valid_mask.sum()), mcap_col, ind_dummies])

    # WLS权重
    weights = np.sqrt(np.exp(mcap_vals))
    W_sqrt = np.sqrt(weights)
    W_sqrt = W_sqrt / W_sqrt.mean()

    Xw = X * W_sqrt[:, np.newaxis]

    # 预计算 projection = (Xw'Xw)^-1 Xw'
    try:
        XwTXw = Xw.T @ Xw
        XwTXw_inv = np.linalg.inv(XwTXw)
        projection = XwTXw_inv @ Xw.T
    except np.linalg.LinAlgError:
        projection = None

    return X, W_sqrt, Xw, projection


def _fast_wls_residual(
    y: np.ndarray, X: np.ndarray, W_sqrt: np.ndarray,
    projection: np.ndarray | None,
) -> np.ndarray:
    """用预计算的projection矩阵快速WLS残差。"""
    if projection is None:
        # Fallback: 直接lstsq
        Xw = X * W_sqrt[:, np.newaxis]
        yw = y * W_sqrt
        try:
            beta = np.linalg.lstsq(Xw, yw, rcond=None)[0]
        except np.linalg.LinAlgError:
            return y
    else:
        yw = y * W_sqrt
        beta = projection @ yw

    return y - X @ beta


def process_segment(args: tuple) -> dict:
    """处理单个时间段（独立进程，独立DB连接）。"""
    start_str, end_str = args
    start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_str, "%Y-%m-%d").date()

    conn = _get_conn()
    t0 = time.time()

    # 加载因子定义
    factors = dict(PHASE0_FULL_FACTORS)
    factors.update(RESERVE_FACTORS)

    # 1. 加载全量数据
    print(f"[{start_str}~{end_str}] 加载数据...", flush=True)
    df = load_bulk_data(start_date, end_date, conn=conn)
    if df.empty:
        conn.close()
        return {"segment": start_str, "rows": 0, "elapsed": 0}

    t_load = time.time() - t0

    # 2. 计算滚动因子
    print(f"[{start_str}~{end_str}] 计算{len(factors)}个滚动因子...", flush=True)
    factor_raw = {}
    for fname, calc_fn in factors.items():
        try:
            factor_raw[fname] = calc_fn(df)
        except Exception as e:
            print(f"[{start_str}] 因子{fname}计算失败: {e}", flush=True)

    t_calc = time.time() - t0 - t_load

    # 3. 逐日预处理（优化版）
    all_dates = sorted(df.loc[
        (df["trade_date"] >= start_date) & (df["trade_date"] <= end_date),
        "trade_date"
    ].unique())

    print(f"[{start_str}~{end_str}] 逐日处理{len(all_dates)}天 (load={t_load:.0f}s, calc={t_calc:.0f}s)...", flush=True)

    total_rows = 0
    batch_rows = []  # 累积行，批量commit

    for i, td in enumerate(all_dates):
        td_date = td.date() if hasattr(td, "date") else td
        today_mask = df["trade_date"] == td
        if today_mask.sum() == 0:
            continue

        today_codes = df.loc[today_mask, "code"].values
        today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
        today_industry.index = today_codes
        today_ln_mcap = df.loc[today_mask, "total_mv"].apply(lambda x: np.log(x + 1e-12))
        today_ln_mcap.index = today_codes

        # 优化1+2: 一次性构建X矩阵 + projection
        base_valid = today_ln_mcap.notna() & today_industry.notna()
        if base_valid.sum() >= 30:
            X, W_sqrt, Xw, projection = _build_wls_matrix(
                today_ln_mcap, today_industry, base_valid
            )
            has_matrix = True
        else:
            has_matrix = False

        def _safe(v):
            if pd.isna(v):
                return None
            fv = float(v)
            return None if not np.isfinite(fv) else fv

        day_rows = []
        for fname in factor_raw:
            raw_today = factor_raw[fname][today_mask].copy()
            raw_today.index = today_codes

            # Step 1: MAD去极值
            step1 = preprocess_mad(raw_today)
            # Step 2: 缺失值填充
            step2 = preprocess_fill(step1, today_industry)

            # Step 3: 优化WLS中性化
            if has_matrix:
                valid_mask = step2.notna() & base_valid
                if valid_mask.sum() >= 30:
                    # 对齐valid_mask到base_valid（base_valid是X矩阵的mask）
                    # 如果step2有额外NaN，需要重新计算
                    extra_nan = base_valid & ~valid_mask
                    if extra_nan.sum() == 0:
                        # 完美匹配: 直接用预计算的projection
                        y = step2[base_valid].values
                        residual = _fast_wls_residual(y, X, W_sqrt, projection)
                        step3 = step2.copy()
                        step3[base_valid] = residual
                        step3[~base_valid] = np.nan
                    else:
                        # 少量额外NaN: fallback到重新构建（少数情况）
                        from engines.factor_engine import preprocess_neutralize
                        step3 = preprocess_neutralize(step2, today_ln_mcap, today_industry)
                else:
                    step3 = step2
            else:
                step3 = step2

            # Step 4: zscore
            step4 = preprocess_zscore(step3)
            # Step 5: clip ±3
            step5 = step4.clip(lower=-3.0, upper=3.0)

            for code in today_codes:
                rv = raw_today.get(code, np.nan)
                nv = step5.get(code, np.nan)
                day_rows.append((
                    code, td_date, fname,
                    _safe(rv), _safe(nv), _safe(nv),
                ))

        batch_rows.extend(day_rows)
        total_rows += len(day_rows)

        # 优化3: 每COMMIT_INTERVAL天批量commit
        if ((i + 1) % COMMIT_INTERVAL == 0 or i == len(all_dates) - 1) and batch_rows:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """INSERT INTO factor_values
                           (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                           VALUES %s
                           ON CONFLICT (code, trade_date, factor_name)
                           DO UPDATE SET raw_value = EXCLUDED.raw_value,
                                         neutral_value = EXCLUDED.neutral_value,
                                         zscore = EXCLUDED.zscore""",
                    batch_rows,
                    page_size=10000,
                )
            conn.commit()
            batch_rows = []

        if (i + 1) % 50 == 0 or i == 0 or i == len(all_dates) - 1:
            elapsed = time.time() - t0
            print(
                f"  [{start_str}] [{i+1}/{len(all_dates)}] {td_date} | "
                f"{len(day_rows)}行 | 累计{total_rows}行 | {elapsed:.0f}s",
                flush=True,
            )

    # Final commit
    if batch_rows:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO factor_values
                   (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                   VALUES %s
                   ON CONFLICT (code, trade_date, factor_name)
                   DO UPDATE SET raw_value = EXCLUDED.raw_value,
                                 neutral_value = EXCLUDED.neutral_value,
                                 zscore = EXCLUDED.zscore""",
                batch_rows,
                page_size=10000,
            )
        conn.commit()

    elapsed = time.time() - t0
    conn.close()

    result = {
        "segment": start_str,
        "rows": total_rows,
        "days": len(all_dates),
        "elapsed": round(elapsed, 1),
        "load_time": round(t_load, 1),
        "calc_time": round(t_calc, 1),
    }
    print(f"[{start_str}~{end_str}] 完成: {total_rows:,}行, {elapsed:.0f}s", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="因子全量重算(优化+并行)")
    parser.add_argument("--workers", type=int, default=6, help="并行进程数(默认6)")
    parser.add_argument("--segment", type=str, default=None, help="只跑指定年份(如2021)")
    args = parser.parse_args()

    if args.segment:
        segments = [(s, e) for s, e in SEGMENTS if s.startswith(args.segment)]
        if not segments:
            print(f"未找到匹配段: {args.segment}")
            sys.exit(1)
    else:
        segments = SEGMENTS

    print(f"=== 因子全量重算 ({len(segments)}段, {args.workers}并行) ===", flush=True)
    t0 = time.time()

    if len(segments) == 1 or args.workers == 1:
        results = [process_segment(seg) for seg in segments]
    else:
        with Pool(min(args.workers, len(segments))) as pool:
            results = pool.map(process_segment, segments)

    total_rows = sum(r["rows"] for r in results)
    total_time = time.time() - t0

    print(f"\n{'='*60}")
    print(f"全部完成: {total_rows:,}行, {total_time:.0f}s ({total_time/60:.1f}min)")
    for r in results:
        print(f"  {r['segment']}: {r['rows']:>12,}行 | {r['elapsed']:.0f}s")
    print(f"{'='*60}")

    # 验证
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT MAX(ABS(zscore)) FROM factor_values WHERE trade_date >= '2021-01-01'")
    max_z = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM factor_values WHERE trade_date >= '2021-01-01'")
    total = cur.fetchone()[0]
    conn.close()

    print(f"\n验证: MAX|zscore|={float(max_z):.4f} (应≤3.0), 总行数={total:,}")


if __name__ == "__main__":
    main()
