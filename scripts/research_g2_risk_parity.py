#!/usr/bin/env python3
"""G2 风险平价权重研究 — 批量对比实验 + 风险贡献分析。

实验矩阵:
  1. equal                        基线确认
  2. risk_parity (vol_20)         核心实验
  3. min_variance (vol_20)        更激进版本
  4a. risk_parity (vol_5)         短窗口灵敏度
  4b. risk_parity (vol_60)        长窗口灵敏度
  5. equal + vol_regime            动态仓位单独效果
  6. risk_parity + vol_regime      两维度叠加

分析模块:
  A. 风险贡献分析 (Herfindahl指数)
  B. 因子信号稀释检查 (Spearman相关)
  C. 市值分布对比
  D. 2022极端行情验证
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.backtest_engine import BacktestConfig, SimpleBacktester
from engines.config_guard import print_config_header
from engines.metrics import generate_report
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)
from engines.slippage_model import SlippageConfig
from engines.vol_regime import calc_vol_regime

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.WARNING,  # 减少噪音，只输出WARNING+
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# 配置
# ============================================================
START = "2021-01-01"
END = "2026-03-31"
CAPITAL = 1_000_000
TOP_N = 15
FREQ = "monthly"
FACTOR_NAMES = PAPER_TRADING_CONFIG.factor_names  # 5因子


EXPERIMENTS = [
    {"name": "1_equal",             "weight_method": "equal",       "vol_regime": False, "vol_factor": None},
    {"name": "2_risk_parity",       "weight_method": "risk_parity", "vol_regime": False, "vol_factor": "volatility_20"},
    {"name": "3_min_variance",      "weight_method": "min_variance","vol_regime": False, "vol_factor": "volatility_20"},
    {"name": "4a_rp_vol5",          "weight_method": "risk_parity", "vol_regime": False, "vol_factor": "volatility_5"},
    {"name": "4b_rp_vol60",         "weight_method": "risk_parity", "vol_regime": False, "vol_factor": "volatility_60"},
    {"name": "5_equal_volregime",   "weight_method": "equal",       "vol_regime": True,  "vol_factor": None},
    {"name": "6_rp_volregime",      "weight_method": "risk_parity", "vol_regime": True,  "vol_factor": "volatility_20"},
]


# ============================================================
# 数据加载（与run_backtest.py一致）
# ============================================================
def load_factor_values(trade_date, conn):
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value FROM factor_values WHERE trade_date = %s",
        conn, params=(trade_date,),
    )


def load_volatility(trade_date, factor_name, conn):
    """加载个股波动率raw_value（用于风险平价权重）。"""
    df = pd.read_sql(
        "SELECT code, raw_value FROM factor_values WHERE trade_date = %s AND factor_name = %s",
        conn, params=(trade_date, factor_name),
    )
    return dict(zip(df["code"], df["raw_value"].astype(float), strict=False))


def load_universe(trade_date, conn):
    df = pd.read_sql(
        """SELECT k.code
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s AND k.volume > 0
             AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000""",
        conn, params=(trade_date, trade_date),
    )
    return set(df["code"].tolist())


def load_industry(conn):
    df = pd.read_sql(
        "SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'", conn,
    )
    return df.set_index("code")["industry_sw1"].fillna("其他")


def load_price_data(start_date, end_date, conn):
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
                  k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
           ORDER BY k.trade_date, k.code""",
        conn, params=(start_date, end_date),
    )


def load_benchmark(start_date, end_date, conn):
    return pd.read_sql(
        """SELECT trade_date, close FROM index_daily
           WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn, params=(start_date, end_date),
    )


def load_market_cap(trade_date, conn):
    """加载个股总市值(万元)用于市值分布分析。"""
    df = pd.read_sql(
        "SELECT code, total_mv FROM daily_basic WHERE trade_date = %s AND total_mv > 0",
        conn, params=(trade_date,),
    )
    return dict(zip(df["code"], df["total_mv"].astype(float), strict=False))


# ============================================================
# 单次实验
# ============================================================
def run_experiment(exp, rebalance_dates, industry, price_data, benchmark_data,
                   csi300_closes, conn):
    """运行单个实验，返回 (report, portfolios_meta)。"""
    name = exp["name"]
    weight_method = exp["weight_method"]
    use_vol_regime = exp["vol_regime"]
    vol_factor = exp["vol_factor"]

    logger.info(f"=== 实验 {name} ===")

    sig_config = SignalConfig(
        factor_names=FACTOR_NAMES,
        top_n=TOP_N,
        rebalance_freq=FREQ,
        weight_method=weight_method,
    )
    bt_config = BacktestConfig(
        initial_capital=CAPITAL,
        top_n=TOP_N,
        rebalance_freq=FREQ,
        slippage_mode="volume_impact",
        slippage_config=SlippageConfig(),
    )

    composer = SignalComposer(sig_config)
    builder = PortfolioBuilder(sig_config)

    target_portfolios = {}
    prev_weights = {}
    # 收集分析数据
    portfolios_meta = []  # [{date, scores, weights, vol_map, mcap_map}]

    need_vol = weight_method in ("risk_parity", "min_variance")

    for rd in rebalance_dates:
        fv = load_factor_values(rd, conn)
        if fv.empty:
            continue
        universe = load_universe(rd, conn)
        scores = composer.compose(fv, universe)
        if scores.empty:
            continue

        vol_map = None
        if need_vol and vol_factor:
            vol_map = load_volatility(rd, vol_factor, conn)

        vol_regime_scale = 1.0
        if use_vol_regime and csi300_closes is not None:
            closes_up_to = csi300_closes[csi300_closes.index <= rd]
            if len(closes_up_to) >= 21:
                vol_regime_scale = calc_vol_regime(closes_up_to)

        target = builder.build(
            scores, industry, prev_weights,
            vol_regime_scale=vol_regime_scale,
            volatility_map=vol_map,
        )
        if target:
            target_portfolios[rd] = target
            prev_weights = target
            # 收集分析元数据
            mcap_map = load_market_cap(rd, conn)
            portfolios_meta.append({
                "date": rd,
                "scores": scores,
                "weights": target,
                "vol_map": vol_map or {},
                "mcap_map": mcap_map,
                "vol_regime_scale": vol_regime_scale,
            })

    backtester = SimpleBacktester(bt_config)
    result = backtester.run(target_portfolios, price_data, benchmark_data)
    report = generate_report(result, price_data)

    return report, portfolios_meta


# ============================================================
# 分析模块
# ============================================================
def analyze_risk_contribution(portfolios_meta):
    """A. 风险贡献分析 — Herfindahl指数。"""
    hhi_list = []
    max_rc_list = []

    for pm in portfolios_meta:
        weights = pm["weights"]
        vol_map = pm["vol_map"]
        if not vol_map:
            continue

        codes = list(weights.keys())
        w = np.array([weights[c] for c in codes])
        vols = np.array([vol_map.get(c, np.nan) for c in codes])

        # 缺失vol用中位数填充
        valid = ~np.isnan(vols)
        if valid.sum() == 0:
            continue
        median_vol = np.nanmedian(vols)
        vols[~valid] = median_vol

        # 风险贡献: RC_i = w_i * σ_i (简化版，忽略相关性)
        rc = w * vols
        rc_pct = rc / rc.sum() if rc.sum() > 0 else rc

        hhi = float((rc_pct ** 2).sum())
        hhi_list.append(hhi)
        max_rc_list.append(float(rc_pct.max()))

    if not hhi_list:
        return {"hhi_mean": np.nan, "hhi_std": np.nan, "max_rc_mean": np.nan}

    return {
        "hhi_mean": np.mean(hhi_list),
        "hhi_std": np.std(hhi_list),
        "max_rc_mean": np.mean(max_rc_list),
        "max_rc_max": np.max(max_rc_list),
    }


def analyze_signal_dilution(portfolios_meta):
    """B. 因子信号稀释检查 — Spearman(因子排名, 权重排名)。"""
    corrs = []
    for pm in portfolios_meta:
        scores = pm["scores"]
        weights = pm["weights"]
        codes = list(weights.keys())
        if len(codes) < 3:
            continue

        score_vals = [float(scores.get(c, 0)) for c in codes]
        weight_vals = [weights[c] for c in codes]

        rho, _ = stats.spearmanr(score_vals, weight_vals)
        if not np.isnan(rho):
            corrs.append(rho)

    if not corrs:
        return {"spearman_mean": np.nan, "spearman_std": np.nan}

    return {
        "spearman_mean": np.mean(corrs),
        "spearman_std": np.std(corrs),
        "spearman_min": np.min(corrs),
        "spearman_max": np.max(corrs),
    }


def analyze_market_cap_distribution(portfolios_meta):
    """C. 市值分布对比 — 大/中/小盘占比。"""
    large_pcts, mid_pcts, small_pcts = [], [], []

    for pm in portfolios_meta:
        weights = pm["weights"]
        mcap_map = pm["mcap_map"]
        total_w = {"large": 0.0, "mid": 0.0, "small": 0.0}

        for code, w in weights.items():
            mv = mcap_map.get(code, 0)  # 万元
            mv_yi = mv / 10000  # 转亿元
            if mv_yi >= 500:
                total_w["large"] += w
            elif mv_yi >= 100:
                total_w["mid"] += w
            else:
                total_w["small"] += w

        w_sum = sum(total_w.values()) or 1
        large_pcts.append(total_w["large"] / w_sum * 100)
        mid_pcts.append(total_w["mid"] / w_sum * 100)
        small_pcts.append(total_w["small"] / w_sum * 100)

    return {
        "large_mean": np.mean(large_pcts) if large_pcts else 0,
        "mid_mean": np.mean(mid_pcts) if mid_pcts else 0,
        "small_mean": np.mean(small_pcts) if small_pcts else 0,
    }


# ============================================================
# 报告生成
# ============================================================
def format_results(all_results):
    """格式化所有实验结果为对比表。"""
    lines = []
    lines.append("\n" + "=" * 100)
    lines.append("G2 风险平价权重研究 — 对比报告")
    lines.append("=" * 100)
    lines.append(f"回测区间: {START} ~ {END} | 因子: 5等权 | Top: {TOP_N} | 频率: {FREQ}")
    lines.append(f"滑点: volume_impact | 初始资金: {CAPITAL:,.0f}")

    # 核心指标对比表
    lines.append("\n--- 核心指标对比 ---")
    header = f"{'实验':<25} {'Sharpe':>8} {'AutoCorr':>8} {'CAGR':>8} {'MDD':>8} {'Calmar':>8} {'换手率':>8} {'CI_lo':>8} {'CI_hi':>8}"
    lines.append(header)
    lines.append("-" * len(header))

    for name, report, _, _ in all_results:
        ci_lo, ci_hi = report.bootstrap_sharpe_ci[1], report.bootstrap_sharpe_ci[2]
        lines.append(
            f"{name:<25} {report.sharpe_ratio:>8.2f} {report.autocorr_adjusted_sharpe_ratio:>8.2f} "
            f"{report.annual_return * 100:>7.1f}% {report.max_drawdown * 100:>7.1f}% "
            f"{report.calmar_ratio:>8.2f} {report.annual_turnover:>8.2f} "
            f"{ci_lo:>8.2f} {ci_hi:>8.2f}"
        )

    # 成本敏感性
    lines.append("\n--- 成本敏感性 (Sharpe @ 不同成本倍数) ---")
    header2 = f"{'实验':<25} {'0.5x':>8} {'1.0x':>8} {'1.5x':>8} {'2.0x':>8}"
    lines.append(header2)
    lines.append("-" * len(header2))
    for name, report, _, _ in all_results:
        cs = report.cost_sensitivity
        vals = []
        for mult in ["0.5", "1.0", "1.5", "2.0"]:
            if mult in cs:
                vals.append(f"{cs[mult].get('sharpe', 0):>8.2f}")
            else:
                vals.append(f"{'N/A':>8}")
        lines.append(f"{name:<25} {' '.join(vals)}")

    # 年度分解
    lines.append("\n--- 年度Sharpe对比 ---")
    years = sorted(all_results[0][1].annual_breakdown.index)
    header3 = f"{'实验':<25} " + " ".join(f"{y:>8}" for y in years)
    lines.append(header3)
    lines.append("-" * len(header3))
    for name, report, _, _ in all_results:
        ab = report.annual_breakdown
        vals = []
        for y in years:
            if y in ab.index:
                vals.append(f"{ab.loc[y, 'sharpe']:>8.2f}")
            else:
                vals.append(f"{'N/A':>8}")
        lines.append(f"{name:<25} {' '.join(vals)}")

    # 年度MDD对比
    lines.append("\n--- 年度MDD对比 ---")
    lines.append(header3)
    lines.append("-" * len(header3))
    for name, report, _, _ in all_results:
        ab = report.annual_breakdown
        vals = []
        for y in years:
            if y in ab.index:
                vals.append(f"{ab.loc[y, 'mdd']:>7.1f}%")
            else:
                vals.append(f"{'N/A':>8}")
        lines.append(f"{name:<25} {' '.join(vals)}")

    # 分析模块
    lines.append("\n--- A. 风险贡献分析 ---")
    header4 = f"{'实验':<25} {'HHI均值':>10} {'HHI标准差':>10} {'最大RC均值':>10} {'最大RC峰值':>10}"
    lines.append(header4)
    lines.append("-" * len(header4))
    for name, _, risk_analysis, _ in all_results:
        rc = risk_analysis["risk_contribution"]
        lines.append(
            f"{name:<25} {rc['hhi_mean']:>10.4f} {rc.get('hhi_std', 0):>10.4f} "
            f"{rc.get('max_rc_mean', 0):>10.2%} {rc.get('max_rc_max', 0):>10.2%}"
        )

    lines.append("\n--- B. 因子信号稀释 (Spearman: 因子排名 vs 权重排名) ---")
    header5 = f"{'实验':<25} {'均值':>8} {'标准差':>8} {'最小':>8} {'最大':>8} {'解读':<20}"
    lines.append(header5)
    lines.append("-" * len(header5))
    for name, _, risk_analysis, _ in all_results:
        sd = risk_analysis["signal_dilution"]
        mean_v = sd["spearman_mean"]
        if np.isnan(mean_v):
            interp = "N/A(等权)"
        elif mean_v < -0.3:
            interp = "严重稀释"
        elif mean_v < 0:
            interp = "轻微稀释"
        elif mean_v < 0.3:
            interp = "正交(可接受)"
        else:
            interp = "理想(正相关)"
        lines.append(
            f"{name:<25} {mean_v:>8.3f} {sd.get('spearman_std', 0):>8.3f} "
            f"{sd.get('spearman_min', 0):>8.3f} {sd.get('spearman_max', 0):>8.3f} {interp:<20}"
        )

    lines.append("\n--- C. 市值分布(权重占比%) ---")
    header6 = f"{'实验':<25} {'大盘>500亿':>12} {'中盘100-500':>12} {'小盘<100亿':>12}"
    lines.append(header6)
    lines.append("-" * len(header6))
    for name, _, risk_analysis, _ in all_results:
        mc = risk_analysis["market_cap"]
        lines.append(
            f"{name:<25} {mc['large_mean']:>11.1f}% {mc['mid_mean']:>11.1f}% {mc['small_mean']:>11.1f}%"
        )

    return "\n".join(lines)


# ============================================================
# 主程序
# ============================================================
def main():
    print_config_header()
    t0 = time.time()

    start = datetime.strptime(START, "%Y-%m-%d").date()
    end = datetime.strptime(END, "%Y-%m-%d").date()

    conn = _get_sync_conn()

    # 共享数据加载
    logger.info("加载共享数据...")
    rebalance_dates = get_rebalance_dates(start, end, freq=FREQ, conn=conn)
    industry = load_industry(conn)
    price_data = load_price_data(start, end, conn)
    benchmark_data = load_benchmark(start, end, conn)
    csi300_closes = benchmark_data.set_index("trade_date")["close"]
    logger.info(f"共享数据加载完成: {len(rebalance_dates)}调仓日, {len(price_data)}行价格")

    # 运行所有实验
    all_results = []  # [(name, report, analysis_dict, portfolios_meta)]

    for exp in EXPERIMENTS:
        exp_t0 = time.time()
        report, portfolios_meta = run_experiment(
            exp, rebalance_dates, industry, price_data, benchmark_data,
            csi300_closes, conn,
        )

        # 分析
        risk_analysis = {
            "risk_contribution": analyze_risk_contribution(portfolios_meta),
            "signal_dilution": analyze_signal_dilution(portfolios_meta),
            "market_cap": analyze_market_cap_distribution(portfolios_meta),
        }

        all_results.append((exp["name"], report, risk_analysis, portfolios_meta))
        elapsed = time.time() - exp_t0
        logger.info(
            f"  {exp['name']}: Sharpe={report.sharpe_ratio:.2f}, "
            f"MDD={report.max_drawdown * 100:.1f}%, "
            f"CAGR={report.annual_return * 100:.1f}%, "
            f"耗时={elapsed:.0f}s"
        )

    conn.close()

    # 输出报告
    report_text = format_results(all_results)
    print(report_text)

    # 写入文件
    output_path = Path(__file__).resolve().parent.parent / "G2_RISK_PARITY_REPORT.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("```\n")
        f.write(report_text)
        f.write("\n```\n")

    total_elapsed = time.time() - t0
    logger.info(f"\n总耗时: {total_elapsed:.0f}s ({total_elapsed / 60:.1f}分钟)")
    logger.info(f"报告已写入: {output_path}")


if __name__ == "__main__":
    main()
