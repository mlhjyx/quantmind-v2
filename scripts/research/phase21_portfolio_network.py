#!/usr/bin/env python
"""Phase 2.1 层2: PortfolioNetwork训练+评估。

训练模式(冻结层1):
  1. 加载Layer 1 LightGBM模型(per fold)
  2. 生成LightGBM OOS得分(不训练, 冻结)
  3. 训练PortfolioMLP(loss=-Sharpe)
  4. 生成OOS target_portfolios
  5. SimpleBacktester评估(铁律16)

前提: Part 2完成, cache/phase21/oos_predictions_exp_*.parquet + 模型已保存

Usage:
    cd backend && python ../scripts/research/phase21_portfolio_network.py --exp C
    cd backend && python ../scripts/research/phase21_portfolio_network.py --exp A
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"
MODEL_BASE = Path(__file__).resolve().parent.parent.parent / "models" / "lgbm_phase21"


def load_price_data():
    """加载12年price_data + benchmark。"""
    price_parts, bench_parts = [], []
    for y in range(2014, 2027):
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
    return price, bench


def load_oos_predictions(exp_key: str) -> pd.DataFrame:
    """加载Layer 1 OOS预测。"""
    # OOS predictions saved by Part 2 (CWD=backend/ → backend/cache/phase21/)
    path = BACKEND_DIR / "cache" / "phase21" / f"oos_predictions_exp_{exp_key.lower()}.parquet"
    if not path.exists():
        # Fallback: project root cache/
        path = CACHE_DIR / "phase21" / f"oos_predictions_exp_{exp_key.lower()}.parquet"
    if not path.exists():
        raise FileNotFoundError("OOS predictions not found.\nRun Part 2 first.")
    return pd.read_parquet(path)


def load_factor_features(feature_names: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """从DB加载因子neutral_value作为特征。"""
    import os

    import psycopg2
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
    conn = psycopg2.connect(
        dbname=os.getenv("PG_DB", "quantmind_v2"),
        user=os.getenv("PG_USER", "xin"),
        host=os.getenv("PG_HOST", "localhost"),
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )

    placeholders = ",".join(["%s"] * len(feature_names))
    query = f"""
        SELECT code, trade_date, factor_name, neutral_value
        FROM factor_values
        WHERE factor_name IN ({placeholders})
          AND trade_date BETWEEN %s AND %s
          AND neutral_value IS NOT NULL
    """
    params = list(feature_names) + [start_date, end_date]
    df = pd.read_sql(query, conn, params=params)
    conn.close()

    # Pivot to wide: (code, trade_date, feat1, feat2, ...)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    wide = df.pivot_table(
        index=["code", "trade_date"],
        columns="factor_name",
        values="neutral_value",
    ).reset_index()
    wide.columns.name = None

    return wide


def get_monthly_rebalance_dates(trade_dates: list) -> list:
    """月末最后交易日列表。"""
    df = pd.DataFrame({"td": trade_dates})
    df["ym"] = df["td"].apply(lambda d: (d.year, d.month))
    return df.groupby("ym")["td"].max().sort_values().tolist()


def compute_forward_returns(price: pd.DataFrame, bench: pd.DataFrame,
                            rebal_dates: list, horizon: int = 20) -> dict:
    """计算T+horizon前瞻收益。"""
    trade_dates = sorted(price["trade_date"].unique())
    td_idx = {d: i for i, d in enumerate(trade_dates)}

    close_wide = price.pivot_table(index="trade_date", columns="code", values="close").sort_index()
    bench_s = bench.set_index("trade_date")["close"].sort_index()

    results = {}
    for rd in rebal_dates:
        if rd not in td_idx:
            continue
        idx = td_idx[rd]
        if idx + horizon >= len(trade_dates):
            continue
        fwd_date = trade_dates[idx + horizon]
        if rd in close_wide.index and fwd_date in close_wide.index:
            stock_ret = close_wide.loc[fwd_date] / close_wide.loc[rd] - 1.0
            if rd in bench_s.index and fwd_date in bench_s.index:
                bench_ret = bench_s.loc[fwd_date] / bench_s.loc[rd] - 1.0
                excess = (stock_ret - bench_ret).dropna()
                results[rd] = excess

    return results


def run_portfolio_network(exp_key: str, feature_names: list[str]):
    """运行Layer 2训练+评估。"""
    from engines.backtest import BacktestConfig, SimpleBacktester
    from engines.metrics import TRADING_DAYS_PER_YEAR, calc_max_drawdown, calc_sharpe
    from engines.portfolio_network import PortfolioTrainer, TrainerConfig

    print(f"\n{'='*70}")
    print(f"Phase 2.1 Layer 2: PortfolioNetwork (Exp-{exp_key})")
    print(f"{'='*70}")

    # 1. Load OOS predictions from Layer 1
    print("\n[1] Loading Layer 1 OOS predictions...")
    oos_preds = load_oos_predictions(exp_key)
    print(f"    {len(oos_preds):,} OOS prediction rows")
    print(f"    Columns: {list(oos_preds.columns)}")

    # 2. Load price data
    print("\n[2] Loading price data...")
    price, bench = load_price_data()
    trade_dates = sorted(price["trade_date"].unique())
    rebal_dates = get_monthly_rebalance_dates(trade_dates)
    print(f"    {len(price):,} price rows, {len(rebal_dates)} rebal dates")

    # 3. Load factor features
    print("\n[3] Loading factor features...")
    features_df = load_factor_features(feature_names, "2014-01-01", "2026-04-10")
    print(f"    {len(features_df):,} feature rows, {len(feature_names)} features")

    # 4. Compute forward returns for training
    print("\n[4] Computing forward returns...")
    fwd_returns = compute_forward_returns(price, bench, rebal_dates, horizon=20)
    print(f"    {len(fwd_returns)} dates with forward returns")

    # 5. Determine fold structure from OOS predictions
    # Group by fold (if fold_id column exists) or by date ranges
    oos_preds["trade_date"] = pd.to_datetime(oos_preds["trade_date"]).dt.date

    # Split into train/valid/test periods for Layer 2
    # Use first 60% OOS dates as L2 train, next 20% as L2 valid, last 20% as L2 test
    oos_dates = sorted(oos_preds["trade_date"].unique())
    n_dates = len(oos_dates)
    train_end = oos_dates[int(n_dates * 0.6)]
    valid_end = oos_dates[int(n_dates * 0.8)]

    l2_train_dates = [d for d in oos_dates if d <= train_end]
    l2_valid_dates = [d for d in oos_dates if train_end < d <= valid_end]
    l2_test_dates = [d for d in oos_dates if d > valid_end]

    print("\n[5] Layer 2 splits:")
    print(f"    Train: {len(l2_train_dates)} dates [{l2_train_dates[0]}..{l2_train_dates[-1]}]")
    print(f"    Valid: {len(l2_valid_dates)} dates [{l2_valid_dates[0]}..{l2_valid_dates[-1]}]")
    print(f"    Test:  {len(l2_test_dates)} dates [{l2_test_dates[0]}..{l2_test_dates[-1]}]")

    # 6. Prepare data for trainer
    def prepare_fold_data(dates_list):
        """准备{date: arrays}格式数据。"""
        scores_dict = {}
        features_dict = {}
        returns_dict = {}
        rebal_list = []

        for rd in dates_list:
            # Get closest rebalance date
            closest_rebal = max([d for d in rebal_dates if d <= rd], default=None)
            if closest_rebal is None or closest_rebal not in fwd_returns:
                continue

            # OOS predictions for this date
            day_preds = oos_preds[oos_preds["trade_date"] == rd]
            if day_preds.empty:
                continue

            # Factor features for this date
            day_feats = features_df[features_df["trade_date"] == rd]
            if day_feats.empty:
                continue

            # Merge on code
            merged = day_preds.merge(day_feats, on=["code", "trade_date"], how="inner")
            if len(merged) < 20:
                continue

            # Forward returns
            fwd = fwd_returns.get(closest_rebal)
            if fwd is None:
                continue

            common_codes = merged["code"].values
            fwd_aligned = fwd.reindex(common_codes).fillna(0)

            # Extract arrays
            pred_col = [c for c in merged.columns if c.startswith("pred") or c == "lgbm_score"]
            if pred_col:
                lgbm_scores = merged[pred_col[0]].values.astype(np.float32)
            else:
                # Use target/prediction column
                num_cols = merged.select_dtypes(include=[np.number]).columns
                extra = [c for c in num_cols if c not in feature_names and c != "trade_date"]
                if extra:
                    lgbm_scores = merged[extra[0]].values.astype(np.float32)
                else:
                    continue

            feat_array = merged[feature_names].fillna(0).values.astype(np.float32)
            ret_array = fwd_aligned.values.astype(np.float32)

            rd_str = str(rd)
            scores_dict[rd_str] = lgbm_scores
            features_dict[rd_str] = feat_array
            returns_dict[rd_str] = ret_array
            rebal_list.append(rd_str)

        return scores_dict, features_dict, returns_dict, rebal_list

    print("\n[6] Preparing training data...")
    train_scores, train_feats, train_rets, train_rebals = prepare_fold_data(l2_train_dates)
    valid_scores, valid_feats, valid_rets, valid_rebals = prepare_fold_data(l2_valid_dates)
    test_scores, test_feats, test_rets, test_rebals = prepare_fold_data(l2_test_dates)

    print(f"    Train: {len(train_rebals)} rebal dates")
    print(f"    Valid: {len(valid_rebals)} rebal dates")
    print(f"    Test:  {len(test_rebals)} rebal dates")

    if len(train_rebals) < 10:
        print("  ❌ Insufficient training data! Need at least 10 rebalance dates.")
        return None

    # 7. Train PortfolioMLP
    print("\n[7] Training PortfolioMLP...")
    cfg = TrainerConfig(
        lr=1e-3,
        weight_decay=0.01,
        max_epochs=500,
        patience=20,
        max_grad_norm=1.0,
        lambda_turnover=0.1,
        max_weight=0.10,
        hidden=64,
        dropout=0.3,
        device="cuda" if __import__("torch").cuda.is_available() else "cpu",
        print_every=10,
    )

    trainer = PortfolioTrainer(cfg)
    model, train_result = trainer.train_fold(
        train_lgbm_scores=train_scores,
        train_features=train_feats,
        train_returns=train_rets,
        valid_lgbm_scores=valid_scores,
        valid_features=valid_feats,
        valid_returns=valid_rets,
        n_features=len(feature_names),
        rebal_dates_train=train_rebals,
        rebal_dates_valid=valid_rebals,
    )

    print(f"\n    Best epoch: {train_result.best_epoch}")
    print(f"    Best val Sharpe: {train_result.best_val_sharpe:.4f}")

    # 8. Generate OOS target_portfolios
    print("\n[8] Generating OOS target_portfolios...")
    target_portfolios = {}

    for rd_str in test_rebals:
        if rd_str not in test_scores:
            continue
        codes = oos_preds[oos_preds["trade_date"] == date.fromisoformat(rd_str)]["code"].values.tolist()
        if not codes:
            continue

        weights = trainer.predict(
            model, test_scores[rd_str], test_feats[rd_str], codes
        )

        if weights:
            rd_date = date.fromisoformat(rd_str)
            target_portfolios[rd_date] = weights

    print(f"    Generated {len(target_portfolios)} target portfolios")

    if not target_portfolios:
        print("  ❌ No target portfolios generated!")
        return None

    # 9. Backtest (SimpleBacktester, 铁律16)
    print("\n[9] Running SimpleBacktester...")
    bt_config = BacktestConfig(
        initial_capital=1_000_000.0,
        rebalance_freq="monthly",
        historical_stamp_tax=True,
        slippage_mode="volume_impact",
    )

    backtester = SimpleBacktester(bt_config)
    bt_result = backtester.run(
        target_portfolios=target_portfolios,
        price_data=price,
        benchmark_data=bench,
    )

    nav = bt_result.daily_nav
    returns = bt_result.daily_returns
    sharpe = calc_sharpe(returns) if len(returns) > 1 else 0
    mdd = calc_max_drawdown(nav)
    ann_ret = (nav.iloc[-1] / nav.iloc[0]) ** (TRADING_DAYS_PER_YEAR / len(nav)) - 1 if len(nav) > 1 else 0

    # 10. E2E简化回测Sharpe vs SimpleBacktester Sharpe diff检查
    # 简化Sharpe: 直接从test period返回序列算
    test_port_rets = []
    for rd_str in test_rebals:
        if rd_str in test_scores and rd_str in test_rets:
            import torch
            model.eval()
            with torch.no_grad():
                s = torch.tensor(test_scores[rd_str], dtype=torch.float32).to(trainer.device)
                f = torch.tensor(test_feats[rd_str], dtype=torch.float32).to(trainer.device)
                w = model(s, f).cpu().numpy()
            port_ret = (w * test_rets[rd_str]).sum()
            test_port_rets.append(port_ret)

    if test_port_rets:
        simple_sharpe = np.mean(test_port_rets) / (np.std(test_port_rets) + 1e-8)
    else:
        simple_sharpe = 0

    diff_pct = abs(sharpe - simple_sharpe) / (abs(sharpe) + 1e-8) * 100

    print(f"\n{'='*60}")
    print(f"Layer 2 Results (Exp-{exp_key}):")
    print(f"{'='*60}")
    print(f"  SimpleBacktester Sharpe: {sharpe:.4f}")
    print(f"  SimpleBacktester MDD:    {mdd:.2%}")
    print(f"  SimpleBacktester Ann Ret:{ann_ret:.2%}")
    print(f"  E2E tensor Sharpe:       {simple_sharpe:.4f}")
    print(f"  Diff:                    {diff_pct:.1f}%")

    if diff_pct > 5:
        print("  ⚠️ WARNING: Diff > 5%! 停下报告。")
    else:
        print("  ✅ Diff < 5%, backtests aligned.")

    print("\n  Baseline: SN b=0.50 WF OOS Sharpe=0.6521")
    improvement = (sharpe - 0.6521) / 0.6521 * 100
    print(f"  vs Baseline: {improvement:+.1f}%")

    # Save results
    result_dict = {
        "experiment": exp_key,
        "sharpe": sharpe,
        "mdd": mdd,
        "ann_ret": ann_ret,
        "simple_sharpe": simple_sharpe,
        "diff_pct": diff_pct,
        "best_epoch": train_result.best_epoch,
        "best_val_sharpe": train_result.best_val_sharpe,
        "n_portfolios": len(target_portfolios),
        "test_period": f"{l2_test_dates[0]}~{l2_test_dates[-1]}",
    }

    out_json = BACKEND_DIR / "cache" / "phase21" / f"l2_result_exp_{exp_key.lower()}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(result_dict, f, indent=2, default=str)
    print(f"\n  Results saved: {out_json}")

    return result_dict


def main():

    parser = argparse.ArgumentParser(description="Phase 2.1 Layer 2 PortfolioNetwork")
    parser.add_argument("--exp", type=str, required=True, help="Experiment key: C, A, or B")
    args = parser.parse_args()

    # Feature sets (must match Part 2)
    FEATURES_C = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    FEATURES_A = FEATURES_C + ["RSQR_20", "QTLU_20", "ind_mom_60", "high_vol_price_ratio_20",
                                "nb_change_rate_20d", "nb_trend_20d", "nb_ratio_change_5d", "nb_net_buy_5d_ratio"]
    FEATURES_B = FEATURES_A + ["IMAX_20", "IMIN_20", "RESI_20", "CORD_20", "ind_mom_20"]

    feature_map = {"C": FEATURES_C, "A": FEATURES_A, "B": FEATURES_B}

    exp_key = args.exp.upper()
    if exp_key not in feature_map:
        print(f"Unknown experiment: {exp_key}")
        return

    run_portfolio_network(exp_key, feature_map[exp_key])


if __name__ == "__main__":
    main()
