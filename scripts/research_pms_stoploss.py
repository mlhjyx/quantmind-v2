#!/usr/bin/env python3
"""PMS止损回测验证 — 个股止损+利润保护对Sharpe/MDD的影响。

改造: 月频选股 + 日频持仓监控(每天检查止损/利润保护规则)。
实验矩阵: 7组(A无→G阶梯式)。
"""
import logging, os, sys, time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.signal_engine import (PAPER_TRADING_CONFIG, PortfolioBuilder,
                                   SignalComposer, SignalConfig, get_rebalance_dates)
from engines.slippage_model import SlippageConfig, volume_impact_slippage
from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

START, END = "2021-01-01", "2026-03-31"
CAPITAL = 1_000_000
TOP_N, FREQ = 15, "monthly"
COMMISSION = 0.0000854
STAMP_TAX = 0.0005
TRANSFER_FEE = 0.00001


@dataclass
class PMSConfig:
    """止损/利润保护配置。"""
    name: str = "baseline"
    stop_loss: float = 0.0        # 0=无止损, 0.20=-20%止损
    profit_protect: bool = False
    profit_threshold: float = 0.30   # 盈利>30%激活保护
    trailing_stop: float = 0.15      # 从高点回撤15%卖出
    tiered: bool = False             # 阶梯式利润保护


@dataclass
class HoldingState:
    """个股持仓状态。"""
    code: str
    buy_price: float
    buy_date: date
    shares: int
    weight: float
    max_price: float = 0.0

    def __post_init__(self):
        if self.max_price == 0:
            self.max_price = self.buy_price


EXPERIMENTS = [
    PMSConfig(name="A_baseline"),
    PMSConfig(name="B_sl15", stop_loss=0.15),
    PMSConfig(name="C_sl20", stop_loss=0.20),
    PMSConfig(name="D_sl25", stop_loss=0.25),
    PMSConfig(name="E_profit_only", profit_protect=True),
    PMSConfig(name="F_sl20_profit", stop_loss=0.20, profit_protect=True),
    PMSConfig(name="G_tiered", stop_loss=0.20, profit_protect=True, tiered=True),
]


def should_stop(holding: HoldingState, close: float, cfg: PMSConfig) -> tuple[bool, str]:
    """检查是否应触发止损/利润保护。返回(是否卖出, 原因)。"""
    pnl = (close - holding.buy_price) / holding.buy_price
    dd_from_peak = (close - holding.max_price) / holding.max_price if holding.max_price > 0 else 0

    # 止损
    if cfg.stop_loss > 0 and pnl < -cfg.stop_loss:
        return True, f"stop_loss({pnl:.1%})"

    # 利润保护
    if cfg.profit_protect and not cfg.tiered:
        if pnl > cfg.profit_threshold and dd_from_peak < -cfg.trailing_stop:
            return True, f"profit_protect(pnl={pnl:.1%},dd={dd_from_peak:.1%})"

    # 阶梯式
    if cfg.tiered:
        if pnl > 0.30 and dd_from_peak < -0.15:
            return True, f"tiered_30(pnl={pnl:.1%},dd={dd_from_peak:.1%})"
        elif pnl > 0.20 and dd_from_peak < -0.12:
            return True, f"tiered_20(pnl={pnl:.1%},dd={dd_from_peak:.1%})"
        elif pnl > 0.10 and dd_from_peak < -0.10:
            return True, f"tiered_10(pnl={pnl:.1%},dd={dd_from_peak:.1%})"

    return False, ""


def calc_sell_cost(amount: float) -> float:
    """卖出交易成本。"""
    return max(amount * COMMISSION, 5.0) + amount * STAMP_TAX + amount * TRANSFER_FEE


def calc_buy_cost(amount: float) -> float:
    """买入交易成本。"""
    return max(amount * COMMISSION, 5.0) + amount * TRANSFER_FEE


def is_limit_down(row, close):
    """跌停封板检查。"""
    dl = row.get("down_limit")
    tr = row.get("turnover_rate")
    if dl is not None and not pd.isna(dl):
        if abs(close - float(dl)) < 0.015:
            if tr is None or pd.isna(tr) or float(tr) < 1.0:
                return True
    return False


def run_experiment(cfg: PMSConfig, rebalance_dates, target_portfolios,
                   price_lookup, all_trading_days) -> dict:
    """运行单个PMS实验。"""
    cash = float(CAPITAL)
    holdings: dict[str, HoldingState] = {}
    nav_series = {}
    stop_events = []  # [{date, code, reason, pnl, buy_price, sell_price}]

    rebal_set = set(rebalance_dates)
    rebal_targets = {}
    for rd in rebalance_dates:
        if rd in target_portfolios:
            rebal_targets[rd] = target_portfolios[rd]

    current_target = {}
    last_rebal = None

    for td in all_trading_days:
        day_prices = price_lookup.get(td, {})

        # 1. 月末调仓日: 执行买卖
        if td in rebal_set and td in rebal_targets:
            current_target = rebal_targets[td]
            last_rebal = td
            portfolio_value = cash + sum(
                h.shares * float(day_prices.get(h.code, {}).get("close", h.buy_price))
                for h in holdings.values()
            )

            # 卖出不在目标中的持仓
            to_sell = [c for c in list(holdings.keys()) if c not in current_target]
            for code in to_sell:
                h = holdings[code]
                p = day_prices.get(code, {})
                close = float(p.get("close", h.buy_price))
                if is_limit_down(p, close):
                    continue
                amount = h.shares * close
                cost = calc_sell_cost(amount)
                cash += amount - cost
                del holdings[code]

            # 买入新目标
            for code, weight in current_target.items():
                if code in holdings:
                    continue
                p = day_prices.get(code, {})
                close = float(p.get("close", 0))
                if close <= 0:
                    continue
                target_amount = portfolio_value * weight
                shares = int(target_amount / close / 100) * 100
                if shares <= 0:
                    continue
                amount = shares * close
                cost = calc_buy_cost(amount)
                if amount + cost > cash:
                    shares = int(cash / (close * 1.001) / 100) * 100
                    if shares <= 0:
                        continue
                    amount = shares * close
                    cost = calc_buy_cost(amount)
                cash -= amount + cost
                holdings[code] = HoldingState(
                    code=code, buy_price=close, buy_date=td,
                    shares=shares, weight=weight, max_price=close)

        # 2. 日频PMS检查(非调仓日也检查)
        elif cfg.stop_loss > 0 or cfg.profit_protect or cfg.tiered:
            for code in list(holdings.keys()):
                h = holdings[code]
                p = day_prices.get(code, {})
                close = float(p.get("close", 0))
                high = float(p.get("high", close))
                if close <= 0:
                    continue

                # 更新max_price
                h.max_price = max(h.max_price, high)

                # 检查止损/利润保护
                trigger, reason = should_stop(h, close, cfg)
                if trigger:
                    if is_limit_down(p, close):
                        continue  # 跌停不成交
                    amount = h.shares * close
                    cost = calc_sell_cost(amount)
                    pnl = (close - h.buy_price) / h.buy_price
                    stop_events.append({
                        "date": td, "code": code, "reason": reason,
                        "pnl": pnl, "buy_price": h.buy_price, "sell_price": close,
                        "hold_days": (td - h.buy_date).days,
                    })
                    cash += amount - cost
                    del holdings[code]

        # 3. 计算当日NAV
        nav = cash
        for h in holdings.values():
            p = day_prices.get(h.code, {})
            close = float(p.get("close", h.buy_price))
            nav += h.shares * close
        nav_series[td] = nav

    # 计算指标
    nav_s = pd.Series(nav_series).sort_index()
    returns = nav_s.pct_change().dropna()
    total_ret = nav_s.iloc[-1] / nav_s.iloc[0] - 1
    years = len(returns) / 244
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    sharpe = returns.mean() / returns.std() * np.sqrt(244) if returns.std() > 0 else 0
    drawdowns = nav_s / nav_s.cummax() - 1
    mdd = drawdowns.min()
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # 年度分解
    returns.index = pd.to_datetime(returns.index)
    annual = {}
    for yr in range(2021, 2027):
        yr_ret = returns[returns.index.year == yr]
        if len(yr_ret) < 10:
            continue
        yr_nav = (1 + yr_ret).cumprod()
        yr_sharpe = yr_ret.mean() / yr_ret.std() * np.sqrt(244) if yr_ret.std() > 0 else 0
        yr_mdd = (yr_nav / yr_nav.cummax() - 1).min()
        yr_total = yr_nav.iloc[-1] - 1
        annual[yr] = {"sharpe": yr_sharpe, "mdd": yr_mdd, "return": yr_total}

    return {
        "name": cfg.name,
        "sharpe": sharpe,
        "mdd": mdd,
        "cagr": cagr,
        "calmar": calmar,
        "annual": annual,
        "stop_events": stop_events,
        "nav_series": nav_s,
        "returns": returns,
    }


def analyze_post_stop(stop_events, price_lookup, all_trading_days):
    """分析被止损卖出的股票后续1个月表现。"""
    if not stop_events:
        return {"avg_1m_ret": np.nan, "pct_rebounded": np.nan, "n": 0}

    td_list = sorted(all_trading_days)
    td_idx = {d: i for i, d in enumerate(td_list)}
    post_rets = []

    for ev in stop_events:
        sell_date = ev["date"]
        code = ev["code"]
        idx = td_idx.get(sell_date)
        if idx is None:
            continue
        # 1月后(~22交易日)
        future_idx = min(idx + 22, len(td_list) - 1)
        future_date = td_list[future_idx]
        sell_price = ev["sell_price"]
        future_p = price_lookup.get(future_date, {}).get(code, {})
        future_close = float(future_p.get("close", 0))
        if future_close > 0 and sell_price > 0:
            post_ret = future_close / sell_price - 1
            post_rets.append(post_ret)

    if not post_rets:
        return {"avg_1m_ret": np.nan, "pct_rebounded": np.nan, "n": 0}

    return {
        "avg_1m_ret": np.mean(post_rets),
        "pct_rebounded": np.mean([1 if r > 0 else 0 for r in post_rets]),
        "n": len(post_rets),
    }


def main():
    t0 = time.time()
    conn = _get_sync_conn()

    start = datetime.strptime(START, "%Y-%m-%d").date()
    end = datetime.strptime(END, "%Y-%m-%d").date()

    # 共享数据
    logger.info("加载数据...")
    rebalance_dates = get_rebalance_dates(start, end, freq=FREQ, conn=conn)
    industry = pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'",
                            conn).set_index("code")["industry_sw1"].fillna("其他")

    # 月度目标持仓
    sig_config = SignalConfig(factor_names=PAPER_TRADING_CONFIG.factor_names, top_n=TOP_N, rebalance_freq=FREQ)
    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)
    target_portfolios = {}
    prev = {}
    for rd in rebalance_dates:
        fv = pd.read_sql("SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
                          conn, params=(rd,))
        if fv.empty:
            continue
        uni = pd.read_sql(
            "SELECT k.code FROM klines_daily k JOIN symbols s ON k.code = s.code "
            "LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
            "WHERE k.trade_date = %s AND k.volume > 0 AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%' "
            "AND (s.list_date IS NULL OR s.list_date <= %s::date - INTERVAL '60 days') "
            "AND COALESCE(db.total_mv, 0) > 100000", conn, params=(rd, rd))
        universe = set(uni["code"].tolist())
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue
        t = builder.build(scores, industry, prev)
        if t:
            target_portfolios[rd] = t
            prev = t

    # 日频价格数据(构建lookup: date → {code → {close, high, low, down_limit, turnover_rate}})
    logger.info("构建日频价格lookup...")
    price_raw = pd.read_sql(
        "SELECT k.code, k.trade_date, k.close, k.high, k.low, k.down_limit, db.turnover_rate "
        "FROM klines_daily k LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date "
        "WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0",
        conn, params=(START, END))

    price_lookup = {}
    for _, row in price_raw.iterrows():
        td = row["trade_date"]
        if td not in price_lookup:
            price_lookup[td] = {}
        price_lookup[td][row["code"]] = row.to_dict()

    all_trading_days = sorted(price_lookup.keys())
    logger.info(f"数据就绪: {len(rebalance_dates)}调仓日, {len(all_trading_days)}交易日, "
                f"{len(target_portfolios)}目标持仓")
    conn.close()

    # 运行实验
    all_results = []
    for cfg in EXPERIMENTS:
        exp_t0 = time.time()
        result = run_experiment(cfg, rebalance_dates, target_portfolios, price_lookup, all_trading_days)
        post = analyze_post_stop(result["stop_events"], price_lookup, all_trading_days)
        result["post_stop"] = post
        all_results.append(result)
        n_stops = len(result["stop_events"])
        elapsed = time.time() - exp_t0
        logger.info(f"  {cfg.name}: Sharpe={result['sharpe']:.2f}, MDD={result['mdd']*100:.1f}%, "
                     f"CAGR={result['cagr']*100:.1f}%, stops={n_stops}, 耗时={elapsed:.0f}s")

    # 报告
    print("\n" + "=" * 120)
    print("PMS止损回测验证")
    print("=" * 120)
    print(f"回测: {START}~{END} | 5因子等权Top15月度 | 日频PMS监控 | 资金{CAPITAL:,.0f}")

    header = f"{'实验':<20} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8} {'Calmar':>8} {'止损次':>6} {'年均':>6} {'卖后1月':>8} {'反弹率':>8}"
    print(f"\n{header}\n{'-'*len(header)}")
    for r in all_results:
        ps = r["post_stop"]
        n = len(r["stop_events"])
        yrs = len(r.get("annual", {})) or 5
        post_ret = f"{ps['avg_1m_ret']*100:>+7.1f}%" if not np.isnan(ps["avg_1m_ret"]) else f"{'N/A':>8}"
        rebound = f"{ps['pct_rebounded']*100:>7.0f}%" if not np.isnan(ps["pct_rebounded"]) else f"{'N/A':>8}"
        print(f"{r['name']:<20} {r['sharpe']:>8.2f} {r['mdd']*100:>7.1f}% {r['cagr']*100:>7.1f}% "
              f"{r['calmar']:>8.2f} {n:>6} {n/yrs:>6.1f} {post_ret} {rebound}")

    # 年度分解
    years = sorted(all_results[0]["annual"].keys())
    print(f"\n--- 年度Sharpe ---")
    hdr = f"{'实验':<20} " + " ".join(f"{y:>8}" for y in years)
    print(f"{hdr}\n{'-'*len(hdr)}")
    for r in all_results:
        vals = " ".join(f"{r['annual'].get(y, {}).get('sharpe', 0):>8.2f}" for y in years)
        print(f"{r['name']:<20} {vals}")

    print(f"\n--- 年度MDD ---")
    print(f"{hdr}\n{'-'*len(hdr)}")
    for r in all_results:
        vals = " ".join(f"{r['annual'].get(y, {}).get('mdd', 0)*100:>7.1f}%" for y in years)
        print(f"{r['name']:<20} {vals}")

    # Bootstrap
    print(f"\n--- Paired Bootstrap (vs baseline) ---")
    baseline_ret = all_results[0]["returns"]
    for r in all_results[1:]:
        common = baseline_ret.index.intersection(r["returns"].index)
        ra, rb = baseline_ret.loc[common], r["returns"].loc[common]
        if len(ra) < 30:
            continue
        obs_diff = (ra.mean()/ra.std() - rb.mean()/rb.std()) * np.sqrt(244)
        # Quick bootstrap
        n_boot = 3000
        diffs = []
        n = len(ra)
        ra_v, rb_v = ra.values, rb.values
        for _ in range(n_boot):
            idx = np.random.randint(0, n, n)
            ba, bb = ra_v[idx], rb_v[idx]
            sa = ba.mean() / ba.std() * np.sqrt(244) if ba.std() > 0 else 0
            sb = bb.mean() / bb.std() * np.sqrt(244) if bb.std() > 0 else 0
            diffs.append(sa - sb)
        diffs = np.array(diffs)
        p = (diffs <= 0).mean() if obs_diff > 0 else (diffs >= 0).mean()
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else "n.s."
        print(f"  baseline vs {r['name']}: Sharpe diff={-obs_diff:+.3f}, p={p:.3f} {sig}")

    elapsed = time.time() - t0
    logger.info(f"\n总耗时: {elapsed:.0f}s ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
