"""PMS v2.0 组合级回撤保护回测 — 6组实验"""
import importlib.util
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
logging.basicConfig(level=logging.WARNING)

spec = importlib.util.spec_from_file_location("rb", str(Path(__file__).resolve().parent / "run_backtest.py"))
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)

from engines.backtest_engine import BacktestConfig, PMSConfig, SimpleBacktester, SlippageConfig
from engines.metrics import generate_report
from engines.signal_engine import (
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)

conn = rb._get_sync_conn()
industry = rb.load_industry(conn)
START, END = date(2019, 1, 1), date(2024, 12, 31)

sig_config = SignalConfig(
    factor_names=["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"],
    top_n=20, rebalance_freq="monthly", weight_method="equal", industry_cap=1.0,
)
composer, builder = SignalComposer(sig_config), PortfolioBuilder(sig_config)

rebal = get_rebalance_dates(START, END, freq="monthly", conn=conn)
price_data = rb.load_price_data(START, END, conn)
benchmark = rb.load_benchmark(START, END, conn)

portfolios, prev = {}, {}
for rd in rebal:
    fv = rb.load_factor_values(rd, conn)
    if fv.empty:
        continue
    universe = rb.load_universe(rd, conn)
    scores = composer.compose(fv, universe)
    if scores.empty:
        continue
    target = builder.build(scores, industry, prev)
    if target:
        portfolios[rd] = target
        prev = target
conn.close()

print(f"数据: {len(rebal)}调仓月, {len(price_data)}价格行")


def simulate_portfolio_protection(
    nav_series, trigger_3d=-0.10, trigger_5d=-0.15,
    recovery_thresh=-0.05, recovery_days=3,
):
    """在NAV序列上模拟组合级保护。降仓=现金, 成本15bps/次。"""
    dates = nav_series.index.tolist()
    adjusted_nav = np.zeros(len(dates))
    adjusted_nav[0] = float(nav_series.iloc[0])

    in_protection = False
    target_ratio = 1.0
    consec_recovery = 0
    triggers = []
    cash_portion = 0.0
    equity_portion = float(nav_series.iloc[0])

    for i in range(1, len(dates)):
        raw_return = (float(nav_series.iloc[i]) - float(nav_series.iloc[i - 1])) / float(nav_series.iloc[i - 1])
        equity_portion *= 1 + raw_return
        total_value = equity_portion + cash_portion
        adjusted_nav[i] = total_value

        ret_3d = (total_value - adjusted_nav[max(0, i - 3)]) / adjusted_nav[max(0, i - 3)] if i >= 3 else 0
        ret_5d = (total_value - adjusted_nav[max(0, i - 5)]) / adjusted_nav[max(0, i - 5)] if i >= 5 else 0

        if not in_protection:
            trigger_rule = None
            new_ratio = 1.0
            if ret_3d < trigger_3d:
                trigger_rule = f"3d/{trigger_3d * 100:.0f}%"
                new_ratio = 0.50
            elif ret_5d < trigger_5d:
                trigger_rule = f"5d/{trigger_5d * 100:.0f}%"
                new_ratio = 0.20

            if trigger_rule:
                in_protection = True
                target_ratio = new_ratio
                consec_recovery = 0
                sell_amount = equity_portion * (1 - target_ratio)
                cost = sell_amount * 0.0015
                cash_portion += sell_amount - cost
                equity_portion -= sell_amount
                triggers.append({
                    "trigger_date": dates[i], "rule": trigger_rule,
                    "nav_at_trigger": total_value, "target_ratio": target_ratio,
                    "recover_date": None, "duration": 0,
                })
        else:
            if ret_3d > recovery_thresh:
                consec_recovery += 1
                if consec_recovery >= recovery_days:
                    buy_amount = cash_portion
                    cost = buy_amount * 0.0015
                    equity_portion += buy_amount - cost
                    cash_portion = 0
                    in_protection = False
                    target_ratio = 1.0
                    if triggers:
                        triggers[-1]["recover_date"] = dates[i]
                        triggers[-1]["duration"] = i - dates.index(triggers[-1]["trigger_date"])
            else:
                consec_recovery = 0

    return pd.Series(adjusted_nav, index=dates), triggers


def run_base(pms_config):
    bt = BacktestConfig(
        initial_capital=1_000_000, top_n=20, rebalance_freq="monthly",
        slippage_mode="volume_impact", slippage_config=SlippageConfig(), pms=pms_config,
    )
    return SimpleBacktester(bt).run(portfolios, price_data, benchmark)


# === 实验 ===
print("\n运行实验A(基线)...")
result_a = run_base(PMSConfig(enabled=False))
nav_a = result_a.daily_nav
rpt_a = generate_report(result_a, price_data)

print("运行实验B(PMS v1.0)...")
result_b = run_base(PMSConfig(enabled=True, exec_mode="same_close"))
rpt_b = generate_report(result_b, price_data)

print("运行实验C(组合级)...")
nav_c, triggers_c = simulate_portfolio_protection(nav_a, -0.10, -0.15)
ret_c = nav_c.pct_change().fillna(0)
sharpe_c = float(ret_c.mean() / (ret_c.std() + 1e-12) * np.sqrt(244))
mdd_c = float(((nav_c - nav_c.cummax()) / nav_c.cummax()).min())

print("运行实验D(v1.0+组合级)...")
nav_d, triggers_d = simulate_portfolio_protection(result_b.daily_nav, -0.10, -0.15)
ret_d = nav_d.pct_change().fillna(0)
sharpe_d = float(ret_d.mean() / (ret_d.std() + 1e-12) * np.sqrt(244))
mdd_d = float(((nav_d - nav_d.cummax()) / nav_d.cummax()).min())

print("运行实验E(宽松)...")
nav_e, triggers_e = simulate_portfolio_protection(nav_a, -0.12, -0.20)
ret_e = nav_e.pct_change().fillna(0)
sharpe_e = float(ret_e.mean() / (ret_e.std() + 1e-12) * np.sqrt(244))
mdd_e = float(((nav_e - nav_e.cummax()) / nav_e.cummax()).min())

print("运行实验F(严格)...")
nav_f, triggers_f = simulate_portfolio_protection(nav_a, -0.07, -0.12)
ret_f = nav_f.pct_change().fillna(0)
sharpe_f = float(ret_f.mean() / (ret_f.std() + 1e-12) * np.sqrt(244))
mdd_f = float(((nav_f - nav_f.cummax()) / nav_f.cummax()).min())

# === 输出 ===
print(f"\n{'=' * 80}")
print(f"{'实验':<10s} {'Sharpe':>8s} {'MDD%':>8s} {'触发':>6s} {'平均持续天':>10s}")
print(f"{'-' * 80}")
for label, sharpe, mdd, triggers in [
    ("A 基线", rpt_a.sharpe_ratio, rpt_a.max_drawdown, []),
    ("B v1.0", rpt_b.sharpe_ratio, rpt_b.max_drawdown, []),
    ("C 组合级", sharpe_c, mdd_c, triggers_c),
    ("D v1+v2", sharpe_d, mdd_d, triggers_d),
    ("E 宽松", sharpe_e, mdd_e, triggers_e),
    ("F 严格", sharpe_f, mdd_f, triggers_f),
]:
    n_trig = len(triggers)
    avg_dur = np.mean([t["duration"] for t in triggers if t["duration"] > 0]) if triggers else 0
    print(f"{label:<10s} {sharpe:>+8.3f} {mdd * 100:>7.1f}% {n_trig:>6d} {avg_dur:>10.0f}")

# 年度分解(C)
print("\n=== 实验C年度分解 ===")
nav_c_dt = nav_c.copy()
nav_c_dt.index = pd.to_datetime(nav_c_dt.index)
ret_c_dt = ret_c.copy()
ret_c_dt.index = pd.to_datetime(ret_c_dt.index)
for year in range(2019, 2025):
    yr = ret_c_dt[ret_c_dt.index.year == year]
    if len(yr) == 0:
        continue
    s = float(yr.mean() / (yr.std() + 1e-12) * np.sqrt(244))
    yr_nav = nav_c_dt[nav_c_dt.index.year == year]
    m = float(((yr_nav - yr_nav.cummax()) / yr_nav.cummax()).min())
    n_t = sum(1 for t in triggers_c if str(t["trigger_date"])[:4] == str(year))
    print(f"  {year}: Sharpe={s:+.3f} MDD={m * 100:.1f}% 触发={n_t}")

# 触发记录(C)
print("\n=== 实验C触发记录 ===")
for t in triggers_c:
    print(f"  {t['trigger_date']} | {t['rule']} | NAV={t['nav_at_trigger']:.0f} | "
          f"恢复={t['recover_date']} | {t['duration']}天 | {t['target_ratio'] * 100:.0f}%仓位")

# 机会成本(C)
print("\n=== 降仓机会成本 ===")
for t in triggers_c:
    td, rd = t["trigger_date"], t["recover_date"]
    if rd is None:
        rd = nav_a.index[-1]
    if td in nav_a.index and rd in nav_a.index:
        fullhold_ret = (float(nav_a.loc[rd]) - float(nav_a.loc[td])) / float(nav_a.loc[td])
        verdict = "避损" if fullhold_ret < 0 else "踏空"
        print(f"  {td}~{rd}: 满仓收益={fullhold_ret * 100:+.1f}% → {verdict}")

# Bootstrap
print("\n=== Bootstrap(C vs A) ===")
a_r = result_a.daily_returns.values
c_r = ret_c.values
ml = min(len(a_r), len(c_r))
diff = c_r[:ml] - a_r[:ml]
rng = np.random.RandomState(42)
n = len(diff)
boots = []
for _ in range(1000):
    starts = rng.randint(0, max(n - 20, 1), size=n // 20 + 1)
    samp = np.concatenate([diff[i : i + 20] for i in starts])[:n]
    boots.append(float(samp.mean() / (samp.std() + 1e-12) * np.sqrt(244)))
boots = np.array(boots)
p = float((boots <= 0).mean())
print(f"  p-value: {p:.4f}")

# 锯齿检测
print("\n=== 7天内重复触发 ===")
sawteeth = 0
for i in range(1, len(triggers_c)):
    pr = triggers_c[i - 1].get("recover_date")
    ct = triggers_c[i]["trigger_date"]
    if pr is not None:
        try:
            gap = (pd.Timestamp(ct) - pd.Timestamp(pr)).days
            if gap <= 7:
                print(f"  锯齿: {pr}恢复 → {ct}再触发 (间隔{gap}天)")
                sawteeth += 1
        except Exception:
            pass
if sawteeth == 0:
    print("  无锯齿触发")

print(f"\n{'=' * 80}")
