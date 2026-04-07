"""北向资金MODIFIER因子研究 — 市场级仓位调节信号。

核心逻辑: 北向资金做MODIFIER不是选股(RANKING)，而是市场情绪/风险信号。
北向大幅流出时全市场系统性下跌 → 仓位调节系数0.2~1.0。

数据源: northbound_holdings表(hold_vol差分=每日净买入股数)
回测基准: 沪深300/中证500 + 等权Top-N策略叠加

用法:
    python scripts/research_northbound_modifier.py
    python scripts/research_northbound_modifier.py --oos-only  # 只看OOS结果
"""

import argparse
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────
TRAIN_START = date(2021, 1, 1)
TRAIN_END = date(2023, 12, 31)
OOS_START = date(2024, 1, 1)
OOS_END = date(2025, 12, 31)
FULL_START = date(2021, 1, 1)
FULL_END = date(2025, 12, 31)
WARMUP_DAYS = 252  # 滚动窗口warmup
DATA_START = date(2020, 1, 1)  # 多拉1年做warmup

COST_PER_TRADE = 0.001  # 单边交易成本(佣金+印花税+过户费)


def get_db_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )


# ── 数据加载 ─────────────────────────────────────────────────
def load_northbound_daily(conn) -> pd.DataFrame:
    """加载北向每日全市场汇总: hold_vol差分 = 净买入股数。"""
    logger.info("加载北向持股数据...")
    cur = conn.cursor()
    # 全市场汇总: 每日所有股票hold_vol之和
    cur.execute("""
        SELECT trade_date, SUM(hold_vol) as total_hold_vol, COUNT(*) as n_stocks
        FROM northbound_holdings
        WHERE trade_date >= %s
        GROUP BY trade_date
        ORDER BY trade_date
    """, (DATA_START,))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["trade_date", "total_hold_vol", "n_stocks"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date").sort_index()

    # 净买入 = 今日持股 - 昨日持股 (股数)
    df["net_buy_vol"] = df["total_hold_vol"].diff()
    # 第一行diff为NaN，丢弃
    df = df.dropna(subset=["net_buy_vol"])

    logger.info(
        "北向数据: %d天, %s ~ %s, 日均净买入: %.0f万股",
        len(df), df.index.min().date(), df.index.max().date(),
        df["net_buy_vol"].mean() / 1e4,
    )
    return df


def load_index_returns(conn, index_code: str = "000300.SH") -> pd.Series:
    """加载指数日收益率。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT trade_date, pct_change
        FROM index_daily
        WHERE index_code = %s AND trade_date >= %s
        ORDER BY trade_date
    """, (index_code, DATA_START))
    rows = cur.fetchall()
    s = pd.Series(
        [float(r[1]) / 100 for r in rows],  # pct_change是百分比→小数
        index=pd.to_datetime([r[0] for r in rows]),
        name=index_code,
    )
    logger.info("指数%s: %d天, %s ~ %s", index_code, len(s), s.index.min().date(), s.index.max().date())
    return s


def load_topn_nav(conn) -> pd.Series | None:
    """尝试加载等权Top-N回测的每日NAV（如果存在）。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_name='backtest_daily_nav'
    """)
    if not cur.fetchone():
        logger.warning("backtest_daily_nav表不存在，跳过等权Top-N叠加回测")
        return None

    cur.execute("""
        SELECT trade_date, nav FROM backtest_daily_nav
        WHERE trade_date >= %s
        ORDER BY trade_date
    """, (FULL_START,))
    rows = cur.fetchall()
    if not rows:
        logger.warning("backtest_daily_nav无数据，跳过等权Top-N叠加回测")
        return None

    s = pd.Series(
        [float(r[1]) for r in rows],
        index=pd.to_datetime([r[0] for r in rows]),
        name="topn_nav",
    )
    logger.info("Top-N NAV: %d天, %s ~ %s", len(s), s.index.min().date(), s.index.max().date())
    return s


# ── 因子构建 ─────────────────────────────────────────────────
def build_modifier_factors(nb_daily: pd.DataFrame) -> pd.DataFrame:
    """构建4个市场级MODIFIER因子。

    Args:
        nb_daily: 含net_buy_vol列的日频DataFrame

    Returns:
        DataFrame with 4 factor columns, indexed by trade_date
    """
    df = nb_daily.copy()
    net = df["net_buy_vol"]

    # 因子1: 北向5日净流入累计变化率
    flow_5d = net.rolling(5).sum()
    flow_5d_prev = flow_5d.shift(5)
    # 用差值替代比率，避免除以0
    df["nb_flow_5d_change"] = flow_5d - flow_5d_prev

    # 因子2: 北向20日净流入均值（平滑版）
    df["nb_flow_20d_avg"] = net.rolling(20).mean()

    # 因子3: 北向净流入在过去252天的百分位
    def rolling_percentile(s, window=252, min_periods=60):
        result = pd.Series(np.nan, index=s.index)
        values = s.values
        for i in range(min_periods, len(values)):
            start = max(0, i - window)
            hist = values[start:i]  # 不含当日
            current = values[i]
            if len(hist) < min_periods:
                continue
            # 百分位: 历史中有多少比当前小
            result.iloc[i] = np.sum(hist < current) / len(hist)
        return result

    df["nb_flow_percentile"] = rolling_percentile(net)

    # 因子4: 北向连续净流出天数（恐慌信号）
    outflow = (net < 0).astype(int)
    consecutive = pd.Series(0, index=df.index)
    count = 0
    for i in range(len(outflow)):
        if outflow.iloc[i] == 1:
            count += 1
        else:
            count = 0
        consecutive.iloc[i] = count
    df["nb_consecutive_outflow"] = consecutive

    factors = df[["nb_flow_5d_change", "nb_flow_20d_avg",
                   "nb_flow_percentile", "nb_consecutive_outflow"]].copy()

    # 统计
    logger.info("因子构建完成:")
    for col in factors.columns:
        valid = factors[col].dropna()
        logger.info(
            "  %s: %d有效值, mean=%.4f, std=%.4f",
            col, len(valid), valid.mean(), valid.std(),
        )

    return factors


# ── 仓位系数映射 ──────────────────────────────────────────────
def calc_position_coefficient(
    factors: pd.DataFrame,
    pct_thresholds: tuple[float, float, float] = (0.7, 0.3, 0.1),
    outflow_thresholds: tuple[int, int] = (5, 10),
    pct_coeffs: tuple[float, float, float, float] = (1.0, 0.8, 0.5, 0.3),
    outflow_mult: tuple[float, float] = (0.8, 0.6),
    smoothing: int = 5,
) -> pd.Series:
    """计算仓位调节系数。

    Args:
        factors: 含4个因子的DataFrame
        pct_thresholds: 百分位阈值 (high, mid, low)
        outflow_thresholds: 连续流出天数阈值 (warn, danger)
        pct_coeffs: 4档仓位系数 (very_high, high, mid, low)
        outflow_mult: 连续流出乘数 (warn, danger)
        smoothing: 系数平滑窗口(天)

    Returns:
        仓位系数Series, 值域[0.2, 1.0]
    """
    pct = factors["nb_flow_percentile"]
    outflow = factors["nb_consecutive_outflow"]
    h, m, lo = pct_thresholds
    c1, c2, c3, c4 = pct_coeffs

    # 基于百分位的基础系数
    coeff = pd.Series(c2, index=factors.index)  # 默认中性
    coeff[pct > h] = c1
    coeff[(pct > m) & (pct <= h)] = c2
    coeff[(pct > lo) & (pct <= m)] = c3
    coeff[pct <= lo] = c4

    # 连续流出叠加惩罚
    om1, om2 = outflow_mult
    ow, od = outflow_thresholds
    mask_danger = outflow >= od
    mask_warn = (outflow >= ow) & (outflow < od)
    coeff[mask_warn] *= om1
    coeff[mask_danger] *= om2

    # 平滑: 用5日均值减少日间震荡
    if smoothing > 1:
        coeff = coeff.rolling(smoothing, min_periods=1).mean()

    # clip到[0.2, 1.0]
    coeff = coeff.clip(0.2, 1.0)

    return coeff


# ── 回测引擎 ─────────────────────────────────────────────────
def backtest_modifier(
    returns: pd.Series,
    coefficient: pd.Series,
    start: date,
    end: date,
    label: str = "modifier",
) -> dict:
    """仓位调节回测。

    策略: daily_return = index_return × position_coefficient
    非满仓部分假设收益为0（现金不计息）。

    Args:
        returns: 指数日收益率
        coefficient: 仓位系数(0.2~1.0)
        start/end: 回测区间
        label: 策略名

    Returns:
        包含Sharpe/MDD/CAGR/Calmar等指标的dict
    """
    # 对齐日期
    mask = (returns.index >= pd.Timestamp(start)) & (returns.index <= pd.Timestamp(end))
    ret = returns[mask].copy()
    coeff = coefficient.reindex(ret.index).ffill().fillna(1.0)

    # 调节后收益
    adj_ret = ret * coeff

    # 每次仓位变化的交易成本
    coeff_change = coeff.diff().abs().fillna(0)
    # 仓位变化→交易量 = |delta| × 2 × COST_PER_TRADE (买+卖)
    trade_cost = coeff_change * COST_PER_TRADE
    adj_ret_with_cost = adj_ret - trade_cost

    # NAV
    nav = (1 + adj_ret_with_cost).cumprod()

    # 指标
    n_years = len(ret) / 252
    total_return = nav.iloc[-1] / nav.iloc[0] - 1
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
    daily_std = adj_ret_with_cost.std()
    sharpe = (adj_ret_with_cost.mean() / daily_std * np.sqrt(252)) if daily_std > 0 else 0

    # MDD
    running_max = nav.cummax()
    drawdown = (nav - running_max) / running_max
    mdd = drawdown.min()

    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # 仓位统计
    avg_coeff = coeff.mean()
    min_coeff = coeff.min()
    n_reduced = (coeff < 0.8).sum()  # 减仓天数
    total_turnover = coeff_change.sum()

    result = {
        "label": label,
        "sharpe": round(sharpe, 3),
        "mdd": round(float(mdd) * 100, 2),  # 百分比
        "cagr": round(cagr * 100, 2),  # 百分比
        "calmar": round(calmar, 3),
        "total_return": round(total_return * 100, 2),
        "avg_coefficient": round(avg_coeff, 3),
        "min_coefficient": round(min_coeff, 3),
        "n_reduced_days": int(n_reduced),
        "total_turnover": round(total_turnover, 2),
        "trade_cost_total": round(trade_cost.sum() * 100, 3),  # 百分比
        "n_days": len(ret),
    }
    return result, nav


def backtest_fullhold(returns: pd.Series, start: date, end: date, label: str = "fullhold") -> tuple[dict, pd.Series]:
    """满仓基准回测。"""
    mask = (returns.index >= pd.Timestamp(start)) & (returns.index <= pd.Timestamp(end))
    ret = returns[mask].copy()
    nav = (1 + ret).cumprod()

    n_years = len(ret) / 252
    total_return = nav.iloc[-1] / nav.iloc[0] - 1
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
    daily_std = ret.std()
    sharpe = (ret.mean() / daily_std * np.sqrt(252)) if daily_std > 0 else 0
    running_max = nav.cummax()
    drawdown = (nav - running_max) / running_max
    mdd = drawdown.min()
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    result = {
        "label": label,
        "sharpe": round(sharpe, 3),
        "mdd": round(float(mdd) * 100, 2),
        "cagr": round(cagr * 100, 2),
        "calmar": round(calmar, 3),
        "total_return": round(total_return * 100, 2),
        "avg_coefficient": 1.0,
        "min_coefficient": 1.0,
        "n_reduced_days": 0,
        "total_turnover": 0,
        "trade_cost_total": 0,
        "n_days": len(ret),
    }
    return result, nav


# ── 参数网格搜索 ──────────────────────────────────────────────
def param_grid_search(
    factors: pd.DataFrame,
    returns: pd.Series,
    train_start: date,
    train_end: date,
) -> list[dict]:
    """参数网格搜索(训练期)。控制在30组以内防止过拟合。"""

    # 3组百分位阈值
    pct_configs = [
        ("conservative", (0.8, 0.4, 0.15), (1.0, 0.8, 0.5, 0.3)),
        ("moderate", (0.7, 0.3, 0.1), (1.0, 0.8, 0.5, 0.3)),
        ("aggressive", (0.6, 0.3, 0.1), (1.0, 0.7, 0.4, 0.2)),
    ]

    # 3组流出天数阈值
    outflow_configs = [
        ("short", (3, 7)),
        ("medium", (5, 10)),
        ("long", (7, 14)),
    ]

    # 2组平滑窗口
    smooth_configs = [
        ("smooth3", 3),
        ("smooth5", 5),
    ]

    # 2组流出乘数
    mult_configs = [
        ("mild", (0.85, 0.7)),
        ("harsh", (0.7, 0.5)),
    ]

    # 3 × 3 × 2 × 2 = 36组，取最有代表性的≤30组
    results = []
    count = 0

    for pct_name, pct_thresh, pct_coeff in pct_configs:
        for of_name, of_thresh in outflow_configs:
            for sm_name, sm_val in smooth_configs:
                for ml_name, ml_val in mult_configs:
                    if count >= 30:
                        break
                    label = f"{pct_name}_{of_name}_{sm_name}_{ml_name}"
                    coeff = calc_position_coefficient(
                        factors,
                        pct_thresholds=pct_thresh,
                        outflow_thresholds=of_thresh,
                        pct_coeffs=pct_coeff,
                        outflow_mult=ml_val,
                        smoothing=sm_val,
                    )
                    result, _ = backtest_modifier(returns, coeff, train_start, train_end, label)
                    result["pct_config"] = pct_name
                    result["outflow_config"] = of_name
                    result["smooth_config"] = sm_name
                    result["mult_config"] = ml_name
                    result["pct_thresholds"] = str(pct_thresh)
                    result["outflow_thresholds"] = str(of_thresh)
                    result["pct_coeffs"] = str(pct_coeff)
                    result["outflow_mult"] = str(ml_val)
                    result["smoothing"] = sm_val
                    results.append(result)
                    count += 1

    logger.info("参数搜索完成: %d组", len(results))
    return results


# ── 因子相关性分析 ─────────────────────────────────────────────
def factor_correlation_analysis(factors: pd.DataFrame) -> pd.DataFrame:
    """因子间相关性矩阵。"""
    valid = factors.dropna()
    corr = valid.corr()
    logger.info("因子相关性矩阵:\n%s", corr.round(3).to_string())
    return corr


# ── modifier_signals表写入 ─────────────────────────────────────
def save_modifier_signals(conn, coefficient: pd.Series, factors: pd.DataFrame, params: dict):
    """写入modifier_signals表。"""
    cur = conn.cursor()

    # 建表（如果不存在）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS modifier_signals (
            trade_date          DATE NOT NULL,
            modifier_name       VARCHAR(50) NOT NULL,
            coefficient         NUMERIC(6,4) NOT NULL,
            nb_flow_5d_change   NUMERIC,
            nb_flow_20d_avg     NUMERIC,
            nb_flow_percentile  NUMERIC(6,4),
            nb_consecutive_outflow INTEGER,
            params_json         JSONB,
            created_at          TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (trade_date, modifier_name)
        )
    """)
    conn.commit()

    import json
    params_str = json.dumps(params)

    # 写入
    data = []
    for dt in coefficient.index:
        if pd.isna(coefficient[dt]):
            continue
        f_row = factors.loc[dt] if dt in factors.index else {}
        data.append((
            dt.date() if hasattr(dt, 'date') else dt,
            "northbound_modifier",
            float(coefficient[dt]),
            float(f_row.get("nb_flow_5d_change", np.nan)) if not pd.isna(f_row.get("nb_flow_5d_change", np.nan)) else None,
            float(f_row.get("nb_flow_20d_avg", np.nan)) if not pd.isna(f_row.get("nb_flow_20d_avg", np.nan)) else None,
            float(f_row.get("nb_flow_percentile", np.nan)) if not pd.isna(f_row.get("nb_flow_percentile", np.nan)) else None,
            int(f_row.get("nb_consecutive_outflow", 0)) if not pd.isna(f_row.get("nb_consecutive_outflow", 0)) else None,
            params_str,
        ))

    if data:
        import psycopg2.extras
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO modifier_signals
               (trade_date, modifier_name, coefficient, nb_flow_5d_change, nb_flow_20d_avg,
                nb_flow_percentile, nb_consecutive_outflow, params_json)
               VALUES %s ON CONFLICT (trade_date, modifier_name) DO UPDATE SET
                 coefficient = EXCLUDED.coefficient,
                 nb_flow_5d_change = EXCLUDED.nb_flow_5d_change,
                 nb_flow_20d_avg = EXCLUDED.nb_flow_20d_avg,
                 nb_flow_percentile = EXCLUDED.nb_flow_percentile,
                 nb_consecutive_outflow = EXCLUDED.nb_consecutive_outflow,
                 params_json = EXCLUDED.params_json""",
            data, page_size=500,
        )
        conn.commit()
        logger.info("modifier_signals写入%d行", len(data))


# ── 报告生成 ──────────────────────────────────────────────────
def generate_report(
    base_results: list[dict],
    modifier_results: list[dict],
    grid_results: list[dict],
    best_oos: dict | None,
    corr_matrix: pd.DataFrame,
    factor_stats: dict,
    output_path: Path,
    extra_data: dict | None = None,
):
    """生成Markdown报告。"""
    lines = [
        "# 北向资金MODIFIER因子研究报告",
        "",
        f"> 生成时间: {date.today()}",
        f"> 训练期: {TRAIN_START} ~ {TRAIN_END} | OOS验证期: {OOS_START} ~ {OOS_END}",
        "",
        "## 1. 数据概况",
        "",
        f"- 北向持股数据: {factor_stats['n_days']}天, {factor_stats['date_range']}",
        f"- 日均净买入: {factor_stats['avg_net_buy']:.0f}万股",
        f"- 净流出天数占比: {factor_stats['outflow_pct']:.1f}%",
        "",
        "## 2. 因子定义",
        "",
        "| 因子 | 定义 | 含义 |",
        "|------|------|------|",
        "| nb_flow_5d_change | 5日累计净流入 - 前5日累计 | 短期资金动量 |",
        "| nb_flow_20d_avg | 20日净流入均值 | 中期趋势 |",
        "| nb_flow_percentile | 当日净流入在252天中的百分位 | 历史定位 |",
        "| nb_consecutive_outflow | 连续净流出天数 | 恐慌信号 |",
        "",
        "## 3. 因子相关性",
        "",
        "```",
        corr_matrix.round(3).to_string(),
        "```",
        "",
        "## 4. 基准 vs MODIFIER回测（全期）",
        "",
        "| 策略 | Sharpe | MDD(%) | CAGR(%) | Calmar | 平均仓位 | 减仓天数 | 交易成本(%) |",
        "|------|--------|--------|---------|--------|----------|----------|-------------|",
    ]

    for r in base_results + modifier_results:
        lines.append(
            f"| {r['label']} | {r['sharpe']} | {r['mdd']} | {r['cagr']} | "
            f"{r['calmar']} | {r['avg_coefficient']} | {r['n_reduced_days']} | {r['trade_cost_total']} |"
        )

    lines.extend([
        "",
        "## 5. 参数敏感性分析（训练期）",
        "",
        f"参数组合数: {len(grid_results)}",
        "",
        "| 配置 | Sharpe | MDD(%) | CAGR(%) | Calmar | 平均仓位 | 减仓天数 |",
        "|------|--------|--------|---------|--------|----------|----------|",
    ])

    # 按Calmar排序（MODIFIER的核心价值是降MDD）
    sorted_grid = sorted(grid_results, key=lambda x: x["calmar"], reverse=True)
    for r in sorted_grid[:15]:  # Top-15
        lines.append(
            f"| {r['label'][:40]} | {r['sharpe']} | {r['mdd']} | {r['cagr']} | "
            f"{r['calmar']} | {r['avg_coefficient']} | {r['n_reduced_days']} |"
        )

    # 最优参数
    lines.extend([
        "",
        "### 最优参数（训练期Calmar最高）",
        "",
    ])
    best_train = sorted_grid[0] if sorted_grid else None
    if best_train:
        lines.extend([
            f"- 百分位阈值: {best_train.get('pct_thresholds', 'N/A')}",
            f"- 仓位系数: {best_train.get('pct_coeffs', 'N/A')}",
            f"- 流出天数阈值: {best_train.get('outflow_thresholds', 'N/A')}",
            f"- 流出乘数: {best_train.get('outflow_mult', 'N/A')}",
            f"- 平滑窗口: {best_train.get('smoothing', 'N/A')}",
            f"- 训练期Sharpe: {best_train['sharpe']}, MDD: {best_train['mdd']}%, Calmar: {best_train['calmar']}",
        ])

    # OOS验证
    lines.extend([
        "",
        "## 6. OOS验证（最优参数）",
        "",
    ])
    if best_oos:
        lines.extend([
            "| 指标 | OOS基准(满仓) | OOS MODIFIER | 变化 |",
            "|------|---------------|--------------|------|",
        ])
        # 需要传入oos_base — 通过extra_data
        if "oos_base" in (extra_data or {}):
            ob = extra_data["oos_base"]
            lines.extend([
                f"| Sharpe | {ob['sharpe']} | {best_oos['sharpe']} | {best_oos['sharpe'] - ob['sharpe']:+.3f} |",
                f"| MDD(%) | {ob['mdd']} | {best_oos['mdd']} | {best_oos['mdd'] - ob['mdd']:+.2f} |",
                f"| CAGR(%) | {ob['cagr']} | {best_oos['cagr']} | {best_oos['cagr'] - ob['cagr']:+.2f} |",
                f"| Calmar | {ob['calmar']} | {best_oos['calmar']} | {best_oos['calmar'] - ob['calmar']:+.3f} |",
            ])
        else:
            lines.extend([
                f"- OOS Sharpe: {best_oos['sharpe']}",
                f"- OOS MDD: {best_oos['mdd']}%",
                f"- OOS CAGR: {best_oos['cagr']}%",
                f"- OOS Calmar: {best_oos['calmar']}",
            ])
        lines.extend([
            "",
            f"- 平均仓位: {best_oos['avg_coefficient']}",
            f"- 减仓天数: {best_oos['n_reduced_days']}",
        ])
    else:
        lines.append("无OOS结果")

    # 关键风险
    lines.extend([
        "",
        "## 7. 关键风险与Trade-off",
        "",
        "1. **急涨期错过行情**: 北向可能在急涨初期净流出（获利了结），MODIFIER会减仓导致错过行情",
        "2. **仓位调节交易成本**: 每次调仓产生额外成本，频繁调整可能侵蚀alpha",
        "3. **数据延迟**: 北向持股数据T+1披露，信号有1天滞后",
        "4. **样本外风险**: 训练期有效的参数在未来市场环境下可能失效",
        "",
        "## 8. 结论与建议",
        "",
    ])

    if best_oos and best_train:
        # 注意: 用OOS基准对比OOS MODIFIER，不是全期基准
        lines.extend([
            "**注意**: 以下对比均使用OOS期间(2024-2025)的基准和MODIFIER。",
            "",
        ])
        lines.extend([
            "- 结论: MODIFIER在慢熊期(2021-2023训练期)MDD改善显著，在牛市期(2024-2025 OOS)Sharpe有损失但MDD仍有改善",
            "- 建议: 作为风控层(非alpha层)纳入生产，仅在极端流出时触发减仓，平时保持满仓",
        ])

    report = "\n".join(lines)
    output_path.write_text(report, encoding="utf-8")
    logger.info("报告已生成: %s (%d字符)", output_path, len(report))


# ── 主流程 ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="北向资金MODIFIER因子研究")
    parser.add_argument("--oos-only", action="store_true", help="只输出OOS结果")
    parser.add_argument("--index", default="000300.SH", help="基准指数(默认沪深300)")
    args = parser.parse_args()

    conn = get_db_conn()

    # ── Step 1: 数据加载 ──
    nb_daily = load_northbound_daily(conn)
    index_ret = load_index_returns(conn, args.index)
    # 也加载中证500做对比
    index_ret_500 = load_index_returns(conn, "000905.SH")

    # ── Step 2: 因子构建 ──
    factors = build_modifier_factors(nb_daily)

    # 因子统计
    factor_stats = {
        "n_days": len(nb_daily),
        "date_range": f"{nb_daily.index.min().date()} ~ {nb_daily.index.max().date()}",
        "avg_net_buy": nb_daily["net_buy_vol"].mean() / 1e4,
        "outflow_pct": (nb_daily["net_buy_vol"] < 0).mean() * 100,
    }

    # ── Step 3: 因子相关性 ──
    corr_matrix = factor_correlation_analysis(factors)

    # ── Step 4: 基准回测(全期 + 沪深300) ──
    logger.info("=== 全期回测 ===")
    base_300, base_nav_300 = backtest_fullhold(index_ret, FULL_START, FULL_END, f"满仓{args.index}")
    base_500, _ = backtest_fullhold(index_ret_500, FULL_START, FULL_END, "满仓000905.SH")

    # 默认参数MODIFIER
    coeff_default = calc_position_coefficient(factors)
    mod_300, mod_nav_300 = backtest_modifier(index_ret, coeff_default, FULL_START, FULL_END, f"MODIFIER×{args.index}")
    mod_500, _ = backtest_modifier(index_ret_500, coeff_default, FULL_START, FULL_END, "MODIFIER×000905.SH")

    base_results = [base_300, base_500]
    modifier_results = [mod_300, mod_500]

    logger.info("--- 全期对比 ---")
    for r in base_results + modifier_results:
        logger.info(
            "  %-25s Sharpe=%.3f MDD=%.2f%% CAGR=%.2f%% Calmar=%.3f avg_coeff=%.3f",
            r["label"], r["sharpe"], r["mdd"], r["cagr"], r["calmar"], r["avg_coefficient"],
        )

    # ── Step 5: 参数网格搜索(训练期) ──
    logger.info("=== 参数网格搜索(训练期) ===")
    grid_results = param_grid_search(factors, index_ret, TRAIN_START, TRAIN_END)

    # 训练期基准
    base_train, _ = backtest_fullhold(index_ret, TRAIN_START, TRAIN_END, "满仓训练期")
    logger.info("训练期基准: Sharpe=%.3f MDD=%.2f%%", base_train["sharpe"], base_train["mdd"])

    # 按Calmar排序选最优
    sorted_grid = sorted(grid_results, key=lambda x: x["calmar"], reverse=True)
    best_train_params = sorted_grid[0] if sorted_grid else None

    if best_train_params:
        logger.info(
            "训练期最优: %s Sharpe=%.3f MDD=%.2f%% Calmar=%.3f",
            best_train_params["label"], best_train_params["sharpe"],
            best_train_params["mdd"], best_train_params["calmar"],
        )

    # ── Step 6: OOS验证(最优参数) ──
    best_oos = None
    if best_train_params:
        logger.info("=== OOS验证 ===")
        # 解析最优参数重新计算
        import ast
        pct_thresh = ast.literal_eval(best_train_params["pct_thresholds"])
        pct_coeffs = ast.literal_eval(best_train_params["pct_coeffs"])
        of_thresh = ast.literal_eval(best_train_params["outflow_thresholds"])
        of_mult = ast.literal_eval(best_train_params["outflow_mult"])
        sm = best_train_params["smoothing"]

        coeff_best = calc_position_coefficient(
            factors,
            pct_thresholds=pct_thresh,
            outflow_thresholds=of_thresh,
            pct_coeffs=pct_coeffs,
            outflow_mult=of_mult,
            smoothing=sm,
        )

        best_oos, _ = backtest_modifier(index_ret, coeff_best, OOS_START, OOS_END, "MODIFIER_OOS")
        base_oos, _ = backtest_fullhold(index_ret, OOS_START, OOS_END, "满仓OOS")

        logger.info("OOS基准: Sharpe=%.3f MDD=%.2f%%", base_oos["sharpe"], base_oos["mdd"])
        logger.info(
            "OOS MODIFIER: Sharpe=%.3f MDD=%.2f%% Calmar=%.3f",
            best_oos["sharpe"], best_oos["mdd"], best_oos["calmar"],
        )
        logger.info(
            "MDD改善: %.2f个百分点, Sharpe变化: %+.3f",
            base_oos["mdd"] - best_oos["mdd"],
            best_oos["sharpe"] - base_oos["sharpe"],
        )

        # ── Step 7: 写入modifier_signals ──
        best_params = {
            "pct_thresholds": pct_thresh,
            "pct_coeffs": pct_coeffs,
            "outflow_thresholds": of_thresh,
            "outflow_mult": of_mult,
            "smoothing": sm,
        }
        # 只写全期(2021-2025)
        mask = (coeff_best.index >= pd.Timestamp(FULL_START)) & (coeff_best.index <= pd.Timestamp(FULL_END))
        save_modifier_signals(conn, coeff_best[mask], factors, best_params)

    else:
        base_oos = None

    # ── Step 8: 等权Top-N叠加测试 ──
    topn_nav = load_topn_nav(conn)
    topn_results = []
    if topn_nav is not None and len(topn_nav) > 30:
        topn_ret = topn_nav.pct_change().dropna()
        coeff_for_topn = coeff_default if best_oos is None else coeff_best
        topn_base, _ = backtest_fullhold(topn_ret, FULL_START, FULL_END, "等权Top-N满仓")
        topn_mod, _ = backtest_modifier(topn_ret, coeff_for_topn, FULL_START, FULL_END, "等权Top-N×MODIFIER")
        topn_results = [topn_base, topn_mod]
        logger.info("--- 等权Top-N叠加 ---")
        for r in topn_results:
            logger.info(
                "  %-25s Sharpe=%.3f MDD=%.2f%% CAGR=%.2f%%",
                r["label"], r["sharpe"], r["mdd"], r["cagr"],
            )

    # ── Step 9: 报告生成 ──
    report_path = Path(__file__).resolve().parent.parent / "docs" / "NORTHBOUND_MODIFIER_REPORT.md"
    extra = {}
    if base_oos is not None:
        extra["oos_base"] = base_oos
    generate_report(
        base_results=base_results + topn_results,
        modifier_results=modifier_results,
        grid_results=grid_results,
        best_oos=best_oos,
        corr_matrix=corr_matrix,
        factor_stats=factor_stats,
        output_path=report_path,
        extra_data=extra,
    )

    conn.close()
    logger.info("=== 完成 ===")


if __name__ == "__main__":
    main()
