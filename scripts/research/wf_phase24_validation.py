"""Phase 2.4 WF验证: 3个候选配置的Walk-Forward 5-fold OOS验证。

候选配置（按优先级）:
  1. CORE3+dv_ttm + SN b=0.50 + Top-20 + 月度    → 全样本Sharpe=1.03
  2. CORE5+dv_ttm + SN b=0.50 + Top-20 + 月度    → 全样本Sharpe=0.87
  3. CORE3+dv_ttm + SN b=0.50 + Top-25 + 季度    → 预期最高(未测)

基线对比:
  - CORE5+SN b=0.50 WF OOS: Sharpe=0.6521, MDD=-30.23% (Step 6-H)
  - 验收标准: OOS Sharpe > 0.72 (基线×1.1) AND MDD < -40%

WF配置:
  - 5-fold, train=750天(~3年), gap=5天, test=250天(~1年)
  - 需要 750 + 5 + 5×250 = 2005天 (~8年), 我们有12年(2014-2026)

用法:
    python scripts/research/wf_phase24_validation.py              # 全部3个候选
    python scripts/research/wf_phase24_validation.py --config 1   # 仅候选1
    python scripts/research/wf_phase24_validation.py --config 1 2 # 候选1和2

输出: cache/phase24/wf_validation_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# 项目路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

from engines.backtest.config import BacktestConfig  # noqa: E402
from engines.metrics import calc_sharpe  # noqa: E402
from engines.size_neutral import load_ln_mcap_pivot  # noqa: E402
from engines.walk_forward import (  # noqa: E402
    WalkForwardEngine,
    WFConfig,
    make_equal_weight_signal_func,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── 候选配置定义 ─────────────────────────────────────────────

CONFIGS = {
    1: {
        "name": "CORE3+dv_ttm+SN050 Top20 Monthly",
        "directions": {
            "turnover_mean_20": -1,
            "volatility_20": -1,
            "bp_ratio": 1,
            "dv_ttm": 1,
        },
        "top_n": 20,
        "rebalance_freq": "monthly",
        "sn_beta": 0.50,
        "full_sample_sharpe": 1.0341,  # P0-3修正值
    },
    2: {
        "name": "CORE5+dv_ttm+SN050 Top20 Monthly",
        "directions": {
            "turnover_mean_20": -1,
            "volatility_20": -1,
            "reversal_20": 1,
            "amihud_20": 1,
            "bp_ratio": 1,
            "dv_ttm": 1,
        },
        "top_n": 20,
        "rebalance_freq": "monthly",
        "sn_beta": 0.50,
        "full_sample_sharpe": 0.87,
    },
    3: {
        "name": "CORE3+dv_ttm+SN050 Top25 Quarterly",
        "directions": {
            "turnover_mean_20": -1,
            "volatility_20": -1,
            "bp_ratio": 1,
            "dv_ttm": 1,
        },
        "top_n": 25,
        "rebalance_freq": "quarterly",
        "sn_beta": 0.50,
        "full_sample_sharpe": None,  # 未测，WF中计算
    },
}

# 基线 (Step 6-H CORE5+SN WF OOS)
BASELINE_WF_SHARPE = 0.6521
BASELINE_WF_MDD = -0.3023

# 验收标准
ACCEPTANCE_SHARPE = 0.72  # 基线×1.1
ACCEPTANCE_MDD = -0.40

CACHE_DIR = PROJECT_ROOT / "cache" / "phase24"
OUTPUT_FILE = CACHE_DIR / "wf_validation_results.json"


# ── 数据加载 ─────────────────────────────────────────────────

def load_parquet_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """从Parquet缓存加载12年price + benchmark数据。"""
    cache_root = PROJECT_ROOT / "cache" / "backtest"
    price_parts, bench_parts = [], []

    for year_dir in sorted(cache_root.iterdir()):
        if not year_dir.is_dir():
            continue
        pf = year_dir / "price_data.parquet"
        bf = year_dir / "benchmark.parquet"
        if pf.exists():
            price_parts.append(pd.read_parquet(pf))
        if bf.exists():
            bench_parts.append(pd.read_parquet(bf))

    price_df = pd.concat(price_parts, ignore_index=True).sort_values(
        ["code", "trade_date"]
    )
    bench_df = pd.concat(bench_parts, ignore_index=True).drop_duplicates("trade_date")

    # 确保 trade_date 是 date 类型
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"]).dt.date
    bench_df["trade_date"] = pd.to_datetime(bench_df["trade_date"]).dt.date

    logger.info(
        "Price: %d行 (%s~%s), Bench: %d行",
        len(price_df),
        price_df["trade_date"].min(),
        price_df["trade_date"].max(),
        len(bench_df),
    )
    return price_df, bench_df


def load_factor_data(factor_names: list[str], conn) -> pd.DataFrame:
    """从Parquet(CORE5) + DB(其他因子)混合加载因子数据。

    CORE5因子从Parquet加载(已中性化, 列名raw_value实际是neutral_value)。
    dv_ttm等非CORE5因子从DB加载(COALESCE(neutral_value, raw_value))。
    """
    cache_root = PROJECT_ROOT / "cache" / "backtest"
    core5 = {"turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"}

    parquet_factors = [f for f in factor_names if f in core5]
    db_factors = [f for f in factor_names if f not in core5]

    parts = []

    # Parquet部分 (CORE5)
    if parquet_factors:
        pq_parts = []
        for year_dir in sorted(cache_root.iterdir()):
            if not year_dir.is_dir():
                continue
            ff = year_dir / "factor_data.parquet"
            if ff.exists():
                df = pd.read_parquet(ff)
                df = df[df["factor_name"].isin(parquet_factors)]
                pq_parts.append(df)
        if pq_parts:
            pq_df = pd.concat(pq_parts, ignore_index=True)
            # raw_value列实际是COALESCE(neutral_value, raw_value), rename
            if "neutral_value" not in pq_df.columns and "raw_value" in pq_df.columns:
                pq_df = pq_df.rename(columns={"raw_value": "neutral_value"})
            pq_df["trade_date"] = pd.to_datetime(pq_df["trade_date"]).dt.date
            parts.append(pq_df)
            logger.info("Parquet因子: %d行 (%s)", len(pq_df), parquet_factors)

    # DB部分 (dv_ttm等)
    if db_factors:
        placeholders = ",".join(["%s"] * len(db_factors))
        query = f"""
            SELECT code, trade_date, factor_name,
                   COALESCE(neutral_value, raw_value) AS neutral_value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
              AND trade_date >= '2014-01-01' AND trade_date <= '2026-12-31'
              AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)
        """
        db_df = pd.read_sql(query, conn, params=db_factors)
        db_df["trade_date"] = pd.to_datetime(db_df["trade_date"]).dt.date
        db_df["neutral_value"] = db_df["neutral_value"].astype(float)
        # 过滤NaN (安全网)
        db_df = db_df[db_df["neutral_value"].notna() & np.isfinite(db_df["neutral_value"])]
        parts.append(db_df)
        logger.info("DB因子: %d行 (%s)", len(db_df), db_factors)

    factor_df = pd.concat(parts, ignore_index=True)
    logger.info("因子合计: %d行, %d个因子", len(factor_df), factor_df["factor_name"].nunique())
    return factor_df


# ── 季度调仓支持 ─────────────────────────────────────────────

def _patch_quarterly_rebalance():
    """为vectorized_signal.compute_rebalance_dates添加quarterly支持。

    原函数只支持 daily/weekly/biweekly/monthly。
    季度=每季最后一个交易日。
    """
    from engines import vectorized_signal

    _original = vectorized_signal.compute_rebalance_dates

    def _patched(trading_days, freq):
        if freq == "quarterly":
            if not trading_days:
                return []
            td_series = pd.Series(trading_days)
            return list(
                td_series.groupby(
                    td_series.apply(lambda d: (d.year, (d.month - 1) // 3))
                ).last()
            )
        return _original(trading_days, freq)

    vectorized_signal.compute_rebalance_dates = _patched
    logger.info("Patched compute_rebalance_dates for quarterly support")


# ── WF验证核心 ───────────────────────────────────────────────

def run_wf_for_config(
    config_id: int,
    config: dict,
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    ln_mcap_pivot: pd.DataFrame,
) -> dict:
    """对单个候选配置运行5-fold WF验证。"""
    name = config["name"]
    directions = config["directions"]
    top_n = config["top_n"]
    rebalance_freq = config["rebalance_freq"]
    sn_beta = config["sn_beta"]
    full_sample_sharpe = config["full_sample_sharpe"]

    logger.info("=" * 70)
    logger.info("Config %d: %s", config_id, name)
    logger.info("  Factors: %s", list(directions.keys()))
    logger.info("  Top-N=%d, Freq=%s, SN_beta=%.2f", top_n, rebalance_freq, sn_beta)
    logger.info("=" * 70)

    t0 = time.time()

    # 过滤因子数据到所需因子
    cfg_factors = list(directions.keys())
    cfg_factor_df = factor_df[factor_df["factor_name"].isin(cfg_factors)].copy()
    logger.info("  因子数据: %d行", len(cfg_factor_df))

    # WF配置
    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    bt_config = BacktestConfig(
        top_n=top_n,
        rebalance_freq=rebalance_freq,
        initial_capital=1_000_000,
    )

    # 构建signal function
    signal_func = make_equal_weight_signal_func(
        cfg_factor_df,
        directions,
        price_df,
        top_n=top_n,
        rebalance_freq=rebalance_freq,
        size_neutral_beta=sn_beta,
        ln_mcap_pivot=ln_mcap_pivot,
    )

    # 运行WF
    all_dates = sorted(price_df["trade_date"].unique())
    engine = WalkForwardEngine(wf_config, bt_config)
    result = engine.run(signal_func, price_df, bench_df, all_dates)

    elapsed = time.time() - t0

    # 提取fold结果
    fold_data = []
    for fr in result.fold_results:
        fold_data.append({
            "fold": fr.fold_idx,
            "train_period": [str(fr.train_period[0]), str(fr.train_period[1])],
            "test_period": [str(fr.test_period[0]), str(fr.test_period[1])],
            "oos_sharpe": round(fr.oos_sharpe, 4),
            "oos_mdd": round(fr.oos_mdd, 4),
            "oos_annual_return": round(fr.oos_annual_return, 4),
            "test_days": fr.test_days,
        })

    # 如果full_sample_sharpe未知,跑一次全样本回测
    if full_sample_sharpe is None:
        logger.info("  Running full-sample backtest for overfit ratio...")
        from engines.backtest.runner import run_hybrid_backtest
        from engines.signal_engine import SignalConfig

        sig_config = SignalConfig(
            factor_names=cfg_factors,
            top_n=top_n,
            weight_method="equal",
            rebalance_freq=rebalance_freq,
            size_neutral_beta=sn_beta,
        )
        # 使用2020-2026窗口(与Phase 2.4一致)
        p20 = price_df[price_df["trade_date"] >= date(2020, 1, 1)]
        b20 = bench_df[bench_df["trade_date"] >= date(2020, 1, 1)]
        f20 = cfg_factor_df[cfg_factor_df["trade_date"] >= date(2020, 1, 1)]

        full_result = run_hybrid_backtest(
            factor_df=f20,
            directions=directions,
            price_data=p20,
            config=bt_config,
            benchmark_data=b20,
            signal_config=sig_config,
            conn=None,
        )
        nav = full_result.daily_nav
        if isinstance(nav, pd.Series) and len(nav) > 0:
            full_sample_sharpe = round(calc_sharpe(nav), 4)
            logger.info("  Full-sample Sharpe (2020-2026): %.4f", full_sample_sharpe)

    # 过拟合比率
    overfit_ratio = None
    if full_sample_sharpe and full_sample_sharpe > 0:
        overfit_ratio = round(result.combined_oos_sharpe / full_sample_sharpe, 4)

    # 判定
    oos_sharpe = result.combined_oos_sharpe
    oos_mdd = result.combined_oos_mdd
    sharpe_pass = oos_sharpe >= ACCEPTANCE_SHARPE
    mdd_pass = oos_mdd >= ACCEPTANCE_MDD  # MDD是负数, 越大(越接近0)越好
    beats_baseline = oos_sharpe > BASELINE_WF_SHARPE

    if sharpe_pass and mdd_pass and beats_baseline:
        verdict = "PASS"
    elif beats_baseline:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    # 输出
    logger.info("")
    logger.info("  --- Results ---")
    for fd in fold_data:
        logger.info(
            "  Fold %d: Sharpe=%.4f  MDD=%.4f  AnnRet=%.4f  [%s ~ %s]",
            fd["fold"], fd["oos_sharpe"], fd["oos_mdd"], fd["oos_annual_return"],
            fd["test_period"][0], fd["test_period"][1],
        )

    logger.info("")
    logger.info("  Combined OOS Sharpe:  %.4f (baseline=%.4f, target=%.2f)", oos_sharpe, BASELINE_WF_SHARPE, ACCEPTANCE_SHARPE)
    logger.info("  Combined OOS MDD:     %.4f (target>%.2f)", oos_mdd, ACCEPTANCE_MDD)
    logger.info("  Overfit Ratio:        %s (full=%.4f, >0.50 needed)", overfit_ratio, full_sample_sharpe or 0)
    logger.info("  Verdict:              %s %s", verdict, "✅" if verdict == "PASS" else "⚠️" if verdict == "MARGINAL" else "❌")
    logger.info("  Elapsed:              %.1fs", elapsed)

    # Fold稳定性分析
    fold_sharpes = [fd["oos_sharpe"] for fd in fold_data]
    sharpe_std = float(np.std(fold_sharpes))
    n_negative = sum(1 for s in fold_sharpes if s < 0)
    stability = "STABLE" if sharpe_std < 1.0 and n_negative <= 1 else "UNSTABLE"
    logger.info("  Fold Stability:       %s (std=%.2f, %d negative folds)", stability, sharpe_std, n_negative)

    return {
        "config_id": config_id,
        "name": name,
        "factors": cfg_factors,
        "directions": directions,
        "top_n": top_n,
        "rebalance_freq": rebalance_freq,
        "sn_beta": sn_beta,
        "full_sample_sharpe": full_sample_sharpe,
        "folds": fold_data,
        "combined": {
            "oos_sharpe": round(oos_sharpe, 4),
            "oos_mdd": round(oos_mdd, 4),
            "oos_annual_return": round(result.combined_oos_annual_return, 4),
            "oos_total_return": round(result.combined_oos_total_return, 4),
            "total_oos_days": result.total_oos_days,
        },
        "analysis": {
            "overfit_ratio": overfit_ratio,
            "fold_sharpe_std": round(sharpe_std, 4),
            "n_negative_folds": n_negative,
            "stability": stability,
            "beats_baseline": beats_baseline,
            "sharpe_pass": sharpe_pass,
            "mdd_pass": mdd_pass,
            "verdict": verdict,
        },
        "elapsed_s": round(elapsed, 1),
    }


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 2.4 WF Validation")
    parser.add_argument(
        "--config", type=int, nargs="*", default=None,
        help="指定候选配置ID (1/2/3), 不指定=全部",
    )
    args = parser.parse_args()

    config_ids = args.config if args.config else [1, 2, 3]

    # 验证配置ID
    for cid in config_ids:
        if cid not in CONFIGS:
            print(f"无效配置ID: {cid}. 可选: 1, 2, 3")
            return 1

    # 收集所有需要的因子
    all_factors = set()
    for cid in config_ids:
        all_factors.update(CONFIGS[cid]["directions"].keys())
    all_factors = sorted(all_factors)
    logger.info("需要因子: %s", all_factors)

    # 季度调仓补丁
    if any(CONFIGS[cid]["rebalance_freq"] == "quarterly" for cid in config_ids):
        _patch_quarterly_rebalance()

    # 加载数据
    t_start = time.time()
    price_df, bench_df = load_parquet_data()

    import psycopg2
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )

    factor_df = load_factor_data(all_factors, conn)

    # ln_mcap for SN
    min_date = price_df["trade_date"].min()
    max_date = price_df["trade_date"].max()
    logger.info("Loading ln_mcap_pivot (%s ~ %s)...", min_date, max_date)
    ln_mcap_pivot = load_ln_mcap_pivot(min_date, max_date, conn)
    ln_mcap_pivot.index = pd.to_datetime(ln_mcap_pivot.index).date
    logger.info("ln_mcap_pivot: %d dates x %d stocks", *ln_mcap_pivot.shape)

    t_load = time.time() - t_start
    logger.info("数据加载完成 (%.1fs)", t_load)

    # 运行WF验证
    results = {}
    for cid in config_ids:
        result = run_wf_for_config(
            cid, CONFIGS[cid], factor_df, price_df, bench_df, ln_mcap_pivot,
        )
        results[str(cid)] = result

    conn.close()

    # 汇总比较
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY: Phase 2.4 WF Validation")
    logger.info("=" * 70)
    logger.info(
        "%-45s %8s %8s %8s %8s %8s",
        "Config", "OOS_Sh", "OOS_MDD", "Overfit", "Stable", "Verdict",
    )
    logger.info("-" * 90)

    # 基线行
    logger.info(
        "%-45s %8.4f %8.4f %8s %8s %8s",
        "[BASELINE] CORE5+SN050 WF OOS",
        BASELINE_WF_SHARPE, BASELINE_WF_MDD, "-", "-", "-",
    )

    for cid_str, r in results.items():
        a = r["analysis"]
        logger.info(
            "%-45s %8.4f %8.4f %8s %8s %8s",
            f"[{cid_str}] {r['name'][:38]}",
            r["combined"]["oos_sharpe"],
            r["combined"]["oos_mdd"],
            f"{a['overfit_ratio']:.2f}" if a["overfit_ratio"] else "N/A",
            a["stability"],
            f"{a['verdict']} {'✅' if a['verdict'] == 'PASS' else '⚠️' if a['verdict'] == 'MARGINAL' else '❌'}",
        )

    # 保存结果
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "baseline": {
                    "sharpe": BASELINE_WF_SHARPE,
                    "mdd": BASELINE_WF_MDD,
                },
                "acceptance": {
                    "sharpe": ACCEPTANCE_SHARPE,
                    "mdd": ACCEPTANCE_MDD,
                },
                "results": results,
            },
            f,
            indent=2,
            default=str,
        )
    logger.info("\n结果已保存: %s", OUTPUT_FILE)
    logger.info("总耗时: %.1f分钟", (time.time() - t_start) / 60)

    # 返回码: 任一PASS则0, 否则1
    any_pass = any(r["analysis"]["verdict"] == "PASS" for r in results.values())
    return 0 if any_pass else 1


if __name__ == "__main__":
    sys.exit(main())
