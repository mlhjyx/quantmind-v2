#!/usr/bin/env python
"""Phase 2.2: Gate驱动的多方向验证。

Gate 0: LightGBM Exp-C(60月CORE5) OOS predictions → 实际回测Sharpe
Part 1: LambdaRank替代regression objective
Part 3 #1: IC加权SignalComposer
Part 3 #2/#3: MVO + IC+MVO
Part 2: PN v2 Gap诊断 + 修复

Usage:
    cd backend && python ../scripts/research/phase22_gate_verification.py --gate0
    cd backend && python ../scripts/research/phase22_gate_verification.py --lambdarank
    cd backend && python ../scripts/research/phase22_gate_verification.py --ic-weight
    cd backend && python ../scripts/research/phase22_gate_verification.py --mvo
    cd backend && python ../scripts/research/phase22_gate_verification.py --pn-diag
    cd backend && python ../scripts/research/phase22_gate_verification.py --all
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

CACHE_DIR = PROJECT_ROOT / "cache"
PHASE21_CACHE = BACKEND_DIR / "cache" / "phase21"
PHASE22_CACHE = CACHE_DIR / "phase22"

# CORE 5 因子 + 方向 (from signal_engine.py FACTOR_DIRECTION)
CORE5_FACTORS = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
CORE5_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "reversal_20": 1,
    "amihud_20": 1,
    "bp_ratio": 1,
}
SN_BETA = 0.50


# ─── 共享工具函数 ──────────────────────────────────────────


def get_db_conn():
    """获取psycopg2同步连接。"""
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
    return psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )


def load_price_data(start_year: int = 2020, end_year: int = 2026):
    """从Parquet缓存加载price_data + benchmark。"""
    price_parts, bench_parts = [], []
    for y in range(start_year, end_year + 1):
        pf = CACHE_DIR / "backtest" / str(y) / "price_data.parquet"
        bf = CACHE_DIR / "backtest" / str(y) / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    price = pd.concat(price_parts, ignore_index=True)
    bench = pd.concat(bench_parts, ignore_index=True)
    price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.date
    bench["trade_date"] = pd.to_datetime(bench["trade_date"]).dt.date
    bench = bench.sort_values("trade_date").drop_duplicates("trade_date")
    print(f"  Price: {len(price):,} rows, Benchmark: {len(bench):,} rows")
    return price, bench


def load_oos_predictions(exp_key: str = "c") -> pd.DataFrame:
    """加载Layer 1 OOS预测。"""
    path = PHASE21_CACHE / f"oos_predictions_exp_{exp_key}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"OOS predictions not found: {path}")
    df = pd.read_parquet(path)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    print(
        f"  OOS predictions: {len(df):,} rows, {df['trade_date'].min()} ~ {df['trade_date'].max()}"
    )
    return df


def get_monthly_rebal_dates(trade_dates) -> list:
    """月末最后交易日。"""
    df = pd.DataFrame({"td": sorted(set(trade_dates))})
    df["ym"] = df["td"].apply(lambda d: (d.year, d.month))
    return df.groupby("ym")["td"].max().sort_values().tolist()


def compute_metrics(nav: pd.Series) -> dict:
    """计算Sharpe/MDD/年化收益。"""
    from engines.metrics import TRADING_DAYS_PER_YEAR, calc_max_drawdown, calc_sharpe

    returns = nav.pct_change().dropna()
    n_days = len(nav)
    total_ret = nav.iloc[-1] / nav.iloc[0] - 1.0
    ann_ret = (1 + total_ret) ** (TRADING_DAYS_PER_YEAR / max(n_days, 1)) - 1.0
    return {
        "sharpe": round(float(calc_sharpe(returns)), 4),
        "mdd": round(float(calc_max_drawdown(nav)), 4),
        "annual_return": round(float(ann_ret), 4),
        "total_return": round(float(total_ret), 4),
        "n_days": n_days,
        "n_rebal": 0,  # caller fills
    }


def predictions_to_backtest(
    oos_df: pd.DataFrame,
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame | None,
    top_n: int = 20,
    ln_mcap_pivot: pd.DataFrame | None = None,
    sn_beta: float = 0.0,
    label: str = "",
) -> dict:
    """OOS预测 → target_portfolios → SimpleBacktester → metrics。

    Args:
        oos_df: (trade_date, code, predicted, ...)
        ln_mcap_pivot: (index=trade_date, columns=code, values=ln_mcap) for SN
        sn_beta: size-neutral beta (0=off)
    """
    from engines.backtest import BacktestConfig, SimpleBacktester
    from engines.size_neutral import apply_size_neutral

    all_oos_dates = sorted(oos_df["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_oos_dates)
    monthly_set = set(monthly_dates)

    target_portfolios = {}
    for td, group in oos_df.groupby("trade_date"):
        if td not in monthly_set:
            continue

        # 按predicted排序
        scores = group.set_index("code")["predicted"].sort_values(ascending=False)

        # 可选: Size-neutral adjustment
        if sn_beta > 0 and ln_mcap_pivot is not None and td in ln_mcap_pivot.index:
            scores = apply_size_neutral(scores, ln_mcap_pivot.loc[td], sn_beta)

        # Top-N 等权
        top = scores.nlargest(top_n)
        if len(top) == 0:
            continue
        w = 1.0 / len(top)
        target_portfolios[td] = {code: w for code in top.index}

    if not target_portfolios:
        return {"sharpe": 0.0, "mdd": 0.0, "annual_return": 0.0, "n_rebal": 0, "label": label}

    bt_config = BacktestConfig(top_n=top_n, rebalance_freq="monthly", initial_capital=1_000_000)
    tester = SimpleBacktester(bt_config)
    result = tester.run(target_portfolios, price_data, benchmark_data)

    metrics = compute_metrics(result.daily_nav)
    metrics["n_rebal"] = len(target_portfolios)
    metrics["label"] = label
    return metrics


def baseline_equal_weight(
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame | None,
    start_date: date,
    end_date: date,
    top_n: int = 20,
    sn_beta: float = 0.0,
    conn=None,
) -> dict:
    """等权CORE5基线回测(同期)。"""
    from engines.backtest.config import BacktestConfig
    from engines.backtest.runner import run_hybrid_backtest
    from engines.signal_engine import SignalConfig

    # 加载因子数据
    own_conn = conn is None
    if own_conn:
        conn = get_db_conn()

    try:
        placeholders = ",".join(["%s"] * len(CORE5_FACTORS))
        query = f"""
            SELECT code, trade_date, factor_name,
                   COALESCE(neutral_value, raw_value) AS raw_value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
              AND trade_date >= %s AND trade_date <= %s
              AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)
        """
        params = CORE5_FACTORS + [start_date, end_date]
        factor_df = pd.read_sql(query, conn, params=params)
        factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date
        print(f"  Baseline factors: {len(factor_df):,} rows")

        # 过滤price_data到同期
        price_period = price_data[
            (price_data["trade_date"] >= start_date) & (price_data["trade_date"] <= end_date)
        ].copy()
        bench_period = None
        if benchmark_data is not None:
            bench_period = benchmark_data[
                (benchmark_data["trade_date"] >= start_date)
                & (benchmark_data["trade_date"] <= end_date)
            ].copy()

        bt_config = BacktestConfig(
            top_n=top_n,
            rebalance_freq="monthly",
            initial_capital=1_000_000,
        )

        sig_config = SignalConfig(
            factor_names=CORE5_FACTORS,
            top_n=top_n,
            weight_method="equal",
            rebalance_freq="monthly",
            size_neutral_beta=sn_beta,
        )

        result = run_hybrid_backtest(
            factor_df=factor_df,
            directions=CORE5_DIRECTIONS,
            price_data=price_period,
            config=bt_config,
            benchmark_data=bench_period,
            signal_config=sig_config,
            conn=conn,
        )

        metrics = compute_metrics(result.daily_nav)
        metrics["n_rebal"] = len([d for d in result.daily_nav.index])
        metrics["label"] = f"等权CORE5{'+ SN' if sn_beta > 0 else ''}(同期)"
        return metrics

    finally:
        if own_conn:
            conn.close()


# ─── Gate 0: LightGBM Exp-C 实际回测 ────────────────────────


def gate0(args):
    """Gate 0: 60月Exp-C OOS predictions → 实际回测Sharpe。"""
    print("\n" + "=" * 70)
    print("Gate 0: LightGBM 60月 Exp-C (CORE5) — 实际回测")
    print("=" * 70)

    PHASE22_CACHE.mkdir(parents=True, exist_ok=True)

    # 1. Load data
    print("\n[1] Loading data...")
    oos_df = load_oos_predictions("c")
    price, bench = load_price_data(2020, 2026)

    oos_start = oos_df["trade_date"].min()
    oos_end = oos_df["trade_date"].max()
    print(f"  OOS period: {oos_start} ~ {oos_end}")

    # 2. Load ln_mcap for SN
    print("\n[2] Loading ln_market_cap for size-neutral...")
    conn = get_db_conn()
    from engines.size_neutral import load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(oos_start, oos_end, conn)
    print(f"  ln_mcap pivot: {ln_mcap_pivot.shape}")

    # 3. LightGBM回测: 无SN
    print("\n[3] LightGBM Top-20 回测 (无SN)...")
    t0 = time.time()
    lgbm_no_sn = predictions_to_backtest(
        oos_df,
        price,
        bench,
        top_n=20,
        ln_mcap_pivot=None,
        sn_beta=0.0,
        label="LightGBM Top-20(无SN)",
    )
    print(
        f"  Sharpe={lgbm_no_sn['sharpe']}, MDD={lgbm_no_sn['mdd']}, "
        f"AnnRet={lgbm_no_sn['annual_return']}, Rebals={lgbm_no_sn['n_rebal']} "
        f"({time.time() - t0:.1f}s)"
    )

    # 4. LightGBM回测: 有SN
    print("\n[4] LightGBM Top-20 + SN b=0.50 回测...")
    t0 = time.time()
    lgbm_sn = predictions_to_backtest(
        oos_df,
        price,
        bench,
        top_n=20,
        ln_mcap_pivot=ln_mcap_pivot,
        sn_beta=SN_BETA,
        label="LightGBM Top-20+SN",
    )
    print(
        f"  Sharpe={lgbm_sn['sharpe']}, MDD={lgbm_sn['mdd']}, "
        f"AnnRet={lgbm_sn['annual_return']}, Rebals={lgbm_sn['n_rebal']} "
        f"({time.time() - t0:.1f}s)"
    )

    # 5. 同期等权基线 (无SN)
    print("\n[5] 等权 CORE5 基线 (同期, 无SN)...")
    t0 = time.time()
    baseline_no_sn = baseline_equal_weight(
        price,
        bench,
        oos_start,
        oos_end,
        top_n=20,
        sn_beta=0.0,
        conn=conn,
    )
    print(
        f"  Sharpe={baseline_no_sn['sharpe']}, MDD={baseline_no_sn['mdd']}, "
        f"AnnRet={baseline_no_sn['annual_return']} ({time.time() - t0:.1f}s)"
    )

    # 6. 同期等权基线 (有SN)
    print("\n[6] 等权 CORE5 + SN b=0.50 基线 (同期)...")
    t0 = time.time()
    baseline_sn = baseline_equal_weight(
        price,
        bench,
        oos_start,
        oos_end,
        top_n=20,
        sn_beta=SN_BETA,
        conn=conn,
    )
    print(
        f"  Sharpe={baseline_sn['sharpe']}, MDD={baseline_sn['mdd']}, "
        f"AnnRet={baseline_sn['annual_return']} ({time.time() - t0:.1f}s)"
    )

    conn.close()

    # 7. 汇总
    print("\n" + "=" * 70)
    print("Gate 0 Results:")
    print("=" * 70)
    print(f"\n{'方法':<30} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10} {'Rebals':>8}")
    print("-" * 70)

    results = [baseline_no_sn, baseline_sn, lgbm_no_sn, lgbm_sn]
    for r in results:
        print(
            f"{r['label']:<30} {r['sharpe']:>8.4f} {r['mdd']:>10.4f} "
            f"{r['annual_return']:>10.4f} {r['n_rebal']:>8}"
        )

    # 8. Gate判断
    best_lgbm = max(lgbm_no_sn["sharpe"], lgbm_sn["sharpe"])
    best_baseline = max(baseline_no_sn["sharpe"], baseline_sn["sharpe"])
    improvement = best_lgbm - best_baseline

    print(f"\n{'Gate 判断':}")
    print(f"  Best LightGBM Sharpe: {best_lgbm:.4f}")
    print(f"  Best 等权基线 Sharpe: {best_baseline:.4f}")
    print(f"  Improvement: {improvement:+.4f}")

    if best_lgbm > best_baseline:
        print("  → Gate 0 PASS: LightGBM > 等权基线")
        gate_result = "PASS"
    else:
        print("  → Gate 0 CONDITIONAL: LightGBM ≤ 等权基线, IC→Sharpe断裂")
        gate_result = "CONDITIONAL"

    # 保存结果
    gate0_result = {
        "gate": "Gate 0",
        "result": gate_result,
        "baseline_no_sn": baseline_no_sn,
        "baseline_sn": baseline_sn,
        "lgbm_no_sn": lgbm_no_sn,
        "lgbm_sn": lgbm_sn,
        "improvement": improvement,
        "oos_period": f"{oos_start}~{oos_end}",
    }
    output_path = PHASE22_CACHE / "gate0_result.json"
    with open(output_path, "w") as f:
        json.dump(gate0_result, f, indent=2, default=str)
    print(f"\n  Saved: {output_path}")

    return gate0_result


# ─── Part 1: LambdaRank ─────────────────────────────────────


def part1_lambdarank(args):
    """Part 1: LambdaRank objective替代regression。"""
    from engines.ml_engine import MLConfig, WalkForwardTrainer

    print("\n" + "=" * 70)
    print("Part 1: LambdaRank LightGBM (CORE5, 60月)")
    print("=" * 70)

    PHASE22_CACHE.mkdir(parents=True, exist_ok=True)

    model_dir = str(PROJECT_ROOT / "models" / "lgbm_phase22" / "lambdarank")

    config = MLConfig(
        feature_names=CORE5_FACTORS,
        target="excess_return_20",
        mode="lambdarank",
        ndcg_at_k=20,
        train_months=60,
        valid_months=12,
        test_months=12,
        step_months=12,
        purge_days=21,
        expanding_folds=0,
        data_start=date(2014, 1, 1),
        data_end=date(2026, 4, 10),
        gpu=True,
        model_dir=model_dir,
        seed=42,
    )

    engine = WalkForwardTrainer(config)

    # 显示fold结构
    folds = engine.generate_folds()
    print(f"\n  Generated {len(folds)} folds:")
    for f in folds:
        print(
            f"    Fold {f.fold_id}: train [{f.train_start}..{f.train_end}] "
            f"valid [{f.valid_start}..{f.valid_end}] "
            f"test [{f.test_start}..{f.test_end}]"
        )

    # 运行WF
    print("\n  Training (lambdarank, GPU)...")
    t0 = time.time()
    result = engine.run_full_walkforward()
    elapsed = time.time() - t0

    print(f"\n  Training completed in {elapsed / 60:.1f} min")
    print(f"  Overall OOS IC: {result.overall_ic:.4f}")
    print(f"  Overall OOS RankIC: {result.overall_rank_ic:.4f}")
    print(f"  Overall ICIR: {result.overall_icir:.4f}")
    print(f"  Folds used: {result.num_folds_used}/{len(result.fold_results)}")

    # Fold-by-fold
    print(
        f"\n  {'Fold':<6} {'Train IC':>10} {'Valid IC':>10} {'OOS IC':>10} "
        f"{'OOS RankIC':>12} {'Overfit':>10} {'Flag':>6}"
    )
    print(f"  {'-' * 66}")
    for fr in result.fold_results:
        overfit_str = f"{fr.overfit_ratio:.2f}" if fr.overfit_ratio else "N/A"
        flag = "OVERFIT" if fr.is_overfit else "OK"
        print(
            f"  F{fr.fold_id:<5} {fr.train_ic:>10.4f} {fr.valid_ic:>10.4f} "
            f"{fr.oos_ic:>10.4f} {fr.oos_rank_ic:>12.4f} {overfit_str:>10} {flag:>6}"
        )

    # 保存OOS predictions
    if result.oos_predictions is not None and not result.oos_predictions.empty:
        oos_path = PHASE22_CACHE / "oos_predictions_lambdarank.parquet"
        result.oos_predictions.to_parquet(oos_path)
        print(f"\n  OOS predictions saved: {oos_path}")

        # 回测
        print("\n  Running backtest on OOS predictions...")
        price, bench = load_price_data(2020, 2026)

        conn = get_db_conn()
        from engines.size_neutral import load_ln_mcap_pivot

        oos_preds = result.oos_predictions.copy()
        oos_preds["trade_date"] = pd.to_datetime(oos_preds["trade_date"]).dt.date
        oos_start = oos_preds["trade_date"].min()
        oos_end = oos_preds["trade_date"].max()
        ln_mcap_pivot = load_ln_mcap_pivot(oos_start, oos_end, conn)
        conn.close()

        # 无SN
        lr_no_sn = predictions_to_backtest(
            oos_preds,
            price,
            bench,
            top_n=20,
            label="LambdaRank Top-20(无SN)",
        )
        # 有SN
        lr_sn = predictions_to_backtest(
            oos_preds,
            price,
            bench,
            top_n=20,
            ln_mcap_pivot=ln_mcap_pivot,
            sn_beta=SN_BETA,
            label="LambdaRank Top-20+SN",
        )

        print("\n  LambdaRank回测结果:")
        print(f"    无SN: Sharpe={lr_no_sn['sharpe']}, MDD={lr_no_sn['mdd']}")
        print(f"    +SN:  Sharpe={lr_sn['sharpe']}, MDD={lr_sn['mdd']}")
    else:
        print("\n  WARNING: No OOS predictions generated")
        lr_no_sn = {"sharpe": 0.0, "mdd": 0.0, "label": "LambdaRank(无OOS)"}
        lr_sn = lr_no_sn.copy()

    # 保存结果
    lr_result = {
        "part": "Part 1: LambdaRank",
        "overall_ic": result.overall_ic,
        "overall_rank_ic": result.overall_rank_ic,
        "overall_icir": result.overall_icir,
        "num_folds_used": result.num_folds_used,
        "elapsed_min": elapsed / 60,
        "backtest_no_sn": lr_no_sn,
        "backtest_sn": lr_sn,
        "folds": [
            {
                "fold_id": fr.fold_id,
                "train_ic": fr.train_ic,
                "valid_ic": fr.valid_ic,
                "oos_ic": fr.oos_ic,
                "oos_rank_ic": fr.oos_rank_ic,
                "overfit_ratio": fr.overfit_ratio,
                "is_overfit": fr.is_overfit,
            }
            for fr in result.fold_results
        ],
    }
    output_path = PHASE22_CACHE / "part1_lambdarank_result.json"
    with open(output_path, "w") as f:
        json.dump(lr_result, f, indent=2, default=str)
    print(f"\n  Saved: {output_path}")

    return lr_result


# ─── Part 3 #1: IC加权 ──────────────────────────────────────


def part3_ic_weighted(args):
    """Part 3 #1: IC_IR加权因子合成替代等权。"""
    print("\n" + "=" * 70)
    print("Part 3 #1: IC_IR 加权 SignalComposer (CORE5)")
    print("=" * 70)

    PHASE22_CACHE.mkdir(parents=True, exist_ok=True)

    conn = get_db_conn()

    # 1. 读 factor_ic_history: CORE5每因子日度IC (ic_20d = 20日horizon)
    print("\n[1] Loading factor IC history...")
    ic_query = """
        SELECT factor_name, trade_date, ic_20d
        FROM factor_ic_history
        WHERE factor_name IN %s
          AND ic_20d IS NOT NULL
        ORDER BY factor_name, trade_date
    """
    ic_df = pd.read_sql(ic_query, conn, params=(tuple(CORE5_FACTORS),))
    ic_df["trade_date"] = pd.to_datetime(ic_df["trade_date"]).dt.date
    print(f"  IC history: {len(ic_df)} rows, factors: {ic_df['factor_name'].unique().tolist()}")

    if ic_df.empty:
        print("  ERROR: No IC history found. Cannot compute IC weights.")
        conn.close()
        return {"error": "No IC history"}

    # 2. 日度IC → 月度聚合 → 滚动12月IC_IR
    print("\n[2] Computing rolling 12-month IC_IR weights...")
    # Pivot daily IC to wide format
    ic_pivot_daily = ic_df.pivot_table(
        index="trade_date", columns="factor_name", values="ic_20d"
    ).sort_index()

    # Aggregate to monthly: mean IC per month
    ic_pivot_daily.index = pd.to_datetime(ic_pivot_daily.index)
    ic_monthly = ic_pivot_daily.resample("ME").mean().dropna(how="all")
    ic_monthly.index = ic_monthly.index.date  # back to date

    print(f"  Monthly IC: {ic_monthly.shape[0]} months × {ic_monthly.shape[1]} factors")

    # Rolling 12-month IC_IR = rolling_mean / rolling_std
    rolling_mean = ic_monthly.rolling(12, min_periods=6).mean()
    rolling_std = ic_monthly.rolling(12, min_periods=6).std()
    rolling_icir = (rolling_mean / rolling_std.replace(0, np.nan)).dropna(how="all")

    print(f"  Rolling IC_IR: {rolling_icir.shape[0]} months × {rolling_icir.shape[1]} factors")
    print(f"  Latest IC_IR:\n{rolling_icir.iloc[-1].to_string()}")

    # 3. 加载因子数据 (同OOS期间)
    print("\n[3] Loading factor values...")
    oos_df = load_oos_predictions("c")
    oos_start = oos_df["trade_date"].min()
    oos_end = oos_df["trade_date"].max()
    del oos_df
    gc.collect()

    placeholders = ",".join(["%s"] * len(CORE5_FACTORS))
    fv_query = f"""
        SELECT code, trade_date, factor_name, neutral_value
        FROM factor_values
        WHERE factor_name IN ({placeholders})
          AND trade_date >= %s AND trade_date <= %s
          AND neutral_value IS NOT NULL
    """
    fv_params = CORE5_FACTORS + [oos_start, oos_end]
    factor_df = pd.read_sql(fv_query, conn, params=fv_params)
    factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date
    print(f"  Factor values: {len(factor_df):,} rows")

    # 4. 加载ln_mcap for SN
    from engines.size_neutral import apply_size_neutral, load_ln_mcap_pivot

    ln_mcap_pivot = load_ln_mcap_pivot(oos_start, oos_end, conn)
    conn.close()

    # 5. 加载price/bench
    price, bench = load_price_data(2020, 2026)
    all_trade_dates = sorted(factor_df["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_trade_dates)

    # 6. IC加权合成 → Top-20 + SN → target_portfolios
    print("\n[4] Building IC-weighted portfolios...")
    target_portfolios_no_sn = {}
    target_portfolios_sn = {}

    for rd in monthly_dates:
        # 当日因子截面
        day_factors = factor_df[factor_df["trade_date"] == rd]
        if day_factors.empty:
            continue

        # 找到最近的IC_IR (按月匹配)
        date(rd.year, rd.month, 1)
        available_months = [d for d in rolling_icir.index if d <= rd]
        if not available_months:
            continue
        latest_ic_month = available_months[-1]
        ic_weights = rolling_icir.loc[latest_ic_month].dropna()

        if len(ic_weights) < 3:
            continue

        # Pivot to wide
        wide = day_factors.pivot_table(index="code", columns="factor_name", values="neutral_value")

        # IC_IR加权合成 (方向统一: value × direction → 越大越好)
        composite = pd.Series(0.0, index=wide.index)
        total_weight = 0.0
        for factor in CORE5_FACTORS:
            if factor not in wide.columns or factor not in ic_weights.index:
                continue
            direction = CORE5_DIRECTIONS[factor]
            w = abs(ic_weights[factor])
            if np.isnan(w) or w == 0:
                continue
            composite += wide[factor].fillna(0) * direction * w
            total_weight += w

        if total_weight == 0:
            continue
        composite /= total_weight
        scores = composite.sort_values(ascending=False)

        # 无SN: Top-20
        top = scores.nlargest(20)
        if len(top) > 0:
            w_eq = 1.0 / len(top)
            target_portfolios_no_sn[rd] = {code: w_eq for code in top.index}

        # 有SN: apply_size_neutral then Top-20
        if ln_mcap_pivot is not None and rd in ln_mcap_pivot.index:
            adj_scores = apply_size_neutral(scores, ln_mcap_pivot.loc[rd], SN_BETA)
            top_sn = adj_scores.nlargest(20)
            if len(top_sn) > 0:
                w_eq = 1.0 / len(top_sn)
                target_portfolios_sn[rd] = {code: w_eq for code in top_sn.index}

    print(
        f"  Portfolios built: {len(target_portfolios_no_sn)} (无SN), {len(target_portfolios_sn)} (+SN)"
    )

    # 7. 回测
    from engines.backtest import BacktestConfig, SimpleBacktester

    bt_config = BacktestConfig(top_n=20, rebalance_freq="monthly", initial_capital=1_000_000)

    print("\n[5] Running backtests...")
    # 无SN
    if target_portfolios_no_sn:
        tester = SimpleBacktester(bt_config)
        result_no_sn = tester.run(target_portfolios_no_sn, price, bench)
        m_no_sn = compute_metrics(result_no_sn.daily_nav)
        m_no_sn["n_rebal"] = len(target_portfolios_no_sn)
        m_no_sn["label"] = "IC加权(无SN)"
    else:
        m_no_sn = {"sharpe": 0.0, "mdd": 0.0, "label": "IC加权(无SN)", "n_rebal": 0}

    # 有SN
    if target_portfolios_sn:
        tester = SimpleBacktester(bt_config)
        result_sn = tester.run(target_portfolios_sn, price, bench)
        m_sn = compute_metrics(result_sn.daily_nav)
        m_sn["n_rebal"] = len(target_portfolios_sn)
        m_sn["label"] = "IC加权+SN"
    else:
        m_sn = {"sharpe": 0.0, "mdd": 0.0, "label": "IC加权+SN", "n_rebal": 0}

    print("\n  IC加权回测结果:")
    print(f"    无SN: Sharpe={m_no_sn['sharpe']}, MDD={m_no_sn.get('mdd', 'N/A')}")
    print(f"    +SN:  Sharpe={m_sn['sharpe']}, MDD={m_sn.get('mdd', 'N/A')}")

    # 保存
    ic_result = {
        "part": "Part 3 #1: IC-weighted",
        "backtest_no_sn": m_no_sn,
        "backtest_sn": m_sn,
        "n_ic_months": len(rolling_icir),
        "latest_icir": rolling_icir.iloc[-1].to_dict() if len(rolling_icir) > 0 else {},
    }
    output_path = PHASE22_CACHE / "part3_ic_weighted_result.json"
    with open(output_path, "w") as f:
        json.dump(ic_result, f, indent=2, default=str)
    print(f"\n  Saved: {output_path}")

    return ic_result


# ─── Part 3 #2/#3: MVO + IC+MVO ─────────────────────────────


def part3_mvo(args):
    """Part 3 #2: MVO, #3: IC+MVO。"""
    import riskfolio as rp

    print("\n" + "=" * 70)
    print("Part 3 #2/#3: MVO + IC+MVO")
    print("=" * 70)

    PHASE22_CACHE.mkdir(parents=True, exist_ok=True)

    conn = get_db_conn()

    # 1. Load OOS期间因子数据 (for pre-selection)
    print("\n[1] Loading data...")
    oos_pred = load_oos_predictions("c")
    oos_start = oos_pred["trade_date"].min()
    oos_end = oos_pred["trade_date"].max()
    del oos_pred
    gc.collect()

    placeholders = ",".join(["%s"] * len(CORE5_FACTORS))
    fv_query = f"""
        SELECT code, trade_date, factor_name, neutral_value
        FROM factor_values
        WHERE factor_name IN ({placeholders})
          AND trade_date >= %s AND trade_date <= %s
          AND neutral_value IS NOT NULL
    """
    factor_df = pd.read_sql(fv_query, conn, params=CORE5_FACTORS + [oos_start, oos_end])
    factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date
    print(f"  Factors: {len(factor_df):,} rows")

    # 加载IC_IR (for #3) — 日度ic_20d → 月度聚合 → 滚动12月IC_IR
    ic_query = """
        SELECT factor_name, trade_date, ic_20d
        FROM factor_ic_history
        WHERE factor_name IN %s AND ic_20d IS NOT NULL
        ORDER BY factor_name, trade_date
    """
    ic_df = pd.read_sql(ic_query, conn, params=(tuple(CORE5_FACTORS),))
    ic_df["trade_date"] = pd.to_datetime(ic_df["trade_date"]).dt.date
    ic_pivot_daily = ic_df.pivot_table(
        index="trade_date", columns="factor_name", values="ic_20d"
    ).sort_index()
    ic_pivot_daily.index = pd.to_datetime(ic_pivot_daily.index)
    ic_monthly = ic_pivot_daily.resample("ME").mean().dropna(how="all")
    ic_monthly.index = ic_monthly.index.date
    rolling_icir = (
        ic_monthly.rolling(12, min_periods=6).mean()
        / ic_monthly.rolling(12, min_periods=6).std().replace(0, np.nan)
    ).dropna(how="all")

    conn.close()

    # 2. Load price data
    price, bench = load_price_data(2020, 2026)

    # 构建日收益率矩阵 (for MVO)
    close_wide = price.pivot_table(index="trade_date", columns="code", values="close").sort_index()
    daily_returns = close_wide.pct_change().dropna(how="all")

    all_trade_dates = sorted(factor_df["trade_date"].unique())
    monthly_dates = get_monthly_rebal_dates(all_trade_dates)

    # 3. 等权合成Top-40 → MVO
    print("\n[2] Building MVO portfolios...")
    target_mvo = {}  # #2: 等权选Top-40 → MVO
    target_ic_mvo = {}  # #3: IC加权选Top-40 → MVO
    mvo_failures = 0

    for rd in monthly_dates:
        day_factors = factor_df[factor_df["trade_date"] == rd]
        if day_factors.empty:
            continue

        wide = day_factors.pivot_table(index="code", columns="factor_name", values="neutral_value")

        # #2: 等权合成 → Top-40
        eq_composite = pd.Series(0.0, index=wide.index)
        for factor in CORE5_FACTORS:
            if factor not in wide.columns:
                continue
            eq_composite += wide[factor].fillna(0) * CORE5_DIRECTIONS[factor]
        eq_composite /= len(CORE5_FACTORS)
        top40_eq = eq_composite.nlargest(40).index.tolist()

        # #3: IC加权合成 → Top-40
        date(rd.year, rd.month, 1)
        avail = [d for d in rolling_icir.index if d <= rd]
        if avail:
            ic_w = rolling_icir.loc[avail[-1]].dropna()
            ic_composite = pd.Series(0.0, index=wide.index)
            tw = 0.0
            for factor in CORE5_FACTORS:
                if factor not in wide.columns or factor not in ic_w.index:
                    continue
                w = abs(ic_w[factor])
                ic_composite += wide[factor].fillna(0) * CORE5_DIRECTIONS[factor] * w
                tw += w
            if tw > 0:
                ic_composite /= tw
            top40_ic = ic_composite.nlargest(40).index.tolist()
        else:
            top40_ic = top40_eq

        # MVO优化 (共用逻辑)
        for label, top40_codes, target_dict in [
            ("#2 MVO", top40_eq, target_mvo),
            ("#3 IC+MVO", top40_ic, target_ic_mvo),
        ]:
            # 60日收益率
            lookback_dates = [d for d in daily_returns.index if d <= rd]
            if len(lookback_dates) < 60:
                continue
            recent_dates = lookback_dates[-60:]
            ret_sub = (
                daily_returns.loc[recent_dates, :]
                .reindex(columns=top40_codes)
                .dropna(axis=1, how="all")
            )
            ret_sub = ret_sub.dropna(how="any")

            if ret_sub.shape[1] < 10 or ret_sub.shape[0] < 30:
                # Fallback: 等权
                w_eq = 1.0 / len(top40_codes)
                target_dict[rd] = {c: w_eq for c in top40_codes[:20]}
                continue

            try:
                port = rp.Portfolio(returns=ret_sub)
                port.assets_stats(method_mu="hist", method_cov="ledoit_wolf")

                # 约束: long-only, max_weight=0.10
                port.upperlng = 0.10

                w = port.optimization(
                    model="Classic",
                    rm="MV",
                    obj="Sharpe",
                    rf=0.02 / 252,
                    l=0,
                    hist=True,
                )

                if w is not None and not w.empty:
                    weights = w.iloc[:, 0]
                    weights = weights[weights > 0.005]  # 过滤<0.5%的微小仓位
                    weights = weights / weights.sum()
                    target_dict[rd] = weights.to_dict()
                else:
                    # Fallback
                    w_eq = 1.0 / min(20, len(top40_codes))
                    target_dict[rd] = {c: w_eq for c in top40_codes[:20]}
                    mvo_failures += 1
            except Exception:
                # Fallback
                w_eq = 1.0 / min(20, len(top40_codes))
                target_dict[rd] = {c: w_eq for c in top40_codes[:20]}
                mvo_failures += 1

    print(f"  MVO portfolios: {len(target_mvo)} (#2), {len(target_ic_mvo)} (#3)")
    print(f"  MVO failures (fallback to equal): {mvo_failures}")

    # 4. 回测
    from engines.backtest import BacktestConfig, SimpleBacktester

    bt_config = BacktestConfig(top_n=40, rebalance_freq="monthly", initial_capital=1_000_000)

    print("\n[3] Running backtests...")
    results = {}
    for tag, tp in [("#2 MVO", target_mvo), ("#3 IC+MVO", target_ic_mvo)]:
        if not tp:
            results[tag] = {"sharpe": 0.0, "mdd": 0.0, "label": tag, "n_rebal": 0}
            continue
        tester = SimpleBacktester(bt_config)
        bt_result = tester.run(tp, price, bench)
        m = compute_metrics(bt_result.daily_nav)
        m["n_rebal"] = len(tp)
        m["label"] = tag
        results[tag] = m
        print(
            f"    {tag}: Sharpe={m['sharpe']}, MDD={m['mdd']}, AnnRet={m.get('annual_return', 'N/A')}"
        )

    # 保存
    mvo_result = {
        "part": "Part 3 #2/#3: MVO",
        "mvo": results.get("#2 MVO", {}),
        "ic_mvo": results.get("#3 IC+MVO", {}),
        "mvo_failures": mvo_failures,
    }
    output_path = PHASE22_CACHE / "part3_mvo_result.json"
    with open(output_path, "w") as f:
        json.dump(mvo_result, f, indent=2, default=str)
    print(f"\n  Saved: {output_path}")

    return mvo_result


# ─── Part 2: PN Gap诊断 ─────────────────────────────────────


def part2_pn_diag(args):
    """Part 2: PN v1 gap诊断 — 重跑Layer 2训练并分析权重分布。"""
    print("\n" + "=" * 70)
    print("Part 2: PortfolioNetwork Gap诊断")
    print("=" * 70)
    print("\n  Running phase21_portfolio_network.py --exp C ...")
    print("  (需要~15-20min, 含Layer 2训练)")
    print("  TODO: 实现gap诊断逻辑")
    # 将在Step 5实现
    return {"status": "not_implemented"}


# ─── Summary ─────────────────────────────────────────────────


def summary(args):
    """汇总所有结果到对比矩阵。"""
    print("\n" + "=" * 70)
    print("Phase 2.2 汇总对比矩阵")
    print("=" * 70)

    results = []

    # Load all cached results
    for fname, key in [
        ("gate0_result.json", "gate0"),
        ("part1_lambdarank_result.json", "lambdarank"),
        ("part3_ic_weighted_result.json", "ic_weighted"),
        ("part3_mvo_result.json", "mvo"),
    ]:
        path = PHASE22_CACHE / fname
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            results.append((key, data))

    if not results:
        print("  No results found. Run individual steps first.")
        return

    # 构建对比矩阵
    print(f"\n{'#':<4} {'方法':<30} {'Sharpe':>8} {'MDD':>10} {'AnnRet':>10}")
    print("-" * 66)

    rows = []
    for key, data in results:
        if key == "gate0":
            for sub in ["baseline_no_sn", "baseline_sn", "lgbm_no_sn", "lgbm_sn"]:
                if sub in data:
                    d = data[sub]
                    label = d.get("label", sub)
                    print(
                        f"{'0':<4} {label:<30} {d.get('sharpe', 0):>8.4f} "
                        f"{d.get('mdd', 0):>10.4f} {d.get('annual_return', 0):>10.4f}"
                    )
                    rows.append(d)
        elif key == "lambdarank":
            for sub in ["backtest_no_sn", "backtest_sn"]:
                if sub in data:
                    d = data[sub]
                    print(
                        f"{'1':<4} {d.get('label', 'LR'):<30} {d.get('sharpe', 0):>8.4f} "
                        f"{d.get('mdd', 0):>10.4f} {d.get('annual_return', 0):>10.4f}"
                    )
                    rows.append(d)
        elif key == "ic_weighted":
            for sub in ["backtest_no_sn", "backtest_sn"]:
                if sub in data:
                    d = data[sub]
                    print(
                        f"{'3a':<4} {d.get('label', 'IC'):<30} {d.get('sharpe', 0):>8.4f} "
                        f"{d.get('mdd', 0):>10.4f} {d.get('annual_return', 0):>10.4f}"
                    )
                    rows.append(d)
        elif key == "mvo":
            for sub in ["mvo", "ic_mvo"]:
                if sub in data:
                    d = data[sub]
                    print(
                        f"{'3b':<4} {d.get('label', 'MVO'):<30} {d.get('sharpe', 0):>8.4f} "
                        f"{d.get('mdd', 0):>10.4f} {d.get('annual_return', 0):>10.4f}"
                    )
                    rows.append(d)

    # Go条件检查
    go_threshold = 0.717
    best_sharpe = max((r.get("sharpe", 0) for r in rows), default=0)
    print(f"\n  Go条件: Sharpe > {go_threshold}")
    print(f"  Best Sharpe: {best_sharpe:.4f}")
    if best_sharpe > go_threshold:
        print("  → GO: 存在方法超过阈值")
    else:
        print("  → NO-GO: 所有方法未达阈值")


# ─── Main ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Phase 2.2: Gate驱动的多方向验证")
    parser.add_argument("--gate0", action="store_true", help="Gate 0: LightGBM Exp-C回测")
    parser.add_argument("--lambdarank", action="store_true", help="Part 1: LambdaRank")
    parser.add_argument("--ic-weight", action="store_true", help="Part 3 #1: IC加权")
    parser.add_argument("--mvo", action="store_true", help="Part 3 #2/#3: MVO + IC+MVO")
    parser.add_argument("--pn-diag", action="store_true", help="Part 2: PN Gap诊断")
    parser.add_argument("--summary", action="store_true", help="汇总对比矩阵")
    parser.add_argument("--all", action="store_true", help="运行全部")
    args = parser.parse_args()

    if not any(
        [
            args.gate0,
            args.lambdarank,
            args.ic_weight,
            args.mvo,
            args.pn_diag,
            args.summary,
            args.all,
        ]
    ):
        parser.print_help()
        return

    t_total = time.time()

    if args.gate0 or args.all:
        gate0(args)
        gc.collect()

    if args.lambdarank or args.all:
        part1_lambdarank(args)
        gc.collect()

    if args.ic_weight or args.all:
        part3_ic_weighted(args)
        gc.collect()

    if args.mvo or args.all:
        part3_mvo(args)
        gc.collect()

    if args.pn_diag or args.all:
        part2_pn_diag(args)
        gc.collect()

    if args.summary or args.all:
        summary(args)

    print(f"\n  Total elapsed: {(time.time() - t_total) / 60:.1f} min")


if __name__ == "__main__":
    main()
