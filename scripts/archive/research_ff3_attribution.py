#!/usr/bin/env python3
"""G3 风格归因 — Fama-French三因子回归。

RM = CSI300月度收益
SMB = CSI500月度收益 - CSI300月度收益 (小盘减大盘)
HML = 高BP组月度收益 - 低BP组月度收益 (价值减成长)

R_strategy = alpha + beta1*RM + beta2*SMB + beta3*HML + epsilon
"""
import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))

import pandas as pd

from app.services.price_utils import _get_sync_conn


def main():
    conn = _get_sync_conn()
    print("=== G3 FAMA-FRENCH 3-FACTOR ATTRIBUTION ===\n")

    # 1. RM: CSI300 monthly returns
    bench = pd.read_sql(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code = '000300.SH' AND trade_date >= '2021-01-01' ORDER BY trade_date", conn)
    bench["trade_date"] = pd.to_datetime(bench["trade_date"])
    bench["ym"] = bench["trade_date"].dt.to_period("M")
    rm = bench.groupby("ym")["close"].last().pct_change().dropna()
    rm.name = "RM"

    # 2. SMB: CSI500 - CSI300
    csi500 = pd.read_sql(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code = '000905.SH' AND trade_date >= '2021-01-01' ORDER BY trade_date", conn)
    csi500["trade_date"] = pd.to_datetime(csi500["trade_date"])
    csi500["ym"] = csi500["trade_date"].dt.to_period("M")
    csi500_m = csi500.groupby("ym")["close"].last().pct_change().dropna()
    smb = (csi500_m - rm).dropna()
    smb.name = "SMB"

    # 3. HML: high-BP minus low-BP monthly returns
    print("Computing HML from PB quintiles...")
    month_ends_df = pd.read_sql(
        "SELECT DISTINCT trade_date FROM klines_daily "
        "WHERE trade_date >= '2021-01-01' AND trade_date <= '2026-03-31' ORDER BY trade_date", conn)
    month_ends_df["trade_date"] = pd.to_datetime(month_ends_df["trade_date"])
    month_ends_df["ym"] = month_ends_df["trade_date"].dt.to_period("M")
    month_ends = month_ends_df.groupby("ym")["trade_date"].max().to_dict()

    hml_list = []
    sorted_yms = sorted(month_ends.keys())
    for i, ym in enumerate(sorted_yms[:-1]):
        me = month_ends[ym]
        next_ym = sorted_yms[i + 1]
        next_me = month_ends[next_ym]
        me_s, next_s = me.strftime("%Y-%m-%d"), next_me.strftime("%Y-%m-%d")

        try:
            data = pd.read_sql(
                "SELECT k.code, db.pb, k2.close as nc, k.close as cc "
                "FROM klines_daily k "
                "JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
                "JOIN klines_daily k2 ON k.code = k2.code AND k2.trade_date = %s "
                "WHERE k.trade_date = %s AND k.volume > 0 AND k2.volume > 0 "
                "AND db.pb > 0 AND db.pb < 100",
                conn, params=(next_s, me_s))
            if len(data) < 100:
                continue
            data["bp"] = 1.0 / data["pb"]
            data["ret"] = data["nc"] / data["cc"] - 1
            hi = data[data["bp"] >= data["bp"].quantile(0.7)]["ret"].mean()
            lo = data[data["bp"] <= data["bp"].quantile(0.3)]["ret"].mean()
            hml_list.append({"ym": ym, "HML": hi - lo})
        except Exception:
            conn.rollback()
            continue

    hml = pd.DataFrame(hml_list).set_index("ym")["HML"]
    print(f"  HML computed: {len(hml)} months")

    # 4. Strategy monthly returns (run backtest)
    print("Running backtest for strategy returns...")
    from datetime import datetime

    from engines.backtest_engine import BacktestConfig, SimpleBacktester
    from engines.signal_engine import (
        PAPER_TRADING_CONFIG,
        PortfolioBuilder,
        SignalComposer,
        SignalConfig,
        get_rebalance_dates,
    )
    from engines.slippage_model import SlippageConfig

    start = datetime.strptime("2021-01-01", "%Y-%m-%d").date()
    end = datetime.strptime("2026-03-31", "%Y-%m-%d").date()
    sig_config = SignalConfig(factor_names=PAPER_TRADING_CONFIG.factor_names, top_n=15, rebalance_freq="monthly")
    bt_config = BacktestConfig(initial_capital=1_000_000, top_n=15, rebalance_freq="monthly",
                               slippage_mode="volume_impact", slippage_config=SlippageConfig())

    rebalance_dates = get_rebalance_dates(start, end, freq="monthly", conn=conn)
    industry = pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'", conn)
    industry = industry.set_index("code")["industry_sw1"].fillna("其他")

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)
    targets, prev = {}, {}
    for rd in rebalance_dates:
        fv = pd.read_sql("SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
                          conn, params=(rd,))
        if fv.empty:
            continue
        uni = pd.read_sql(
            "SELECT k.code FROM klines_daily k JOIN symbols s ON k.code = s.code "
            "LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
            "WHERE k.trade_date = %s AND k.volume > 0 AND s.list_status = 'L' "
            "AND s.name NOT LIKE '%%ST%%' "
            "AND (s.list_date IS NULL OR s.list_date <= %s::date - INTERVAL '60 days') "
            "AND COALESCE(db.total_mv, 0) > 100000", conn, params=(rd, rd))
        universe = set(uni["code"].tolist())
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        t = builder.build(scores, industry, prev)
        if t:
            targets[rd] = t
            prev = t

    price_data = pd.read_sql(
        "SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close, "
        "k.volume, k.amount, k.up_limit, k.down_limit, db.turnover_rate "
        "FROM klines_daily k LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
        "WHERE k.trade_date BETWEEN '2021-01-01' AND '2026-03-31' AND k.volume > 0 "
        "ORDER BY k.trade_date, k.code", conn)
    bench_data = pd.read_sql(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code = '000300.SH' AND trade_date BETWEEN '2021-01-01' AND '2026-03-31' "
        "ORDER BY trade_date", conn)

    bt = SimpleBacktester(bt_config)
    result = bt.run(targets, price_data, bench_data)

    nav = result.daily_nav
    nav.index = pd.to_datetime(nav.index)
    strat_m = nav.groupby(nav.index.to_period("M")).last().pct_change().dropna()
    strat_m.name = "Strategy"
    print(f"  Strategy returns: {len(strat_m)} months, mean={strat_m.mean()*100:.2f}%/mo")

    # 5. OLS regression
    from statsmodels.api import OLS, add_constant
    df = pd.DataFrame({"Strategy": strat_m, "RM": rm, "SMB": smb, "HML": hml}).dropna()
    print(f"\n  Regression sample: {len(df)} months ({df.index.min()} to {df.index.max()})")

    X = add_constant(df[["RM", "SMB", "HML"]])
    y = df["Strategy"]
    model = OLS(y, X).fit()

    print("\n" + "=" * 70)
    print("FF3 REGRESSION RESULTS")
    print("=" * 70)
    print(model.summary().tables[1].as_text())
    print(f"\nR-squared: {model.rsquared:.4f}")
    print(f"Adj R-sq:  {model.rsquared_adj:.4f}")
    alpha_m = model.params["const"]
    alpha_a = (1 + alpha_m) ** 12 - 1
    print(f"\nAlpha (monthly):    {alpha_m*100:+.3f}% (t={model.tvalues['const']:+.2f}, p={model.pvalues['const']:.3f})")
    print(f"Alpha (annualized): {alpha_a*100:+.2f}%")
    print(f"RM  beta: {model.params['RM']:+.3f} (t={model.tvalues['RM']:+.2f})")
    print(f"SMB beta: {model.params['SMB']:+.3f} (t={model.tvalues['SMB']:+.2f})")
    print(f"HML beta: {model.params['HML']:+.3f} (t={model.tvalues['HML']:+.2f})")

    # Decomposition
    avg = df[["RM", "SMB", "HML"]].mean()
    contrib = model.params[["RM", "SMB", "HML"]] * avg * 12
    total = strat_m.mean() * 12
    print(f"\n{'='*50}")
    print("RETURN DECOMPOSITION (annualized)")
    print(f"{'='*50}")
    print(f"Total strategy:  {total*100:+.1f}%")
    print(f"  Alpha:         {alpha_m*12*100:+.1f}%")
    print(f"  RM exposure:   {contrib['RM']*100:+.1f}%")
    print(f"  SMB exposure:  {contrib['SMB']*100:+.1f}%")
    print(f"  HML exposure:  {contrib['HML']*100:+.1f}%")
    print(f"  Residual:      {(total - alpha_m*12 - contrib.sum())*100:+.1f}%")

    # Interpretation
    print(f"\n{'='*50}")
    print("INTERPRETATION")
    print(f"{'='*50}")
    if model.params["SMB"] > 0.3 and model.tvalues["SMB"] > 2:
        print(f"  ⚠️  SMB beta={model.params['SMB']:.2f} (t={model.tvalues['SMB']:.1f}): 显著小盘暴露")
    if model.params["HML"] > 0.3 and model.tvalues["HML"] > 2:
        print(f"  ⚠️  HML beta={model.params['HML']:.2f} (t={model.tvalues['HML']:.1f}): 显著价值暴露")
    if abs(model.tvalues["const"]) > 2:
        print(f"  ✅ Alpha显著 (t={model.tvalues['const']:.2f}): 有真正的选股能力")
    else:
        print(f"  ❌ Alpha不显著 (t={model.tvalues['const']:.2f}): 收益主要来自风格暴露")

    conn.close()

if __name__ == "__main__":
    main()
