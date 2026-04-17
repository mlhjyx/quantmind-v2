#!/usr/bin/env python
"""Phase 2.1: 7因子批量计算 + 入库 + 中性化 + IC验证。

NOTE (P2-1 DATA_SYSTEM_V1 2026-04-17): 新研究工作请优先使用 DataOrchestrator:
    orch = DataOrchestrator(start, end)
    orch.neutralize_factors(factor_list, incremental=True, validate=True)
本脚本保留为 Phase 2.1 历史重现 + 含计算入库 (不只中性化), 不强制迁移.


因子列表:
  1. high_vol_price_ratio_20 (HVP) — 高位放量因子, IC=-0.077, direction=-1
  2. IMAX_20 — 窗口内最大日收益率, direction=-1
  3. IMIN_20 — 窗口内最小日收益率, direction=+1
  4. QTLU_20 — 窗口内收益率75th分位, direction=-1
  5. CORD_20 — 收盘价与时间相关性, direction=-1
  6. RSQR_20 — 个股~市场 R², direction=-1
  7. RESI_20 — OLS alpha/截距, direction=+1

执行流程:
  1. 从Parquet缓存逐段加载price_data + benchmark
  2. 计算7因子(wide-format向量化)
  3. 通过DataPipeline写入factor_values(铁律17)
  4. fast_neutralize_batch SW1中性化
  5. ic_calculator计算IC + 写入factor_ic_history(铁律11)

内存策略: 3年一段(含1年lookback), 峰值<6GB(铁律9)

使用:
    cd backend && python ../scripts/compute_factor_phase21.py
    cd backend && python ../scripts/compute_factor_phase21.py --factors QTLU_20,RSQR_20
    cd backend && python ../scripts/compute_factor_phase21.py --skip-neutralize --skip-ic
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

# 确保backend在path中
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

ALL_FACTORS = [
    "high_vol_price_ratio_20",
    "IMAX_20", "IMIN_20", "QTLU_20", "CORD_20",
    "RSQR_20", "RESI_20",
]

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "backtest"
AVAILABLE_YEARS = list(range(2014, 2027))


def get_conn():
    """获取数据库连接。"""
    from dotenv import load_dotenv
    env_path = BACKEND_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    return psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )


def load_price_years(years: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """加载多年price_data + benchmark, 合并返回。"""
    price_parts = []
    bench_parts = []
    for y in years:
        pf = CACHE_DIR / str(y) / "price_data.parquet"
        bf = CACHE_DIR / str(y) / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    price = pd.concat(price_parts, ignore_index=True)
    bench = pd.concat(bench_parts, ignore_index=True)

    # 确保排序
    price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
    price = price.sort_values(["code", "trade_date"])
    bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date
    bench = bench.sort_values("trade_date")

    return price, bench


def compute_all_factors(
    price: pd.DataFrame,
    bench: pd.DataFrame,
    factor_names: list[str],
) -> dict[str, pd.DataFrame]:
    """计算所有指定因子, 返回 {factor_name: wide DataFrame}。"""
    from engines.factor_engine import (
        calc_alpha158_rsqr_resi,
        calc_alpha158_simple_four,
        calc_high_vol_price_ratio_wide,
    )

    results = {}
    t0 = time.time()

    # 构建wide表
    print("  Pivoting to wide format...")
    close_wide = price.pivot_table(index="trade_date", columns="code", values="close")
    close_wide = close_wide.sort_index()

    # HVP需要open/high/low
    if "high_vol_price_ratio_20" in factor_names:
        print("  Computing high_vol_price_ratio_20...")
        open_wide = price.pivot_table(index="trade_date", columns="code", values="open").sort_index()
        high_wide = price.pivot_table(index="trade_date", columns="code", values="high").sort_index()
        low_wide = price.pivot_table(index="trade_date", columns="code", values="low").sort_index()
        hvp = calc_high_vol_price_ratio_wide(close_wide, open_wide, high_wide, low_wide)
        results["high_vol_price_ratio_20"] = hvp
        n_valid = hvp.notna().sum().sum()
        print(f"    high_vol_price_ratio_20: {n_valid:,} valid ({time.time()-t0:.1f}s)")
        del open_wide, high_wide, low_wide
        gc.collect()

    # Alpha158简单四因子需要daily_ret
    simple_four = {"IMAX_20", "IMIN_20", "QTLU_20", "CORD_20"}
    need_simple = [f for f in factor_names if f in simple_four]
    if need_simple:
        print("  Computing Alpha158 simple four...")
        daily_ret = close_wide.pct_change(1)
        four = calc_alpha158_simple_four(daily_ret, close_wide, window=20)
        for fn in need_simple:
            results[fn] = four[fn]
            n_valid = four[fn].notna().sum().sum()
            print(f"    {fn}: {n_valid:,} valid ({time.time()-t0:.1f}s)")
        del daily_ret
        gc.collect()

    # RSQR/RESI需要market_ret
    rsqr_resi = {"RSQR_20", "RESI_20"}
    need_rsqr = [f for f in factor_names if f in rsqr_resi]
    if need_rsqr:
        print("  Computing RSQR/RESI (vectorized rolling OLS)...")
        daily_ret = close_wide.pct_change(1)
        # 市场收益率(CSI300)
        bench_s = bench.drop_duplicates("trade_date").set_index("trade_date")["close"].sort_index()
        market_ret = bench_s.pct_change(1)
        rr = calc_alpha158_rsqr_resi(daily_ret, market_ret, window=20)
        for fn in need_rsqr:
            results[fn] = rr[fn]
            n_valid = rr[fn].notna().sum().sum()
            print(f"    {fn}: {n_valid:,} valid ({time.time()-t0:.1f}s)")
        del daily_ret, market_ret
        gc.collect()

    print(f"  All factors computed in {time.time()-t0:.1f}s")
    return results


def wide_to_long(factor_name: str, wide_df: pd.DataFrame) -> pd.DataFrame:
    """Wide DataFrame → long format for DataPipeline ingest。"""
    long = wide_df.stack(dropna=True).reset_index()
    long.columns = ["trade_date", "code", "raw_value"]
    long["factor_name"] = factor_name
    long["trade_date"] = pd.to_datetime(long["trade_date"]).dt.date
    # 过滤inf
    long = long[np.isfinite(long["raw_value"])]
    return long[["code", "trade_date", "factor_name", "raw_value"]]


def ingest_to_db(factor_dfs: dict[str, pd.DataFrame], conn) -> dict[str, int]:
    """通过DataPipeline写入factor_values(铁律17)。"""
    from app.data_fetcher.contracts import FACTOR_VALUES
    from app.data_fetcher.pipeline import DataPipeline

    pipeline = DataPipeline(conn)
    counts = {}

    for fn, wide_df in factor_dfs.items():
        print(f"  Ingesting {fn}...")
        long = wide_to_long(fn, wide_df)
        print(f"    {len(long):,} rows to ingest")

        # 分批写入(每批50万行, 防止内存/事务过大)
        batch_size = 500_000
        total_upserted = 0
        for start in range(0, len(long), batch_size):
            batch = long.iloc[start:start + batch_size]
            result = pipeline.ingest(batch, FACTOR_VALUES)
            total_upserted += result.upserted_rows
            if start % (batch_size * 5) == 0 and start > 0:
                conn.commit()
                print(f"      Committed at {start:,}/{len(long):,}")

        conn.commit()
        counts[fn] = total_upserted
        print(f"    {fn}: {total_upserted:,} rows inserted/updated")
        gc.collect()

    return counts


def run_neutralize(factor_names: list[str]):
    """SW1中性化(复用fast_neutralize_batch)。"""
    from engines.fast_neutralize import fast_neutralize_batch

    print(f"\n{'='*60}")
    print(f"Neutralizing {len(factor_names)} factors...")
    n = fast_neutralize_batch(
        factor_names,
        start_date="2014-01-01",
        end_date="2026-04-11",
    )
    print(f"Neutralized {n:,} rows")
    return n


def run_ic_verification(factor_names: list[str], conn):
    """IC计算+写入factor_ic_history(铁律11)。

    策略: 调用已有的 backend/scripts/compute_factor_ic.py 做完整IC计算+入库,
    然后从 factor_ic_history 读取结果做方向一致性校验。
    """
    import subprocess

    from engines.factor_engine import PHASE21_FACTOR_DIRECTION

    print(f"\n{'='*60}")
    print("IC verification (via compute_factor_ic.py)...")

    ic_script = BACKEND_DIR / "scripts" / "compute_factor_ic.py"

    # Step 1: 调用compute_factor_ic.py计算并写入factor_ic_history
    for fn in factor_names:
        print(f"\n  Computing IC for {fn}...")
        cmd = [
            sys.executable, str(ic_script),
            "--factor", fn,
            "--start", "2014-01-01",
            "--end", "2026-04-11",
        ]
        result = subprocess.run(cmd, cwd=str(BACKEND_DIR), capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    ERROR: {result.stderr[-500:]}")
        else:
            # 打印最后几行输出
            lines = result.stdout.strip().split("\n")
            for line in lines[-5:]:
                print(f"    {line}")

    # Step 2: 从factor_ic_history读取结果, 做方向一致性校验
    print(f"\n{'='*60}")
    print("IC Direction Consistency Check:")
    cur = conn.cursor()
    results = {}

    for fn in factor_names:
        direction = PHASE21_FACTOR_DIRECTION.get(fn, 1)
        cur.execute("""
            SELECT trade_date, ic_20d FROM factor_ic_history
            WHERE factor_name = %s AND ic_20d IS NOT NULL
            ORDER BY trade_date
        """, (fn,))
        ic_rows = cur.fetchall()

        if not ic_rows:
            print(f"  {fn}: ❌ No IC data in factor_ic_history")
            results[fn] = {"ic": None, "t": None, "direction": direction}
            continue

        ic_values = [float(r[1]) for r in ic_rows]
        mean_ic = np.mean(ic_values)
        std_ic = np.std(ic_values, ddof=1)
        t_stat = mean_ic / (std_ic / np.sqrt(len(ic_values))) if len(ic_values) > 1 and std_ic > 0 else 0
        results[fn] = {"ic": mean_ic, "t": t_stat, "direction": direction, "n_days": len(ic_values)}

        # 方向一致性检查
        expected_sign = -1 if direction == -1 else 1
        actual_sign = 1 if mean_ic > 0 else -1
        consistent = "✅" if expected_sign == actual_sign else "⚠️ MISMATCH"
        print(f"  {fn}: IC={mean_ic:.4f}, t={t_stat:.2f}, dir={direction}, n={len(ic_values)} {consistent}")

        if expected_sign != actual_sign and abs(mean_ic) > 0.01:
            print(f"    ⚠️ WARNING: IC方向({actual_sign})与预期direction({direction})不一致! 需停下报告。")

    return results


def main():
    parser = argparse.ArgumentParser(description="Phase 2.1: 7因子批量计算+入库+中性化+IC")
    parser.add_argument("--factors", type=str, default=None,
                        help="逗号分隔因子名(默认全部7个)")
    parser.add_argument("--skip-neutralize", action="store_true",
                        help="跳过中性化步骤")
    parser.add_argument("--skip-ic", action="store_true",
                        help="跳过IC验证步骤")
    parser.add_argument("--skip-compute", action="store_true",
                        help="跳过计算+入库(仅中性化+IC)")
    parser.add_argument("--start-year", type=int, default=None,
                        help="从指定年份的segment开始(跳过已完成segments, 用于OOM恢复)")
    args = parser.parse_args()

    factor_names = args.factors.split(",") if args.factors else ALL_FACTORS
    print(f"Phase 2.1 Factor Computation: {factor_names}")
    print(f"{'='*60}")

    t_start = time.time()

    if not args.skip_compute:
        # 分段处理: 每段加载3年数据(含1年lookback)
        # 段划分: [2014-2016], [2016-2019], [2019-2022], [2022-2026]
        # lookback: 前一段末1年overlap确保rolling window连续
        segments = [
            (2014, 2016),  # 第一段无lookback
            (2016, 2019),  # lookback=2016
            (2019, 2022),
            (2022, 2026),
        ]

        conn = get_conn()
        all_counts = {}

        # OOM恢复: --start-year跳过已完成segments
        if args.start_year:
            segments = [(s, e) for s, e in segments if e > args.start_year or s >= args.start_year]
            print(f"  Resuming from year {args.start_year}, {len(segments)} segments remaining")

        for seg_start, seg_end in segments:
            # Lookback: 前1年(rolling 20d需要, 但多留些安全边际)
            load_start = max(seg_start - 1, 2014)
            load_years = list(range(load_start, seg_end + 1))
            keep_start = date(seg_start, 1, 1) if seg_start > 2014 else date(2014, 1, 1)
            keep_end = date(seg_end, 12, 31)

            print(f"\n{'='*60}")
            print(f"Segment {seg_start}-{seg_end} (loading {load_start}-{seg_end})...")

            price, bench = load_price_years(load_years)
            print(f"  Loaded {len(price):,} price rows, {len(bench):,} bench rows")

            # 计算因子
            factor_dfs = compute_all_factors(price, bench, factor_names)

            # 只保留当段日期(去除lookback部分)
            for fn in factor_dfs:
                df = factor_dfs[fn]
                mask = [(d >= keep_start and d <= keep_end) for d in df.index]
                factor_dfs[fn] = df.loc[mask]
                n = factor_dfs[fn].notna().sum().sum()
                print(f"  {fn} kept: {n:,} valid values for {keep_start}~{keep_end}")

            # 入库
            counts = ingest_to_db(factor_dfs, conn)
            for fn, c in counts.items():
                all_counts[fn] = all_counts.get(fn, 0) + c

            del price, bench, factor_dfs
            gc.collect()

        conn.close()
        print(f"\n{'='*60}")
        print("Ingest summary:")
        for fn, c in all_counts.items():
            print(f"  {fn}: {c:,} total rows")

    # 中性化
    if not args.skip_neutralize:
        run_neutralize(factor_names)

    # IC验证
    if not args.skip_ic:
        conn = get_conn()
        ic_results = run_ic_verification(factor_names, conn)
        conn.close()

        print(f"\n{'='*60}")
        print("IC Summary:")
        print(f"{'Factor':<30} {'IC':>8} {'t-stat':>8} {'Dir':>5}")
        print("-" * 55)
        for fn, r in ic_results.items():
            ic = f"{r['ic']:.4f}" if r.get('ic') is not None else "N/A"
            t = f"{r['t']:.2f}" if r.get('t') is not None else "N/A"
            print(f"{fn:<30} {ic:>8} {t:>8} {r['direction']:>5}")

    elapsed = time.time() - t_start
    print(f"\nTotal elapsed: {elapsed/60:.1f} min")


if __name__ == "__main__":
    main()
